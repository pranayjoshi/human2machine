"""Unit checks for scripts/demo_mvp.py event construction. No live sockets."""

from __future__ import annotations

import sys
from pathlib import Path

from intent_contracts.validation import parse_unnormalized_event

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from demo_mvp import build_scenario_events, demo_passed  # noqa: E402
from run_stack import is_optional_stack_child, stack_commands  # noqa: E402

NOW_NS = 100_000_000


def _by_type(events: list[dict]) -> dict[str, dict]:
    return {str(event["event_type"]): event for event in events}


def test_success_events_parse_unnormalized() -> None:
    events = build_scenario_events(
        "success",
        session_id="session_demo",
        trial_id="trial_demo",
        now_ns=NOW_NS,
    )
    types = [event["event_type"] for event in events]
    assert "vision.objects" in types
    assert "audio.intent_candidate" in types
    assert "modality.feature" in types
    for event in events:
        assert "normalized_time_ns" not in event
        parsed = parse_unnormalized_event(event)
        assert parsed.normalized_time_ns is None
        assert parsed.session_id == "session_demo"
        assert parsed.trial_id == "trial_demo"


def test_success_payload_shapes() -> None:
    events = _by_type(build_scenario_events("success", session_id="s", trial_id="t", now_ns=NOW_NS))
    vision = events["vision.objects"]["payload"]
    assert any(
        candidate["object_id"] == "object_blue_1" for candidate in vision["pointing_candidates"]
    )
    assert {obj["object_id"] for obj in vision["objects"]} >= {
        "object_blue_1",
        "object_red_1",
    }
    audio = events["audio.intent_candidate"]["payload"]
    assert audio["action"] == "REQUEST_HANDOFF"
    assert audio["target_reference"] == "DEICTIC"
    assert audio["is_final"] is True
    emg = events["modality.feature"]["payload"]
    assert emg["feature_name"] == "emg_gesture"
    assert emg["label"] == "confirm"
    assert emg["confidence"] == 0.91


def test_conflict_spoken_vs_pointed() -> None:
    events = _by_type(
        build_scenario_events("conflict", session_id="s", trial_id="t", now_ns=NOW_NS)
    )
    for event in events.values():
        parse_unnormalized_event(event)
    audio = events["audio.intent_candidate"]["payload"]
    assert audio["action"] == "REQUEST_HANDOFF"
    assert audio["target_reference"] == "NAMED"
    assert audio["target_object_id"] == "object_blue_1"
    pointing = events["vision.objects"]["payload"]["pointing_candidates"]
    assert pointing[0]["object_id"] == "object_red_1"


def test_cancel_audio_parses() -> None:
    events = build_scenario_events("cancel", session_id="s", trial_id="t", now_ns=NOW_NS)
    for event in events:
        parse_unnormalized_event(event)
        assert "normalized_time_ns" not in event
    audio = _by_type(events)["audio.intent_candidate"]["payload"]
    assert audio["action"] == "CANCEL"
    assert audio["transcript"] == "cancel"


def test_demo_pass_criteria() -> None:
    assert demo_passed("APPROVE", "COMPLETED", "success")
    assert demo_passed("ASK_CONFIRMATION", None, "success")
    assert not demo_passed("HOLD", None, "success")
    assert not demo_passed("APPROVE", None, "success")
    assert demo_passed("APPROVE", None, "cancel")
    assert demo_passed("APPROVE", "CANCELLED", "cancel")
    assert demo_passed("ASK_CONFIRMATION", None, "conflict")


def _joined(mock: bool) -> list[str]:
    return [" ".join(command) for command in stack_commands("python", mock=mock)]


def test_mock_stack_passes_mock_to_every_service() -> None:
    rows = _joined(True)
    assert any("fusion_runtime.main --mock" in row for row in rows)
    assert any("ganglion_adapter.main --mock" in row for row in rows)
    assert any("crown_adapter.main --mock" in row for row in rows)


def test_hardware_stack_keeps_simulator_loop_on_mock() -> None:
    rows = _joined(False)
    for service in ("fusion_runtime.main", "safety_gateway.main", "robot_simulator.main"):
        assert any(f"{service} --mock" in row for row in rows)
        assert not any(f"{service} --hardware" in row for row in rows)
    for service in ("ganglion_adapter.main", "audio_adapter.main", "vision_adapter.main", "crown_adapter.main"):
        assert any(f"{service} --hardware" in row for row in rows)


def test_crown_adapter_is_optional_only_in_hardware_stack() -> None:
    hardware = stack_commands("python", mock=False)
    mock = stack_commands("python", mock=True)
    crown_hw = next(cmd for cmd in hardware if "crown_adapter.main" in cmd)
    crown_mock = next(cmd for cmd in mock if "crown_adapter.main" in cmd)
    assert is_optional_stack_child(crown_hw, mock=False)
    assert not is_optional_stack_child(crown_mock, mock=True)
    ganglion = next(cmd for cmd in hardware if "ganglion_adapter.main" in cmd)
    assert is_optional_stack_child(ganglion, mock=False)
    assert not is_optional_stack_child(ganglion, mock=True)
