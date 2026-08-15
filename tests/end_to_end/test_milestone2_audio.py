"""Milestone 2 audio command evaluation. Grammar only; no microphone or ASR."""

from __future__ import annotations

import sys
from pathlib import Path

from audio_adapter.mock import AudioMockRuntime
from audio_adapter.parser import parse_utterance

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from eval_audio_commands import (  # noqa: E402
    ACCURACY_GATE,
    DEFAULT_FIXTURE,
    LATENCY_P95_GATE_S,
    SAFETY_RECALL_GATE,
    evaluate,
)

REQUIRED_CATEGORY_MINIMUMS = {
    "named_target": 25,
    "deictic": 25,
    "confirm_select_handoff": 20,
    "stop": 10,
    "cancel": 10,
    "unknown": 10,
}


def test_milestone2_fixture_covers_required_classes() -> None:
    result = evaluate(DEFAULT_FIXTURE)
    assert result.n >= 100, result.n
    for name, minimum in REQUIRED_CATEGORY_MINIMUMS.items():
        assert result.category_counts.get(name, 0) >= minimum, (name, result.category_counts)


def test_action_accuracy_and_safety_recall_gates() -> None:
    result = evaluate(DEFAULT_FIXTURE)
    assert result.action_accuracy >= ACCURACY_GATE, (
        result.action_accuracy,
        result.failures[:10],
    )
    assert result.stop_cancel_recall >= SAFETY_RECALL_GATE, (
        result.stop_cancel_recall,
        result.safety_hits,
        result.safety_n,
    )
    assert result.latency_p95_s < LATENCY_P95_GATE_S, result.latency_p95_s


def test_unsupported_language_is_unknown_not_invented() -> None:
    result = evaluate(DEFAULT_FIXTURE)
    assert result.unknown_n >= 10
    assert result.unknown_hits == result.unknown_n
    for row in _unknown_rows():
        parsed = parse_utterance(row["transcript"])
        assert parsed.action == "UNKNOWN", row["transcript"]
        assert parsed.action not in {"REQUEST_HANDOFF", "SELECT_OBJECT", "CONFIRM"}


def test_stop_and_cancel_win_over_other_intents() -> None:
    stop = parse_utterance("stop giving me the red one")
    assert stop.action == "STOP"
    cancel = parse_utterance("never mind the blue block")
    assert cancel.action == "CANCEL"


def test_partial_transcripts_do_not_commit_actions() -> None:
    events = AudioMockRuntime().collect()
    intents = [event for event in events if event.event_type == "audio.intent_candidate"]
    partials = [event for event in intents if event.payload["is_final"] is False]
    assert partials
    for event in partials:
        assert event.payload["is_final"] is False
        assert event.payload["confidence"] <= 0.4


def _unknown_rows() -> list[dict]:
    import json

    rows = json.loads(DEFAULT_FIXTURE.read_text())
    return [row for row in rows if row["action"] == "UNKNOWN"]
