from __future__ import annotations

import numpy as np
from audio_adapter.capture import AudioHardwareRuntime, segment_utterances
from audio_adapter.parser import parse_utterance
from intent_contracts.validation import parse_unnormalized_event


def _tone_and_silence(sample_rate: int = 16_000) -> np.ndarray:
    preroll = np.zeros(int(0.20 * sample_rate), dtype=np.float32)
    t = np.arange(int(0.50 * sample_rate), dtype=np.float32) / sample_rate
    tone = (0.3 * np.sin(2 * np.pi * 440.0 * t)).astype(np.float32)
    tail = np.zeros(int(0.70 * sample_rate), dtype=np.float32)
    return np.concatenate([preroll, tone, tail])


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
