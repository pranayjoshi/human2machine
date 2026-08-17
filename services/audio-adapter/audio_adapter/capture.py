from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
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
ENERGY_THRESHOLD = 0.008
PENDING_BLOCK_LIMIT = 300
SILENCE_PEAK = 1e-4
SILENCE_WATCHDOG_S = 2.5

RAW_AUDIO_KEYS = frozenset(
    {
        "pcm",
        "samples",
        "waveform",
        "raw_audio",
        "audio_pcm",
        "audio_samples",
        "audio_bytes",
    }
)


@dataclass(frozen=True)
class CompletedUtterance:
    samples: NDArray[np.floating]
    start_ns: int
    end_ns: int


@dataclass(frozen=True)
class AsrResult:
    """Local ASR output. confidence is None unless the backend supplies it."""

    transcript: str
    confidence: float | None = None


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

    @property
    def in_speech(self) -> bool:
        return self._in_speech

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
        energy = False
        if frame.size:
            rms = float(np.sqrt(np.mean(np.square(frame, dtype=np.float64))))
            energy = rms >= self.energy_threshold
        if self._webrtc is not None and frame.size == self.frame_samples:
            pcm = np.clip(frame * 32768.0, -32768, 32767).astype(np.int16).tobytes()
            try:
                return bool(self._webrtc.is_speech(pcm, self.sample_rate_hz)) or energy
            except Exception:
                pass
        return energy


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


def extract_asr_confidence(result: Any) -> float | None:
    """Use backend confidence only when it is explicitly provided.

    Whisper/MLX results expose avg_logprob, not token confidence. Do not convert
    that into a fabricated high score such as 0.99.
    """
    if result is None:
        return None
    if isinstance(result, bool):
        return None
    if isinstance(result, (int, float)):
        value = float(result)
        return value if 0.0 <= value <= 1.0 else None
    if not isinstance(result, dict):
        return None
    for key in ("token_confidence", "avg_token_confidence", "confidence"):
        if key not in result:
            continue
        raw = result[key]
        if raw is None or isinstance(raw, bool):
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if 0.0 <= value <= 1.0:
            return value
    return None


def _asr_from_whisper_result(result: dict[str, Any]) -> AsrResult:
    text = str(result.get("text", "")).strip()
    return AsrResult(transcript=text, confidence=extract_asr_confidence(result))


def _transcribe_with_mlx(audio: NDArray[np.floating], sample_rate_hz: int) -> AsrResult:
    import mlx_whisper

    array = np.asarray(audio, dtype=np.float32).reshape(-1)
    model = "mlx-community/whisper-tiny"
    try:
        result = mlx_whisper.transcribe(array, path_or_hf_repo=model, language="en")
    except Exception:
        result = _mlx_transcribe_wav(array, sample_rate_hz, model)
    if not isinstance(result, dict):
        return AsrResult(transcript=str(result).strip(), confidence=None)
    return _asr_from_whisper_result(result)


def _mlx_transcribe_wav(
    audio: NDArray[np.float32], sample_rate_hz: int, model: str
) -> dict[str, Any]:
    import tempfile
    import wave

    import mlx_whisper

    pcm = np.clip(audio * 32767.0, -32768, 32767).astype(np.int16)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
        path = handle.name
    try:
        with wave.open(path, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(int(sample_rate_hz))
            wav.writeframes(pcm.tobytes())
        result = mlx_whisper.transcribe(path, path_or_hf_repo=model, language="en")
        return result if isinstance(result, dict) else {"text": str(result)}
    finally:
        Path(path).unlink(missing_ok=True)


def resolve_asr() -> Callable[[NDArray[np.floating], int], AsrResult] | None:
    try:
        import mlx_whisper  # noqa: F401

        print(
            '{"event":"asr_backend","backend":"mlx-whisper","model":"whisper-tiny","service":"audio-adapter"}',
            flush=True,
        )
        return _transcribe_with_mlx
    except Exception:
        pass
    try:
        import whisper

        model = whisper.load_model("tiny.en")

        def _whisper(audio: NDArray[np.floating], sample_rate_hz: int) -> AsrResult:
            _ = sample_rate_hz
            result = model.transcribe(
                np.asarray(audio, dtype=np.float32), language="en", fp16=False
            )
            if not isinstance(result, dict):
                return AsrResult(transcript=str(result).strip(), confidence=None)
            return _asr_from_whisper_result(result)

        print(
            '{"event":"asr_backend","backend":"openai-whisper","model":"tiny.en","service":"audio-adapter"}',
            flush=True,
        )
        return _whisper
    except Exception:
        print(
            '{"event":"asr_backend","backend":null,"service":"audio-adapter"}',
            flush=True,
        )
        return None


def describe_asr(asr: Callable[[NDArray[np.floating], int], Any] | None) -> str | None:
    if asr is None:
        return None
    if asr is _transcribe_with_mlx:
        return "mlx-whisper"
    name = getattr(asr, "__name__", "")
    if name == "_whisper":
        return "openai-whisper"
    if name == "_transcribe_with_mlx":
        return "mlx-whisper"
    return "local-asr"


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


def event_contains_raw_audio(event: EventEnvelope | dict[str, Any]) -> bool:
    payload = event.payload if isinstance(event, EventEnvelope) else event.get("payload", event)
    return _payload_has_raw_audio(payload)


def _payload_has_raw_audio(value: Any) -> bool:
    if isinstance(value, dict):
        for key, nested in value.items():
            lowered = str(key).lower()
            if lowered in RAW_AUDIO_KEYS or lowered == "audio":
                if isinstance(nested, (list, tuple, bytes, bytearray, np.ndarray)):
                    return True
                if isinstance(nested, str) and len(nested) > 256:
                    return True
            if _payload_has_raw_audio(nested):
                return True
        return False
    if isinstance(value, (list, tuple)):
        return any(_payload_has_raw_audio(item) for item in value)
    return False


def strip_raw_audio_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Drop raw PCM fields so events never carry microphone samples."""
    cleaned: dict[str, Any] = {}
    for key, value in payload.items():
        lowered = str(key).lower()
        if lowered in RAW_AUDIO_KEYS or lowered == "audio":
            continue
        if isinstance(value, dict):
            cleaned[key] = strip_raw_audio_payload(value)
        else:
            cleaned[key] = value
    return cleaned


class AudioHardwareRuntime:
    def __init__(
        self,
        *,
        sample_rate_hz: int = SAMPLE_RATE_HZ,
        device_name: str | int | None = None,
        phrase: str | None = None,
        asr: Callable[[NDArray[np.floating], int], Any] | None = None,
        resolve_backend: bool = True,
        model_id: str = "grammar_v1",
        preroll_ms: int = PREROLL_MS,
        silence_end_ms: int = SILENCE_END_MS,
        max_utterance_ms: int = MAX_UTTERANCE_MS,
        stream_factory: Callable[..., Any] | None = None,
        research_recording: bool = False,
        use_webrtc: bool = True,
    ) -> None:
        self.sample_rate_hz = sample_rate_hz
        self.device_name = device_name
        self.phrase = phrase
        self.model_id = model_id
        self.research_recording = bool(research_recording)
        self.sequence = 0
        self.ring = RingBuffer(sample_rate_hz=sample_rate_hz)
        self.vad = EnergyVadSegmenter(
            sample_rate_hz=sample_rate_hz,
            preroll_ms=preroll_ms,
            silence_end_ms=silence_end_ms,
            max_utterance_ms=max_utterance_ms,
            use_webrtc=use_webrtc,
        )
        self.asr = resolve_asr() if resolve_backend else asr
        self._stream_factory = stream_factory
        self._stream: Any | None = None
        self._started = False
        self._capture_live = False
        self._phrase_emitted = False
        self._asr_notice_sent = False
        self.dropped_blocks = 0
        self._pending_blocks: deque[tuple[NDArray[np.floating], int]] = deque()
        self._pending_limit = PENDING_BLOCK_LIMIT
        self._pending_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._stream_failed = False
        self._disconnect_detail = "microphone disconnected"
        self._disconnect_emitted = False
        self.session_pcm: list[CompletedUtterance] = []
        self._last_rms = 0.0
        self._last_peak = 0.0
        self._peak_since_start = 0.0
        self._capture_started_mono = 0.0
        self._silence_warned = False
        self._asr_warm: threading.Thread | None = None

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
        self._capture_live = True
        self._stream_failed = False
        self._disconnect_emitted = False
        self._silence_warned = False
        self._peak_since_start = 0.0
        self._capture_started_mono = time.monotonic()
        if self.asr is not None:
            self._asr_warm = threading.Thread(target=self._warmup_asr, name="asr-warmup", daemon=True)
            self._asr_warm.start()

    def _warmup_asr(self) -> None:
        try:
            if self.asr is not None:
                self.asr(np.zeros(self.sample_rate_hz, dtype=np.float32), self.sample_rate_hz)
        except Exception:
            pass

    def stop(self) -> None:
        self._capture_live = False
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
        try:
            self._observe_stream()
            if not self._started:
                if self._stream_failed:
                    events.append(self._device_status("degraded", self._disconnect_detail))
                    self._disconnect_emitted = True
                elif self.asr is None and not self.phrase:
                    events.append(self._device_status("degraded", "asr_unavailable"))
                else:
                    backend = describe_asr(self.asr)
                    detail = "microphone capture started"
                    if backend:
                        detail = f"{detail} ({backend})"
                    elif self.phrase:
                        detail = f"{detail} (phrase fallback)"
                    events.append(self._device_status("healthy", detail))
                self._started = True
            elif self._stream_failed and not self._disconnect_emitted:
                events.append(self._device_status("degraded", self._disconnect_detail))
                self._disconnect_emitted = True
            events.extend(self.drain_capture())
            events.extend(self._silence_watchdog())
            if self.asr is None and self.phrase and not self._phrase_emitted:
                events.extend(
                    self.events_for_transcript(
                        self.phrase, is_final=True, start_ns=0, end_ns=350_000_000
                    )
                )
                self._phrase_emitted = True
        except Exception as exc:
            self._mark_disconnected(str(exc) or "capture poll failure")
            if not self._disconnect_emitted:
                events.append(self._device_status("degraded", self._disconnect_detail))
                self._disconnect_emitted = True
        return events

    def ingest_block(self, samples: NDArray[np.floating], received_ns: int) -> list[EventEnvelope]:
        self.ring.push(samples, received_ns)
        events: list[EventEnvelope] = []
        was_speech = self.vad.in_speech
        utterances = self.vad.push_block(samples, received_ns)
        if self.vad.in_speech and not was_speech:
            events.append(self._device_status("healthy", "speech detected; waiting for pause"))
        for utterance in utterances:
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
            self._quality_event(quality=quality, grammar=parsed.grammar_match, end_ns=end_ns)
        )
        return events

    def heartbeat(self, uptime_seconds: float, dropped: int) -> EventEnvelope:
        # Historical ring overflows are counted but do not keep the mic degraded
        # forever after capture has started.
        silent = self._silence_warned and not self._stream_failed
        status = "degraded" if self._stream_failed or silent else "healthy"
        age_ms = None
        if self.ring.last_receive_ns is not None:
            age_ms = (time.monotonic_ns() - self.ring.last_receive_ns) / 1_000_000.0
        event = runtime_heartbeat(
            SOURCE,
            uptime_seconds=uptime_seconds,
            last_data_age_ms=age_ms,
            error_count=dropped + self.dropped_blocks + int(self.ring.overflows),
            sequence=self._next_seq(),
            status=status,
        )
        payload = dict(event.payload)
        payload.update(
            {
                "rms": round(self._last_rms, 5),
                "peak": round(self._last_peak, 5),
                "listening": self.vad.in_speech,
                "asr_backend": describe_asr(self.asr),
            }
        )
        return event.model_copy(update={"payload": payload})

    def _silence_watchdog(self) -> list[EventEnvelope]:
        if not self._capture_live or self._stream_failed:
            return []
        elapsed = time.monotonic() - self._capture_started_mono if self._capture_started_mono else 0.0
        if elapsed < SILENCE_WATCHDOG_S:
            return []
        if self.ring.last_receive_ns is None:
            if self._silence_warned:
                return []
            self._silence_warned = True
            return [
                self._device_status(
                    "degraded",
                    "microphone opened but no samples arrived",
                )
            ]
        if self._peak_since_start < SILENCE_PEAK:
            if self._silence_warned:
                return []
            self._silence_warned = True
            return [
                self._device_status(
                    "degraded",
                    "microphone is silent; grant Microphone permission to Terminal or Cursor in System Settings → Privacy & Security → Microphone",
                )
            ]
        if self._silence_warned:
            self._silence_warned = False
            backend = describe_asr(self.asr)
            detail = "microphone capture started"
            if backend:
                detail = f"{detail} ({backend})"
            return [self._device_status("healthy", detail)]
        return []

    def shutdown(self) -> EventEnvelope:
        return self._device_status("offline", "adapter stopping")

    def _events_for_utterance(self, utterance: CompletedUtterance) -> list[EventEnvelope]:
        events: list[EventEnvelope] = []
        try:
            if self.asr is not None:
                try:
                    result = self._run_asr(utterance.samples, self.sample_rate_hz)
                except Exception:
                    result = AsrResult(transcript="", confidence=None)
                if result.transcript:
                    events = self.events_for_transcript(
                        result.transcript,
                        is_final=True,
                        start_ns=utterance.start_ns,
                        end_ns=utterance.end_ns,
                        asr_confidence=result.confidence,
                    )
                else:
                    events = [
                        self._device_status("healthy", "heard speech; ASR returned no words")
                    ]
            elif self.phrase:
                if not self._phrase_emitted:
                    self._phrase_emitted = True
                    events = self.events_for_transcript(
                        self.phrase,
                        is_final=True,
                        start_ns=utterance.start_ns,
                        end_ns=utterance.end_ns,
                    )
            elif not self._asr_notice_sent:
                self._asr_notice_sent = True
                events = [self._device_status("degraded", "asr_unavailable")]
        finally:
            if self.research_recording and utterance.samples.size:
                self.session_pcm.append(utterance)
        return events

    def _run_asr(self, samples: NDArray[np.floating], sample_rate_hz: int) -> AsrResult:
        raw = self.asr(samples, sample_rate_hz) if self.asr is not None else ""
        if isinstance(raw, AsrResult):
            return AsrResult(transcript=raw.transcript.strip(), confidence=raw.confidence)
        if isinstance(raw, dict):
            return _asr_from_whisper_result(raw)
        if isinstance(raw, tuple) and len(raw) == 2:
            text, conf = raw
            return AsrResult(transcript=str(text).strip(), confidence=extract_asr_confidence(conf))
        return AsrResult(transcript=str(raw).strip(), confidence=None)

    def _on_audio(self, indata, frames, time_info, status) -> None:  # noqa: ANN001
        """Queue PCM only. ASR and parse run later in drain_capture/poll."""
        _ = frames, time_info
        try:
            if status:
                self.dropped_blocks += 1
            if indata is None:
                self._mark_disconnected("microphone stream ended")
                return
            received_ns = time.monotonic_ns()
            mono = np.asarray(indata, dtype=np.float32)
            if mono.ndim > 1:
                mono = mono[:, 0]
            if mono.size:
                peak = float(np.max(np.abs(mono)))
                rms = float(np.sqrt(np.mean(np.square(mono, dtype=np.float64))))
                with self._state_lock:
                    self._last_peak = peak
                    self._last_rms = rms
                    self._peak_since_start = max(self._peak_since_start, peak)
            block = (mono.copy(), received_ns)
            with self._pending_lock:
                if len(self._pending_blocks) >= self._pending_limit:
                    self._pending_blocks.popleft()
                    self.dropped_blocks += 1
                    self.ring.overflows += 1
                self._pending_blocks.append(block)
        except Exception as exc:
            self._mark_disconnected(str(exc) or "microphone stream failure")

    def drain_capture(self) -> list[EventEnvelope]:
        events: list[EventEnvelope] = []
        overflows_before = self.ring.overflows
        while True:
            with self._pending_lock:
                if not self._pending_blocks:
                    break
                samples, received_ns = self._pending_blocks.popleft()
            events.extend(self.ingest_block(samples, received_ns))
        if self.ring.overflows > overflows_before and not any(
            event.event_type == "data.quality" for event in events
        ):
            events.append(
                self._quality_event(
                    quality=0.4,
                    grammar=0.0,
                    end_ns=self.ring.last_receive_ns or 0,
                )
            )
        return events

    def _observe_stream(self) -> None:
        if not self._capture_live:
            return
        stream = self._stream
        if stream is None:
            self._mark_disconnected("microphone disconnected")
            return
        try:
            active = getattr(stream, "active", True)
            if callable(active):
                active = active()
        except Exception as exc:
            self._mark_disconnected(str(exc) or "microphone stream failure")
            return
        if not active:
            self._mark_disconnected("microphone disconnected")

    def _mark_disconnected(self, detail: str) -> None:
        with self._state_lock:
            self._stream_failed = True
            if detail:
                self._disconnect_detail = detail

    def _quality_event(self, *, quality: float, grammar: float, end_ns: int) -> EventEnvelope:
        flags = ["overflow"] if self.ring.overflows else []
        return make_event(
            event_type="data.quality",
            sequence=self._next_seq(),
            source_time_ns=end_ns,
            quality=quality,
            payload={
                "score": quality,
                "components": {"asr": quality, "grammar": grammar},
                "flags": flags,
            },
        )

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
                "metadata": {
                    "capture": "sounddevice",
                    "research_recording": self.research_recording,
                },
            },
        )

    def _next_seq(self) -> int:
        value = self.sequence
        self.sequence += 1
        return value
