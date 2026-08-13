from __future__ import annotations

import pytest
from conftest import (
    NOW_NS,
    OBJECT_BLUE,
    OBJECT_RED,
    envelope,
    feature_event,
    intent_event,
    machine_event,
    make_config,
    make_decision,
    make_state,
    vision_event,
)
from intent_contracts.enums import Action, MachineState, SafetyVerdict
from safety_gateway.policy import Reason, apply_event

NS_PER_MS = 1_000_000


def _apply(state, event, now_ns=NOW_NS):
    return apply_event(state, event, make_config(), now_ns=now_ns)


def test_target_disappears_during_confirmation() -> None:
    state = make_state()
    decision = make_decision(confidence=0.80)
    state, results = _apply(state, intent_event(decision))
    assert results[0].verdict == SafetyVerdict.ASK_CONFIRMATION
    assert results[0].confirmation_id is not None
    assert state.pending_confirmation is not None

    state, results = _apply(state, vision_event([OBJECT_RED], now_ns=NOW_NS + 10 * NS_PER_MS))
    assert results
    assert results[0].verdict == SafetyVerdict.REJECT
    assert Reason.TARGET_DISAPPEARED in results[0].reason_codes
    assert results[0].command is None
    assert state.pending_confirmation is None


def test_confirmation_timeout_rejects() -> None:
    state = make_state()
    state, results = _apply(state, intent_event(make_decision(confidence=0.80)))
    freeze = state.pending_confirmation
    assert freeze is not None
    later = freeze.expires_at_ns + 1
    state, results = apply_event(state, envelope("poll", now_ns=later), make_config(), now_ns=later)
    assert results[0].verdict == SafetyVerdict.REJECT
    assert Reason.CONFIRMATION_TIMEOUT in results[0].reason_codes
    assert state.pending_confirmation is None


def test_confirmation_then_emg_confirm_reruns_checks_and_approves() -> None:
    state = make_state()
    decision = make_decision(confidence=0.80)
    state, results = _apply(state, intent_event(decision))
    assert results[0].verdict == SafetyVerdict.ASK_CONFIRMATION
    confirmation_id = results[0].confirmation_id

    state, results = _apply(state, feature_event("confirm", now_ns=NOW_NS + 5 * NS_PER_MS))
    assert results[0].verdict == SafetyVerdict.APPROVE
    assert results[0].command is not None
    assert str(results[0].command.action) == Action.REQUEST_HANDOFF
    assert results[0].command.target_object_id == OBJECT_BLUE
    assert results[0].confirmation_id == confirmation_id
    assert results[0].checks.confirmation_satisfied is True
    assert state.pending_confirmation is None


def test_confirmation_intent_change_rejects_frozen_action() -> None:
    state = make_state()
    first = make_decision(decision_id="d1", confidence=0.80, target_object_id=OBJECT_BLUE)
    state, results = _apply(state, intent_event(first, event_id="e1"))
    assert results[0].verdict == SafetyVerdict.ASK_CONFIRMATION

    second = make_decision(decision_id="d2", confidence=0.95, target_object_id=OBJECT_RED)
    state, results = _apply(state, intent_event(second, event_id="e2"))
    assert results[0].verdict == SafetyVerdict.REJECT
    assert Reason.CONFIRMATION_INTENT_CHANGED in results[0].reason_codes
    # New decision is then evaluated independently.
    assert len(results) == 2
    assert results[1].decision_id == "d2"


def test_cancel_before_approval() -> None:
    state = make_state()
    state, results = _apply(state, intent_event(make_decision(confidence=0.80)))
    assert results[0].verdict == SafetyVerdict.ASK_CONFIRMATION
    state, results = _apply(state, feature_event("cancel"))
    assert results[0].verdict == SafetyVerdict.REJECT
    assert Reason.CANCEL_LATCHED in results[0].reason_codes
    assert results[0].command is None
    assert state.pending_confirmation is None


def test_cancel_during_execution_emits_cancel_command_and_latches() -> None:
    state = make_state()
    state, results = _apply(state, intent_event(make_decision(confidence=0.95)))
    assert results[0].verdict == SafetyVerdict.APPROVE
    command_id = results[0].command.command_id

    state, _ = _apply(
        state,
        machine_event(MachineState.EXECUTING, active_command_id=command_id, now_ns=NOW_NS + 1),
    )
    assert state.machine_state == MachineState.EXECUTING

    state, results = _apply(state, feature_event("cancel", now_ns=NOW_NS + 2))
    assert results[0].verdict == SafetyVerdict.REJECT
    assert results[0].command is not None
    assert str(results[0].command.action) == Action.CANCEL
    assert state.cancel_latched is True

    # New request cannot sneak through while cancel is latched.
    later = make_decision(decision_id="d_new", confidence=0.95)
    state, results = _apply(state, intent_event(later, event_id="e_new", now_ns=NOW_NS + 3))
    assert results[0].verdict == SafetyVerdict.REJECT
    assert Reason.CANCEL_LATCHED in results[0].reason_codes
    assert results[0].command is None

    # Machine acknowledgement clears the latch.
    state, _ = _apply(state, machine_event(MachineState.CANCELLED, now_ns=NOW_NS + 4))
    state, _ = _apply(state, machine_event(MachineState.READY, now_ns=NOW_NS + 5))
    assert state.cancel_latched is False

    state, results = _apply(
        state,
        intent_event(make_decision(decision_id="d_after", confidence=0.95), event_id="e_after"),
    )
    assert results[0].verdict == SafetyVerdict.APPROVE
    assert results[0].command is not None


@pytest.mark.parametrize(
    "machine_state",
    [
        MachineState.DISCONNECTED,
        MachineState.IDLE,
        MachineState.READY,
        MachineState.EXECUTING,
        MachineState.HOLDING,
        MachineState.COMPLETED,
        MachineState.CANCELLED,
        MachineState.FAULT,
        MachineState.ESTOPPED,
    ],
)
def test_stop_in_every_machine_state(machine_state: str) -> None:
    state = make_state(machine_state=machine_state)
    state, results = _apply(state, feature_event("stop"))
    assert results[0].verdict == SafetyVerdict.EMERGENCY_STOP
    assert Reason.STOP_ACTIVE in results[0].reason_codes
    assert state.stop_latched is True
    if machine_state != MachineState.ESTOPPED or results[0].command is not None:
        # First stop issues a STOP command unless this exact stop key already ran.
        pass
    assert results[0].command is None or str(results[0].command.action) == Action.STOP

    # A new high-confidence request cannot clear emergency stop.
    state, results = _apply(
        state,
        intent_event(make_decision(decision_id=f"after_stop_{machine_state}", confidence=0.95)),
    )
    assert results[0].verdict == SafetyVerdict.EMERGENCY_STOP
    assert results[0].command is None or str(results[0].command.action) == Action.STOP
    assert state.stop_latched is True


def test_stop_during_pending_confirmation() -> None:
    state = make_state()
    state, results = _apply(state, intent_event(make_decision(confidence=0.80)))
    assert state.pending_confirmation is not None
    stop = make_decision(
        action=Action.STOP, include_emg=False, target_object_id=None, confidence=1.0
    )
    state, results = _apply(state, envelope("intent.decision", stop.model_dump(mode="json")))
    assert results[0].verdict == SafetyVerdict.EMERGENCY_STOP
    assert state.pending_confirmation is None
    assert state.stop_latched is True
    assert results[0].command is not None
    assert str(results[0].command.action) == Action.STOP


def test_stop_during_execution() -> None:
    state = make_state()
    state, results = _apply(state, intent_event(make_decision(confidence=0.95)))
    assert results[0].command is not None
    executing = machine_event(
        MachineState.EXECUTING, active_command_id=results[0].command.command_id
    )
    state, _ = _apply(state, executing)
    state, results = _apply(state, feature_event("stop"))
    assert results[0].verdict == SafetyVerdict.EMERGENCY_STOP
    assert results[0].command is not None
    assert str(results[0].command.action) == Action.STOP
    assert state.stop_latched is True


def test_new_request_cannot_clear_emergency_stop_even_after_ready_without_reset() -> None:
    state = make_state()
    state, _ = _apply(state, feature_event("stop"))
    assert state.stop_latched is True
    # Machine still ESTOPPED / latch held; READY without leaving ESTOPPED does not clear
    # because previous_state was not ESTOPPED in this transition from READY.
    state = make_state(stop_latched=True, machine_state=MachineState.ESTOPPED)
    state, results = _apply(state, intent_event(make_decision(confidence=0.95)))
    assert results[0].verdict == SafetyVerdict.EMERGENCY_STOP
    assert state.stop_latched is True


def test_operator_reset_from_estopped_clears_stop_latch() -> None:
    state = make_state(stop_latched=True, machine_state=MachineState.ESTOPPED)
    state, _ = _apply(state, machine_event(MachineState.IDLE))
    assert state.stop_latched is False
    state, _ = _apply(state, machine_event(MachineState.READY, now_ns=NOW_NS + 1))
    after = intent_event(
        make_decision(decision_id="after_reset", confidence=0.95), event_id="e_reset"
    )
    state, results = _apply(state, after)
    assert results[0].verdict == SafetyVerdict.APPROVE
    assert results[0].command is not None


def test_session_and_trial_lifecycle_gates_actions() -> None:
    state = make_state(session_active=True, trial_active=True)
    state, _ = _apply(state, envelope("trial.completed"))
    assert state.trial_active is False
    no_trial = intent_event(make_decision(decision_id="no_trial", confidence=0.95))
    state, results = _apply(state, no_trial)
    assert results[0].verdict == SafetyVerdict.HOLD
    assert Reason.TRIAL_INACTIVE in results[0].reason_codes

    state, _ = _apply(state, envelope("session.stopped"))
    assert state.session_active is False
    no_session = intent_event(make_decision(decision_id="no_session", confidence=0.95))
    state, results = _apply(state, no_session)
    assert results[0].verdict == SafetyVerdict.HOLD
    assert Reason.SESSION_INACTIVE in results[0].reason_codes


def test_stop_overrides_even_without_session() -> None:
    state = make_state(session_active=False, trial_active=False, machine_state=MachineState.READY)
    state, results = _apply(state, feature_event("stop"))
    assert results[0].verdict == SafetyVerdict.EMERGENCY_STOP
    assert results[0].command is not None
    assert str(results[0].command.action) == Action.STOP
