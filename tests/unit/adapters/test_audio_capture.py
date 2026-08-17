from __future__ import annotations

import time

import numpy as np
from audio_adapter.capture import (
    AsrResult,
    AudioHardwareRuntime,
    RingBuffer,
    describe_asr,
    event_contains_raw_audio,
    extract_asr_confidence,
    segment_utterances,
)
from audio_adapter.parser import parse_utterance
from intent_contracts.validation import parse_unnormalized_event


def _tone_and_silence(sample_rate: int = 16_000) -> np.ndarray:
    preroll = np.zeros(int(0.20 * sample_rate), dtype=np.float32)
    t = np.arange(int(0.50 * sample_rate), dtype=np.float32) / sample_rate
    tone = (0.3 * np.sin(2 * np.pi * 440.0 * t)).astype(np.float32)
    tail = np.zeros(int(0.70 * sample_rate), dtype=np.float32)
    return np.concatenate([preroll, tone, tail])


def _long_tone(duration_s: float, sample_rate: int = 16_000) -> np.ndarray:
    t = np.arange(int(duration_s * sample_rate), dtype=np.float32) / sample_rate
    return (0.3 * np.sin(2 * np.pi * 440.0 * t)).astype(np.float32)


class FakeStream:
    """sounddevice.InputStream stand-in that can stop or raise on disconnect."""

    last_instance: FakeStream | None = None

    def __init__(self, **kwargs) -> None:
        self.callback = kwargs.get("callback")
        self.kwargs = kwargs
        self._active = True
        self._raise_on_active = False
        self.started = False
        self.stopped = False
        self.closed = False
        FakeStream.last_instance = self

    def start(self) -> None:
        self.started = True
        self._active = True

    def stop(self) -> None:
        self._active = False
        self.stopped = True

    def close(self) -> None:
        self._active = False
        self.closed = True

    @property
    def active(self) -> bool:
        if self._raise_on_active:
            raise RuntimeError("device disconnected")
        return self._active

    def disconnect(self, *, raise_on_poll: bool = False) -> None:
        self._active = False
        self._raise_on_active = raise_on_poll
        if self.callback is not None:
            try:
                self.callback(np.zeros((0, 1), dtype=np.float32), 0, None, "abort")
            except Exception:
                pass


def test_vad_segments_tone_between_silence() -> None:
    sr = 16_000
    audio = _tone_and_silence(sr)
    utterances = segment_utterances(audio, sample_rate_hz=sr)
    assert len(utterances) == 1
    duration_s = utterances[0].samples.size / sr
    assert duration_s >= 0.45
    assert duration_s <= 1.6
    # preroll should keep some leading silence so onsets are not clipped
    leading = utterances[0].samples[: int(0.05 * sr)]
    assert float(np.max(np.abs(leading))) < 0.05


def test_parser_still_perfect_on_stop_and_cancel() -> None:
    for transcript, expected in (
        ("stop", "STOP"),
        ("emergency stop", "STOP"),
        ("cancel", "CANCEL"),
        ("never mind", "CANCEL"),
        ("don't do that", "CANCEL"),
    ):
        assert parse_utterance(transcript).action == expected


def test_phrase_fallback_parses_without_inventing_asr() -> None:
    runtime = AudioHardwareRuntime(phrase="stop", resolve_backend=False, asr=None)
    events = runtime.poll()
    parse_unnormalized_event(events[0].to_unnormalized_dict())
    finals = [
        event
        for event in events
        if event.event_type == "audio.intent_candidate" and event.payload["is_final"] is True
    ]
    partials = [
        event
        for event in events
        if event.event_type == "audio.intent_candidate" and event.payload["is_final"] is False
    ]
    assert finals
    assert finals[0].payload["action"] == "STOP"
    assert partials
    assert all(event.payload["is_final"] is False for event in partials)
    assert "normalized_time_ns" not in events[0].to_unnormalized_dict()


def test_asr_unavailable_does_not_invent_transcripts() -> None:
    runtime = AudioHardwareRuntime(resolve_backend=False, asr=None)
    events = runtime.poll()
    statuses = [event for event in events if event.event_type == "device.status"]
    assert statuses
    assert statuses[0].payload["status"] == "degraded"
    assert statuses[0].payload["detail"] == "asr_unavailable"
    assert not [event for event in events if event.event_type == "audio.intent_candidate"]


def test_fake_stream_disconnect_emits_degraded_without_crashing_poll() -> None:
    runtime = AudioHardwareRuntime(
        resolve_backend=False,
        asr=lambda _audio, _sr: "stop",
        stream_factory=FakeStream,
    )
    runtime.start()
    stream = FakeStream.last_instance
    assert stream is not None
    stream.disconnect(raise_on_poll=True)
    first = runtime.poll()
    second = runtime.poll()
    third = runtime.poll()
    statuses = [event for event in [*first, *second, *third] if event.event_type == "device.status"]
    assert any(event.payload["status"] == "degraded" for event in statuses)
    assert any("disconnect" in str(event.payload.get("detail", "")).lower() for event in statuses)


def test_slow_asr_does_not_run_inside_on_audio() -> None:
    calls: list[str] = []

    def slow_asr(audio, sample_rate_hz):
        _ = audio, sample_rate_hz
        calls.append("asr")
        time.sleep(0.15)
        return "stop"

    runtime = AudioHardwareRuntime(resolve_backend=False, asr=slow_asr, use_webrtc=False)
    block = (0.3 * np.ones((320, 1), dtype=np.float32)).astype(np.float32)
    started = time.perf_counter()
    runtime._on_audio(block, 320, None, None)
    elapsed = time.perf_counter() - started
    assert calls == []
    assert elapsed < 0.05
    runtime.drain_capture()
    # One 20 ms block is not a completed utterance; ASR must still not have run
    # until an utterance is closed. Feed a full tone through drain only.
    runtime.ingest_block(_tone_and_silence(), 1_000_000_000)
    assert "asr" in calls


def test_missing_asr_confidence_is_passed_as_none(monkeypatch) -> None:
    seen: list[float | None] = []

    def spy(transcript: str, *, asr_confidence: float | None = None):
        seen.append(asr_confidence)
        return parse_utterance(transcript, asr_confidence=asr_confidence)

    monkeypatch.setattr("audio_adapter.capture.parse_utterance", spy)
    runtime = AudioHardwareRuntime(
        resolve_backend=False,
        asr=lambda _audio, _sr: "cancel",
        use_webrtc=False,
    )
    runtime.ingest_block(_tone_and_silence(), 1_000_000_000)
    assert seen
    assert seen[0] is None


def test_whisper_wrap_does_not_fabricate_high_confidence(monkeypatch) -> None:
    assert extract_asr_confidence({"text": "stop"}) is None
    assert extract_asr_confidence({"text": "stop", "segments": [{"avg_logprob": -0.05}]}) is None
    seen: list[float | None] = []

    def spy(transcript: str, *, asr_confidence: float | None = None):
        seen.append(asr_confidence)
        return parse_utterance(transcript, asr_confidence=asr_confidence)

    monkeypatch.setattr("audio_adapter.capture.parse_utterance", spy)
    runtime = AudioHardwareRuntime(
        resolve_backend=False,
        asr=lambda _audio, _sr: {"text": "cancel", "segments": [{"avg_logprob": -0.01}]},
        use_webrtc=False,
    )
    runtime.ingest_block(_tone_and_silence(), 1_000_000_000)
    assert seen
    assert seen[0] is None


def test_explicit_asr_confidence_is_forwarded(monkeypatch) -> None:
    seen: list[float | None] = []

    def spy(transcript: str, *, asr_confidence: float | None = None):
        seen.append(asr_confidence)
        return parse_utterance(transcript, asr_confidence=asr_confidence)

    monkeypatch.setattr("audio_adapter.capture.parse_utterance", spy)
    runtime = AudioHardwareRuntime(
        resolve_backend=False,
        asr=lambda _audio, _sr: AsrResult("cancel", 0.42),
        use_webrtc=False,
    )
    runtime.ingest_block(_tone_and_silence(), 1_000_000_000)
    assert seen
    assert seen[0] == 0.42


def test_ring_overflow_increments_and_flags_quality() -> None:
    buf = RingBuffer(sample_rate_hz=16_000, seconds=0.05)
    buf.push(np.ones(400, dtype=np.float32), 1)
    assert buf.overflows == 0
    buf.push(np.ones(500, dtype=np.float32), 2)
    assert buf.overflows >= 1

    runtime = AudioHardwareRuntime(resolve_backend=False, asr=lambda _a, _sr: "stop")
    runtime.ring = RingBuffer(sample_rate_hz=16_000, seconds=0.05)
    runtime.ring.push(np.ones(runtime.ring.capacity + 32, dtype=np.float32), 3)
    assert runtime.ring.overflows > 0
    events = runtime.events_for_transcript("stop", is_final=True, start_ns=0, end_ns=1_000)
    quality = [event for event in events if event.event_type == "data.quality"]
    assert quality
    assert "overflow" in quality[0].payload["flags"]


def test_heartbeat_is_healthy_when_mic_is_live_even_after_overflow() -> None:
    runtime = AudioHardwareRuntime(resolve_backend=False, asr=lambda _a, _sr: "stop")
    runtime.ring = RingBuffer(sample_rate_hz=16_000, seconds=0.05)
    runtime.ring.push(np.ones(runtime.ring.capacity + 32, dtype=np.float32), 3)
    event = runtime.heartbeat(1.0, dropped=0)
    assert event.payload["status"] == "healthy"
    assert event.payload["error_count"] >= 1
    runtime._stream_failed = True
    failed = runtime.heartbeat(2.0, dropped=0)
    assert failed.payload["status"] == "degraded"


def test_long_tone_is_closed_at_max_utterance_ms() -> None:
    sr = 16_000
    max_ms = 400
    utterances = segment_utterances(
        _long_tone(1.6, sr),
        sample_rate_hz=sr,
        max_utterance_ms=max_ms,
    )
    assert utterances
    for utterance in utterances:
        duration_ms = 1000.0 * utterance.samples.size / sr
        assert duration_ms <= max_ms + 40.0


def test_default_path_discards_pcm_after_parse() -> None:
    runtime = AudioHardwareRuntime(
        resolve_backend=False,
        asr=lambda _audio, _sr: "stop",
        use_webrtc=False,
    )
    events = runtime.ingest_block(_tone_and_silence(), 1_000_000_000)
    assert runtime.session_pcm == []
    assert events
    assert all(not event_contains_raw_audio(event) for event in events)


def test_empty_asr_is_visible_as_device_status() -> None:
    runtime = AudioHardwareRuntime(
        resolve_backend=False,
        asr=lambda _audio, _sr: "",
        use_webrtc=False,
    )
    events = runtime.ingest_block(_tone_and_silence(), 1_000_000_000)
    statuses = [event for event in events if event.event_type == "device.status"]
    assert any("ASR returned no words" in str(event.payload.get("detail", "")) for event in statuses)
    assert not [event for event in events if event.event_type == "audio.intent_candidate"]


def test_silent_microphone_is_reported_by_watchdog() -> None:
    runtime = AudioHardwareRuntime(
        resolve_backend=False,
        asr=lambda _audio, _sr: "stop",
        stream_factory=FakeStream,
        use_webrtc=False,
    )
    runtime.start()
    zeros = np.zeros((320, 1), dtype=np.float32)
    for _ in range(8):
        runtime._on_audio(zeros, 320, None, None)
    runtime._capture_started_mono = time.monotonic() - 3.0
    events = runtime.poll()
    statuses = [event for event in events if event.event_type == "device.status"]
    assert any("silent" in str(event.payload.get("detail", "")).lower() for event in statuses)
    beat = runtime.heartbeat(3.0, dropped=0)
    assert beat.payload["status"] == "degraded"
    assert beat.payload["rms"] == 0.0
    assert beat.payload["asr_backend"] == "local-asr"


def test_describe_asr_names_mlx_wrapper() -> None:
    assert describe_asr(None) is None
    assert describe_asr(lambda _audio, _sr: "stop") == "local-asr"


def test_research_recording_keeps_pcm_in_memory_only() -> None:
    runtime = AudioHardwareRuntime(
        resolve_backend=False,
        asr=lambda _audio, _sr: "stop",
        use_webrtc=False,
        research_recording=True,
    )
    events = runtime.ingest_block(_tone_and_silence(), 1_000_000_000)
    assert runtime.session_pcm
    assert runtime.session_pcm[0].samples.size > 0
    assert all(not event_contains_raw_audio(event) for event in events)
    assert all("pcm" not in event.payload for event in events)
    assert all("samples" not in event.payload for event in events)
