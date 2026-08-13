from __future__ import annotations

import json
from pathlib import Path

from event_hub.hub import EventHub, encode_pub_message
from intent_contracts.control import ControlRequest
from intent_contracts.enums import ControlMethod, SessionState

from tests.unit.event_hub.helpers import new_hub, start_session, unnormalized_event

FIXTURE = Path(__file__).parent / "fixtures" / "tiny_replay.jsonl"


def test_duplicate_event_id_published_once() -> None:
    hub = new_hub()
    event = unnormalized_event(event_id="dup0000000000001", sequence=1)
    first = hub.ingest(event)
    second = hub.ingest(event)
    assert first is not None
    assert second is None
    assert hub.metrics.duplicate == 1
    published = [e for e in hub.published if e.event_id == "dup0000000000001"]
    assert len(published) == 1


def test_sequence_gap_is_observable() -> None:
    hub = new_hub()
    first = unnormalized_event(event_id="gap0000000000001", sequence=1, source="emg")
    second = unnormalized_event(event_id="gap0000000000002", sequence=4, source="emg")
    assert hub.ingest(first) is not None
    assert hub.ingest(second) is not None
    assert hub.metrics.sequence_gaps == 1
    assert hub.metrics.sequence_regressions == 0
    assert len(hub.sequence_anomalies) == 1
    anomaly = hub.sequence_anomalies[0]
    assert anomaly.source == "emg"
    assert anomaly.kind == "gap"
    assert anomaly.previous == 1
    assert anomaly.sequence == 4


def test_sequence_regression_is_observable_and_still_published() -> None:
    hub = new_hub()
    first = unnormalized_event(event_id="reg0000000000001", sequence=5, source="eeg")
    second = unnormalized_event(event_id="reg0000000000002", sequence=3, source="eeg")
    assert hub.ingest(first) is not None
    published = hub.ingest(second)
    assert published is not None
    assert hub.metrics.sequence_regressions == 1
    assert hub.sequence_anomalies[-1].kind == "regression"


def test_invalid_probability_rejected() -> None:
    hub = new_hub()
    payload = dict(unnormalized_event(event_type="audio.intent_candidate")["payload"])
    payload["confidence"] = 1.4
    event = unnormalized_event(event_type="audio.intent_candidate", payload=payload, sequence=1)
    assert hub.ingest(event) is None
    assert hub.metrics.invalid == 1
    assert hub.published == []


def test_future_schema_major_version_rejected() -> None:
    hub = new_hub()
    event = unnormalized_event(schema_version="2.0.0", sequence=1)
    assert hub.ingest(event) is None
    assert hub.metrics.invalid == 1
    assert hub.published == []


def test_normalized_time_ns_from_adapter_rejected() -> None:
    hub = new_hub()
    event = unnormalized_event(sequence=1)
    event["normalized_time_ns"] = 123
    assert hub.ingest(event) is None
    assert hub.metrics.invalid == 1


def test_session_start_attaches_session_id_to_adapter_event() -> None:
    hub = new_hub()
    session_id = start_session(hub)
    event = unnormalized_event(
        event_type="biosignal.chunk",
        source="ganglion-emg",
        modality="emg",
        session_id=None,
        trial_id=None,
        sequence=1,
    )
    published = hub.ingest(event)
    assert published is not None
    assert published.session_id == session_id
    assert published.normalized_time_ns is not None
    assert published.normalized_time_ns >= 0


def test_preview_health_without_session_keeps_null_ids() -> None:
    hub = new_hub()
    published = hub.ingest(unnormalized_event(event_type="service.heartbeat", sequence=0))
    assert published is not None
    assert published.session_id is None
    assert published.normalized_time_ns is not None


def test_session_stop_finalizes() -> None:
    hub = new_hub()
    session_id = start_session(hub)
    response = hub.handle_control(
        ControlRequest(
            method=ControlMethod.SESSION_STOP,
            request_id="req-stop",
            session_id=session_id,
        )
    )
    assert response.ok
    assert response.state == SessionState.FINALIZED
    types = [str(event.event_type) for event in hub.published]
    assert "session.started" in types
    assert "session.stopped" in types


def test_trial_lifecycle() -> None:
    hub = new_hub()
    start_session(hub)
    started = hub.handle_control(
        ControlRequest(
            method=ControlMethod.TRIAL_START,
            request_id="t1",
            payload={"instruction": "select the blue block"},
        )
    )
    assert started.ok
    assert started.trial_id is not None
    completed = hub.handle_control(
        ControlRequest(
            method=ControlMethod.TRIAL_COMPLETE,
            request_id="t2",
            trial_id=started.trial_id,
        )
    )
    assert completed.ok
    types = [str(event.event_type) for event in hub.published]
    assert types.count("trial.started") == 1
    assert types.count("trial.completed") == 1


def test_shutdown_fails_active_session() -> None:
    hub = new_hub()
    start_session(hub)
    failed = hub.fail_active_session("hub_shutdown")
    assert failed is not None
    assert str(failed.event_type) == "session.failed"
    assert hub.session.state == SessionState.FAILED


def test_received_monotonic_ns_injected_when_missing() -> None:
    hub = new_hub()
    event = unnormalized_event(sequence=1)
    del event["received_monotonic_ns"]
    published = hub.ingest(event)
    assert published is not None
    assert published.received_monotonic_ns > 0


def test_oversized_event_rejected() -> None:
    hub = EventHub(max_event_bytes=64, retain_published=True)
    raw = json.dumps(unnormalized_event(sequence=1)).encode()
    assert len(raw) > 64
    assert hub.ingest_raw(raw) is None
    assert hub.metrics.oversized == 1
    assert hub.metrics.invalid == 1


def test_pub_format_is_topic_prefixed() -> None:
    hub = new_hub()
    event = hub.ingest(unnormalized_event(event_type="biosignal.chunk", sequence=1))
    assert event is not None
    frame = encode_pub_message(event)
    assert frame.startswith(b"biosignal.chunk ")
    _, body = frame.split(b" ", 1)
    decoded = json.loads(body)
    assert decoded["event_id"] == event.event_id
    assert decoded["normalized_time_ns"] == event.normalized_time_ns


def test_fixture_replay_preserves_event_type_order() -> None:
    hub = new_hub()
    expected = [
        json.loads(line)["event_type"] for line in FIXTURE.read_text().splitlines() if line.strip()
    ]
    published = hub.inject_fixture_file(str(FIXTURE))
    assert [str(event.event_type) for event in published] == expected
