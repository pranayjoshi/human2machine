from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np
from intent_contracts.envelope import EventEnvelope
from intent_runtime.heartbeat import heartbeat_event as runtime_heartbeat
from numpy.typing import NDArray

from audio_adapter.mock import SOURCE, make_event
from audio_adapter.parser import parse_utterance

SAMPLE_RATE_HZ = 16_000
PREROLL_MS = 250
SILENCE_END_MS = 400
MAX_UTTERANCE_MS = 4000
FRAME_MS = 20
ENERGY_THRESHOLD = 0.02


@dataclass(frozen=True)
class CompletedUtterance:
    samples: NDArray[np.floating]
    start_ns: int
    end_ns: int


class RingBuffer:
    """Bounded mono PCM buffer. Oldest samples are dropped on overflow."""

    def __init__(self, sample_rate_hz: int = SAMPLE_RATE_HZ, seconds: float = 6.0) -> None:
        self.sample_rate_hz = sample_rate_hz
        self.capacity = max(1, int(sample_rate_hz * seconds))
        self._buf = np.zeros(self.capacity, dtype=np.float32)
        self._write = 0
        self._filled = 0
        self.overflows = 0
        self.last_receive_ns: int | None = None

    def push(self, samples: NDArray[np.floating], received_ns: int) -> None:
        data = np.asarray(samples, dtype=np.float32).reshape(-1)
        if data.size == 0:
            return
        if data.size >= self.capacity:
            self._buf[:] = data[-self.capacity :]
            self._write = 0
            self._filled = self.capacity
            self.overflows += 1
            self.last_receive_ns = received_ns
            return
        end = self._write + data.size
        if end <= self.capacity:
            self._buf[self._write : end] = data
        else:
            first = self.capacity - self._write
            self._buf[self._write :] = data[:first]
            self._buf[: data.size - first] = data[first:]
        self._write = (self._write + data.size) % self.capacity
        new_filled = self._filled + data.size
        if new_filled > self.capacity:
            self.overflows += 1
            self._filled = self.capacity
        else:
            self._filled = new_filled
        self.last_receive_ns = received_ns

    def latest(self, n: int) -> NDArray[np.float32]:
        n = min(int(n), self._filled)
        if n <= 0:
            return np.zeros(0, dtype=np.float32)
        start = (self._write - n) % self.capacity
        if start + n <= self.capacity:
            return self._buf[start : start + n].copy()
        first = self.capacity - start
        return np.concatenate([self._buf[start:], self._buf[: n - first]])


class EnergyVadSegmenter:
    def __init__(
        self,
        sample_rate_hz: int = SAMPLE_RATE_HZ,
        preroll_ms: int = PREROLL_MS,
        silence_end_ms: int = SILENCE_END_MS,
        max_utterance_ms: int = MAX_UTTERANCE_MS,
        frame_ms: int = FRAME_MS,
        energy_threshold: float = ENERGY_THRESHOLD,
        use_webrtc: bool = True,
    ) -> None:
        self.sample_rate_hz = sample_rate_hz
        self.frame_samples = max(1, int(sample_rate_hz * frame_ms / 1000))
        self.preroll_frames = max(1, int(preroll_ms / frame_ms))
        self.silence_frames = max(1, int(silence_end_ms / frame_ms))
        self.max_frames = max(self.preroll_frames + 1, int(max_utterance_ms / frame_ms))
        self.energy_threshold = energy_threshold
        self._webrtc = None
        if use_webrtc:
            try:
                import webrtcvad

                self._webrtc = webrtcvad.Vad(2)
            except Exception:
                self._webrtc = None
        self._pending = np.zeros(0, dtype=np.float32)
        self._preroll: deque[tuple[NDArray[np.float32], int, bool]] = deque(
            maxlen=self.preroll_frames
        )
        self._utterance: list[NDArray[np.float32]] = []
        self._utterance_start_ns: int | None = None
        self._last_frame_ns = 0
        self._silence_run = 0
        self._in_speech = False

    def push_block(
        self, samples: NDArray[np.floating], received_ns: int
    ) -> list[CompletedUtterance]:
        data = np.asarray(samples, dtype=np.float32).reshape(-1)
        if data.size == 0:
            return []
        self._pending = np.concatenate([self._pending, data]) if self._pending.size else data
        n_frames = self._pending.size // self.frame_samples
        if n_frames == 0:
            return []
        used = n_frames * self.frame_samples
        block = self._pending[:used]
        self._pending = self._pending[used:]
        frame_ns = int(1_000_000_000 * self.frame_samples / self.sample_rate_hz)
        first_ns = received_ns - frame_ns * n_frames
        completed: list[CompletedUtterance] = []
        for i in range(n_frames):
            frame = block[i * self.frame_samples : (i + 1) * self.frame_samples]
            ts = first_ns + i * frame_ns
            completed.extend(self._consume_frame(frame, ts))
        return completed

    def flush(self) -> list[CompletedUtterance]:
        out: list[CompletedUtterance] = []
        if self._in_speech:
            ended = self._close_utterance(self._last_frame_ns)
            if ended is not None:
                out.append(ended)
        self._pending = np.zeros(0, dtype=np.float32)
        self._preroll.clear()
        return out

    def _consume_frame(
        self, frame: NDArray[np.float32], timestamp_ns: int
    ) -> list[CompletedUtterance]:
        speech = self._is_speech(frame)
        self._last_frame_ns = timestamp_ns
        completed: list[CompletedUtterance] = []
        if not self._in_speech:
            self._preroll.append((frame.copy(), timestamp_ns, speech))
            if speech:
                self._in_speech = True
                self._silence_run = 0
                self._utterance = [item[0] for item in self._preroll]
                self._utterance_start_ns = self._preroll[0][1]
        else:
            self._utterance.append(frame.copy())
            if speech:
                self._silence_run = 0
            else:
                self._silence_run += 1
            too_long = len(self._utterance) >= self.max_frames
            silence_done = self._silence_run >= self.silence_frames
            if too_long or silence_done:
                ended = self._close_utterance(timestamp_ns)
                if ended is not None:
                    completed.append(ended)
        return completed

    def _close_utterance(self, end_ns: int) -> CompletedUtterance | None:
        samples = (
            np.concatenate(self._utterance).astype(np.float32)
            if self._utterance
            else np.zeros(0, dtype=np.float32)
        )
        start_ns = self._utterance_start_ns if self._utterance_start_ns is not None else end_ns
        self._in_speech = False
        self._silence_run = 0
        self._utterance = []
        self._utterance_start_ns = None
        self._preroll.clear()
        if samples.size < self.frame_samples:
            return None
        return CompletedUtterance(samples=samples, start_ns=int(start_ns), end_ns=int(end_ns))

    def _is_speech(self, frame: NDArray[np.float32]) -> bool:
        if self._webrtc is not None and frame.size == self.frame_samples:
            pcm = np.clip(frame * 32768.0, -32768, 32767).astype(np.int16).tobytes()
            try:
                return bool(self._webrtc.is_speech(pcm, self.sample_rate_hz))
            except Exception:
                pass
        if frame.size == 0:
            return False
        rms = float(np.sqrt(np.mean(np.square(frame, dtype=np.float64))))
        return rms >= self.energy_threshold


def segment_utterances(
    samples: NDArray[np.floating],
    sample_rate_hz: int = SAMPLE_RATE_HZ,
    **kwargs: Any,
) -> list[CompletedUtterance]:
    """Offline VAD for tests. Does not open a microphone."""
    vad = EnergyVadSegmenter(sample_rate_hz=sample_rate_hz, use_webrtc=False, **kwargs)
    frame = vad.frame_samples
    hop_ns = int(1_000_000_000 * frame / sample_rate_hz)
    data = np.asarray(samples, dtype=np.float32).reshape(-1)
    t_ns = 0
    out: list[CompletedUtterance] = []
    for start in range(0, data.size, frame):
        chunk = data[start : start + frame]
        if chunk.size < frame:
            padded = np.zeros(frame, dtype=np.float32)
            padded[: chunk.size] = chunk
            chunk = padded
        t_ns += hop_ns
        out.extend(vad.push_block(chunk, t_ns))
    out.extend(vad.flush())
    return out


def resolve_asr() -> Callable[[NDArray[np.floating], int], str] | None:
    try:
        import mlx_whisper

        def _mlx(audio: NDArray[np.floating], sample_rate_hz: int) -> str:
            _ = sample_rate_hz
            result = mlx_whisper.transcribe(np.asarray(audio, dtype=np.float32), language="en")
            return str(result.get("text", "")).strip()

        return _mlx
    except Exception:
        pass
    try:
        import whisper

        model = whisper.load_model("tiny.en")

        def _whisper(audio: NDArray[np.floating], sample_rate_hz: int) -> str:
            _ = sample_rate_hz
            result = model.transcribe(
                np.asarray(audio, dtype=np.float32), language="en", fp16=False
            )
            return str(result.get("text", "")).strip()

        return _whisper
    except Exception:
        return None


def list_sound_devices() -> list[str]:
    try:
        import sounddevice as sd
    except Exception:
        return []
    rows: list[str] = []
    devices = sd.query_devices()
    for index, info in enumerate(devices):
        max_in = int(info.get("max_input_channels", 0))
        if max_in <= 0:
            continue
        name = str(info.get("name", f"device-{index}"))
        rows.append(f"{index}: {name} (in={max_in})")
    return rows


class AudioHardwareRuntime:
    def __init__(
        self,
        *,
        sample_rate_hz: int = SAMPLE_RATE_HZ,
        device_name: str | int | None = None,
        phrase: str | None = None,
        asr: Callable[[NDArray[np.floating], int], str] | None = None,
        resolve_backend: bool = True,
        model_id: str = "grammar_v1",
        preroll_ms: int = PREROLL_MS,
        silence_end_ms: int = SILENCE_END_MS,
        max_utterance_ms: int = MAX_UTTERANCE_MS,
        stream_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.sample_rate_hz = sample_rate_hz
        self.device_name = device_name
        self.phrase = phrase
        self.model_id = model_id
        self.sequence = 0
        self.ring = RingBuffer(sample_rate_hz=sample_rate_hz)
        self.vad = EnergyVadSegmenter(
            sample_rate_hz=sample_rate_hz,
            preroll_ms=preroll_ms,
            silence_end_ms=silence_end_ms,
            max_utterance_ms=max_utterance_ms,
        )
        self.asr = resolve_asr() if resolve_backend else asr
        self._stream_factory = stream_factory
        self._stream: Any | None = None
        self._started = False
        self._phrase_emitted = False
        self._asr_notice_sent = False
        self.dropped_blocks = 0
        self._pending_blocks: deque[tuple[NDArray[np.floating], int]] = deque()

    def start(self) -> None:
        factory = self._stream_factory
        if factory is None:
            import sounddevice as sd

            factory = sd.InputStream
        self._stream = factory(
            samplerate=self.sample_rate_hz,
            channels=1,
            dtype="float32",
            device=self.device_name,
            callback=self._on_audio,
            blocksize=int(self.sample_rate_hz * FRAME_MS / 1000),
        )
        start = getattr(self._stream, "start", None)
        if start is not None:
            start()

    def stop(self) -> None:
        stream = self._stream
        self._stream = None
        if stream is None:
            return
        for method in ("stop", "close"):
            fn = getattr(stream, method, None)
            if fn is not None:
                try:
                    fn()
                except Exception:
                    pass

    def poll(self) -> list[EventEnvelope]:
        events: list[EventEnvelope] = []
        if not self._started:
            if self.asr is None and not self.phrase:
                events.append(self._device_status("degraded", "asr_unavailable"))
            else:
                events.append(self._device_status("healthy", "microphone capture started"))
            self._started = True
        events.extend(self.drain_capture())
        if self.asr is None and self.phrase and not self._phrase_emitted:
            events.extend(
                self.events_for_transcript(
                    self.phrase, is_final=True, start_ns=0, end_ns=350_000_000
                )
            )
            self._phrase_emitted = True
        return events

    def ingest_block(self, samples: NDArray[np.floating], received_ns: int) -> list[EventEnvelope]:
        self.ring.push(samples, received_ns)
        events: list[EventEnvelope] = []
        for utterance in self.vad.push_block(samples, received_ns):
            events.extend(self._events_for_utterance(utterance))
        return events

    def events_for_transcript(
        self,
        transcript: str,
        *,
        is_final: bool,
        start_ns: int,
        end_ns: int,
        asr_confidence: float | None = None,
    ) -> list[EventEnvelope]:
        parsed = parse_utterance(transcript, asr_confidence=asr_confidence)
        quality = 0.9 if is_final else 0.5
        events: list[EventEnvelope] = []
        if is_final:
            partial_text = transcript.split(" ")[0] if transcript.strip() else transcript
            partial = parse_utterance(partial_text, asr_confidence=0.4)
            events.append(
                self._intent_event(
                    partial_text,
                    partial,
                    is_final=False,
                    start_ns=start_ns,
                    end_ns=start_ns + 80_000_000,
                    quality=quality * 0.7,
                )
            )
        events.append(
            self._intent_event(
                transcript,
                parsed,
                is_final=is_final,
                start_ns=start_ns,
                end_ns=end_ns,
                quality=quality,
            )
        )
        events.append(
            make_event(
                event_type="data.quality",
                sequence=self._next_seq(),
                source_time_ns=end_ns,
                quality=quality,
                payload={
                    "score": quality,
                    "components": {"asr": quality, "grammar": parsed.grammar_match},
                    "flags": ["overflow"] if self.ring.overflows else [],
                },
            )
        )
        return events

    def heartbeat(self, uptime_seconds: float, dropped: int) -> EventEnvelope:
        status = "degraded" if dropped or (self.asr is None and not self.phrase) else "healthy"
        return runtime_heartbeat(
            SOURCE,
            uptime_seconds=uptime_seconds,
            last_data_age_ms=None,
            error_count=dropped + self.dropped_blocks,
            sequence=self._next_seq(),
            status=status,
        )

    def shutdown(self) -> EventEnvelope:
        return self._device_status("offline", "adapter stopping")

    def _events_for_utterance(self, utterance: CompletedUtterance) -> list[EventEnvelope]:
        if self.asr is not None:
            try:
                transcript = self.asr(utterance.samples, self.sample_rate_hz)
            except Exception:
                transcript = ""
            if transcript:
                return self.events_for_transcript(
                    transcript,
                    is_final=True,
                    start_ns=utterance.start_ns,
                    end_ns=utterance.end_ns,
                )
            return []
        if self.phrase:
            if self._phrase_emitted:
                return []
            self._phrase_emitted = True
            return self.events_for_transcript(
                self.phrase,
                is_final=True,
                start_ns=utterance.start_ns,
                end_ns=utterance.end_ns,
            )
        if not self._asr_notice_sent:
            self._asr_notice_sent = True
            return [self._device_status("degraded", "asr_unavailable")]
        return []

    def _on_audio(self, indata, frames, time_info, status) -> None:  # noqa: ANN001
        import time

        received_ns = time.monotonic_ns()
        if status:
            self.dropped_blocks += 1
        mono = np.asarray(indata, dtype=np.float32)
        if mono.ndim > 1:
            mono = mono[:, 0]
        self._pending_blocks.append((mono.copy(), received_ns))

    def drain_capture(self) -> list[EventEnvelope]:
        events: list[EventEnvelope] = []
        while self._pending_blocks:
            samples, received_ns = self._pending_blocks.popleft()
            events.extend(self.ingest_block(samples, received_ns))
        return events

    def _intent_event(
        self, transcript, parsed, is_final, start_ns, end_ns, quality
    ) -> EventEnvelope:
        return make_event(
            event_type="audio.intent_candidate",
            sequence=self._next_seq(),
            source_time_ns=end_ns,
            quality=quality,
            payload={
                "transcript": transcript,
                "is_final": is_final,
                "action": parsed.action,
                "target_reference": parsed.target_reference,
                "target_object_id": parsed.target_object_id,
                "confidence": parsed.confidence if is_final else min(parsed.confidence, 0.4),
                "utterance_start_ns": start_ns,
                "utterance_end_ns": end_ns,
                "model_id": self.model_id,
            },
        )

    def _device_status(self, status: str, detail: str) -> EventEnvelope:
        return make_event(
            event_type="device.status",
            sequence=self._next_seq(),
            modality="audio",
            payload={
                "status": status,
                "device_alias": "audio-mic",
                "detail": detail,
                "metadata": {"capture": "sounddevice"},
            },
        )

    def _next_seq(self) -> int:
        value = self.sequence
        self.sequence += 1
        return value
