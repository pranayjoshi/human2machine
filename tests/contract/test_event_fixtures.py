from pathlib import Path

from intent_contracts.commands import ActionCommand
from intent_contracts.validation import parse_event
import json

FIXTURES = Path("data/fixtures/events")


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def test_python_accepts_audio_fixture() -> None:
    parse_event(_load("audio_intent.json"))


def test_python_accepts_vision_fixture() -> None:
    parse_event(_load("vision_objects.json"))


def test_python_accepts_emg_fixture() -> None:
    parse_event(_load("emg_confirm.json"))


def test_python_accepts_intent_and_safety() -> None:
    parse_event(_load("intent_decision.json"))
    parse_event(_load("safety_decision.json"))


def test_python_accepts_eeg_and_heartbeat() -> None:
    parse_event(_load("eeg_chunk.json"))
    parse_event(_load("heartbeat.json"))


def test_action_command_roundtrip() -> None:
    command = ActionCommand.model_validate(_load("action_command.json"))
    assert command.action == "REQUEST_HANDOFF"
    dumped = json.loads(command.model_dump_json())
    ActionCommand.model_validate(dumped)


def test_rejects_invalid_probability() -> None:
    data = _load("audio_intent.json")
    data["payload"]["confidence"] = 1.4
    try:
        parse_event(data)
        raise AssertionError("expected invalid confidence to fail")
    except ValueError:
        pass


def test_rejects_future_major_schema() -> None:
    data = _load("audio_intent.json")
    data["schema_version"] = "2.0.0"
    try:
        parse_event(data)
        raise AssertionError("expected major version rejection")
    except Exception:
        pass


def test_integer_timestamps_preserved() -> None:
    event = parse_event(_load("audio_intent.json"))
    dumped = event.model_dump()
    assert isinstance(dumped["received_monotonic_ns"], int)
    assert dumped["event_id"] == "01jfxtest00000000000000001"
