"""Milestone 2 audio runtime: disconnect, overflow, max utterance, privacy.

In-process only. Does not open a microphone or download an ASR model.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
for extra in (
    ROOT / "packages/contracts-python/src",
    ROOT / "packages/runtime-python/src",
    ROOT / "services/audio-adapter",
):
    sys.path.insert(0, str(extra))

from audio_adapter.capture import (  # noqa: E402
    AudioHardwareRuntime,
    RingBuffer,
    event_contains_raw_audio,
    segment_utterances,
)
from audio_adapter.publisher import ListSink  # noqa: E402
from intent_contracts.validation import parse_unnormalized_event  # noqa: E402


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
    last_instance: FakeStream | None = None

    def __init__(self, **kwargs) -> None:
        self.callback = kwargs.get("callback")
        self._active = True
        self._raise_on_active = False
        FakeStream.last_instance = self

    def start(self) -> None:
        self._active = True

    def stop(self) -> None:
        self._active = False

    def close(self) -> None:
        self._active = False

    @property
    def active(self) -> bool:
        if self._raise_on_active:
            raise RuntimeError("device disconnected")
        return self._active

    def disconnect(self) -> None:
        self._active = False
        self._raise_on_active = True
        if self.callback is not None:
            try:
                self.callback(None, 0, None, "abort")
            except Exception:
                pass


def test_disconnect_emits_degraded_status_and_keeps_polling() -> None:
    runtime = AudioHardwareRuntime(
        resolve_backend=False,
        asr=lambda _audio, _sr: "stop",
        stream_factory=FakeStream,
    )
    sink = ListSink()
    runtime.start()
    stream = FakeStream.last_instance
    assert stream is not None
    stream.disconnect()
    for _ in range(3):
        for event in runtime.poll():
            sink.send_event(event)
    statuses = [event for event in sink.events if event["event_type"] == "device.status"]
    assert statuses
    assert any(event["payload"]["status"] == "degraded" for event in statuses)
    for event in sink.events:
        parse_unnormalized_event(event)


def test_overflow_flags_quality() -> None:
    runtime = AudioHardwareRuntime(resolve_backend=False, asr=lambda _a, _sr: "stop")
    runtime.ring = RingBuffer(sample_rate_hz=16_000, seconds=0.05)
    runtime.ring.push(np.ones(runtime.ring.capacity + 64, dtype=np.float32), 1)
    assert runtime.ring.overflows > 0
    events = runtime.events_for_transcript("stop", is_final=True, start_ns=0, end_ns=2_000)
    quality = [event for event in events if event.event_type == "data.quality"]
    assert quality
    assert "overflow" in quality[0].payload["flags"]
    for event in events:
        parse_unnormalized_event(event.to_unnormalized_dict())


def test_max_utterance_closes_long_tone() -> None:
    sr = 16_000
    max_ms = 400
    utterances = segment_utterances(
        _long_tone(1.5, sr),
        sample_rate_hz=sr,
        max_utterance_ms=max_ms,
    )
    assert utterances
    for utterance in utterances:
        duration_ms = 1000.0 * utterance.samples.size / sr
        assert duration_ms <= max_ms + 40.0


def test_events_do_not_contain_raw_audio() -> None:
    runtime = AudioHardwareRuntime(
        resolve_backend=False,
        asr=lambda _audio, _sr: "stop",
        use_webrtc=False,
    )
    sink = ListSink()
    events = runtime.poll()
    events.extend(runtime.ingest_block(_tone_and_silence(), 1_000_000_000))
    for event in events:
        payload = event.to_unnormalized_dict()
        sink.send_event(event)
        parse_unnormalized_event(payload)
        assert not event_contains_raw_audio(event)
        assert "pcm" not in event.payload
        assert "samples" not in event.payload
        assert "waveform" not in event.payload
        dumped = str(payload)
        assert "audio_pcm" not in dumped
    assert runtime.session_pcm == []
    assert any(event.event_type == "audio.intent_candidate" for event in events)
