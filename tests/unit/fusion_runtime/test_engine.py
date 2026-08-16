# ruff: noqa: E402
from __future__ import annotations

import importlib.util
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

_spec = importlib.util.spec_from_file_location(
    "_fusion_runtime_path_setup", Path(__file__).with_name("path_setup.py")
)
assert _spec and _spec.loader
_spec.loader.exec_module(importlib.util.module_from_spec(_spec))

from fusion_runtime.engine import FusionConfig, FusionRuntimeState, UserProfile, step
from intent_contracts.enums import EventType, FusionState, IntentStatus, MachineState
from intent_contracts.events import IntentDecisionPayload
from intent_contracts.validation import parse_unnormalized_event

NOW_NS = 100_000_000
CONFIG = FusionConfig(emg_shadow_only=False)
M1_CONFIG = FusionConfig()  # emg_shadow_only defaults True


def _envelope(
    event_id: str,
    event_type: str,
    payload: dict[str, Any],
    *,
    modality: str | None,
    sequence: int,
    time_ns: int,
    quality: float = 1.0,
    session_id: str | None = "session_test",
    trial_id: str | None = "trial_test",
    source: str = "fixture",
) -> dict[str, Any]:
    if len(event_id) < 8:
        event_id = event_id.ljust(8, "0")
    return {
        "schema_version": "1.0.0",
        "event_id": event_id,
        "event_type": event_type,
        "source": source,
        "modality": modality,
        "session_id": session_id,
        "trial_id": trial_id,
        "sequence": sequence,
        "source_time_ns": time_ns,
        "received_monotonic_ns": time_ns,
        "normalized_time_ns": time_ns,
        "quality": quality,
        "producer_version": "0.1.0",
        "payload": payload,
    }


def session_started(time_ns: int = 1_000_000) -> dict[str, Any]:
    return _envelope(
        "evt_session_1",
        EventType.SESSION_STARTED,
        {"state": "RECORDING", "contract_version": "1.0.0"},
        modality=None,
        sequence=0,
        time_ns=time_ns,
        source="event-hub",
    )


def machine_ready(time_ns: int = 2_000_000) -> dict[str, Any]:
    return _envelope(
        "evt_machine_1",
        EventType.MACHINE_STATE,
        {"state": MachineState.READY, "progress": 0.0},
        modality="machine",
        sequence=1,
        time_ns=time_ns,
        source="robot-simulator",
    )


def audio_intent(
    event_id: str,
    *,
    action: str,
    target_reference: str = "NONE",
    target_object_id: str | None = None,
    confidence: float = 0.94,
    time_ns: int = 50_000_000,
    quality: float = 0.94,
    is_final: bool = True,
    transcript: str = "give me that one",
) -> dict[str, Any]:
    return _envelope(
        event_id,
        EventType.AUDIO_INTENT_CANDIDATE,
        {
            "transcript": transcript,
            "is_final": is_final,
            "action": action,
            "target_reference": target_reference,
            "target_object_id": target_object_id,
            "confidence": confidence,
            "utterance_start_ns": max(0, time_ns - 10_000_000),
            "utterance_end_ns": time_ns,
            "model_id": "local-asr-v1",
        },
        modality="audio",
        sequence=10,
        time_ns=time_ns,
        quality=quality,
        source="audio-adapter",
    )


def vision_objects(
    event_id: str,
    *,
    pointing: list[dict[str, Any]] | None = None,
    head: list[dict[str, Any]] | None = None,
    object_ids: tuple[str, ...] = ("object_blue_1", "object_red_1"),
    time_ns: int = 60_000_000,
    quality: float = 0.95,
) -> dict[str, Any]:
    objects = [
        {
            "object_id": object_id,
            "class_name": object_id.replace("object_", "").replace("_1", "_block"),
            "confidence": 0.98,
            "bbox_xyxy": [0.0, 0.0, 1.0, 1.0],
            "table_position_xy": [0.3, 0.5],
        }
        for object_id in object_ids
    ]
    return _envelope(
        event_id,
        EventType.VISION_OBJECTS,
        {
            "frame_id": 1,
            "objects": objects,
            "pointing_candidates": pointing or [],
            "head_direction_candidates": head or [],
        },
        modality="vision",
        sequence=20,
        time_ns=time_ns,
        quality=quality,
        source="vision-adapter",
    )


def emg_feature(
    event_id: str,
    *,
    label: str,
    confidence: float = 0.91,
    time_ns: int = 80_000_000,
    quality: float = 0.91,
    scores: dict[str, float] | None = None,
) -> dict[str, Any]:
    default_scores = {"rest": 0.04, "confirm": 0.91, "cancel": 0.05}
    if label == "cancel":
        default_scores = {"rest": 0.04, "confirm": 0.05, "cancel": confidence}
    elif label == "unknown":
        default_scores = {"rest": 0.4, "confirm": 0.3, "cancel": 0.3}
    return _envelope(
        event_id,
        EventType.MODALITY_FEATURE,
        {
            "feature_name": "emg_gesture",
            "window_start_ns": max(0, time_ns - 5_000_000),
            "window_end_ns": time_ns,
            "label": label,
            "confidence": confidence,
            "candidate_scores": scores or default_scores,
            "model_id": "emg-primary-user-v3",
            "shadow_only": False,
        },
        modality="emg",
        sequence=40,
        time_ns=time_ns,
        quality=quality,
        source="ganglion-emg",
    )


def eeg_shadow(
    event_id: str = "evt_eeg_1",
    *,
    confidence: float = 0.99,
    time_ns: int = 70_000_000,
    quality: float = 0.99,
) -> dict[str, Any]:
    return _envelope(
        event_id,
        EventType.MODALITY_FEATURE,
        {
            "feature_name": "eeg_shadow",
            "window_start_ns": max(0, time_ns - 5_000_000),
            "window_end_ns": time_ns,
            "label": "ready",
            "confidence": confidence,
            "candidate_scores": {"ready": confidence},
            "model_id": "eeg-shadow-v1",
            "shadow_only": True,
        },
        modality="eeg",
        sequence=30,
        time_ns=time_ns,
        quality=quality,
        source="crown-eeg",
    )


def fresh_state() -> FusionRuntimeState:
    return FusionRuntimeState()


def run(window: list[dict[str, Any]], *, now_ns: int = NOW_NS, config: FusionConfig = CONFIG):
    return step(fresh_state(), window, UserProfile(), config, now_ns=now_ns)


def decisions(result) -> list[dict[str, Any]]:
    return [
        event.payload for event in result.events if event.event_type == EventType.INTENT_DECISION
    ]


def conflicts(result) -> list[dict[str, Any]]:
    return [
        event.payload for event in result.events if event.event_type == EventType.INTENT_CONFLICT
    ]


def event_types(result) -> list[str]:
    return [str(event.event_type) for event in result.events]


HAPPY_WINDOW = [
    session_started(),
    machine_ready(),
    audio_intent("evt_audio_1", action="REQUEST_HANDOFF", target_reference="DEICTIC"),
    vision_objects(
        "evt_vision_1",
        pointing=[{"object_id": "object_blue_1", "confidence": 0.82}],
    ),
    emg_feature("evt_emg_01", label="confirm"),
]


@pytest.mark.parametrize(
    ("name", "window", "check"),
    [
        (
            "happy_path_commits",
            HAPPY_WINDOW,
            "happy",
        ),
        (
            "audio_cancel_proposes_cancel",
            [
                session_started(),
                machine_ready(),
                audio_intent(
                    "evt_cancel1",
                    action="CANCEL",
                    transcript="cancel",
                    confidence=0.99,
                    quality=0.99,
                ),
            ],
            "cancel",
        ),
        (
            "audio_stop_proposes_stop",
            [
                session_started(),
                machine_ready(),
                audio_intent(
                    "evt_stop_1",
                    action="STOP",
                    transcript="stop",
                    confidence=0.99,
                    quality=0.99,
                ),
            ],
            "stop",
        ),
        (
            "emg_cancel_proposes_cancel",
            [
                session_started(),
                machine_ready(),
                audio_intent("evt_audio_1", action="REQUEST_HANDOFF", target_reference="DEICTIC"),
                vision_objects(
                    "evt_vision_1",
                    pointing=[{"object_id": "object_blue_1", "confidence": 0.82}],
                ),
                emg_feature("evt_emg_cancel", label="cancel", confidence=0.93),
            ],
            "cancel",
        ),
        (
            "deictic_without_pointing_does_not_commit",
            [
                session_started(),
                machine_ready(),
                audio_intent("evt_audio", action="REQUEST_HANDOFF", target_reference="DEICTIC"),
                vision_objects("evt_vision", pointing=[]),
            ],
            "deictic",
        ),
        (
            "spoken_versus_pointing_conflict",
            [
                session_started(),
                machine_ready(),
                audio_intent(
                    "evt_audio",
                    action="REQUEST_HANDOFF",
                    target_reference="NAMED",
                    target_object_id="object_blue_1",
                    transcript="give me the blue block",
                ),
                vision_objects(
                    "evt_vision",
                    pointing=[{"object_id": "object_red_1", "confidence": 0.88}],
                ),
            ],
            "spoken_pointed",
        ),
        (
            "close_target_margin_conflict",
            [
                session_started(),
                machine_ready(),
                audio_intent("evt_audio", action="REQUEST_HANDOFF", target_reference="DEICTIC"),
                vision_objects(
                    "evt_vision",
                    pointing=[
                        {"object_id": "object_blue_1", "confidence": 0.70},
                        {"object_id": "object_red_1", "confidence": 0.68},
                    ],
                ),
            ],
            "margin",
        ),
        (
            "confirm_and_cancel_conflict",
            [
                session_started(),
                machine_ready(),
                audio_intent(
                    "evt_audio_confirm",
                    action="CONFIRM",
                    transcript="yes",
                    time_ns=50_000_000,
                ),
                audio_intent(
                    "evt_audio_req",
                    action="REQUEST_HANDOFF",
                    target_reference="DEICTIC",
                    time_ns=52_000_000,
                ),
                vision_objects(
                    "evt_vision",
                    pointing=[{"object_id": "object_blue_1", "confidence": 0.82}],
                ),
                emg_feature("evt_emg_cancel", label="cancel", confidence=0.93),
            ],
            "confirm_cancel",
        ),
        (
            "no_session_no_decision",
            [
                machine_ready(),
                audio_intent(
                    "evt_audio",
                    action="REQUEST_HANDOFF",
                    target_reference="NAMED",
                    target_object_id="object_blue_1",
                ),
                vision_objects(
                    "evt_vision",
                    pointing=[{"object_id": "object_blue_1", "confidence": 0.82}],
                ),
                emg_feature("evt_emg", label="confirm"),
            ],
            "no_session",
        ),
        (
            "machine_not_ready_no_commit",
            [
                session_started(),
                _envelope(
                    "evt_machine_idle",
                    EventType.MACHINE_STATE,
                    {"state": MachineState.IDLE, "progress": 0.0},
                    modality="machine",
                    sequence=1,
                    time_ns=2_000_000,
                    source="robot-simulator",
                ),
                audio_intent(
                    "evt_audio",
                    action="REQUEST_HANDOFF",
                    target_reference="NAMED",
                    target_object_id="object_blue_1",
                ),
                vision_objects(
                    "evt_vision",
                    pointing=[{"object_id": "object_blue_1", "confidence": 0.82}],
                ),
                emg_feature("evt_emg", label="confirm"),
            ],
            "not_ready",
        ),
    ],
)
def test_engine_table(name: str, window: list[dict[str, Any]], check: str) -> None:
    result = run(window)
    dumped = [event.model_dump(mode="json") for event in result.events]
    for item in dumped:
        parse_unnormalized_event(item)
        assert item["event_type"] != "action.command"
        assert "ActionCommand" not in str(item)

    payloads = decisions(result)
    conflict_payloads = conflicts(result)

    if check == "happy":
        assert payloads
        decision = payloads[-1]
        IntentDecisionPayload.model_validate(decision)
        assert decision["action"] == "REQUEST_HANDOFF"
        assert decision["target_object_id"] == "object_blue_1"
        assert decision["fusion_state"] == FusionState.COMMIT_PROPOSED
        assert {item["event_id"] for item in decision["evidence"]} >= {
            "evt_audio_1",
            "evt_vision_1",
            "evt_emg_01",
        }
        assert decision["expires_at_ns"] == NOW_NS + CONFIG.decision_ttl_ms * 1_000_000
    elif check == "cancel":
        assert payloads
        decision = payloads[-1]
        assert decision["action"] == "CANCEL"
        assert decision["status"] == IntentStatus.CANCELLED
        assert decision["fusion_state"] == FusionState.CANCELLED
        assert result.state.fusion_state == FusionState.IDLE
    elif check == "stop":
        assert payloads
        decision = payloads[-1]
        assert decision["action"] == "STOP"
        assert decision["status"] == IntentStatus.CANCELLED
    elif check == "deictic":
        assert FusionState.COMMIT_PROPOSED not in {
            event.payload.get("fusion_state") for event in result.events
        }
        for decision in payloads:
            assert decision["fusion_state"] != FusionState.COMMIT_PROPOSED
            assert decision.get("target_object_id") in {None, ""}
    elif check == "spoken_pointed":
        assert conflict_payloads
        reasons = [code for item in conflict_payloads for code in item["reason_codes"]]
        assert "SPOKEN_POINTED_MISMATCH" in reasons
        for decision in payloads:
            assert "SPOKEN_POINTED_MISMATCH" in decision["conflicts"]
            assert decision["fusion_state"] != FusionState.COMMIT_PROPOSED
    elif check == "margin":
        assert conflict_payloads
        reasons = [code for item in conflict_payloads for code in item["reason_codes"]]
        assert "TARGET_MARGIN_LOW" in reasons
        for decision in payloads:
            assert decision["fusion_state"] != FusionState.COMMIT_PROPOSED
    elif check == "confirm_cancel":
        assert conflict_payloads
        reasons = [code for item in conflict_payloads for code in item["reason_codes"]]
        assert "CONFIRM_CANCEL_CONFLICT" in reasons
        for decision in payloads:
            assert decision["fusion_state"] != FusionState.COMMIT_PROPOSED
            assert decision["action"] != "CANCEL" or decision["status"] != IntentStatus.CANCELLED
    elif check == "no_session":
        assert payloads == []
        assert EventType.INTENT_DECISION not in event_types(result)
    elif check == "not_ready":
        for decision in payloads:
            assert decision["fusion_state"] != FusionState.COMMIT_PROPOSED
    else:
        raise AssertionError(f"unknown check {check} for {name}")


def test_identical_input_is_deterministic() -> None:
    first = run(deepcopy(HAPPY_WINDOW))
    second = run(deepcopy(HAPPY_WINDOW))
    assert [event.model_dump(mode="json") for event in first.events] == [
        event.model_dump(mode="json") for event in second.events
    ]
    assert first.state.fusion_state == second.state.fusion_state


def test_cancel_proposal_is_immediate() -> None:
    result = run(
        [
            session_started(),
            machine_ready(),
            audio_intent("evt_cancel", action="CANCEL", transcript="cancel", confidence=0.99),
        ]
    )
    payloads = decisions(result)
    assert len(payloads) == 1
    assert payloads[0]["action"] == "CANCEL"
    assert payloads[0]["status"] == IntentStatus.CANCELLED
    assert EventType.INTENT_DECISION in event_types(result)


def test_missing_eeg_does_not_change_scores() -> None:
    base = deepcopy(HAPPY_WINDOW)
    with_eeg = [*deepcopy(HAPPY_WINDOW), eeg_shadow()]
    without = run(base)
    with_shadow = run(with_eeg)
    left = decisions(without)[-1]
    right = decisions(with_shadow)[-1]
    assert left["action"] == right["action"]
    assert left["target_object_id"] == right["target_object_id"]
    assert left["confidence"] == right["confidence"]
    assert left["fusion_state"] == right["fusion_state"]
    left_live = [item for item in left["evidence"] if item["modality"] != "eeg"]
    right_live = [item for item in right["evidence"] if item["modality"] != "eeg"]
    assert left_live == right_live
    eeg_items = [item for item in right["evidence"] if item["modality"] == "eeg"]
    assert all(item["contribution"] == 0.0 for item in eeg_items)


def test_decision_lists_evidence_event_ids() -> None:
    result = run(HAPPY_WINDOW)
    decision = decisions(result)[-1]
    ids = [item["event_id"] for item in decision["evidence"]]
    assert "evt_audio_1" in ids
    assert "evt_vision_1" in ids
    assert "evt_emg_01" in ids
    for item in decision["evidence"]:
        assert "contribution" in item
        assert 0.0 <= item["contribution"] <= 1.0


def test_expired_vision_is_excluded() -> None:
    result = run(
        [
            session_started(),
            machine_ready(),
            audio_intent("evt_audio", action="REQUEST_HANDOFF", target_reference="DEICTIC"),
            vision_objects(
                "evt_vision",
                pointing=[{"object_id": "object_blue_1", "confidence": 0.99}],
                time_ns=1_000_000,
            ),
            emg_feature("evt_emg", label="confirm"),
        ],
        now_ns=800_000_000,
    )
    for decision in decisions(result):
        assert decision["fusion_state"] != FusionState.COMMIT_PROPOSED
        assert decision.get("target_object_id") in {None, ""}


def test_low_quality_emg_does_not_confirm() -> None:
    result = run(
        [
            session_started(),
            machine_ready(),
            audio_intent(
                "evt_audio",
                action="REQUEST_HANDOFF",
                target_reference="NAMED",
                target_object_id="object_blue_1",
            ),
            vision_objects(
                "evt_vision",
                pointing=[{"object_id": "object_blue_1", "confidence": 0.82}],
            ),
            emg_feature("evt_emg", label="confirm", quality=0.0),
        ]
    )
    for decision in decisions(result):
        assert decision["fusion_state"] != FusionState.COMMIT_PROPOSED


def test_target_must_be_in_object_set() -> None:
    result = run(
        [
            session_started(),
            machine_ready(),
            audio_intent(
                "evt_audio",
                action="REQUEST_HANDOFF",
                target_reference="NAMED",
                target_object_id="object_yellow_1",
            ),
            vision_objects("evt_vision", object_ids=("object_blue_1", "object_red_1")),
            emg_feature("evt_emg", label="confirm"),
        ]
    )
    for decision in decisions(result):
        assert decision.get("target_object_id") != "object_yellow_1"
        assert decision["fusion_state"] != FusionState.COMMIT_PROPOSED


def test_user_profile_records_emg_model_not_self_predictions() -> None:
    profile = UserProfile()
    result = step(fresh_state(), HAPPY_WINDOW, profile, CONFIG, now_ns=NOW_NS)
    assert result.user_profile.emg_model_id == "emg-primary-user-v3"
    assert result.user_profile.reliability == profile.reliability


def test_never_emits_action_command() -> None:
    result = run(HAPPY_WINDOW)
    assert all(event.event_type != "action.command" for event in result.events)
    assert {str(event.event_type) for event in result.events} <= {
        EventType.INTENT_CANDIDATE_SET,
        EventType.INTENT_DECISION,
        EventType.INTENT_CONFLICT,
        EventType.INTENT_TIMEOUT,
        EventType.SERVICE_HEARTBEAT,
    }


def test_milestone1_emg_shadow_does_not_control() -> None:
    """Milestone 1: biosignals are recorded but EMG must not change live decisions."""
    without = [
        session_started(),
        machine_ready(),
        audio_intent("evt_audio_1", action="REQUEST_HANDOFF", target_reference="DEICTIC"),
        vision_objects(
            "evt_vision_1",
            pointing=[{"object_id": "object_blue_1", "confidence": 0.82}],
        ),
    ]
    with_emg = [
        *without,
        emg_feature("evt_emg_01", label="confirm"),
        emg_feature("evt_emg_cancel", label="cancel", confidence=0.93, time_ns=81_000_000),
    ]
    left = run(without, config=M1_CONFIG)
    right = run(with_emg, config=M1_CONFIG)
    left_d = decisions(left)
    right_d = decisions(right)
    assert [item["action"] for item in left_d] == [item["action"] for item in right_d]
    if left_d:
        assert left_d[-1]["confidence"] == right_d[-1]["confidence"]
        assert "evt_emg_01" not in {item["event_id"] for item in right_d[-1]["evidence"]}
    assert not any(
        event.payload.get("action") == "CANCEL" for event in right.events if event.event_type == EventType.INTENT_DECISION
    )
