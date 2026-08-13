from __future__ import annotations

from intent_contracts.envelope import EventEnvelope, new_event_id, now_monotonic_ns
from intent_contracts.enums import DeviceHealth, EventType, PRODUCER_VERSION, SCHEMA_VERSION


def heartbeat_event(
    source: str,
    *,
    uptime_seconds: float,
    last_data_age_ms: float | None = None,
    error_count: int = 0,
    sequence: int = 0,
    session_id: str | None = None,
    status: str = DeviceHealth.HEALTHY,
) -> EventEnvelope:
    return EventEnvelope(
        schema_version=SCHEMA_VERSION,
        event_id=new_event_id(),
        event_type=EventType.SERVICE_HEARTBEAT,
        source=source,
        modality=None,
        session_id=session_id,
        trial_id=None,
        sequence=sequence,
        source_time_ns=None,
        received_monotonic_ns=now_monotonic_ns(),
        quality=1.0,
        producer_version=PRODUCER_VERSION,
        payload={
            "status": status,
            "uptime_seconds": uptime_seconds,
            "last_data_age_ms": last_data_age_ms,
            "error_count": error_count,
        },
    )
