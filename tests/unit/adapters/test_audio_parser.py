from __future__ import annotations

import json
from pathlib import Path

from audio_adapter.mock import AudioMockRuntime
from audio_adapter.parser import parse_utterance
from intent_contracts.validation import parse_unnormalized_event

SAFETY_PHRASES = [
    ("stop", "STOP"),
    ("STOP!", "STOP"),
    ("please stop", "STOP"),
    ("Stop that", "STOP"),
    ("emergency stop", "STOP"),
    ("halt", "STOP"),
    ("freeze", "STOP"),
    ("full stop", "STOP"),
    ("cancel", "CANCEL"),
    ("Cancel it", "CANCEL"),
    ("never mind", "CANCEL"),
    ("nevermind", "CANCEL"),
    ("don't do that", "CANCEL"),
    ("dont do that", "CANCEL"),
    ("do not do that", "CANCEL"),
    ("never mind the blue block", "CANCEL"),
    ("stop giving me the red one", "STOP"),
    ("forget it", "CANCEL"),
    ("scratch that", "CANCEL"),
    ("abort", "CANCEL"),
]

UNSUPPORTED = [
    "what is the weather",
    "play some music",
    "hello robot",
    "aaaa noise",
    "how's it going",
    "tell me a joke",
    "open the door",
]


def test_safety_phrases_are_stop_or_cancel() -> None:
    for transcript, expected in SAFETY_PHRASES:
        parsed = parse_utterance(transcript)
        assert parsed.action == expected, transcript


def test_scripted_safety_set_is_perfect() -> None:
    rows = json.loads(Path("data/fixtures/audio/scripted_utterances.json").read_text())
    safety = [row for row in rows if row["action"] in {"STOP", "CANCEL"}]
    assert safety
    for row in safety:
        parsed = parse_utterance(row["transcript"])
        assert parsed.action == row["action"]


def test_unsupported_language_is_unknown() -> None:
    for transcript in UNSUPPORTED:
        parsed = parse_utterance(transcript)
        assert parsed.action == "UNKNOWN", transcript


def test_named_and_deictic_targets() -> None:
    named = parse_utterance("give me the blue block")
    assert named.action == "REQUEST_HANDOFF"
    assert named.target_reference == "NAMED"
    assert named.target_object_id == "object_blue_1"
    like = parse_utterance("i'd like the red block")
    assert like.action == "REQUEST_HANDOFF"
    assert like.target_object_id == "object_red_1"
    deictic = parse_utterance("give me that one")
    assert deictic.action == "REQUEST_HANDOFF"
    assert deictic.target_reference == "DEICTIC"
    this_one = parse_utterance("give me this")
    assert this_one.target_reference == "DEICTIC"
    select = parse_utterance("pick the green block")
    assert select.action == "SELECT_OBJECT"
    assert select.target_object_id == "object_green_1"
    take = parse_utterance("take that one")
    assert take.action == "SELECT_OBJECT"
    assert take.target_reference == "DEICTIC"


def test_confirm_variants() -> None:
    for transcript in ("confirm", "yes", "okay", "go ahead", "that's right"):
        assert parse_utterance(transcript).action == "CONFIRM", transcript


def test_partials_are_never_final() -> None:
    events = AudioMockRuntime().collect()
    intents = [event for event in events if event.event_type == "audio.intent_candidate"]
    partials = [event for event in intents if event.payload["is_final"] is False]
    assert partials
    for event in partials:
        assert event.payload["is_final"] is False
        assert event.payload["confidence"] <= 0.4


def test_mock_audio_events_pass_unnormalized_contract() -> None:
    for event in AudioMockRuntime().collect():
        parse_unnormalized_event(event.to_unnormalized_dict())
