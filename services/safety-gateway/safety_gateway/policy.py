"""Pure, deterministic safety policy for the Multimodal Intent Compiler.

Transport, clocks, and sockets live in ``main.py``. This module is a pure
function of (decision | event, state, config, now_ns).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

from intent_contracts.commands import ActionCommand
from intent_contracts.enums import SCHEMA_VERSION, Action, MachineState, SafetyVerdict
from intent_contracts.events import (
    IntentDecisionPayload,
    SafetyChecks,
    SafetyDecisionPayload,
)

NS_PER_MS = 1_000_000
SOURCE = "safety-gateway"

# Machine states that may accept a new non-control action.
_READY_STATES = frozenset({MachineState.READY})
_BUSY_STATES = frozenset({MachineState.EXECUTING, MachineState.HOLDING})
_CONTROL_ACTIONS = frozenset({Action.CANCEL, Action.STOP})
_TARGETED_ACTIONS = frozenset({Action.SELECT_OBJECT, Action.REQUEST_HANDOFF})
_COMMAND_ACTIONS = frozenset(
    {Action.SELECT_OBJECT, Action.REQUEST_HANDOFF, Action.CANCEL, Action.STOP}
)

# Blocking ranks: higher always wins. Cancel/stop therefore override proposals.
_RANK = {
    "ok": 0,
    "confirm": 1,
    "hold": 2,
    "reject": 3,
    "estop": 4,
}


class Reason:
    SCHEMA_VALID = "SCHEMA_VALID"
    SCHEMA_INVALID = "SCHEMA_INVALID"
    INTENT_FRESH = "INTENT_FRESH"
    INTENT_EXPIRED = "INTENT_EXPIRED"
    SESSION_ACTIVE = "SESSION_ACTIVE"
    SESSION_INACTIVE = "SESSION_INACTIVE"
    TRIAL_ACTIVE = "TRIAL_ACTIVE"
    TRIAL_INACTIVE = "TRIAL_INACTIVE"
    MACHINE_READY = "MACHINE_READY"
    MACHINE_NOT_READY = "MACHINE_NOT_READY"
    MACHINE_DISCONNECTED = "MACHINE_DISCONNECTED"
    MACHINE_BUSY = "MACHINE_BUSY"
    MACHINE_FAULTED = "MACHINE_FAULTED"
    MACHINE_ESTOPPED = "MACHINE_ESTOPPED"
    MACHINE_STATE_STALE = "MACHINE_STATE_STALE"
    ACTION_ALLOWED = "ACTION_ALLOWED"
    ACTION_NOT_ALLOWED = "ACTION_NOT_ALLOWED"
    NO_FAULT = "NO_FAULT"
    IDEMPOTENCY_NEW = "IDEMPOTENCY_NEW"
    IDEMPOTENCY_DUPLICATE = "IDEMPOTENCY_DUPLICATE"
    CONFIDENCE_HIGH = "CONFIDENCE_HIGH"
    CONFIDENCE_MODERATE = "CONFIDENCE_MODERATE"
    CONFIDENCE_LOW = "CONFIDENCE_LOW"
    TARGET_MARGIN_OK = "TARGET_MARGIN_OK"
    TARGET_MARGIN_LOW = "TARGET_MARGIN_LOW"
    REQUIRED_MODALITIES_PRESENT = "REQUIRED_MODALITIES_PRESENT"
    REQUIRED_MODALITIES_MISSING = "REQUIRED_MODALITIES_MISSING"
    EVIDENCE_STALE_AUDIO = "EVIDENCE_STALE_AUDIO"
    EVIDENCE_STALE_VISION = "EVIDENCE_STALE_VISION"
    EVIDENCE_STALE_EMG = "EVIDENCE_STALE_EMG"
    NO_UNRESOLVED_CONFLICT = "NO_UNRESOLVED_CONFLICT"
    UNRESOLVED_CONFLICT = "UNRESOLVED_CONFLICT"
    SPOKEN_POINTED_CONFLICT = "SPOKEN_POINTED_CONFLICT"
    TARGET_VISIBLE = "TARGET_VISIBLE"
    TARGET_MISSING = "TARGET_MISSING"
    TARGET_DISAPPEARED = "TARGET_DISAPPEARED"
    CONFIRMATION_SATISFIED = "CONFIRMATION_SATISFIED"
    CONFIRMATION_REQUIRED = "CONFIRMATION_REQUIRED"
    CONFIRMATION_TIMEOUT = "CONFIRMATION_TIMEOUT"
    CONFIRMATION_INTENT_CHANGED = "CONFIRMATION_INTENT_CHANGED"
    EMG_CONFIRMATION_MISSING = "EMG_CONFIRMATION_MISSING"
    CANCEL_ABSENT = "CANCEL_ABSENT"
    CANCEL_LATCHED = "CANCEL_LATCHED"
    STOP_ACTIVE = "STOP_ACTIVE"
    PHYSICAL_ROBOT_DISARMED = "PHYSICAL_ROBOT_DISARMED"
    PHYSICAL_COMMAND_BLOCKED = "PHYSICAL_COMMAND_BLOCKED"
    SIMULATOR_ONLY = "SIMULATOR_ONLY"
    NOTHING_TO_CONFIRM = "NOTHING_TO_CONFIRM"


@dataclass(frozen=True)
class SafetyConfig:
    mode: str = "simulator_only"
    policy_version: str = "safety-policy-v1"
    auto_approve_threshold: float = 0.92
    confirmation_threshold: float = 0.65
    minimum_target_margin: float = 0.20
    require_emg_confirmation_for_deictic: bool = True
    max_intent_age_ms: float = 1000.0
    max_machine_state_age_ms: float = 500.0
    confirmation_timeout_ms: float = 4000.0
    stop_latch: bool = True
    physical_robot_requires_arming: bool = True
    allowed_actions: frozenset[str] = frozenset(
        {"SELECT_OBJECT", "REQUEST_HANDOFF", "CONFIRM", "CANCEL", "STOP"}
    )
    risk_tiers: tuple[tuple[str, int], ...] = (
        ("SELECT_OBJECT", 0),
        ("REQUEST_HANDOFF", 1),
        ("CONFIRM", 0),
        ("CANCEL", 0),
        ("STOP", 0),
    )
    evidence_max_age_ms: tuple[tuple[str, float], ...] = (
        ("audio", 5000.0),
        ("vision", 500.0),
        ("emg", 750.0),
    )
    required_modalities: frozenset[str] = frozenset({"audio", "vision"})

    def risk_tier(self, action: str) -> int:
        return dict(self.risk_tiers).get(action, 0)

    def max_age_ms(self, modality: str) -> float:
        return dict(self.evidence_max_age_ms).get(modality, self.max_intent_age_ms)

    @property
    def physical_robot_enabled(self) -> bool:
        return self.mode == "physical_robot"


def safety_config_from_mapping(data: Mapping[str, Any]) -> SafetyConfig:
    """Load from ``safety.yaml`` or a stacked config dict."""
    raw = data.get("safety", data) if isinstance(data, Mapping) else {}
    if not isinstance(raw, Mapping):
        raw = {}
    freshness = data.get("freshness_max_age_ms", {}) if isinstance(data, Mapping) else {}
    evidence_ages = dict(SafetyConfig().evidence_max_age_ms)
    if isinstance(freshness, Mapping):
        if "audio.intent_candidate" in freshness:
            evidence_ages["audio"] = float(freshness["audio.intent_candidate"])
        if "vision.objects" in freshness:
            evidence_ages["vision"] = float(freshness["vision.objects"])
        if "modality.feature.emg_gesture" in freshness:
            evidence_ages["emg"] = float(freshness["modality.feature.emg_gesture"])
    allowed = raw.get("allowed_actions")
    tiers = raw.get("risk_tiers")
    return SafetyConfig(
        mode=str(raw.get("mode", "simulator_only")),
        policy_version=str(raw.get("policy_version", "safety-policy-v1")),
        auto_approve_threshold=float(raw.get("auto_approve_threshold", 0.92)),
        confirmation_threshold=float(raw.get("confirmation_threshold", 0.65)),
        minimum_target_margin=float(raw.get("minimum_target_margin", 0.20)),
        require_emg_confirmation_for_deictic=bool(
            raw.get("require_emg_confirmation_for_deictic", True)
        ),
        max_intent_age_ms=float(raw.get("max_intent_age_ms", 1000.0)),
        max_machine_state_age_ms=float(raw.get("max_machine_state_age_ms", 500.0)),
        confirmation_timeout_ms=float(raw.get("confirmation_timeout_ms", 4000.0)),
        stop_latch=bool(raw.get("stop_latch", True)),
        physical_robot_requires_arming=bool(raw.get("physical_robot_requires_arming", True)),
        allowed_actions=(
            frozenset(str(a) for a in allowed) if allowed else SafetyConfig().allowed_actions
        ),
        risk_tiers=tuple((str(k), int(v)) for k, v in tiers.items())
        if isinstance(tiers, Mapping)
        else SafetyConfig().risk_tiers,
        evidence_max_age_ms=tuple(evidence_ages.items()),
    )


@dataclass(frozen=True)
class ConfirmationFreeze:
    confirmation_id: str
    decision_id: str
    action: str
    target_object_id: str | None
    issued_at_ns: int
    expires_at_ns: int
    decision: IntentDecisionPayload


@dataclass(frozen=True)
class SafetyState:
    session_id: str | None = None
    session_active: bool = False
    trial_id: str | None = None
    trial_active: bool = False
    machine_state: str = MachineState.DISCONNECTED
    machine_updated_at_ns: int | None = None
    machine_fault_reason: str | None = None
    machine_active_command_id: str | None = None
    visible_object_ids: frozenset[str] = frozenset()
    vision_updated_at_ns: int | None = None
    cancel_latched: bool = False
    stop_latched: bool = False
    pending_confirmation: ConfirmationFreeze | None = None
    executed_keys: frozenset[str] = frozenset()
    seen_decision_ids: frozenset[str] = frozenset()
    physical_adapter_configured: bool = False
    physical_armed: bool = False
    command_destination: str = "simulator"
    last_emg_label: str | None = None
    last_emg_at_ns: int | None = None
    last_emg_confidence: float = 0.0


@dataclass(frozen=True)
class _Atom:
    name: str
    passed: bool
    reason_code: str
    blocking: str


@dataclass(frozen=True)
class PolicyResult:
    decision_id: str
    verdict: SafetyVerdict
    reason_codes: tuple[str, ...]
    checks: SafetyChecks
    command: ActionCommand | None = None
    confirmation_id: str | None = None
    freeze: ConfirmationFreeze | None = None

    def to_payload(self, policy_version: str) -> SafetyDecisionPayload:
        return SafetyDecisionPayload(
            decision_id=self.decision_id,
            verdict=self.verdict,
            reason_codes=list(self.reason_codes),
            policy_version=policy_version,
            checks=self.checks,
            command_id=self.command.command_id if self.command is not None else None,
            confirmation_id=self.confirmation_id,
        )


def idempotency_key(decision_id: str, action: str, target_object_id: str | None) -> str:
    return f"{decision_id}:{action}:{target_object_id or ''}"


def _as_action(value: Action | str) -> str:
    return str(value)


def _age_ms(now_ns: int, then_ns: int | None) -> float | None:
    if then_ns is None:
        return None
    return max(0.0, (now_ns - then_ns) / NS_PER_MS)


def _target_margin(decision: IntentDecisionPayload) -> float:
    others = [
        alt.confidence
        for alt in decision.alternatives
        if alt.target_object_id != decision.target_object_id
    ]
    second = max(others) if others else 0.0
    return decision.confidence - second


def _modalities(decision: IntentDecisionPayload) -> set[str]:
    return {item.modality.lower() for item in decision.evidence}


def _evidence_age(decision: IntentDecisionPayload, modality: str) -> float | None:
    ages = [item.age_ms for item in decision.evidence if item.modality.lower() == modality]
    return max(ages) if ages else None


def _conflicts(decision: IntentDecisionPayload) -> list[str]:
    return [str(item) for item in decision.conflicts]


def _emg_confirm_fresh(
    decision: IntentDecisionPayload,
    state: SafetyState,
    config: SafetyConfig,
    now_ns: int,
) -> bool:
    emg_age = _evidence_age(decision, "emg")
    if emg_age is not None and emg_age <= config.max_age_ms("emg"):
        return True
    if state.last_emg_label == "confirm" and state.last_emg_at_ns is not None:
        age = _age_ms(now_ns, state.last_emg_at_ns)
        if age is not None and age <= config.max_age_ms("emg") and state.last_emg_confidence >= 0.5:
            return True
    return False


def _hardware_blocked(state: SafetyState, config: SafetyConfig) -> bool:
    """Physical commands are impossible unless mode is physical_robot and armed."""
    if state.command_destination != "hardware":
        return False
    if not config.physical_robot_enabled:
        return True
    if config.physical_robot_requires_arming and not state.physical_armed:
        return True
    return False


def _command_id(key: str) -> str:
    return f"cmd:{key}"


def _confirmation_id(decision_id: str) -> str:
    return f"conf:{decision_id}"


def _build_command(
    decision: IntentDecisionPayload,
    action: str,
    config: SafetyConfig,
    now_ns: int,
    *,
    target_object_id: str | None | object = ...,
) -> ActionCommand:
    target = decision.target_object_id if target_object_id is ... else target_object_id
    key = idempotency_key(decision.decision_id, action, target)
    ttl_ns = int(config.max_intent_age_ms * NS_PER_MS)
    expires = decision.expires_at_ns if decision.expires_at_ns > now_ns else now_ns + ttl_ns
    return ActionCommand(
        schema_version=SCHEMA_VERSION,
        command_id=_command_id(key),
        decision_id=decision.decision_id,
        action=action,
        target_object_id=target,
        issued_at_ns=now_ns,
        expires_at_ns=expires,
        safety_policy_version=config.policy_version,
        idempotency_key=key,
    )


def evaluate(
    decision: IntentDecisionPayload,
    state: SafetyState,
    config: SafetyConfig,
    *,
    now_ns: int,
    schema_valid: bool = True,
    confirmation_satisfied: bool = False,
    phase: str = "proposal",
    decision_time_ns: int | None = None,
    is_stop_event: bool = False,
    is_cancel_event: bool = False,
) -> PolicyResult:
    """Evaluate one immutable intent (or synthesized control) against world state."""
    action = _as_action(decision.action)
    control = action in _CONTROL_ACTIONS or is_stop_event or is_cancel_event
    stop_event = is_stop_event or action == Action.STOP
    cancel_event = is_cancel_event or action == Action.CANCEL
    in_confirmation = phase == "confirmation"
    atoms: list[_Atom] = []

    def add(name: str, passed: bool, reason_code: str, blocking: str = "ok") -> None:
        atoms.append(_Atom(name, passed, reason_code, blocking if not passed else "ok"))

    # --- required checks (always recorded) ---
    add(
        "schema_valid",
        schema_valid,
        Reason.SCHEMA_VALID if schema_valid else Reason.SCHEMA_INVALID,
        "reject",
    )

    expired = now_ns > decision.expires_at_ns
    if decision_time_ns is not None:
        age = _age_ms(now_ns, decision_time_ns)
        if age is not None and age > config.max_intent_age_ms:
            expired = True
    add(
        "intent_fresh",
        not expired,
        Reason.INTENT_FRESH if not expired else Reason.INTENT_EXPIRED,
        "hold",
    )

    session_ok = state.session_active
    add(
        "session_active",
        session_ok or control,
        Reason.SESSION_ACTIVE if session_ok else Reason.SESSION_INACTIVE,
        "hold",
    )

    trial_required = action in _TARGETED_ACTIONS
    trial_ok = state.trial_active or not trial_required or control
    trial_code = (
        Reason.TRIAL_ACTIVE if (state.trial_active or not trial_required) else Reason.TRIAL_INACTIVE
    )
    add("trial_active", trial_ok, trial_code, "hold")

    machine = str(state.machine_state)
    machine_age = _age_ms(now_ns, state.machine_updated_at_ns)
    machine_stale = state.machine_updated_at_ns is None or (
        machine_age is not None and machine_age > config.max_machine_state_age_ms
    )
    if not control:
        if machine == MachineState.ESTOPPED or state.stop_latched:
            add("machine_ready", False, Reason.MACHINE_ESTOPPED, "estop")
        elif machine == MachineState.FAULT:
            add("machine_ready", False, Reason.MACHINE_FAULTED, "reject")
        elif machine == MachineState.DISCONNECTED:
            add("machine_ready", False, Reason.MACHINE_DISCONNECTED, "hold")
        elif machine_stale:
            add("machine_ready", False, Reason.MACHINE_STATE_STALE, "hold")
        elif machine in _BUSY_STATES:
            add("machine_ready", False, Reason.MACHINE_BUSY, "hold")
        elif machine not in _READY_STATES:
            add("machine_ready", False, Reason.MACHINE_NOT_READY, "hold")
        else:
            add("machine_ready", True, Reason.MACHINE_READY, "ok")
    else:
        if machine == MachineState.ESTOPPED and not stop_event:
            add("machine_ready", False, Reason.MACHINE_ESTOPPED, "estop")
        else:
            add("machine_ready", True, Reason.MACHINE_READY, "ok")

    allowed = action in config.allowed_actions
    add(
        "action_allowed",
        allowed,
        Reason.ACTION_ALLOWED if allowed else Reason.ACTION_NOT_ALLOWED,
        "reject",
    )

    no_fault = machine != MachineState.FAULT and not (
        machine == MachineState.ESTOPPED and not stop_event
    )
    if machine == MachineState.FAULT and not control:
        add("no_fault_or_estop", False, Reason.MACHINE_FAULTED, "reject")
    elif (machine == MachineState.ESTOPPED or state.stop_latched) and not stop_event:
        add("no_fault_or_estop", False, Reason.MACHINE_ESTOPPED, "estop")
    else:
        add("no_fault_or_estop", no_fault or stop_event, Reason.NO_FAULT, "ok")

    key = idempotency_key(decision.decision_id, action, decision.target_object_id)
    duplicate = key in state.executed_keys or decision.decision_id in state.seen_decision_ids
    if duplicate and not control:
        add("idempotency", False, Reason.IDEMPOTENCY_DUPLICATE, "reject")
    else:
        add("idempotency", True, Reason.IDEMPOTENCY_NEW, "ok")

    confidence = decision.confidence
    if confidence < config.confirmation_threshold:
        add("confidence", False, Reason.CONFIDENCE_LOW, "reject")
    elif confidence < config.auto_approve_threshold:
        add(
            "confidence",
            confirmation_satisfied,
            Reason.CONFIDENCE_MODERATE if not confirmation_satisfied else Reason.CONFIDENCE_HIGH,
            "confirm",
        )
    else:
        add("confidence", True, Reason.CONFIDENCE_HIGH, "ok")

    margin = _target_margin(decision)
    if action in _TARGETED_ACTIONS and not confirmation_satisfied:
        margin_ok = margin >= config.minimum_target_margin
        add(
            "target_margin",
            margin_ok,
            Reason.TARGET_MARGIN_OK if margin_ok else Reason.TARGET_MARGIN_LOW,
            "confirm",
        )
    else:
        add("target_margin", True, Reason.TARGET_MARGIN_OK, "ok")

    if action in _TARGETED_ACTIONS:
        present = _modalities(decision)
        missing = set(config.required_modalities) - present
        add(
            "required_modalities",
            not missing,
            (
                Reason.REQUIRED_MODALITIES_PRESENT
                if not missing
                else Reason.REQUIRED_MODALITIES_MISSING
            ),
            "hold",
        )
        for modality in ("audio", "vision", "emg"):
            age = _evidence_age(decision, modality)
            stale_code = {
                "audio": Reason.EVIDENCE_STALE_AUDIO,
                "vision": Reason.EVIDENCE_STALE_VISION,
                "emg": Reason.EVIDENCE_STALE_EMG,
            }[modality]
            if age is not None and age > config.max_age_ms(modality):
                add(f"fresh_{modality}", False, stale_code, "hold")
            else:
                add(f"fresh_{modality}", True, f"EVIDENCE_FRESH_{modality.upper()}", "ok")
        vision_age = _age_ms(now_ns, state.vision_updated_at_ns)
        if vision_age is not None and vision_age > config.max_age_ms("vision"):
            add("fresh_vision_stream", False, Reason.EVIDENCE_STALE_VISION, "hold")
    else:
        add("required_modalities", True, Reason.REQUIRED_MODALITIES_PRESENT, "ok")

    conflict_codes = _conflicts(decision)
    unresolved = bool(conflict_codes) and not confirmation_satisfied
    spoken_pointed = any(
        "SPOKEN" in c.upper() or "POINT" in c.upper() or "CONFLICT" in c.upper()
        for c in conflict_codes
    )
    if unresolved:
        code = Reason.SPOKEN_POINTED_CONFLICT if spoken_pointed else Reason.UNRESOLVED_CONFLICT
        add("no_unresolved_conflict", False, code, "confirm")
    else:
        add("no_unresolved_conflict", True, Reason.NO_UNRESOLVED_CONFLICT, "ok")

    target = decision.target_object_id
    needs_target = action in _TARGETED_ACTIONS
    visible = (target in state.visible_object_ids) if target else not needs_target
    if needs_target and not visible:
        if in_confirmation:
            add("target_visible", False, Reason.TARGET_DISAPPEARED, "reject")
        else:
            add("target_visible", False, Reason.TARGET_MISSING, "hold")
    else:
        add("target_visible", True, Reason.TARGET_VISIBLE, "ok")

    deictic = action in _TARGETED_ACTIONS
    emg_ok = _emg_confirm_fresh(decision, state, config, now_ns)
    needs_emg = deictic and config.require_emg_confirmation_for_deictic
    if action == Action.CONFIRM and not in_confirmation and not confirmation_satisfied:
        add("confirmation", False, Reason.NOTHING_TO_CONFIRM, "reject")
    elif needs_emg and not confirmation_satisfied and not emg_ok:
        add("confirmation", False, Reason.CONFIRMATION_REQUIRED, "confirm")
        add("emg_confirmation", False, Reason.EMG_CONFIRMATION_MISSING, "confirm")
    elif confirmation_satisfied or emg_ok or not needs_emg:
        add("confirmation", True, Reason.CONFIRMATION_SATISFIED, "ok")
    else:
        add("confirmation", True, Reason.CONFIRMATION_SATISFIED, "ok")

    cancel_present = state.cancel_latched and not cancel_event
    add(
        "cancel_absent",
        not cancel_present,
        Reason.CANCEL_ABSENT if not cancel_present else Reason.CANCEL_LATCHED,
        "reject",
    )

    stop_present = (state.stop_latched or machine == MachineState.ESTOPPED) and not stop_event
    if stop_present:
        add("stop_absent", False, Reason.STOP_ACTIVE, "estop")
    else:
        stop_code = Reason.CANCEL_ABSENT if not stop_event else Reason.STOP_ACTIVE
        add("stop_absent", True, stop_code, "ok")

    hardware_blocked = _hardware_blocked(state, config)
    physical_disarmed = not config.physical_robot_enabled or not state.physical_armed
    if hardware_blocked:
        add("physical_robot", False, Reason.PHYSICAL_COMMAND_BLOCKED, "reject")
    else:
        add(
            "physical_robot",
            True,
            Reason.PHYSICAL_ROBOT_DISARMED if physical_disarmed else Reason.SIMULATOR_ONLY,
            "ok",
        )
    if not config.physical_robot_enabled:
        add("simulator_only", True, Reason.SIMULATOR_ONLY, "ok")
    if config.risk_tier(action) >= 2 and not config.physical_robot_enabled:
        add("risk_tier", False, Reason.PHYSICAL_COMMAND_BLOCKED, "reject")

    # Explicit stop/cancel on this event.
    if stop_event:
        add("stop_request", False, Reason.STOP_ACTIVE, "estop")
    if cancel_event and not stop_event:
        add("cancel_request", False, Reason.CANCEL_LATCHED, "reject")

    worst = "ok"
    for atom in atoms:
        if _RANK[atom.blocking] > _RANK[worst]:
            worst = atom.blocking

    verdict = {
        "ok": SafetyVerdict.APPROVE,
        "confirm": SafetyVerdict.ASK_CONFIRMATION,
        "hold": SafetyVerdict.HOLD,
        "reject": SafetyVerdict.REJECT,
        "estop": SafetyVerdict.EMERGENCY_STOP,
    }[worst]

    reason_codes = tuple(atom.reason_code for atom in atoms)
    named = {atom.name: atom.passed for atom in atoms}
    checks = SafetyChecks(
        intent_fresh=named.get("intent_fresh", True),
        target_visible=named.get("target_visible", True),
        cancel_absent=named.get("cancel_absent", True),
        machine_ready=named.get("machine_ready", True),
        session_active=named.get("session_active", True),
        schema_valid=named.get("schema_valid", True),
        no_unresolved_conflict=named.get("no_unresolved_conflict", True),
        confirmation_satisfied=named.get("confirmation", True),
        physical_robot_disarmed=physical_disarmed,
    )

    command: ActionCommand | None = None
    freeze: ConfirmationFreeze | None = None
    confirmation_id: str | None = None

    if verdict == SafetyVerdict.APPROVE and action in _TARGETED_ACTIONS:
        if hardware_blocked or (
            not config.physical_robot_enabled and state.command_destination == "hardware"
        ):
            command = None
        else:
            command = _build_command(decision, action, config, now_ns)
    elif verdict == SafetyVerdict.EMERGENCY_STOP and stop_event:
        stop_key = idempotency_key(decision.decision_id, Action.STOP, None)
        if stop_key not in state.executed_keys:
            command = _build_command(decision, Action.STOP, config, now_ns, target_object_id=None)
    elif verdict == SafetyVerdict.REJECT and cancel_event and machine in _BUSY_STATES:
        cancel_key = idempotency_key(decision.decision_id, Action.CANCEL, None)
        if cancel_key not in state.executed_keys:
            command = _build_command(decision, Action.CANCEL, config, now_ns, target_object_id=None)
    elif verdict == SafetyVerdict.ASK_CONFIRMATION:
        confirmation_id = _confirmation_id(decision.decision_id)
        freeze = ConfirmationFreeze(
            confirmation_id=confirmation_id,
            decision_id=decision.decision_id,
            action=action,
            target_object_id=decision.target_object_id,
            issued_at_ns=now_ns,
            expires_at_ns=now_ns + int(config.confirmation_timeout_ms * NS_PER_MS),
            decision=decision,
        )

    # Hard rule: never emit a command destined for hardware in simulator mode.
    if command is not None and not config.physical_robot_enabled:
        if state.command_destination == "hardware":
            command = None

    return PolicyResult(
        decision_id=decision.decision_id,
        verdict=verdict,
        reason_codes=reason_codes,
        checks=checks,
        command=command,
        confirmation_id=confirmation_id,
        freeze=freeze,
    )


def _payload(event: Mapping[str, Any]) -> dict[str, Any]:
    raw = event.get("payload", {})
    return dict(raw) if isinstance(raw, Mapping) else {}


def _event_time_ns(event: Mapping[str, Any], fallback: int) -> int:
    for key in ("normalized_time_ns", "source_time_ns", "received_monotonic_ns"):
        value = event.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return fallback


def _parse_decision(payload: Mapping[str, Any]) -> tuple[IntentDecisionPayload, bool]:
    try:
        return IntentDecisionPayload.model_validate(payload), True
    except Exception:
        try:
            stub = IntentDecisionPayload(
                decision_id=str(payload.get("decision_id") or "invalid"),
                action=str(payload.get("action") or Action.SELECT_OBJECT),
                confidence=0.0,
                expires_at_ns=int(payload.get("expires_at_ns") or 0),
                fusion_model_id=str(payload.get("fusion_model_id") or "invalid"),
            )
        except Exception:
            stub = IntentDecisionPayload(
                decision_id="invalid",
                action=Action.SELECT_OBJECT,
                confidence=0.0,
                expires_at_ns=0,
                fusion_model_id="invalid",
            )
        return stub, False


def _synthetic(decision_id: str, action: str, now_ns: int) -> IntentDecisionPayload:
    return IntentDecisionPayload(
        decision_id=decision_id,
        action=action,
        confidence=1.0,
        expires_at_ns=now_ns + 10 * NS_PER_MS * 1000,
        fusion_model_id=SOURCE,
        status="PROPOSED",
    )


def _timeout_result(
    freeze: ConfirmationFreeze, state: SafetyState, config: SafetyConfig, now_ns: int
) -> PolicyResult:
    checks = SafetyChecks(
        intent_fresh=False,
        target_visible=True,
        cancel_absent=not state.cancel_latched,
        machine_ready=str(state.machine_state) in _READY_STATES,
        session_active=state.session_active,
        schema_valid=True,
        no_unresolved_conflict=True,
        confirmation_satisfied=False,
        physical_robot_disarmed=not config.physical_robot_enabled,
    )
    return PolicyResult(
        decision_id=freeze.decision_id,
        verdict=SafetyVerdict.REJECT,
        reason_codes=(Reason.CONFIRMATION_TIMEOUT,),
        checks=checks,
        confirmation_id=freeze.confirmation_id,
    )


def _intent_changed_result(
    freeze: ConfirmationFreeze, state: SafetyState, config: SafetyConfig
) -> PolicyResult:
    checks = SafetyChecks(
        intent_fresh=True,
        target_visible=True,
        cancel_absent=not state.cancel_latched,
        machine_ready=str(state.machine_state) in _READY_STATES,
        session_active=state.session_active,
        schema_valid=True,
        no_unresolved_conflict=True,
        confirmation_satisfied=False,
        physical_robot_disarmed=not config.physical_robot_enabled,
    )
    return PolicyResult(
        decision_id=freeze.decision_id,
        verdict=SafetyVerdict.REJECT,
        reason_codes=(Reason.CONFIRMATION_INTENT_CHANGED,),
        checks=checks,
        confirmation_id=freeze.confirmation_id,
    )


def _commit_result(state: SafetyState, result: PolicyResult) -> SafetyState:
    new = state
    if result.verdict == SafetyVerdict.ASK_CONFIRMATION and result.freeze is not None:
        new = replace(new, pending_confirmation=result.freeze)
    elif result.verdict == SafetyVerdict.APPROVE:
        keys = new.executed_keys
        seen = new.seen_decision_ids
        if result.command is not None:
            keys = keys | {result.command.idempotency_key}
        seen = seen | {result.decision_id}
        new = replace(new, pending_confirmation=None, executed_keys=keys, seen_decision_ids=seen)
    elif result.verdict in {SafetyVerdict.REJECT, SafetyVerdict.EMERGENCY_STOP}:
        keys = new.executed_keys
        seen = new.seen_decision_ids | {result.decision_id}
        if result.command is not None:
            keys = keys | {result.command.idempotency_key}
        stop = new.stop_latched
        cancel = new.cancel_latched
        if result.verdict == SafetyVerdict.EMERGENCY_STOP:
            stop = True
        if Reason.CANCEL_LATCHED in result.reason_codes and result.command is not None:
            cancel = True
        new = replace(
            new,
            pending_confirmation=None,
            executed_keys=keys,
            seen_decision_ids=seen,
            stop_latched=stop,
            cancel_latched=cancel,
        )
    return new


def apply_event(
    state: SafetyState,
    event: Mapping[str, Any],
    config: SafetyConfig,
    *,
    now_ns: int,
) -> tuple[SafetyState, tuple[PolicyResult, ...]]:
    """Deterministic state transition. Returns (next_state, outputs)."""
    results: list[PolicyResult] = []
    event_type = str(event.get("event_type") or "")
    payload = _payload(event)
    event_ns = _event_time_ns(event, now_ns)

    pending = state.pending_confirmation
    if pending is not None and now_ns > pending.expires_at_ns:
        timeout = _timeout_result(pending, state, config, now_ns)
        results.append(timeout)
        state = replace(
            state,
            pending_confirmation=None,
            seen_decision_ids=state.seen_decision_ids | {pending.decision_id},
        )

    if event_type == "session.started":
        state = replace(
            state,
            session_id=event.get("session_id") or state.session_id,
            session_active=True,
        )
        return state, tuple(results)
    if event_type in {"session.stopped", "session.failed"}:
        state = replace(state, session_active=False, trial_active=False, trial_id=None)
        return state, tuple(results)
    if event_type == "trial.started":
        state = replace(
            state,
            trial_id=event.get("trial_id") or state.trial_id,
            trial_active=True,
            session_id=event.get("session_id") or state.session_id,
        )
        return state, tuple(results)
    if event_type in {"trial.completed", "trial.aborted"}:
        state = replace(state, trial_active=False)
        return state, tuple(results)

    if event_type == "machine.state":
        previous = str(state.machine_state)
        new_machine = str(payload.get("state") or state.machine_state)
        state = replace(
            state,
            machine_state=new_machine,
            machine_updated_at_ns=event_ns,
            machine_fault_reason=payload.get("fault_reason"),
            machine_active_command_id=payload.get("active_command_id"),
        )
        if state.cancel_latched and new_machine in {
            MachineState.CANCELLED,
            MachineState.READY,
            MachineState.IDLE,
        }:
            state = replace(state, cancel_latched=False)
        if (
            state.stop_latched
            and previous == MachineState.ESTOPPED
            and new_machine in {MachineState.IDLE, MachineState.READY}
        ):
            state = replace(state, stop_latched=False)
        if new_machine == MachineState.ESTOPPED:
            state = replace(state, stop_latched=True)
        return state, tuple(results)

    if event_type == "vision.objects":
        objects = payload.get("objects") or []
        ids = frozenset(
            str(obj.get("object_id"))
            for obj in objects
            if isinstance(obj, Mapping) and obj.get("object_id")
        )
        state = replace(state, visible_object_ids=ids, vision_updated_at_ns=event_ns)
        freeze = state.pending_confirmation
        if freeze is not None and freeze.target_object_id and freeze.target_object_id not in ids:
            result = evaluate(
                freeze.decision,
                state,
                config,
                now_ns=now_ns,
                confirmation_satisfied=False,
                phase="confirmation",
                decision_time_ns=freeze.issued_at_ns,
            )
            if result.verdict != SafetyVerdict.EMERGENCY_STOP:
                codes = result.reason_codes
                if Reason.TARGET_DISAPPEARED not in codes:
                    codes = codes + (Reason.TARGET_DISAPPEARED,)
                result = PolicyResult(
                    decision_id=freeze.decision_id,
                    verdict=SafetyVerdict.REJECT,
                    reason_codes=codes,
                    checks=replace_check(
                        result.checks, target_visible=False, confirmation_satisfied=False
                    ),
                    confirmation_id=freeze.confirmation_id,
                )
            else:
                result = PolicyResult(
                    decision_id=result.decision_id,
                    verdict=result.verdict,
                    reason_codes=result.reason_codes,
                    checks=result.checks,
                    confirmation_id=freeze.confirmation_id,
                )
            results.append(result)
            state = _commit_result(state, result)
            state = replace(state, pending_confirmation=None)
        return state, tuple(results)

    if event_type == "action.outcome":
        outcome = str(payload.get("outcome") or "")
        if outcome == "CANCELLED":
            state = replace(state, cancel_latched=False)
        if outcome == "ESTOPPED":
            state = replace(state, stop_latched=True)
        return state, tuple(results)

    if event_type == "modality.feature":
        label = str(payload.get("label") or "").lower()
        confidence = float(payload.get("confidence") or 0.0)
        state = replace(
            state,
            last_emg_label=label,
            last_emg_at_ns=event_ns,
            last_emg_confidence=confidence,
        )
        if label in {"stop", "estop", "emergency_stop"}:
            return _apply_stop(state, config, now_ns, results, event)
        if label == "cancel":
            return _apply_cancel(state, config, now_ns, results, event)
        if label == "confirm" and state.pending_confirmation is not None:
            freeze = state.pending_confirmation
            result = evaluate(
                freeze.decision,
                state,
                config,
                now_ns=now_ns,
                confirmation_satisfied=True,
                phase="confirmation",
                decision_time_ns=freeze.issued_at_ns,
            )
            result = PolicyResult(
                decision_id=result.decision_id,
                verdict=result.verdict,
                reason_codes=result.reason_codes,
                checks=result.checks,
                command=result.command,
                confirmation_id=freeze.confirmation_id,
                freeze=result.freeze,
            )
            results.append(result)
            state = _commit_result(state, result)
            if result.verdict != SafetyVerdict.ASK_CONFIRMATION:
                state = replace(state, pending_confirmation=None)
        return state, tuple(results)

    if event_type == "intent.decision":
        decision, schema_valid = _parse_decision(payload)
        action = _as_action(decision.action)

        # Cancel/stop always override a pending confirmation or proposal.
        if action == Action.STOP:
            return _apply_stop(state, config, now_ns, results, event, decision=decision)
        if action == Action.CANCEL:
            return _apply_cancel(state, config, now_ns, results, event, decision=decision)

        freeze = state.pending_confirmation

        if freeze is not None:
            changed = (
                freeze.action != action or freeze.target_object_id != decision.target_object_id
            )
            if changed:
                changed_result = _intent_changed_result(freeze, state, config)
                results.append(changed_result)
                state = replace(
                    state,
                    pending_confirmation=None,
                    seen_decision_ids=state.seen_decision_ids | {freeze.decision_id},
                )
            elif decision.decision_id == freeze.decision_id:
                # Duplicate proposal while waiting; re-emit the same confirmation.
                results.append(
                    PolicyResult(
                        decision_id=freeze.decision_id,
                        verdict=SafetyVerdict.ASK_CONFIRMATION,
                        reason_codes=(Reason.CONFIRMATION_REQUIRED,),
                        checks=SafetyChecks(
                            intent_fresh=True,
                            target_visible=freeze.target_object_id in state.visible_object_ids
                            if freeze.target_object_id
                            else True,
                            cancel_absent=not state.cancel_latched,
                            machine_ready=str(state.machine_state) in _READY_STATES,
                            session_active=state.session_active,
                            schema_valid=True,
                            no_unresolved_conflict=True,
                            confirmation_satisfied=False,
                            physical_robot_disarmed=not config.physical_robot_enabled,
                        ),
                        confirmation_id=freeze.confirmation_id,
                        freeze=freeze,
                    )
                )
                return state, tuple(results)

        if action == Action.CONFIRM and state.pending_confirmation is not None:
            freeze = state.pending_confirmation
            result = evaluate(
                freeze.decision,
                state,
                config,
                now_ns=now_ns,
                confirmation_satisfied=True,
                phase="confirmation",
                decision_time_ns=freeze.issued_at_ns,
            )
            result = PolicyResult(
                decision_id=result.decision_id,
                verdict=result.verdict,
                reason_codes=result.reason_codes,
                checks=result.checks,
                command=result.command,
                confirmation_id=freeze.confirmation_id,
                freeze=result.freeze,
            )
            results.append(result)
            state = _commit_result(state, result)
            if result.verdict != SafetyVerdict.ASK_CONFIRMATION:
                state = replace(state, pending_confirmation=None)
            return state, tuple(results)

        session_id = event.get("session_id")
        trial_id = event.get("trial_id")
        if session_id and not state.session_id:
            state = replace(state, session_id=str(session_id))
        if trial_id and not state.trial_id:
            state = replace(state, trial_id=str(trial_id))

        result = evaluate(
            decision,
            state,
            config,
            now_ns=now_ns,
            schema_valid=schema_valid,
            confirmation_satisfied=False,
            phase="proposal",
            decision_time_ns=event_ns,
        )
        results.append(result)
        state = _commit_result(state, result)
        return state, tuple(results)

    return state, tuple(results)


def replace_check(checks: SafetyChecks, **kwargs: bool) -> SafetyChecks:
    data = checks.model_dump()
    data.update(kwargs)
    return SafetyChecks.model_validate(data)


def _apply_stop(
    state: SafetyState,
    config: SafetyConfig,
    now_ns: int,
    results: list[PolicyResult],
    event: Mapping[str, Any],
    decision: IntentDecisionPayload | None = None,
) -> tuple[SafetyState, tuple[PolicyResult, ...]]:
    freeze = state.pending_confirmation
    decision_id = (
        decision.decision_id
        if decision is not None
        else (freeze.decision_id if freeze else f"stop-{now_ns}")
    )
    synthetic = decision or _synthetic(decision_id, Action.STOP, now_ns)
    result = evaluate(
        synthetic,
        state,
        config,
        now_ns=now_ns,
        is_stop_event=True,
        decision_time_ns=_event_time_ns(event, now_ns),
    )
    results.append(result)
    keys = state.executed_keys
    if result.command is not None:
        keys = keys | {result.command.idempotency_key}
    state = replace(
        state,
        pending_confirmation=None,
        stop_latched=True if config.stop_latch else state.stop_latched,
        cancel_latched=state.cancel_latched,
        executed_keys=keys,
        seen_decision_ids=state.seen_decision_ids | {result.decision_id},
    )
    return state, tuple(results)


def _apply_cancel(
    state: SafetyState,
    config: SafetyConfig,
    now_ns: int,
    results: list[PolicyResult],
    event: Mapping[str, Any],
    decision: IntentDecisionPayload | None = None,
) -> tuple[SafetyState, tuple[PolicyResult, ...]]:
    if state.stop_latched or str(state.machine_state) == MachineState.ESTOPPED:
        # A new cancel cannot clear emergency stop; re-assert ESTOP.
        return _apply_stop(state, config, now_ns, results, event, decision)
    freeze = state.pending_confirmation
    decision_id = (
        decision.decision_id
        if decision is not None
        else (freeze.decision_id if freeze else f"cancel-{now_ns}")
    )
    synthetic = decision or _synthetic(decision_id, Action.CANCEL, now_ns)
    result = evaluate(
        synthetic,
        state,
        config,
        now_ns=now_ns,
        is_cancel_event=True,
        decision_time_ns=_event_time_ns(event, now_ns),
    )
    results.append(result)
    keys = state.executed_keys
    if result.command is not None:
        keys = keys | {result.command.idempotency_key}
    busy = str(state.machine_state) in _BUSY_STATES
    # Latch only while the machine must acknowledge; vacuous if already idle/ready.
    latch = busy or result.command is not None
    state = replace(
        state,
        pending_confirmation=None,
        cancel_latched=latch,
        executed_keys=keys,
        seen_decision_ids=state.seen_decision_ids | {result.decision_id},
    )
    return state, tuple(results)


def make_safety_event(
    result: PolicyResult,
    config: SafetyConfig,
    state: SafetyState,
    *,
    sequence: int,
    received_monotonic_ns: int,
    event_id: str,
) -> dict[str, Any]:
    payload = result.to_payload(config.policy_version)
    return {
        "schema_version": SCHEMA_VERSION,
        "event_id": event_id,
        "event_type": "safety.decision",
        "source": SOURCE,
        "modality": "safety",
        "session_id": state.session_id,
        "trial_id": state.trial_id,
        "sequence": sequence,
        "source_time_ns": None,
        "received_monotonic_ns": received_monotonic_ns,
        "quality": 1.0,
        "producer_version": "0.1.0",
        "payload": payload.model_dump(mode="json"),
    }
