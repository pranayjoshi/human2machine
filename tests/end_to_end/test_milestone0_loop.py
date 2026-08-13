"""Milestone 0 closed loop: fusion -> safety -> simulator.

This is an in-process proof of the product loop. It does not start ZeroMQ.
Live-stack smoke lives in scripts/demo_mvp.py.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for extra in (
    ROOT / "packages/contracts-python/src",
    ROOT / "packages/runtime-python/src",
    ROOT / "services/fusion-runtime",
    ROOT / "services/safety-gateway",
    ROOT / "services/robot-simulator",
):
    sys.path.insert(0, str(extra))

from fusion_runtime.engine import FusionConfig, FusionRuntimeState, UserProfile, step
from intent_contracts.enums import EventType, MachineState, OutcomeKind, SafetyVerdict
from intent_contracts.events import IntentDecisionPayload
from robot_simulator.adapter import SimulatedClock, SimulatorMachineAdapter, SimulatorSettings
from safety_gateway.policy import SafetyState, apply_event, evaluate, safety_config_from_mapping

from tests.unit.fusion_runtime.test_engine import (
    HAPPY_WINDOW,
    audio_intent,
    emg_feature,
    machine_ready,
    session_started,
    vision_objects,
)

NOW_NS = 100_000_000


def _fuse(window: list[dict], *, now_ns: int = NOW_NS):
    return step(FusionRuntimeState(), window, UserProfile(), FusionConfig(), now_ns=now_ns)


def _decisions(result) -> list[IntentDecisionPayload]:
    return [
        IntentDecisionPayload.model_validate(event.payload)
        for event in result.events
        if event.event_type == EventType.INTENT_DECISION
    ]


def _safety_state(*, now_ns: int = NOW_NS) -> SafetyState:
    return SafetyState(
        session_id="session_test",
        session_active=True,
        trial_id="trial_test",
        trial_active=True,
        machine_state=MachineState.READY,
        machine_updated_at_ns=now_ns,
        visible_object_ids=frozenset({"object_blue_1", "object_red_1"}),
        vision_updated_at_ns=now_ns,
        last_emg_label="confirm",
        last_emg_at_ns=now_ns,
        last_emg_confidence=0.91,
    )


def _policy():
    return safety_config_from_mapping(
        {
            "safety": {
                "mode": "simulator_only",
                "auto_approve_threshold": 0.70,
                "confirmation_threshold": 0.50,
                "require_emg_confirmation_for_deictic": True,
                "max_intent_age_ms": 5000,
                "max_machine_state_age_ms": 5000,
            }
        }
    )


def test_voice_target_confirm_produces_one_simulated_action() -> None:
    fused = _fuse(HAPPY_WINDOW)
    decisions = _decisions(fused)
    assert decisions, "fusion must propose a handoff"
    decision = decisions[-1]
    assert decision.action == "REQUEST_HANDOFF"
    assert decision.target_object_id == "object_blue_1"
    assert decision.evidence, "decision must cite evidence event IDs"

    result = evaluate(decision, _safety_state(), _policy(), now_ns=NOW_NS)
    assert result.verdict is SafetyVerdict.APPROVE
    assert result.command is not None
    assert result.command.action == "REQUEST_HANDOFF"
    assert result.command.target_object_id == "object_blue_1"

    clock = SimulatedClock(start_ns=NOW_NS)
    adapter = SimulatorMachineAdapter(SimulatorSettings(), clock=clock)
    adapter.connect()
    command = result.command.model_copy(
        update={"issued_at_ns": clock.time_ns(), "expires_at_ns": clock.time_ns() + 5_000_000_000}
    )
    adapter.execute(command)
    adapter.advance_ms(2000)
    assert adapter.emitted_outcomes
    assert adapter.emitted_outcomes[-1].outcome == OutcomeKind.COMPLETED
    assert adapter.state is MachineState.READY


def test_spoken_pointed_conflict_asks_confirmation() -> None:
    fused = _fuse(
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
        ]
    )
    decisions = _decisions(fused)
    assert decisions
    decision = decisions[-1]
    assert decision.conflicts or decision.confidence < 0.92
    result = evaluate(decision, _safety_state(), _policy(), now_ns=NOW_NS)
    assert result.verdict in {SafetyVerdict.ASK_CONFIRMATION, SafetyVerdict.HOLD, SafetyVerdict.REJECT}
    assert result.command is None


def test_cancel_stops_pending_simulator_action() -> None:
    fused = _fuse(HAPPY_WINDOW)
    decision = _decisions(fused)[-1]
    state = _safety_state()
    config = _policy()
    state, results = apply_event(
        state,
        {
            "event_type": "intent.decision",
            "event_id": "evt_intent_1",
            "session_id": "session_test",
            "trial_id": "trial_test",
            "normalized_time_ns": NOW_NS,
            "received_monotonic_ns": NOW_NS,
            "payload": decision.model_dump(mode="json"),
        },
        config,
        now_ns=NOW_NS,
    )
    approved = next(item for item in results if item.command is not None)
    clock = SimulatedClock(start_ns=NOW_NS)
    adapter = SimulatorMachineAdapter(SimulatorSettings(), clock=clock)
    adapter.connect()
    command = approved.command.model_copy(
        update={"issued_at_ns": clock.time_ns(), "expires_at_ns": clock.time_ns() + 5_000_000_000}
    )
    adapter.execute(command)
    assert adapter.state is MachineState.EXECUTING

    state, results = apply_event(
        state,
        {
            "event_type": "machine.state",
            "event_id": "evt_exec_1",
            "normalized_time_ns": NOW_NS + 1,
            "received_monotonic_ns": NOW_NS + 1,
            "payload": {
                "state": MachineState.EXECUTING,
                "active_command_id": command.command_id,
                "progress": 0.2,
            },
        },
        config,
        now_ns=NOW_NS + 1,
    )
    state, results = apply_event(
        state,
        {
            "event_type": "modality.feature",
            "event_id": "evt_emg_cancel",
            "modality": "emg",
            "normalized_time_ns": NOW_NS + 2,
            "received_monotonic_ns": NOW_NS + 2,
            "payload": {
                "feature_name": "emg_gesture",
                "window_start_ns": NOW_NS,
                "window_end_ns": NOW_NS + 2,
                "label": "cancel",
                "confidence": 0.95,
                "candidate_scores": {"cancel": 0.95, "rest": 0.03, "confirm": 0.02},
                "model_id": "emg-primary-user-v3",
                "shadow_only": False,
            },
        },
        config,
        now_ns=NOW_NS + 2,
    )
    cancel_cmd = next(item.command for item in results if item.command is not None)
    assert str(cancel_cmd.action) == "CANCEL"
    cancel_cmd = cancel_cmd.model_copy(
        update={"issued_at_ns": clock.time_ns(), "expires_at_ns": clock.time_ns() + 5_000_000_000}
    )
    adapter.execute(cancel_cmd)
    assert adapter.emitted_outcomes[-1].outcome == OutcomeKind.CANCELLED
    assert adapter.state is MachineState.READY


def test_deictic_without_target_does_not_approve() -> None:
    fused = _fuse(
        [
            session_started(),
            machine_ready(),
            audio_intent("evt_audio", action="REQUEST_HANDOFF", target_reference="DEICTIC"),
            vision_objects("evt_vision", pointing=[]),
        ]
    )
    decisions = _decisions(fused)
    if not decisions:
        return
    result = evaluate(decisions[-1], _safety_state(), _policy(), now_ns=NOW_NS)
    assert result.verdict is not SafetyVerdict.APPROVE
    assert result.command is None
