from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from intent_contracts.enums import (
    Action,
    DeviceHealth,
    FusionState,
    IntentStatus,
    MachineState,
    OutcomeKind,
    SafetyVerdict,
    SessionState,
    TargetReference,
)


def _unit_interval(value: float) -> float:
    if not 0.0 <= value <= 1.0:
        raise ValueError("probability/quality/confidence must be in [0, 1]")
    return value


class BiosignalChunkPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    sample_rate_hz: float = Field(gt=0)
    channel_names: list[str]
    sample_count: int = Field(gt=0)
    samples: list[list[float]]
    units: str = "microvolts"
    filters_applied: list[str] = Field(default_factory=list)
    packet_loss_count: int = Field(ge=0, default=0)
    clock_confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    estimated_first_sample_ns: int | None = None

    @field_validator("samples")
    @classmethod
    def channel_major(cls, samples: list[list[float]]) -> list[list[float]]:
        if not samples:
            raise ValueError("samples must contain at least one channel")
        return samples


class MotionChunkPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    sample_rate_hz: float = Field(gt=0)
    axes: list[str] = Field(default_factory=lambda: ["x", "y", "z"])
    sample_count: int = Field(gt=0)
    samples: list[list[float]]
    units: str = "g"
    magnitude: float | None = None


class ModalityFeaturePayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    feature_name: str
    window_start_ns: int
    window_end_ns: int
    label: str
    confidence: float
    candidate_scores: dict[str, float] = Field(default_factory=dict)
    model_id: str
    shadow_only: bool = False

    @field_validator("confidence")
    @classmethod
    def conf_range(cls, value: float) -> float:
        return _unit_interval(value)

    @field_validator("candidate_scores")
    @classmethod
    def score_range(cls, value: dict[str, float]) -> dict[str, float]:
        for score in value.values():
            _unit_interval(score)
        return value


class VisionObject(BaseModel):
    model_config = ConfigDict(extra="allow")

    object_id: str
    class_name: str
    confidence: float
    bbox_xyxy: list[float] = Field(min_length=4, max_length=4)
    table_position_xy: list[float] = Field(min_length=2, max_length=2)

    @field_validator("confidence")
    @classmethod
    def conf_range(cls, value: float) -> float:
        return _unit_interval(value)


class TargetCandidate(BaseModel):
    model_config = ConfigDict(extra="allow")

    object_id: str
    confidence: float

    @field_validator("confidence")
    @classmethod
    def conf_range(cls, value: float) -> float:
        return _unit_interval(value)


class VisionObjectsPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    frame_id: int = Field(ge=0)
    objects: list[VisionObject] = Field(default_factory=list)
    pointing_candidates: list[TargetCandidate] = Field(default_factory=list)
    head_direction_candidates: list[TargetCandidate] = Field(default_factory=list)


class VisionHandsPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    frame_id: int = Field(ge=0)
    handedness: str | None = None
    landmark_confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    pointing: bool = False
    table_intersection_xy: list[float] | None = None


class VisionHeadDirectionPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    frame_id: int = Field(ge=0)
    yaw_deg: float | None = None
    pitch_deg: float | None = None
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    candidates: list[TargetCandidate] = Field(default_factory=list)


class AudioIntentPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    transcript: str
    is_final: bool
    action: Action | str | None = None
    target_reference: TargetReference | str = TargetReference.NONE
    target_object_id: str | None = None
    confidence: float
    utterance_start_ns: int
    utterance_end_ns: int
    model_id: str

    @field_validator("confidence")
    @classmethod
    def conf_range(cls, value: float) -> float:
        return _unit_interval(value)


class EvidenceItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    event_id: str
    modality: str
    contribution: float
    quality: float
    age_ms: float = Field(ge=0)

    @field_validator("quality")
    @classmethod
    def quality_range(cls, value: float) -> float:
        return _unit_interval(value)


class IntentAlternative(BaseModel):
    model_config = ConfigDict(extra="allow")

    action: Action | str | None = None
    target_object_id: str | None = None
    confidence: float

    @field_validator("confidence")
    @classmethod
    def conf_range(cls, value: float) -> float:
        return _unit_interval(value)


class IntentDecisionPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    decision_id: str
    action: Action | str
    target_object_id: str | None = None
    confidence: float
    status: IntentStatus | str = IntentStatus.PROPOSED
    alternatives: list[IntentAlternative] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    fusion_model_id: str
    fusion_state: FusionState | str | None = None
    expires_at_ns: int
    conflicts: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)

    @field_validator("confidence")
    @classmethod
    def conf_range(cls, value: float) -> float:
        return _unit_interval(value)


class IntentCandidateSetPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    candidates: list[IntentAlternative]
    evidence: list[EvidenceItem] = Field(default_factory=list)


class IntentConflictPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    decision_id: str | None = None
    reason_codes: list[str]
    details: dict[str, Any] = Field(default_factory=dict)


class IntentTimeoutPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    decision_id: str
    reason_codes: list[str] = Field(default_factory=list)


class SafetyChecks(BaseModel):
    model_config = ConfigDict(extra="allow")

    intent_fresh: bool
    target_visible: bool
    cancel_absent: bool
    machine_ready: bool
    session_active: bool = True
    schema_valid: bool = True
    no_unresolved_conflict: bool = True
    confirmation_satisfied: bool = True
    physical_robot_disarmed: bool = True


class SafetyDecisionPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    decision_id: str
    verdict: SafetyVerdict | str
    reason_codes: list[str] = Field(default_factory=list)
    policy_version: str
    checks: SafetyChecks
    command_id: str | None = None
    confirmation_id: str | None = None


class MachineStatePayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    state: MachineState | str
    previous_state: MachineState | str | None = None
    active_command_id: str | None = None
    held_object_id: str | None = None
    target_object_id: str | None = None
    progress: float = Field(ge=0.0, le=1.0, default=0.0)
    objects: list[VisionObject] = Field(default_factory=list)
    fault_reason: str | None = None


class ActionOutcomePayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    command_id: str
    decision_id: str
    outcome: OutcomeKind | str
    duration_ms: float = Field(ge=0)
    user_correction: str | None = None


class ServiceHeartbeatPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: DeviceHealth | str = DeviceHealth.HEALTHY
    uptime_seconds: float = Field(ge=0)
    last_data_age_ms: float | None = None
    error_count: int = Field(ge=0, default=0)


class DeviceStatusPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: DeviceHealth | str
    device_alias: str
    detail: str | None = None
    battery_percent: float | None = Field(default=None, ge=0.0, le=100.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DataQualityPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    score: float
    components: dict[str, float] = Field(default_factory=dict)
    flags: list[str] = Field(default_factory=list)

    @field_validator("score")
    @classmethod
    def score_range(cls, value: float) -> float:
        return _unit_interval(value)


class SessionLifecyclePayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    state: SessionState | str
    config_hash: str | None = None
    contract_version: str = "1.0.0"
    commit: str | None = None
    model_versions: dict[str, str] = Field(default_factory=dict)
    reason: str | None = None


class TrialLifecyclePayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    instruction: str | None = None
    ground_truth_action: Action | str | None = None
    ground_truth_target: str | None = None
    ambiguous: bool = False
    notes: str | None = None
    outcome: str | None = None
    failure_reason: str | None = None
    user_correction: str | None = None
