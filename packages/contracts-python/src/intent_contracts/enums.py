from enum import StrEnum

SCHEMA_VERSION = "1.0.0"
PRODUCER_VERSION = "0.1.0"


class SchemaVersion(StrEnum):
    V1_0_0 = "1.0.0"


class EventType(StrEnum):
    BIOSIGNAL_CHUNK = "biosignal.chunk"
    MOTION_CHUNK = "motion.chunk"
    MODALITY_FEATURE = "modality.feature"
    VISION_OBJECTS = "vision.objects"
    VISION_HANDS = "vision.hands"
    VISION_HEAD_DIRECTION = "vision.head_direction"
    AUDIO_INTENT_CANDIDATE = "audio.intent_candidate"
    INTENT_CANDIDATE_SET = "intent.candidate_set"
    INTENT_DECISION = "intent.decision"
    INTENT_CONFLICT = "intent.conflict"
    INTENT_TIMEOUT = "intent.timeout"
    SAFETY_DECISION = "safety.decision"
    MACHINE_STATE = "machine.state"
    ACTION_OUTCOME = "action.outcome"
    SERVICE_HEARTBEAT = "service.heartbeat"
    DEVICE_STATUS = "device.status"
    DATA_QUALITY = "data.quality"
    SESSION_STARTED = "session.started"
    SESSION_STOPPED = "session.stopped"
    SESSION_FAILED = "session.failed"
    TRIAL_STARTED = "trial.started"
    TRIAL_INSTRUCTION = "trial.instruction"
    TRIAL_LABEL = "trial.label"
    TRIAL_COMPLETED = "trial.completed"
    TRIAL_ABORTED = "trial.aborted"


class Action(StrEnum):
    SELECT_OBJECT = "SELECT_OBJECT"
    REQUEST_HANDOFF = "REQUEST_HANDOFF"
    CONFIRM = "CONFIRM"
    CANCEL = "CANCEL"
    STOP = "STOP"


class TargetReference(StrEnum):
    NAMED = "NAMED"
    DEICTIC = "DEICTIC"
    ORDINAL = "ORDINAL"
    NONE = "NONE"


class IntentStatus(StrEnum):
    PROPOSED = "PROPOSED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class SafetyVerdict(StrEnum):
    APPROVE = "APPROVE"
    ASK_CONFIRMATION = "ASK_CONFIRMATION"
    HOLD = "HOLD"
    REJECT = "REJECT"
    EMERGENCY_STOP = "EMERGENCY_STOP"


class MachineState(StrEnum):
    DISCONNECTED = "DISCONNECTED"
    IDLE = "IDLE"
    READY = "READY"
    EXECUTING = "EXECUTING"
    HOLDING = "HOLDING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    FAULT = "FAULT"
    ESTOPPED = "ESTOPPED"


class SessionState(StrEnum):
    NO_SESSION = "NO_SESSION"
    PREFLIGHT = "PREFLIGHT"
    READY = "READY"
    RECORDING = "RECORDING"
    STOPPING = "STOPPING"
    FINALIZED = "FINALIZED"
    FAILED = "FAILED"


class FusionState(StrEnum):
    IDLE = "IDLE"
    REQUEST_DETECTED = "REQUEST_DETECTED"
    TARGET_PROPOSED = "TARGET_PROPOSED"
    AWAITING_CONFIRMATION = "AWAITING_CONFIRMATION"
    COMMIT_PROPOSED = "COMMIT_PROPOSED"
    OUTCOME_OBSERVED = "OUTCOME_OBSERVED"
    CANCELLED = "CANCELLED"


class ControlMethod(StrEnum):
    SESSION_START = "session.start"
    SESSION_STOP = "session.stop"
    TRIAL_START = "trial.start"
    TRIAL_COMPLETE = "trial.complete"
    TRIAL_ABORT = "trial.abort"


class DeviceHealth(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    OFFLINE = "offline"


class OutcomeKind(StrEnum):
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    FAULT = "FAULT"
    ESTOPPED = "ESTOPPED"
    REJECTED = "REJECTED"
