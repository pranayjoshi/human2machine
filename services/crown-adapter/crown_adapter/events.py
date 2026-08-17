from __future__ import annotations

from typing import Any

from intent_contracts.enums import PRODUCER_VERSION, SCHEMA_VERSION
from intent_contracts.envelope import EventEnvelope, new_event_id, now_monotonic_ns
from intent_runtime.heartbeat import heartbeat_event as runtime_heartbeat

from crown_adapter.quality import CROWN_CHANNELS

SOURCE = "crown-adapter"

__all__ = ["CROWN_CHANNELS", "SOURCE", "device_status", "heartbeat", "make_event"]


def make_event(
    *,
    event_type: str,
    sequence: int,
    payload: dict[str, Any],
    modality: str | None = "eeg",
    source_time_ns: int | None = None,
    quality: float = 1.0,
    received_monotonic_ns: int | None = None,
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
        received_monotonic_ns=(
            received_monotonic_ns if received_monotonic_ns is not None else now_monotonic_ns()
        ),
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


def device_status(
    sequence: int,
    status: str,
    detail: str | None,
    metadata: dict[str, Any] | None = None,
    device_alias: str = "crown-mock",
) -> EventEnvelope:
    payload: dict[str, Any] = {
        "status": status,
        "device_alias": device_alias,
        "detail": detail,
        "metadata": {"stream": "raw", **(metadata or {})},
    }
    if device_alias == "crown-mock":
        payload["battery_percent"] = 92
        payload["metadata"]["os_version"] = "mock"
    return make_event(
        event_type="device.status",
        sequence=sequence,
        payload=payload,
        quality=0.0 if status == "offline" else 1.0,
    )
