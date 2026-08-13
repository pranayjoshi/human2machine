from __future__ import annotations

from typing import Any

from intent_contracts.enums import PRODUCER_VERSION, SCHEMA_VERSION
from intent_contracts.envelope import EventEnvelope, new_event_id, now_monotonic_ns
from intent_runtime.heartbeat import heartbeat_event as runtime_heartbeat

SOURCE = "ganglion-emg"


def make_event(
    *,
    event_type: str,
    sequence: int,
    payload: dict[str, Any],
    modality: str | None = "emg",
    source_time_ns: int | None = None,
    quality: float = 1.0,
) -> EventEnvelope:
    return EventEnvelope(
        schema_version=SCHEMA_VERSION,
        event_id=new_event_id(),
        event_type=event_type,
        source=SOURCE,
        modality=modality,
        session_id=None,
        trial_id=None,
        sequence=sequence,
        source_time_ns=source_time_ns,
        received_monotonic_ns=now_monotonic_ns(),
        quality=quality,
        producer_version=PRODUCER_VERSION,
        payload=payload,
    )


def heartbeat(
    sequence: int,
    uptime_seconds: float,
    last_data_age_ms: float | None,
    error_count: int,
    status: str = "healthy",
) -> EventEnvelope:
    return runtime_heartbeat(
        SOURCE,
        uptime_seconds=uptime_seconds,
        last_data_age_ms=last_data_age_ms,
        error_count=error_count,
        sequence=sequence,
        status=status,
    )
