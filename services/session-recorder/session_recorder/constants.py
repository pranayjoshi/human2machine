"""Recorder constants and event-priority classification."""

from __future__ import annotations

from intent_contracts.enums import EventType

ADAPTER_PUSH = "tcp://127.0.0.1:5555"
NORMALIZED_PUB = "tcp://127.0.0.1:5556"
HEARTBEAT_SECONDS = 2.0
SOURCE_NAME = "session-recorder"

FINALIZATION_PARTIAL = "PARTIAL"
FINALIZATION_FINALIZED = "finalized"
FINALIZATION_FAILED = "FAILED"

# Biosignal/motion may be dropped under backpressure. Everything else is kept.
DROPPABLE_EVENT_TYPES = frozenset(
    {
        EventType.BIOSIGNAL_CHUNK.value,
        EventType.MOTION_CHUNK.value,
    }
)

CRITICAL_EVENT_TYPES = frozenset(
    {
        EventType.SESSION_STARTED.value,
        EventType.SESSION_STOPPED.value,
        EventType.SESSION_FAILED.value,
        EventType.INTENT_DECISION.value,
        EventType.SAFETY_DECISION.value,
        EventType.ACTION_OUTCOME.value,
        EventType.TRIAL_STARTED.value,
        EventType.TRIAL_INSTRUCTION.value,
        EventType.TRIAL_LABEL.value,
        EventType.TRIAL_COMPLETED.value,
        EventType.TRIAL_ABORTED.value,
    }
)

DECISION_EVENT_TYPE = EventType.INTENT_DECISION.value
SAFETY_EVENT_TYPE = EventType.SAFETY_DECISION.value
OUTCOME_EVENT_TYPE = EventType.ACTION_OUTCOME.value
BIOSIGNAL_EVENT_TYPE = EventType.BIOSIGNAL_CHUNK.value
TRIAL_EVENT_TYPES = frozenset(
    {
        EventType.TRIAL_STARTED.value,
        EventType.TRIAL_INSTRUCTION.value,
        EventType.TRIAL_LABEL.value,
        EventType.TRIAL_COMPLETED.value,
        EventType.TRIAL_ABORTED.value,
    }
)

FLUSH_EVERY_EVENTS = 64
BIOSIGNAL_QUEUE_BOUND = 2048
NORMAL_QUEUE_BOUND = 8192
