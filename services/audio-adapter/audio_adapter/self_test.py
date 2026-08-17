"""Operator check for ASR and microphone. Does not require the event hub."""

from __future__ import annotations

import json
import subprocess
import tempfile
import wave
from pathlib import Path

import numpy as np

from audio_adapter.capture import (
    AudioHardwareRuntime,
    ENERGY_THRESHOLD,
    describe_asr,
    list_sound_devices,
    resolve_asr,
)


def _load_wav(path: Path) -> tuple[int, np.ndarray]:
    with wave.open(str(path), "rb") as handle:
        sr = handle.getframerate()
        raw = handle.readframes(handle.getnframes())
        pcm = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        if handle.getnchannels() > 1:
            pcm = pcm.reshape(-1, handle.getnchannels())[:, 0]
        return sr, pcm


def _synthesize_stop(path: Path) -> bool:
    try:
        subprocess.run(
            [
                "say",
                "-o",
                str(path),
                "--file-format=WAVE",
                "--data-format=LEI16@16000",
                "stop",
            ],
            check=True,
            capture_output=True,
        )
        return path.exists()
    except Exception:
        return False


def run_self_test() -> int:
    report: dict[str, object] = {
        "asr_backend": None,
        "asr_transcript": None,
        "mic_rms": None,
        "mic_peak": None,
        "input_devices": list_sound_devices(),
        "ok": False,
        "error": None,
    }
    asr = resolve_asr()
    report["asr_backend"] = describe_asr(asr)
    if asr is None:
        report["error"] = "ASR unavailable. Install with: python -m pip install -e '.[audio-mlx]'"
        print(json.dumps(report, indent=2))
        return 1

    with tempfile.TemporaryDirectory() as tmp:
        wav_path = Path(tmp) / "stop.wav"
        if _synthesize_stop(wav_path):
            sr, pcm = _load_wav(wav_path)
            # Trailing silence so VAD can close the utterance.
            pcm = np.concatenate([pcm, np.zeros(int(0.6 * sr), dtype=np.float32)])
            result = asr(pcm, sr)
            text = result.transcript if hasattr(result, "transcript") else str(result)
            report["asr_transcript"] = text
            runtime = AudioHardwareRuntime(resolve_backend=False, asr=asr, use_webrtc=False)
            events = runtime.ingest_block(pcm, 1_000_000_000)
            finals = [
                event.payload.get("transcript")
                for event in events
                if event.event_type == "audio.intent_candidate" and event.payload.get("is_final")
            ]
            report["pipeline_transcripts"] = finals
            if "stop" not in text.lower():
                report["error"] = f"ASR did not transcribe 'stop' (got {text!r})"
                print(json.dumps(report, indent=2))
                return 1
        else:
            report["asr_transcript"] = "(say unavailable; skipped speech clip)"

    try:
        import sounddevice as sd

        rec = sd.rec(int(1.2 * 16000), samplerate=16000, channels=1, dtype="float32")
        sd.wait()
        mono = rec[:, 0]
        rms = float(np.sqrt(np.mean(np.square(mono, dtype=np.float64))))
        peak = float(np.max(np.abs(mono)))
        report["mic_rms"] = round(rms, 5)
        report["mic_peak"] = round(peak, 5)
        report["mic_above_vad"] = rms >= ENERGY_THRESHOLD
        if peak < 1e-4:
            report["error"] = (
                "Microphone is silent. Grant Microphone permission to Terminal or Cursor "
                "in System Settings → Privacy & Security → Microphone, then retry."
            )
            print(json.dumps(report, indent=2))
            return 2
    except Exception as exc:
        report["error"] = f"microphone open failed: {exc}"
        print(json.dumps(report, indent=2))
        return 1

    report["ok"] = True
    print(json.dumps(report, indent=2))
    return 0
