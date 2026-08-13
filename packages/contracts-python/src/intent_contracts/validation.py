from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from intent_contracts.envelope import EventEnvelope
from intent_contracts.enums import EventType
from intent_contracts.events import (
    ActionOutcomePayload,
    AudioIntentPayload,
    BiosignalChunkPayload,
    DataQualityPayload,
    DeviceStatusPayload,
    IntentCandidateSetPayload,
    IntentConflictPayload,
    IntentDecisionPayload,
    IntentTimeoutPayload,
    MachineStatePayload,
    ModalityFeaturePayload,
    MotionChunkPayload,
    SafetyDecisionPayload,
    ServiceHeartbeatPayload,
    SessionLifecyclePayload,
    TrialLifecyclePayload,
    VisionHandsPayload,
    VisionHeadDirectionPayload,
    VisionObjectsPayload,
)

PAYLOAD_MODELS = {
    EventType.BIOSIGNAL_CHUNK: BiosignalChunkPayload,
    EventType.MOTION_CHUNK: MotionChunkPayload,
    EventType.MODALITY_FEATURE: ModalityFeaturePayload,
    EventType.VISION_OBJECTS: VisionObjectsPayload,
    EventType.VISION_HANDS: VisionHandsPayload,
    EventType.VISION_HEAD_DIRECTION: VisionHeadDirectionPayload,
    EventType.AUDIO_INTENT_CANDIDATE: AudioIntentPayload,
    EventType.INTENT_CANDIDATE_SET: IntentCandidateSetPayload,
    EventType.INTENT_DECISION: IntentDecisionPayload,
    EventType.INTENT_CONFLICT: IntentConflictPayload,
    EventType.INTENT_TIMEOUT: IntentTimeoutPayload,
    EventType.SAFETY_DECISION: SafetyDecisionPayload,
    EventType.MACHINE_STATE: MachineStatePayload,
    EventType.ACTION_OUTCOME: ActionOutcomePayload,
    EventType.SERVICE_HEARTBEAT: ServiceHeartbeatPayload,
    EventType.DEVICE_STATUS: DeviceStatusPayload,
    EventType.DATA_QUALITY: DataQualityPayload,
    EventType.SESSION_STARTED: SessionLifecyclePayload,
    EventType.SESSION_STOPPED: SessionLifecyclePayload,
    EventType.SESSION_FAILED: SessionLifecyclePayload,
    EventType.TRIAL_STARTED: TrialLifecyclePayload,
    EventType.TRIAL_INSTRUCTION: TrialLifecyclePayload,
    EventType.TRIAL_LABEL: TrialLifecyclePayload,
    EventType.TRIAL_COMPLETED: TrialLifecyclePayload,
    EventType.TRIAL_ABORTED: TrialLifecyclePayload,
}


def parse_event(data: dict[str, Any], *, require_normalized: bool = True) -> EventEnvelope:
    envelope = EventEnvelope.model_validate(data)
    if require_normalized and envelope.normalized_time_ns is None:
        raise ValueError("normalized_time_ns is required on hub-published events")
    _validate_payload(envelope)
    return envelope


def parse_unnormalized_event(data: dict[str, Any]) -> EventEnvelope:
    if "normalized_time_ns" in data and data["normalized_time_ns"] is not None:
        raise ValueError("adapter events must omit normalized_time_ns")
    envelope = EventEnvelope.model_validate(data)
    _validate_payload(envelope)
    return envelope


def _validate_payload(envelope: EventEnvelope) -> None:
    try:
        event_type = EventType(envelope.event_type)
    except ValueError as exc:
        raise ValueError(f"unknown event_type: {envelope.event_type}") from exc
    model = PAYLOAD_MODELS.get(event_type)
    if model is None:
        return
    try:
        model.model_validate(envelope.payload)
    except ValidationError as exc:
        raise ValueError(f"invalid payload for {event_type}: {exc}") from exc
