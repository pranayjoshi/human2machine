from __future__ import annotations

from pathlib import Path

import pytest
from conftest import (
    EXPIRES_AT_NS,
    NOW_NS,
    OBJECT_BLUE,
    OBJECT_RED,
    envelope,
    intent_event,
    make_config,
    make_decision,
    make_evidence,
    make_state,
)
from intent_contracts.enums import Action, MachineState, SafetyVerdict
from intent_contracts.events import IntentAlternative
from safety_gateway.policy import (
    Reason,
    apply_event,
    evaluate,
    idempotency_key,
    safety_config_from_mapping,
)


def _codes(result) -> set[str]:
    return set(result.reason_codes)


# ---------------------------------------------------------------------------
# Table-driven proposal evaluation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            {
                "id": "high_confidence_approves",
                "decision": {"confidence": 0.95, "include_emg": True},
                "verdict": SafetyVerdict.APPROVE,
                "reason": Reason.CONFIDENCE_HIGH,
                "command": True,
            },
            id="high_confidence",
        ),
        pytest.param(
            {
                "id": "medium_confidence_asks",
                "decision": {"confidence": 0.80, "include_emg": True},
                "verdict": SafetyVerdict.ASK_CONFIRMATION,
                "reason": Reason.CONFIDENCE_MODERATE,
                "command": False,
            },
            id="medium_confidence",
        ),
        pytest.param(
            {
                "id": "low_confidence_rejects",
                "decision": {"confidence": 0.40, "include_emg": True},
                "verdict": SafetyVerdict.REJECT,
                "reason": Reason.CONFIDENCE_LOW,
                "command": False,
            },
            id="low_confidence",
        ),
        pytest.param(
            {
                "id": "two_close_targets",
                "decision": {
                    "confidence": 0.84,
                    "include_emg": True,
                    "alternatives": [
                        IntentAlternative(target_object_id=OBJECT_RED, confidence=0.72)
                    ],
                },
                "verdict": SafetyVerdict.ASK_CONFIRMATION,
                "reason": Reason.TARGET_MARGIN_LOW,
                "command": False,
            },
            id="two_close_targets",
        ),
        pytest.param(
            {
                "id": "spoken_pointed_conflict",
                "decision": {
                    "confidence": 0.95,
                    "include_emg": True,
                    "conflicts": ["SPOKEN_POINTED_CONFLICT"],
                },
                "verdict": SafetyVerdict.ASK_CONFIRMATION,
                "reason": Reason.SPOKEN_POINTED_CONFLICT,
                "command": False,
            },
            id="spoken_pointed_conflict",
        ),
        pytest.param(
            {
                "id": "missing_target",
                "decision": {
                    "confidence": 0.95,
                    "include_emg": True,
                    "target_object_id": "object_green_1",
                },
                "verdict": SafetyVerdict.HOLD,
                "reason": Reason.TARGET_MISSING,
                "command": False,
            },
            id="missing_target",
        ),
        pytest.param(
            {
                "id": "stale_voice",
                "decision": {
                    "confidence": 0.95,
                    "evidence": make_evidence(audio_age_ms=6000.0),
                },
                "verdict": SafetyVerdict.HOLD,
                "reason": Reason.EVIDENCE_STALE_AUDIO,
                "command": False,
            },
            id="stale_voice",
        ),
        pytest.param(
            {
                "id": "stale_vision",
                "decision": {
                    "confidence": 0.95,
                    "evidence": make_evidence(vision_age_ms=800.0),
                },
                "verdict": SafetyVerdict.HOLD,
                "reason": Reason.EVIDENCE_STALE_VISION,
                "command": False,
            },
            id="stale_vision",
        ),
        pytest.param(
            {
                "id": "stale_emg",
                "decision": {
                    "confidence": 0.95,
                    "evidence": make_evidence(emg_age_ms=2000.0),
                },
                "verdict": SafetyVerdict.HOLD,
                "reason": Reason.EVIDENCE_STALE_EMG,
                "command": False,
            },
            id="stale_emg",
        ),
        pytest.param(
            {
                "id": "machine_busy",
                "decision": {"confidence": 0.95, "include_emg": True},
                "state": {"machine_state": MachineState.EXECUTING},
                "verdict": SafetyVerdict.HOLD,
                "reason": Reason.MACHINE_BUSY,
                "command": False,
            },
            id="machine_busy",
        ),
        pytest.param(
            {
                "id": "machine_faulted",
                "decision": {"confidence": 0.95, "include_emg": True},
                "state": {"machine_state": MachineState.FAULT, "machine_fault_reason": "grasp"},
                "verdict": SafetyVerdict.REJECT,
                "reason": Reason.MACHINE_FAULTED,
                "command": False,
            },
            id="machine_faulted",
        ),
        pytest.param(
            {
                "id": "machine_disconnected",
                "decision": {"confidence": 0.95, "include_emg": True},
                "state": {"machine_state": MachineState.DISCONNECTED},
                "verdict": SafetyVerdict.HOLD,
                "reason": Reason.MACHINE_DISCONNECTED,
                "command": False,
            },
            id="machine_disconnected",
        ),
        pytest.param(
            {
                "id": "machine_idle_not_ready",
                "decision": {"confidence": 0.95, "include_emg": True},
                "state": {"machine_state": MachineState.IDLE},
                "verdict": SafetyVerdict.HOLD,
                "reason": Reason.MACHINE_NOT_READY,
                "command": False,
            },
            id="machine_idle",
        ),
        pytest.param(
            {
                "id": "expired_decision",
                "decision": {"confidence": 0.95, "include_emg": True, "expires_at_ns": NOW_NS - 1},
                "verdict": SafetyVerdict.HOLD,
                "reason": Reason.INTENT_EXPIRED,
                "command": False,
            },
            id="expired_decision",
        ),
        pytest.param(
            {
                "id": "session_inactive",
                "decision": {"confidence": 0.95, "include_emg": True},
                "state": {"session_active": False},
                "verdict": SafetyVerdict.HOLD,
                "reason": Reason.SESSION_INACTIVE,
                "command": False,
            },
            id="session_inactive",
        ),
        pytest.param(
            {
                "id": "trial_inactive",
                "decision": {"confidence": 0.95, "include_emg": True},
                "state": {"trial_active": False},
                "verdict": SafetyVerdict.HOLD,
                "reason": Reason.TRIAL_INACTIVE,
                "command": False,
            },
            id="trial_inactive",
        ),
        pytest.param(
            {
                "id": "missing_emg_asks_confirmation",
                "decision": {"confidence": 0.95, "include_emg": False},
                "verdict": SafetyVerdict.ASK_CONFIRMATION,
                "reason": Reason.CONFIRMATION_REQUIRED,
                "command": False,
            },
            id="missing_emg_deictic",
        ),
        pytest.param(
            {
                "id": "duplicate_decision",
                "decision": {"confidence": 0.95, "include_emg": True, "decision_id": "dup_1"},
                "state": {
                    "seen_decision_ids": frozenset({"dup_1"}),
                    "executed_keys": frozenset({f"dup_1:{Action.REQUEST_HANDOFF}:{OBJECT_BLUE}"}),
                },
                "verdict": SafetyVerdict.REJECT,
                "reason": Reason.IDEMPOTENCY_DUPLICATE,
                "command": False,
            },
            id="duplicate_decision",
        ),
        pytest.param(
            {
                "id": "cancel_latched_overrides",
                "decision": {"confidence": 0.95, "include_emg": True},
                "state": {"cancel_latched": True, "machine_state": MachineState.EXECUTING},
                "verdict": SafetyVerdict.REJECT,
                "reason": Reason.CANCEL_LATCHED,
                "command": False,
            },
            id="cancel_latched",
        ),
        pytest.param(
            {
                "id": "stop_latched_overrides",
                "decision": {"confidence": 0.95, "include_emg": True},
                "state": {"stop_latched": True, "machine_state": MachineState.ESTOPPED},
                "verdict": SafetyVerdict.EMERGENCY_STOP,
                "reason": Reason.STOP_ACTIVE,
                "command": False,
            },
            id="stop_latched",
        ),
        pytest.param(
            {
                "id": "action_not_allowed",
                "decision": {"confidence": 0.95, "include_emg": True, "action": "LAUNCH"},
                "verdict": SafetyVerdict.REJECT,
                "reason": Reason.ACTION_NOT_ALLOWED,
                "command": False,
            },
            id="action_not_allowed",
        ),
        pytest.param(
            {
                "id": "physical_hardware_blocked_in_simulator",
                "decision": {"confidence": 0.95, "include_emg": True},
                "state": {
                    "physical_adapter_configured": True,
                    "command_destination": "hardware",
                    "physical_armed": True,
                },
                "verdict": SafetyVerdict.REJECT,
                "reason": Reason.PHYSICAL_COMMAND_BLOCKED,
                "command": False,
            },
            id="physical_adapter_in_simulator_mode",
        ),
        pytest.param(
            {
                "id": "schema_invalid",
                "decision": {"confidence": 0.95, "include_emg": True},
                "schema_valid": False,
                "verdict": SafetyVerdict.REJECT,
                "reason": Reason.SCHEMA_INVALID,
                "command": False,
            },
            id="schema_invalid",
        ),
        pytest.param(
            {
                "id": "required_modalities_missing",
                "decision": {
                    "confidence": 0.95,
                    "evidence": make_evidence(audio=False, vision=True, emg=True),
                },
                "verdict": SafetyVerdict.HOLD,
                "reason": Reason.REQUIRED_MODALITIES_MISSING,
                "command": False,
            },
            id="missing_audio_modality",
        ),
        pytest.param(
            {
                "id": "stale_machine_state",
                "decision": {"confidence": 0.95, "include_emg": True},
                "state": {"machine_updated_at_ns": NOW_NS - 2_000_000_000},
                "verdict": SafetyVerdict.HOLD,
                "reason": Reason.MACHINE_STATE_STALE,
                "command": False,
            },
            id="stale_machine_state",
        ),
        pytest.param(
            {
                "id": "select_object_high_confidence",
                "decision": {
                    "confidence": 0.96,
                    "include_emg": True,
                    "action": Action.SELECT_OBJECT,
                },
                "verdict": SafetyVerdict.APPROVE,
                "reason": Reason.CONFIDENCE_HIGH,
                "command": True,
            },
            id="select_object_high",
        ),
    ],
)
def test_policy_matrix(case: dict) -> None:
    decision = make_decision(**case["decision"])
    state = make_state(**case.get("state", {}))
    result = evaluate(
        decision,
        state,
        make_config(),
        now_ns=NOW_NS,
        schema_valid=case.get("schema_valid", True),
        decision_time_ns=NOW_NS,
    )
    assert result.verdict == case["verdict"], (
        f"{case['id']}: expected {case['verdict']} got {result.verdict} codes={result.reason_codes}"
    )
    assert case["reason"] in _codes(result)
    assert result.reason_codes, "every verdict must include reason_codes"
    assert result.checks.schema_valid == case.get("schema_valid", True)
    if case["command"]:
        assert result.command is not None
        assert str(result.command.action) == str(decision.action)
        assert result.command.idempotency_key == idempotency_key(
            decision.decision_id, str(decision.action), decision.target_object_id
        )
        assert result.command.safety_policy_version == "safety-policy-v1"
        assert result.command.target_object_id == decision.target_object_id
    else:
        assert result.command is None


def test_evaluate_is_deterministic() -> None:
    decision = make_decision()
    state = make_state()
    config = make_config()
    a = evaluate(decision, state, config, now_ns=NOW_NS, decision_time_ns=NOW_NS)
    b = evaluate(decision, state, config, now_ns=NOW_NS, decision_time_ns=NOW_NS)
    assert a.verdict == b.verdict
    assert a.reason_codes == b.reason_codes
    assert a.command is not None and b.command is not None
    assert a.command.model_dump() == b.command.model_dump()


def test_approve_creates_exactly_one_simulator_command() -> None:
    result = evaluate(
        make_decision(), make_state(), make_config(), now_ns=NOW_NS, decision_time_ns=NOW_NS
    )
    assert result.verdict == SafetyVerdict.APPROVE
    assert result.command is not None
    assert result.confirmation_id is None
    dumped = result.command.model_dump()
    assert dumped["idempotency_key"] == f"decision_1:REQUEST_HANDOFF:{OBJECT_BLUE}"
    assert "hardware" not in dumped
    assert dumped["safety_policy_version"] == "safety-policy-v1"


def test_physical_adapter_config_still_allows_simulator_destination() -> None:
    state = make_state(physical_adapter_configured=True, command_destination="simulator")
    result = evaluate(make_decision(), state, make_config(), now_ns=NOW_NS, decision_time_ns=NOW_NS)
    assert result.verdict == SafetyVerdict.APPROVE
    assert result.command is not None
    assert result.checks.physical_robot_disarmed is True
    assert Reason.SIMULATOR_ONLY in result.reason_codes


def test_physical_robot_mode_without_arming_blocks_hardware() -> None:
    config = make_config(mode="physical_robot")
    state = make_state(
        physical_adapter_configured=True,
        command_destination="hardware",
        physical_armed=False,
    )
    result = evaluate(make_decision(), state, config, now_ns=NOW_NS, decision_time_ns=NOW_NS)
    assert result.command is None
    assert Reason.PHYSICAL_COMMAND_BLOCKED in result.reason_codes


def test_config_matches_checked_in_yaml() -> None:
    import yaml

    raw = yaml.safe_load(Path("configs/safety.yaml").read_text())
    loaded = safety_config_from_mapping(raw)
    assert loaded.mode == "simulator_only"
    assert loaded.auto_approve_threshold == 0.92
    assert loaded.confirmation_threshold == 0.65
    assert loaded.minimum_target_margin == 0.20
    assert loaded.require_emg_confirmation_for_deictic is True
    assert loaded.policy_version == "safety-policy-v1"


def test_every_verdict_populates_required_checks() -> None:
    result = evaluate(
        make_decision(), make_state(), make_config(), now_ns=NOW_NS, decision_time_ns=NOW_NS
    )
    checks = result.checks
    for field in (
        "intent_fresh",
        "target_visible",
        "cancel_absent",
        "machine_ready",
        "session_active",
        "schema_valid",
        "no_unresolved_conflict",
        "confirmation_satisfied",
        "physical_robot_disarmed",
    ):
        assert isinstance(getattr(checks, field), bool)


def test_duplicate_via_apply_event_never_emits_second_command() -> None:
    state = make_state()
    config = make_config()
    event = intent_event(make_decision())
    state, first = apply_event(state, event, config, now_ns=NOW_NS)
    assert len(first) == 1
    assert first[0].verdict == SafetyVerdict.APPROVE
    assert first[0].command is not None
    state, second = apply_event(state, event, config, now_ns=NOW_NS)
    assert len(second) == 1
    assert second[0].command is None
    assert second[0].verdict == SafetyVerdict.REJECT
    assert Reason.IDEMPOTENCY_DUPLICATE in second[0].reason_codes


def test_invalid_payload_is_schema_reject() -> None:
    state = make_state()
    event = envelope(
        "intent.decision",
        {
            "decision_id": "bad",
            "action": "REQUEST_HANDOFF",
            "confidence": 4.0,
            "expires_at_ns": EXPIRES_AT_NS,
        },
    )
    _, results = apply_event(state, event, make_config(), now_ns=NOW_NS)
    assert results
    assert results[0].verdict == SafetyVerdict.REJECT
    assert Reason.SCHEMA_INVALID in results[0].reason_codes
    assert results[0].command is None
    assert results[0].checks.schema_valid is False
