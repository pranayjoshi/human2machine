from __future__ import annotations

import time
import uuid
from typing import Any

from event_hub.hub import EventHub
from intent_contracts.control import ControlRequest
from intent_contracts.enums import ControlMethod

HEARTBEAT_PAYLOAD = {
    "status": "healthy",
    "uptime_seconds": 1.0,
    "error_count": 0,
}

BIOSIGNAL_PAYLOAD = {
    "sample_rate_hz": 200.0,
    "channel_names": ["emg_flexor"],
    "sample_count": 2,
    "samples": [[0.1, 0.2]],
    "units": "microvolts",
    "filters_applied": [],
    "packet_loss_count": 0,
}

AUDIO_PAYLOAD = {
    "transcript": "give me that one",
    "is_final": True,
    "action": "REQUEST_HANDOFF",
    "target_reference": "DEICTIC",
    "target_object_id": None,
    "confidence": 0.94,
    "utterance_start_ns": 10_000_000,
    "utterance_end_ns": 45_000_000,
    "model_id": "local-asr-v1",
}

INTENT_PAYLOAD = {
    "decision_id": "decision_test_1",
    "action": "REQUEST_HANDOFF",
    "target_object_id": "object_blue_1",
    "confidence": 0.92,
    "status": "PROPOSED",
    "alternatives": [],
    "evidence": [],
    "fusion_model_id": "late-fusion-v1",
    "expires_at_ns": 1_000_000_000,
}


def new_hub() -> EventHub:
    return EventHub(config={"runtime": {"max_event_bytes": 262144}}, retain_published=True)


def unnormalized_event(**overrides: Any) -> dict[str, Any]:
    event_type = overrides.get("event_type", "service.heartbeat")
    payload = overrides.get("payload")
    if payload is None:
        if event_type == "biosignal.chunk":
            payload = dict(BIOSIGNAL_PAYLOAD)
        elif event_type == "audio.intent_candidate":
            payload = dict(AUDIO_PAYLOAD)
        elif event_type == "intent.decision":
            payload = dict(INTENT_PAYLOAD)
        else:
            payload = dict(HEARTBEAT_PAYLOAD)
    data: dict[str, Any] = {
        "schema_version": "1.0.0",
        "event_id": overrides.get("event_id", uuid.uuid4().hex),
        "event_type": event_type,
        "source": overrides.get("source", "test-producer"),
        "modality": overrides.get("modality"),
        "session_id": overrides.get("session_id"),
        "trial_id": overrides.get("trial_id"),
        "sequence": overrides.get("sequence", 0),
        "source_time_ns": overrides.get("source_time_ns"),
        "received_monotonic_ns": overrides.get("received_monotonic_ns", time.monotonic_ns()),
        "quality": overrides.get("quality", 1.0),
        "producer_version": "0.1.0",
        "payload": payload,
    }
    for key, value in overrides.items():
        if key == "payload":
            continue
        if key in data:
            data[key] = value
    return data


def start_session(hub: EventHub, request_id: str = "req-start") -> str:
    response = hub.handle_control(
        ControlRequest(method=ControlMethod.SESSION_START, request_id=request_id, payload={})
    )
    assert response.ok, response.error
    assert response.session_id is not None
    return response.session_id
