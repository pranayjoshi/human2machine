from __future__ import annotations

from intent_contracts.enums import Action, MachineState
from intent_contracts.events import EvidenceItem, IntentAlternative, IntentDecisionPayload
from safety_gateway.policy import SafetyConfig, SafetyState, safety_config_from_mapping

NOW_NS = 1_000_000_000
EXPIRES_AT_NS = NOW_NS + 500_000_000
OBJECT_BLUE = "object_blue_1"
OBJECT_RED = "object_red_1"


def make_config(**overrides) -> SafetyConfig:
    base = safety_config_from_mapping(
        {
            "safety": {
                "mode": "simulator_only",
                "policy_version": "safety-policy-v1",
                "auto_approve_threshold": 0.92,
                "confirmation_threshold": 0.65,
                "minimum_target_margin": 0.20,
                "require_emg_confirmation_for_deictic": True,
                "max_intent_age_ms": 1000,
                "max_machine_state_age_ms": 500,
                "confirmation_timeout_ms": 4000,
                "stop_latch": True,
                "physical_robot_requires_arming": True,
                "allowed_actions": [
                    "SELECT_OBJECT",
                    "REQUEST_HANDOFF",
                    "CONFIRM",
                    "CANCEL",
                    "STOP",
                ],
                "risk_tiers": {
                    "SELECT_OBJECT": 0,
                    "REQUEST_HANDOFF": 1,
                    "CONFIRM": 0,
                    "CANCEL": 0,
                    "STOP": 0,
                },
            },
            "freshness_max_age_ms": {
                "audio.intent_candidate": 5000,
                "vision.objects": 500,
                "modality.feature.emg_gesture": 750,
            },
        }
    )
    return SafetyConfig(
        **{**base.__dict__, **overrides},
    )


def make_evidence(
    *,
    audio: bool = True,
    vision: bool = True,
    emg: bool = True,
    audio_age_ms: float = 40.0,
    vision_age_ms: float = 30.0,
    emg_age_ms: float = 10.0,
) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []
    if audio:
        items.append(
            EvidenceItem(
                event_id="ev_audio",
                modality="audio",
                contribution=0.4,
                quality=0.94,
                age_ms=audio_age_ms,
            )
        )
    if vision:
        items.append(
            EvidenceItem(
                event_id="ev_vision",
                modality="vision",
                contribution=0.38,
                quality=0.95,
                age_ms=vision_age_ms,
            )
        )
    if emg:
        items.append(
            EvidenceItem(
                event_id="ev_emg",
                modality="emg",
                contribution=0.22,
                quality=0.91,
                age_ms=emg_age_ms,
            )
        )
    return items


def make_decision(
    *,
    decision_id: str = "decision_1",
    action: str = Action.REQUEST_HANDOFF,
    target_object_id: str | None = OBJECT_BLUE,
    confidence: float = 0.95,
    alternatives: list[IntentAlternative] | None = None,
    evidence: list[EvidenceItem] | None = None,
    expires_at_ns: int = EXPIRES_AT_NS,
    conflicts: list[str] | None = None,
    include_emg: bool = True,
    **kwargs,
) -> IntentDecisionPayload:
    if evidence is None:
        evidence = make_evidence(emg=include_emg)
    if alternatives is None:
        alternatives = [IntentAlternative(target_object_id=OBJECT_RED, confidence=0.06)]
    return IntentDecisionPayload(
        decision_id=decision_id,
        action=action,
        target_object_id=target_object_id,
        confidence=confidence,
        alternatives=alternatives,
        evidence=evidence,
        fusion_model_id="late-fusion-v1",
        fusion_state="COMMIT_PROPOSED",
        expires_at_ns=expires_at_ns,
        conflicts=conflicts or [],
        **kwargs,
    )


def make_state(**overrides) -> SafetyState:
    base = SafetyState(
        session_id="session_1",
        session_active=True,
        trial_id="trial_1",
        trial_active=True,
        machine_state=MachineState.READY,
        machine_updated_at_ns=NOW_NS,
        visible_object_ids=frozenset({OBJECT_BLUE, OBJECT_RED}),
        vision_updated_at_ns=NOW_NS,
    )
    return SafetyState(**{**base.__dict__, **overrides})


def envelope(
    event_type: str,
    payload: dict | None = None,
    *,
    now_ns: int = NOW_NS,
    session_id: str | None = "session_1",
    trial_id: str | None = "trial_1",
    event_id: str = "evt_1",
) -> dict:
    return {
        "schema_version": "1.0.0",
        "event_id": event_id,
        "event_type": event_type,
        "source": "test",
        "session_id": session_id,
        "trial_id": trial_id,
        "sequence": 1,
        "normalized_time_ns": now_ns,
        "received_monotonic_ns": now_ns,
        "quality": 1.0,
        "producer_version": "0.1.0",
        "payload": payload or {},
    }


def intent_event(
    decision: IntentDecisionPayload, *, now_ns: int = NOW_NS, event_id: str = "evt_intent"
) -> dict:
    return envelope(
        "intent.decision",
        decision.model_dump(mode="json"),
        now_ns=now_ns,
        event_id=event_id,
    )


def vision_event(object_ids: list[str], *, now_ns: int = NOW_NS) -> dict:
    objects = [
        {
            "object_id": oid,
            "class_name": "block",
            "confidence": 0.98,
            "bbox_xyxy": [0.0, 0.0, 1.0, 1.0],
            "table_position_xy": [0.1, 0.2],
        }
        for oid in object_ids
    ]
    return envelope(
        "vision.objects",
        {
            "frame_id": 1,
            "objects": objects,
            "pointing_candidates": [],
            "head_direction_candidates": [],
        },
        now_ns=now_ns,
    )


def machine_event(
    state: str, *, now_ns: int = NOW_NS, active_command_id: str | None = None
) -> dict:
    return envelope(
        "machine.state",
        {"state": state, "active_command_id": active_command_id, "progress": 0.0},
        now_ns=now_ns,
    )


def feature_event(label: str, *, now_ns: int = NOW_NS, confidence: float = 0.91) -> dict:
    return envelope(
        "modality.feature",
        {
            "feature_name": "emg_gesture",
            "window_start_ns": now_ns - 1_000_000,
            "window_end_ns": now_ns,
            "label": label,
            "confidence": confidence,
            "candidate_scores": {label: confidence},
            "model_id": "emg-test",
            "shadow_only": False,
        },
        now_ns=now_ns,
    )
