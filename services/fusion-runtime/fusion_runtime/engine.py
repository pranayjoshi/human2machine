"""Pure deterministic late-fusion engine.

    (state, evidence_window, user_profile, config) -> events

Transport, clocks, and I/O live in `main.py`. This module never creates
`ActionCommand` objects.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from intent_contracts.enums import (
    PRODUCER_VERSION,
    SCHEMA_VERSION,
    Action,
    EventType,
    FusionState,
    IntentStatus,
    MachineState,
    SessionState,
    TargetReference,
)
from intent_contracts.envelope import EventEnvelope
from intent_contracts.events import (
    EvidenceItem,
    IntentAlternative,
    IntentCandidateSetPayload,
    IntentConflictPayload,
    IntentDecisionPayload,
    IntentTimeoutPayload,
)

from fusion_runtime.scoring import (
    eeg_live_contribution,
    evidence_contribution,
    freshness_decay,
)
from fusion_runtime.state_machine import (
    advance_to,
    reset_after_cancel,
    reset_after_outcome,
)

NS_PER_MS = 1_000_000
SOURCE = "fusion-runtime"
MODALITY = "fusion"

UNKNOWN_LABELS = frozenset({"unknown", "unk", ""})
EMG_REST_LABELS = frozenset({"rest"})
CONFIRM_LABELS = frozenset({"confirm"})
CANCEL_LABELS = frozenset({"cancel"})
STOP_ACTIONS = frozenset({Action.STOP, "STOP"})
CANCEL_ACTIONS = frozenset({Action.CANCEL, "CANCEL"})
CONFIRM_ACTIONS = frozenset({Action.CONFIRM, "CONFIRM"})
REQUEST_ACTIONS = frozenset({Action.SELECT_OBJECT, Action.REQUEST_HANDOFF})
ACTIVE_SESSION_STATES = frozenset(
    {SessionState.READY, SessionState.RECORDING, "READY", "RECORDING"}
)
BLOCKING_CONFLICTS = frozenset(
    {
        "SPOKEN_POINTED_MISMATCH",
        "CONFIRM_CANCEL_CONFLICT",
        "TARGET_DISAPPEARED",
        "ACTION_CHANGED",
    }
)
CONFLICT_REASON_SPOKEN_POINTED = "SPOKEN_POINTED_MISMATCH"
CONFLICT_REASON_MARGIN = "TARGET_MARGIN_LOW"
CONFLICT_REASON_CONFIRM_CANCEL = "CONFIRM_CANCEL_CONFLICT"
CONFLICT_REASON_TARGET_GONE = "TARGET_DISAPPEARED"
CONFLICT_REASON_ACTION_CHANGED = "ACTION_CHANGED"

_DEFAULT_TIME_CONSTANTS = {
    "audio": 2500.0,
    "vision": 250.0,
    "emg": 400.0,
    "eeg": 800.0,
}
_DEFAULT_WEIGHTS = {
    "audio_action": 1.0,
    "audio_named_target": 0.9,
    "vision_pointing": 0.8,
    "vision_head_direction": 0.2,
    "emg_confirm": 0.85,
    "emg_cancel": 1.0,
    "eeg_shadow": 0.0,
}
_DEFAULT_FRESHNESS = {
    "audio.intent_candidate": 5000,
    "vision.objects": 500,
    "vision.hands": 500,
    "vision.head_direction": 500,
    "modality.feature.emg_gesture": 750,
    "modality.feature.eeg_shadow": 1000,
    "machine.state": 500,
    "service.heartbeat": 5000,
}
_DEFAULT_RELIABILITY = {
    "audio": 1.0,
    "vision": 1.0,
    "emg": 1.0,
    "eeg": 1.0,
}


def _mapping(value: Mapping[str, Any] | None, fallback: dict[str, Any]) -> dict[str, Any]:
    if not value:
        return dict(fallback)
    merged = dict(fallback)
    merged.update(value)
    return merged


@dataclass(frozen=True)
class FusionConfig:
    model_id: str = "late-fusion-v1"
    time_constant_ms: Mapping[str, float] = field(
        default_factory=lambda: dict(_DEFAULT_TIME_CONSTANTS)
    )
    weights: Mapping[str, float] = field(default_factory=lambda: dict(_DEFAULT_WEIGHTS))
    minimum_target_margin: float = 0.20
    decision_ttl_ms: int = 1500
    cancel_latency_ms: int = 120
    eeg_shadow_only: bool = True
    emg_shadow_only: bool = True
    freshness_max_age_ms: Mapping[str, int] = field(
        default_factory=lambda: dict(_DEFAULT_FRESHNESS)
    )
    pointing_confidence_min: float = 0.55
    gesture_confidence_min: float = 0.7
    conflict_confidence_factor: float = 0.6

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> FusionConfig:
        fusion = data.get("fusion", data)
        vision = data.get("vision", {})
        ganglion = data.get("ganglion", {})
        freshness = data.get("freshness_max_age_ms", {})
        return cls(
            model_id=str(fusion.get("model_id", "late-fusion-v1")),
            time_constant_ms=_mapping(fusion.get("time_constant_ms"), _DEFAULT_TIME_CONSTANTS),
            weights=_mapping(fusion.get("weights"), _DEFAULT_WEIGHTS),
            minimum_target_margin=float(fusion.get("minimum_target_margin", 0.20)),
            decision_ttl_ms=int(fusion.get("decision_ttl_ms", 1500)),
            cancel_latency_ms=int(fusion.get("cancel_latency_ms", 120)),
            eeg_shadow_only=bool(fusion.get("eeg_shadow_only", True)),
            emg_shadow_only=bool(fusion.get("emg_shadow_only", ganglion.get("shadow_only", True))),
            freshness_max_age_ms=_mapping(freshness, _DEFAULT_FRESHNESS),
            pointing_confidence_min=float(vision.get("pointing_confidence_min", 0.55)),
            gesture_confidence_min=float(ganglion.get("confidence_threshold", 0.7)),
        )

    def weight(self, key: str) -> float:
        return float(self.weights.get(key, 0.0))

    def time_constant(self, modality: str) -> float:
        return float(self.time_constant_ms.get(modality, 1.0))

    def max_age_ms(self, key: str) -> float | None:
        if key in self.freshness_max_age_ms:
            return float(self.freshness_max_age_ms[key])
        return None


@dataclass
class UserProfile:
    """Pseudonymous per-user calibration. Never updated from fusion's own predictions."""

    emg_model_id: str | None = None
    reliability: dict[str, float] = field(default_factory=lambda: dict(_DEFAULT_RELIABILITY))

    def reliability_for(self, modality: str) -> float:
        return float(self.reliability.get(modality, 1.0))

    def with_emg_model(self, model_id: str | None) -> UserProfile:
        if not model_id or model_id == self.emg_model_id:
            return self
        return replace(self, emg_model_id=model_id, reliability=dict(self.reliability))


@dataclass
class FusionRuntimeState:
    fusion_state: FusionState = FusionState.IDLE
    session_id: str | None = None
    trial_id: str | None = None
    session_active: bool = False
    machine_state: str | None = None
    current_objects: tuple[str, ...] = ()
    proposed_action: str | None = None
    proposed_target: str | None = None
    last_decision_id: str | None = None
    last_decision_expires_at_ns: int | None = None
    last_signature: str | None = None
    event_seq: int = 0
    decision_seq: int = 0

    def clone(self) -> FusionRuntimeState:
        return replace(self, current_objects=tuple(self.current_objects))


@dataclass(frozen=True)
class EngineResult:
    state: FusionRuntimeState
    user_profile: UserProfile
    events: tuple[EventEnvelope, ...]


@dataclass(frozen=True)
class _RawContribution:
    event_id: str
    modality: str
    raw: float
    quality: float
    age_ms: float
    weight_key: str


@dataclass
class _ScoredPair:
    action: str
    target_object_id: str | None
    raw_score: float
    contributions: list[_RawContribution]


def _as_envelope(item: EventEnvelope | Mapping[str, Any]) -> EventEnvelope:
    if isinstance(item, EventEnvelope):
        return item
    return EventEnvelope.model_validate(dict(item))


def _event_time_ns(event: EventEnvelope) -> int:
    if event.normalized_time_ns is not None:
        return event.normalized_time_ns
    return event.received_monotonic_ns


def _event_type(event: EventEnvelope) -> str:
    return str(event.event_type)


def _freshness_key(event: EventEnvelope) -> str:
    etype = _event_type(event)
    if etype == EventType.MODALITY_FEATURE:
        name = str(event.payload.get("feature_name") or "")
        if name:
            return f"modality.feature.{name}"
    return etype


def _age_ms(event: EventEnvelope, now_ns: int) -> float:
    return max(0.0, (now_ns - _event_time_ns(event)) / NS_PER_MS)


def _is_expired(event: EventEnvelope, now_ns: int, config: FusionConfig) -> bool:
    limit = config.max_age_ms(_freshness_key(event))
    if limit is None:
        return False
    return _age_ms(event, now_ns) > limit


def _quality_usable(quality: float) -> bool:
    return quality > 0.0


def _modality_of(event: EventEnvelope, default: str) -> str:
    return (event.modality or default).lower()


def _normalize_action(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    if text.lower() in UNKNOWN_LABELS:
        return None
    return text


def _object_ids(payload: Mapping[str, Any]) -> tuple[str, ...]:
    ids: list[str] = []
    for obj in payload.get("objects") or []:
        object_id = obj.get("object_id") if isinstance(obj, Mapping) else None
        if object_id:
            ids.append(str(object_id))
    return tuple(ids)


def _target_candidates(items: Any) -> list[tuple[str, float]]:
    out: list[tuple[str, float]] = []
    for item in items or []:
        if not isinstance(item, Mapping):
            continue
        object_id = item.get("object_id")
        if not object_id:
            continue
        try:
            confidence = float(item.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        out.append((str(object_id), confidence))
    return out


def _machine_ready(machine_state: str | None) -> bool:
    return machine_state in {MachineState.READY, "READY"}


def _window_now_ns(events: Sequence[EventEnvelope], fallback: int | None) -> int:
    if fallback is not None:
        return fallback
    if not events:
        return 0
    return max(_event_time_ns(event) for event in events)


def _next_event_id(state: FusionRuntimeState) -> str:
    state.event_seq += 1
    return f"fuse{state.event_seq:012d}"


def _next_decision_id(state: FusionRuntimeState) -> str:
    state.decision_seq += 1
    return f"dec{state.decision_seq:013d}"


def _make_event(
    state: FusionRuntimeState,
    event_type: EventType,
    payload: Mapping[str, Any],
    now_ns: int,
    *,
    quality: float = 1.0,
) -> EventEnvelope:
    return EventEnvelope(
        schema_version=SCHEMA_VERSION,
        event_id=_next_event_id(state),
        event_type=event_type,
        source=SOURCE,
        modality=MODALITY,
        session_id=state.session_id,
        trial_id=state.trial_id,
        sequence=state.event_seq,
        source_time_ns=None,
        received_monotonic_ns=max(0, now_ns),
        normalized_time_ns=None,
        quality=quality,
        producer_version=PRODUCER_VERSION,
        payload=dict(payload),
    )


def _apply_context(
    state: FusionRuntimeState,
    events: Sequence[EventEnvelope],
    now_ns: int,
    config: FusionConfig,
    profile: UserProfile,
) -> UserProfile:
    latest_objects: tuple[str, ...] | None = None
    for event in events:
        etype = _event_type(event)
        if etype == EventType.SESSION_STARTED:
            state.session_id = event.session_id or state.session_id
            payload_state = event.payload.get("state")
            state.session_active = payload_state in ACTIVE_SESSION_STATES or payload_state is None
        elif etype == EventType.SESSION_STOPPED:
            state.session_active = False
            payload_state = event.payload.get("state")
            if payload_state:
                state.session_active = False
        elif etype == EventType.SESSION_FAILED:
            state.session_active = False
        elif etype == EventType.TRIAL_STARTED:
            state.trial_id = event.trial_id or state.trial_id
        elif etype in {EventType.TRIAL_COMPLETED, EventType.TRIAL_ABORTED}:
            if event.trial_id and event.trial_id == state.trial_id:
                state.trial_id = event.trial_id
        elif etype == EventType.MACHINE_STATE and not _is_expired(event, now_ns, config):
            machine = event.payload.get("state")
            if machine is not None:
                state.machine_state = str(machine)
        elif etype == EventType.VISION_OBJECTS and not _is_expired(event, now_ns, config):
            latest_objects = _object_ids(event.payload)
        elif etype == EventType.MODALITY_FEATURE:
            feature_name = str(event.payload.get("feature_name") or "")
            if feature_name == "emg_gesture":
                profile = profile.with_emg_model(event.payload.get("model_id"))
    if latest_objects is not None:
        state.current_objects = latest_objects
    if event_session := _latest_session_id(events):
        state.session_id = state.session_id or event_session
    if event_trial := _latest_trial_id(events):
        state.trial_id = event_trial
    return profile


def _latest_session_id(events: Sequence[EventEnvelope]) -> str | None:
    for event in reversed(events):
        if event.session_id:
            return event.session_id
    return None


def _latest_trial_id(events: Sequence[EventEnvelope]) -> str | None:
    for event in reversed(events):
        if event.trial_id:
            return event.trial_id
    return None


def _fresh_events(
    events: Sequence[EventEnvelope],
    now_ns: int,
    config: FusionConfig,
    types: set[str],
) -> list[EventEnvelope]:
    out: list[EventEnvelope] = []
    for event in events:
        if _event_type(event) not in types:
            continue
        if not _quality_usable(event.quality):
            continue
        if _is_expired(event, now_ns, config):
            continue
        out.append(event)
    return out


def _latest(
    events: Sequence[EventEnvelope],
    now_ns: int,
    config: FusionConfig,
    etype: str,
) -> EventEnvelope | None:
    matched = _fresh_events(events, now_ns, config, {etype})
    return matched[-1] if matched else None


def _audio_is_final(event: EventEnvelope) -> bool:
    return bool(event.payload.get("is_final", False))


def _collect_audio(
    events: Sequence[EventEnvelope], now_ns: int, config: FusionConfig
) -> EventEnvelope | None:
    finals = [
        event
        for event in _fresh_events(events, now_ns, config, {EventType.AUDIO_INTENT_CANDIDATE})
        if _audio_is_final(event)
    ]
    return finals[-1] if finals else None


def _collect_all_final_audio(
    events: Sequence[EventEnvelope], now_ns: int, config: FusionConfig
) -> list[EventEnvelope]:
    return [
        event
        for event in _fresh_events(events, now_ns, config, {EventType.AUDIO_INTENT_CANDIDATE})
        if _audio_is_final(event)
    ]


def _emg_events(
    events: Sequence[EventEnvelope], now_ns: int, config: FusionConfig
) -> list[EventEnvelope]:
    out: list[EventEnvelope] = []
    for event in _fresh_events(events, now_ns, config, {EventType.MODALITY_FEATURE}):
        if str(event.payload.get("feature_name") or "") != "emg_gesture":
            continue
        if _modality_of(event, "emg") != "emg":
            continue
        if config.emg_shadow_only or bool(event.payload.get("shadow_only")):
            continue
        out.append(event)
    return out


def _eeg_events(
    events: Sequence[EventEnvelope], now_ns: int, config: FusionConfig
) -> list[EventEnvelope]:
    out: list[EventEnvelope] = []
    for event in _fresh_events(events, now_ns, config, {EventType.MODALITY_FEATURE}):
        name = str(event.payload.get("feature_name") or "")
        modality = _modality_of(event, "eeg")
        if name == "eeg_shadow" or modality == "eeg":
            out.append(event)
    return out


def _label_of(event: EventEnvelope) -> str:
    return str(event.payload.get("label") or "").lower()


def _score_map(event: EventEnvelope) -> dict[str, float]:
    raw = event.payload.get("candidate_scores") or {}
    out: dict[str, float] = {}
    if isinstance(raw, Mapping):
        for key, value in raw.items():
            try:
                out[str(key).lower()] = float(value)
            except (TypeError, ValueError):
                continue
    return out


def _gesture_positive(event: EventEnvelope, labels: frozenset[str], threshold: float) -> bool:
    label = _label_of(event)
    if label in UNKNOWN_LABELS or label in EMG_REST_LABELS:
        scores = _score_map(event)
        return any(scores.get(item, 0.0) >= threshold for item in labels)
    if label in labels:
        try:
            return float(event.payload.get("confidence", 0.0)) >= threshold
        except (TypeError, ValueError):
            return False
    scores = _score_map(event)
    return any(scores.get(item, 0.0) >= threshold for item in labels)


def _normalize_contributions(items: list[_RawContribution]) -> list[EvidenceItem]:
    positive = [item for item in items if item.raw > 0.0]
    total = sum(item.raw for item in positive)
    evidence: list[EvidenceItem] = []
    for item in items:
        contribution = (item.raw / total) if total > 0.0 and item.raw > 0.0 else 0.0
        evidence.append(
            EvidenceItem(
                event_id=item.event_id,
                modality=item.modality,
                contribution=contribution,
                quality=item.quality,
                age_ms=item.age_ms,
            )
        )
    return evidence


def _pair_key(action: str, target: str | None) -> tuple[str, str | None]:
    return (action, target)


def _visible(target: str | None, objects: Iterable[str]) -> bool:
    if target is None:
        return False
    return target in set(objects)


def _score_pairs(
    *,
    audio: EventEnvelope | None,
    vision: EventEnvelope | None,
    head: EventEnvelope | None,
    emg_confirm_event: EventEnvelope | None,
    eeg: Sequence[EventEnvelope],
    objects: Sequence[str],
    now_ns: int,
    config: FusionConfig,
    profile: UserProfile,
) -> list[_ScoredPair]:
    actions: list[str] = []
    named_target: str | None = None
    target_reference = TargetReference.NONE
    audio_contribs: list[_RawContribution] = []

    if audio is not None:
        action = _normalize_action(audio.payload.get("action"))
        if action and action not in STOP_ACTIONS | CANCEL_ACTIONS | CONFIRM_ACTIONS:
            actions.append(action)
        named_target = audio.payload.get("target_object_id")
        named_target = str(named_target) if named_target else None
        target_reference = str(audio.payload.get("target_reference") or TargetReference.NONE)
        age = _age_ms(audio, now_ns)
        decay = freshness_decay(age, config.time_constant("audio"))
        quality = audio.quality
        reliability = profile.reliability_for("audio")
        confidence = float(audio.payload.get("confidence", 0.0))
        if action and action not in STOP_ACTIONS | CANCEL_ACTIONS | CONFIRM_ACTIONS:
            audio_contribs.append(
                _RawContribution(
                    event_id=audio.event_id,
                    modality="audio",
                    raw=evidence_contribution(
                        config.weight("audio_action"),
                        confidence,
                        quality,
                        decay,
                        reliability,
                    ),
                    quality=quality,
                    age_ms=age,
                    weight_key="audio_action",
                )
            )

    pointing: list[tuple[str, float, EventEnvelope]] = []
    heading: list[tuple[str, float, EventEnvelope]] = []
    if vision is not None:
        for object_id, confidence in _target_candidates(vision.payload.get("pointing_candidates")):
            pointing.append((object_id, confidence, vision))
        for object_id, confidence in _target_candidates(
            vision.payload.get("head_direction_candidates")
        ):
            heading.append((object_id, confidence, vision))
    if head is not None:
        for object_id, confidence in _target_candidates(head.payload.get("candidates")):
            heading.append((object_id, confidence, head))

    targets: set[str] = set()
    if named_target and _visible(named_target, objects):
        targets.add(named_target)
    for object_id, confidence, _event in pointing:
        if confidence >= config.pointing_confidence_min and _visible(object_id, objects):
            targets.add(object_id)
    for object_id, confidence, _event in heading:
        if confidence > 0.0 and _visible(object_id, objects):
            targets.add(object_id)

    if not actions:
        return []

    pairs: list[_ScoredPair] = []
    for action in actions:
        candidate_targets: list[str | None]
        if targets:
            candidate_targets = list(targets)
        elif target_reference in {
            TargetReference.DEICTIC,
            "DEICTIC",
            TargetReference.ORDINAL,
            "ORDINAL",
        }:
            candidate_targets = [None]
        elif named_target and not _visible(named_target, objects):
            candidate_targets = [None]
        else:
            candidate_targets = [named_target]

        for target in candidate_targets:
            contribs = [
                replace(item) for item in audio_contribs if item.weight_key == "audio_action"
            ]
            if (
                audio is not None
                and named_target
                and target == named_target
                and target_reference in {TargetReference.NAMED, "NAMED"}
                and _visible(target, objects)
            ):
                age = _age_ms(audio, now_ns)
                contribs.append(
                    _RawContribution(
                        event_id=audio.event_id,
                        modality="audio",
                        raw=evidence_contribution(
                            config.weight("audio_named_target"),
                            float(audio.payload.get("confidence", 0.0)),
                            audio.quality,
                            freshness_decay(age, config.time_constant("audio")),
                            profile.reliability_for("audio"),
                        ),
                        quality=audio.quality,
                        age_ms=age,
                        weight_key="audio_named_target",
                    )
                )
            for object_id, confidence, event in pointing:
                if object_id != target:
                    continue
                age = _age_ms(event, now_ns)
                contribs.append(
                    _RawContribution(
                        event_id=event.event_id,
                        modality="vision",
                        raw=evidence_contribution(
                            config.weight("vision_pointing"),
                            confidence,
                            event.quality,
                            freshness_decay(age, config.time_constant("vision")),
                            profile.reliability_for("vision"),
                        ),
                        quality=event.quality,
                        age_ms=age,
                        weight_key="vision_pointing",
                    )
                )
            for object_id, confidence, event in heading:
                if object_id != target:
                    continue
                age = _age_ms(event, now_ns)
                contribs.append(
                    _RawContribution(
                        event_id=event.event_id,
                        modality="vision",
                        raw=evidence_contribution(
                            config.weight("vision_head_direction"),
                            confidence,
                            event.quality,
                            freshness_decay(age, config.time_constant("vision")),
                            profile.reliability_for("vision"),
                        ),
                        quality=event.quality,
                        age_ms=age,
                        weight_key="vision_head_direction",
                    )
                )
            if emg_confirm_event is not None and target is not None:
                age = _age_ms(emg_confirm_event, now_ns)
                contribs.append(
                    _RawContribution(
                        event_id=emg_confirm_event.event_id,
                        modality="emg",
                        raw=evidence_contribution(
                            config.weight("emg_confirm"),
                            float(emg_confirm_event.payload.get("confidence", 0.0)),
                            emg_confirm_event.quality,
                            freshness_decay(age, config.time_constant("emg")),
                            profile.reliability_for("emg"),
                        ),
                        quality=emg_confirm_event.quality,
                        age_ms=age,
                        weight_key="emg_confirm",
                    )
                )
            for event in eeg:
                age = _age_ms(event, now_ns)
                weight = 0.0 if config.eeg_shadow_only else config.weight("eeg_shadow")
                contribs.append(
                    _RawContribution(
                        event_id=event.event_id,
                        modality="eeg",
                        raw=eeg_live_contribution(
                            float(event.payload.get("confidence", 0.0)),
                            event.quality,
                            freshness_decay(age, config.time_constant("eeg")),
                            profile.reliability_for("eeg"),
                            weight=weight,
                        ),
                        quality=event.quality,
                        age_ms=age,
                        weight_key="eeg_shadow",
                    )
                )
            raw_score = sum(item.raw for item in contribs)
            pairs.append(
                _ScoredPair(
                    action=action,
                    target_object_id=target,
                    raw_score=raw_score,
                    contributions=contribs,
                )
            )
    return pairs


def _normalize_pair_scores(pairs: Sequence[_ScoredPair]) -> list[tuple[_ScoredPair, float]]:
    total = sum(max(0.0, pair.raw_score) for pair in pairs)
    ranked: list[tuple[_ScoredPair, float]] = []
    for pair in pairs:
        confidence = (pair.raw_score / total) if total > 0.0 else 0.0
        ranked.append((pair, min(1.0, max(0.0, confidence))))
    ranked.sort(key=lambda item: (-item[1], item[0].action, item[0].target_object_id or ""))
    return ranked


def _target_margin(ranked: Sequence[tuple[_ScoredPair, float]]) -> float | None:
    seen: list[tuple[str, float]] = []
    for pair, confidence in ranked:
        target = pair.target_object_id
        if not target:
            continue
        existing = next((item for item in seen if item[0] == target), None)
        if existing is None:
            seen.append((target, confidence))
    if len(seen) < 2:
        return None
    seen.sort(key=lambda item: -item[1])
    return seen[0][1] - seen[1][1]


def _top_pointing(
    vision: EventEnvelope | None, config: FusionConfig, objects: Sequence[str]
) -> tuple[str, float] | None:
    if vision is None:
        return None
    ranked = [
        (object_id, confidence)
        for object_id, confidence in _target_candidates(vision.payload.get("pointing_candidates"))
        if _visible(object_id, objects)
    ]
    if not ranked:
        return None
    ranked.sort(key=lambda item: -item[1])
    object_id, confidence = ranked[0]
    if confidence < config.pointing_confidence_min:
        return None
    return object_id, confidence


def _detect_conflicts(
    *,
    state: FusionRuntimeState,
    audio: EventEnvelope | None,
    all_audio: Sequence[EventEnvelope],
    vision: EventEnvelope | None,
    objects: Sequence[str],
    has_confirm: bool,
    has_cancel: bool,
    ranked: Sequence[tuple[_ScoredPair, float]],
    config: FusionConfig,
) -> list[str]:
    reasons: list[str] = []
    if has_confirm and has_cancel:
        reasons.append(CONFLICT_REASON_CONFIRM_CANCEL)

    if audio is not None:
        reference = str(audio.payload.get("target_reference") or TargetReference.NONE)
        named = audio.payload.get("target_object_id")
        named = str(named) if named else None
        pointed = _top_pointing(vision, config, objects)
        if (
            reference in {TargetReference.NAMED, "NAMED"}
            and named
            and pointed
            and pointed[0] != named
        ):
            reasons.append(CONFLICT_REASON_SPOKEN_POINTED)

    margin = _target_margin(ranked)
    if margin is not None and margin < config.minimum_target_margin:
        reasons.append(CONFLICT_REASON_MARGIN)

    if (
        state.proposed_target
        and objects
        and vision is not None
        and state.proposed_target not in set(objects)
        and state.fusion_state
        in {
            FusionState.TARGET_PROPOSED,
            FusionState.AWAITING_CONFIRMATION,
            FusionState.COMMIT_PROPOSED,
        }
    ):
        reasons.append(CONFLICT_REASON_TARGET_GONE)

    if state.fusion_state == FusionState.AWAITING_CONFIRMATION and state.proposed_action:
        for event in all_audio:
            action = _normalize_action(event.payload.get("action"))
            if action is None:
                continue
            if action in STOP_ACTIONS | CANCEL_ACTIONS | CONFIRM_ACTIONS:
                continue
            if action != state.proposed_action:
                reasons.append(CONFLICT_REASON_ACTION_CHANGED)
                break

    # Preserve first-seen order, unique.
    unique: list[str] = []
    for reason in reasons:
        if reason not in unique:
            unique.append(reason)
    return unique


def _decision_confidence(
    pair: _ScoredPair, normalized: float, conflicts: Sequence[str], config: FusionConfig
) -> float:
    weight_sum = 0.0
    raw_sum = 0.0
    seen: set[str] = set()
    for item in pair.contributions:
        if item.weight_key in seen or item.raw <= 0.0:
            continue
        seen.add(item.weight_key)
        weight_sum += 1.0
        raw_sum += item.raw
    if weight_sum <= 0.0:
        confidence = normalized
    else:
        confidence = min(1.0, max(normalized, raw_sum / (raw_sum + 1.0)))
        # Blend ranking mass with saturated raw evidence so a single strong
        # modality cannot look like a sure commit by itself.
        confidence = min(1.0, 0.5 * normalized + 0.5 * min(1.0, raw_sum / max(weight_sum, 1.0)))
    if conflicts:
        confidence *= config.conflict_confidence_factor
    return min(1.0, max(0.0, confidence))


def _alternatives(
    ranked: Sequence[tuple[_ScoredPair, float]], skip: _ScoredPair
) -> list[IntentAlternative]:
    alts: list[IntentAlternative] = []
    for pair, confidence in ranked:
        if pair is skip:
            continue
        alts.append(
            IntentAlternative(
                action=pair.action,
                target_object_id=pair.target_object_id,
                confidence=confidence,
            )
        )
    return alts


def _signature(
    fusion_state: FusionState,
    action: str | None,
    target: str | None,
    status: str,
    conflicts: Sequence[str],
) -> str:
    return "|".join(
        [
            str(fusion_state),
            action or "",
            target or "",
            status,
            ",".join(conflicts),
        ]
    )


def step(
    state: FusionRuntimeState,
    evidence_window: Sequence[EventEnvelope | Mapping[str, Any]],
    user_profile: UserProfile,
    config: FusionConfig,
    *,
    now_ns: int | None = None,
) -> EngineResult:
    """Evaluate one evidence window and return immutable output events."""
    incoming = [_as_envelope(item) for item in evidence_window]
    incoming.sort(key=lambda event: (_event_time_ns(event), event.sequence, event.event_id))
    clock = _window_now_ns(incoming, now_ns)
    next_state = state.clone()
    profile = replace(user_profile, reliability=dict(user_profile.reliability))
    profile = _apply_context(next_state, incoming, clock, config, profile)

    events: list[EventEnvelope] = []
    objects = next_state.current_objects
    audio = _collect_audio(incoming, clock, config)
    all_audio = _collect_all_final_audio(incoming, clock, config)
    vision = _latest(incoming, clock, config, EventType.VISION_OBJECTS)
    head = _latest(incoming, clock, config, EventType.VISION_HEAD_DIRECTION)
    emg = _emg_events(incoming, clock, config)
    eeg = _eeg_events(incoming, clock, config)

    has_stop = False
    has_audio_cancel = False
    has_audio_confirm = False
    for event in all_audio:
        action = _normalize_action(event.payload.get("action"))
        if action in STOP_ACTIONS:
            has_stop = True
        elif action in CANCEL_ACTIONS:
            has_audio_cancel = True
        elif action in CONFIRM_ACTIONS:
            has_audio_confirm = True

    emg_confirm_event = next(
        (
            event
            for event in reversed(emg)
            if _gesture_positive(event, CONFIRM_LABELS, config.gesture_confidence_min)
        ),
        None,
    )
    emg_cancel_event = next(
        (
            event
            for event in reversed(emg)
            if _gesture_positive(event, CANCEL_LABELS, config.gesture_confidence_min)
        ),
        None,
    )
    has_emg_confirm = emg_confirm_event is not None
    has_emg_cancel = emg_cancel_event is not None
    has_confirm = has_audio_confirm or has_emg_confirm
    has_cancel = has_audio_cancel or has_emg_cancel

    expired_decision = (
        next_state.last_decision_expires_at_ns is not None
        and clock >= next_state.last_decision_expires_at_ns
        and next_state.fusion_state
        in {
            FusionState.REQUEST_DETECTED,
            FusionState.TARGET_PROPOSED,
            FusionState.AWAITING_CONFIRMATION,
        }
        and next_state.last_decision_id
    )

    if has_stop or (has_cancel and not has_confirm):
        return _emit_cancel(
            next_state,
            profile,
            config,
            clock,
            audio=audio,
            emg_cancel=emg_cancel_event,
            stop=has_stop,
        )

    if expired_decision and audio is None and not has_confirm:
        timeout = _make_event(
            next_state,
            EventType.INTENT_TIMEOUT,
            IntentTimeoutPayload(
                decision_id=next_state.last_decision_id or "",
                reason_codes=["DECISION_EXPIRED"],
            ).model_dump(mode="json"),
            clock,
        )
        next_state.fusion_state = FusionState.IDLE
        next_state.proposed_action = None
        next_state.proposed_target = None
        next_state.last_decision_id = None
        next_state.last_decision_expires_at_ns = None
        next_state.last_signature = None
        return EngineResult(next_state, profile, (timeout,))

    outcome = _latest(incoming, clock, config, EventType.ACTION_OUTCOME)
    if outcome is not None and next_state.fusion_state == FusionState.COMMIT_PROPOSED:
        next_state.fusion_state = advance_to(next_state.fusion_state, FusionState.OUTCOME_OBSERVED)
        next_state.fusion_state = reset_after_outcome(next_state.fusion_state)
        next_state.proposed_action = None
        next_state.proposed_target = None
        next_state.last_signature = None
        return EngineResult(next_state, profile, tuple(events))

    if not next_state.session_active:
        return EngineResult(next_state, profile, tuple(events))

    confirm_for_scoring = emg_confirm_event if has_emg_confirm and not has_cancel else None
    pairs = _score_pairs(
        audio=audio,
        vision=vision,
        head=head,
        emg_confirm_event=confirm_for_scoring,
        eeg=eeg,
        objects=objects,
        now_ns=clock,
        config=config,
        profile=profile,
    )
    ranked = _normalize_pair_scores(pairs)
    conflicts = _detect_conflicts(
        state=next_state,
        audio=audio,
        all_audio=all_audio,
        vision=vision,
        objects=objects,
        has_confirm=has_confirm,
        has_cancel=has_cancel,
        ranked=ranked,
        config=config,
    )

    top_pair: _ScoredPair | None = ranked[0][0] if ranked else None
    top_norm = ranked[0][1] if ranked else 0.0
    has_request = top_pair is not None and top_pair.action in {str(a) for a in REQUEST_ACTIONS}
    resolved_target = (
        top_pair is not None
        and top_pair.target_object_id is not None
        and _visible(top_pair.target_object_id, objects)
    )
    deictic_unresolved = False
    if audio is not None:
        reference = str(audio.payload.get("target_reference") or TargetReference.NONE)
        if reference in {TargetReference.DEICTIC, "DEICTIC", TargetReference.ORDINAL, "ORDINAL"}:
            if not resolved_target:
                deictic_unresolved = True

    blocking = any(reason in BLOCKING_CONFLICTS for reason in conflicts)
    can_commit = (
        has_request
        and resolved_target
        and has_confirm
        and not has_cancel
        and not blocking
        and CONFLICT_REASON_MARGIN not in conflicts
        and _machine_ready(next_state.machine_state)
        and not deictic_unresolved
    )

    desired = next_state.fusion_state
    if can_commit:
        desired = FusionState.COMMIT_PROPOSED
    elif has_request and resolved_target and not deictic_unresolved:
        desired = FusionState.AWAITING_CONFIRMATION
    elif has_request:
        desired = FusionState.REQUEST_DETECTED
    elif next_state.fusion_state == FusionState.IDLE:
        desired = FusionState.IDLE

    if desired != next_state.fusion_state:
        if desired == FusionState.IDLE:
            next_state.fusion_state = FusionState.IDLE
        else:
            try:
                if _order_index(desired) >= _order_index(next_state.fusion_state):
                    next_state.fusion_state = advance_to(next_state.fusion_state, desired)
                elif (
                    desired == FusionState.REQUEST_DETECTED
                    and CONFLICT_REASON_ACTION_CHANGED in conflicts
                ):
                    next_state.fusion_state = FusionState.REQUEST_DETECTED
                else:
                    next_state.fusion_state = desired
            except ValueError:
                next_state.fusion_state = desired

    if top_pair is not None and has_request:
        next_state.proposed_action = top_pair.action
        next_state.proposed_target = top_pair.target_object_id if resolved_target else None

    if not has_request and next_state.fusion_state == FusionState.IDLE:
        return EngineResult(next_state, profile, tuple(events))

    if top_pair is None:
        return EngineResult(next_state, profile, tuple(events))

    confidence = _decision_confidence(top_pair, top_norm, conflicts, config)
    evidence_items = _normalize_contributions(top_pair.contributions)
    alternatives = _alternatives(ranked, top_pair)
    status = (
        IntentStatus.PROPOSED
        if next_state.fusion_state != FusionState.CANCELLED
        else IntentStatus.CANCELLED
    )
    if next_state.fusion_state == FusionState.COMMIT_PROPOSED and not _machine_ready(
        next_state.machine_state
    ):
        next_state.fusion_state = FusionState.AWAITING_CONFIRMATION

    actionable = next_state.fusion_state in {
        FusionState.TARGET_PROPOSED,
        FusionState.AWAITING_CONFIRMATION,
        FusionState.COMMIT_PROPOSED,
        FusionState.REQUEST_DETECTED,
    }
    if not next_state.session_active or not actionable:
        return EngineResult(next_state, profile, tuple(events))

    # Deictic without a target never becomes a commit proposal.
    if deictic_unresolved and next_state.fusion_state == FusionState.COMMIT_PROPOSED:
        next_state.fusion_state = FusionState.REQUEST_DETECTED

    decision_action = top_pair.action
    decision_target = top_pair.target_object_id if resolved_target else None
    if next_state.fusion_state == FusionState.REQUEST_DETECTED:
        decision_target = None

    sig = _signature(
        next_state.fusion_state,
        decision_action,
        decision_target,
        str(status),
        conflicts,
    )
    if sig == next_state.last_signature:
        return EngineResult(next_state, profile, tuple(events))

    expires_at_ns = clock + int(config.decision_ttl_ms) * NS_PER_MS
    decision_id = _next_decision_id(next_state)
    decision_payload = IntentDecisionPayload(
        decision_id=decision_id,
        action=decision_action,
        target_object_id=decision_target,
        confidence=confidence,
        status=status,
        alternatives=alternatives,
        evidence=evidence_items,
        fusion_model_id=config.model_id,
        fusion_state=next_state.fusion_state,
        expires_at_ns=expires_at_ns,
        conflicts=list(conflicts),
        reason_codes=list(conflicts),
    )
    candidate_payload = IntentCandidateSetPayload(
        candidates=[
            IntentAlternative(
                action=top_pair.action,
                target_object_id=decision_target,
                confidence=confidence,
            ),
            *alternatives,
        ],
        evidence=evidence_items,
    )
    events.append(
        _make_event(
            next_state,
            EventType.INTENT_CANDIDATE_SET,
            candidate_payload.model_dump(mode="json"),
            clock,
        )
    )
    events.append(
        _make_event(
            next_state,
            EventType.INTENT_DECISION,
            decision_payload.model_dump(mode="json"),
            clock,
        )
    )
    if conflicts:
        events.append(
            _make_event(
                next_state,
                EventType.INTENT_CONFLICT,
                IntentConflictPayload(
                    decision_id=decision_id,
                    reason_codes=list(conflicts),
                    details={
                        "action": decision_action,
                        "target_object_id": decision_target,
                    },
                ).model_dump(mode="json"),
                clock,
            )
        )

    next_state.last_decision_id = decision_id
    next_state.last_decision_expires_at_ns = expires_at_ns
    next_state.last_signature = sig
    return EngineResult(next_state, profile, tuple(events))


def _order_index(state: FusionState) -> int:
    order = {
        FusionState.IDLE: 0,
        FusionState.REQUEST_DETECTED: 1,
        FusionState.TARGET_PROPOSED: 2,
        FusionState.AWAITING_CONFIRMATION: 3,
        FusionState.COMMIT_PROPOSED: 4,
        FusionState.OUTCOME_OBSERVED: 5,
        FusionState.CANCELLED: -1,
    }
    return order[state]


def _cancel_contributions(
    *,
    audio: EventEnvelope | None,
    emg_cancel: EventEnvelope | None,
    now_ns: int,
    config: FusionConfig,
    profile: UserProfile,
    stop: bool,
) -> list[_RawContribution]:
    items: list[_RawContribution] = []
    if audio is not None:
        action = _normalize_action(audio.payload.get("action"))
        if action in STOP_ACTIONS | CANCEL_ACTIONS:
            age = _age_ms(audio, now_ns)
            items.append(
                _RawContribution(
                    event_id=audio.event_id,
                    modality="audio",
                    raw=evidence_contribution(
                        1.0,
                        float(audio.payload.get("confidence", 0.0)),
                        audio.quality,
                        freshness_decay(age, config.time_constant("audio")),
                        profile.reliability_for("audio"),
                    ),
                    quality=audio.quality,
                    age_ms=age,
                    weight_key="audio_cancel",
                )
            )
    if emg_cancel is not None and not stop:
        age = _age_ms(emg_cancel, now_ns)
        items.append(
            _RawContribution(
                event_id=emg_cancel.event_id,
                modality="emg",
                raw=evidence_contribution(
                    config.weight("emg_cancel"),
                    float(emg_cancel.payload.get("confidence", 0.0)),
                    emg_cancel.quality,
                    freshness_decay(age, config.time_constant("emg")),
                    profile.reliability_for("emg"),
                ),
                quality=emg_cancel.quality,
                age_ms=age,
                weight_key="emg_cancel",
            )
        )
    return items


def _emit_cancel(
    state: FusionRuntimeState,
    profile: UserProfile,
    config: FusionConfig,
    now_ns: int,
    *,
    audio: EventEnvelope | None,
    emg_cancel: EventEnvelope | None,
    stop: bool,
) -> EngineResult:
    if not state.session_active:
        return EngineResult(state, profile, ())

    action = Action.STOP if stop else Action.CANCEL
    state.fusion_state = advance_to(state.fusion_state, FusionState.CANCELLED)
    contribs = _cancel_contributions(
        audio=audio,
        emg_cancel=emg_cancel,
        now_ns=now_ns,
        config=config,
        profile=profile,
        stop=stop,
    )
    evidence_items = _normalize_contributions(contribs)
    raw_sum = sum(item.raw for item in contribs)
    confidence = min(1.0, raw_sum / (raw_sum + 0.15)) if raw_sum > 0 else 1.0
    expires_at_ns = now_ns + int(config.decision_ttl_ms) * NS_PER_MS
    decision_id = _next_decision_id(state)
    payload = IntentDecisionPayload(
        decision_id=decision_id,
        action=action,
        target_object_id=None,
        confidence=confidence,
        status=IntentStatus.CANCELLED,
        alternatives=[],
        evidence=evidence_items,
        fusion_model_id=config.model_id,
        fusion_state=FusionState.CANCELLED,
        expires_at_ns=expires_at_ns,
        conflicts=[],
        reason_codes=["STOP"] if stop else ["CANCEL"],
    )
    sig = _signature(FusionState.CANCELLED, str(action), None, str(IntentStatus.CANCELLED), [])
    if sig == state.last_signature:
        state.fusion_state = reset_after_cancel(state.fusion_state)
        return EngineResult(state, profile, ())

    event = _make_event(state, EventType.INTENT_DECISION, payload.model_dump(mode="json"), now_ns)
    state.last_decision_id = decision_id
    state.last_decision_expires_at_ns = expires_at_ns
    state.last_signature = sig
    state.proposed_action = str(action)
    state.proposed_target = None
    state.fusion_state = reset_after_cancel(state.fusion_state)
    return EngineResult(state, profile, (event,))
