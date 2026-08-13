from __future__ import annotations

from intent_contracts.validation import parse_unnormalized_event
from vision_adapter.mock import FreezeDetector, VisionMockRuntime


def test_stable_object_ids() -> None:
    runtime = VisionMockRuntime(scenario="all_visible")
    first = None
    for _ in range(6):
        events = runtime.render_frame()
        objects_event = next(event for event in events if event.event_type == "vision.objects")
        ids = [item["object_id"] for item in objects_event.payload["objects"]]
        if first is None:
            first = ids
        else:
            assert ids == first
    assert first == ["object_blue_1", "object_red_1", "object_green_1", "object_yellow_1"]


def test_no_pointing_candidate_when_hand_confidence_low() -> None:
    runtime = VisionMockRuntime(scenario="pointing_blue")
    events = runtime.render_frame(0, hand_confidence=0.1)
    objects_event = next(event for event in events if event.event_type == "vision.objects")
    assert objects_event.payload["pointing_candidates"] == []
    hands = next(event for event in events if event.event_type == "vision.hands")
    assert hands.payload["pointing"] is False
    assert hands.payload["landmark_confidence"] < 0.55


def test_pointing_blue_and_no_hand_scenarios() -> None:
    pointing = VisionMockRuntime(scenario="pointing_blue").render_frame(0)
    objects_event = next(event for event in pointing if event.event_type == "vision.objects")
    assert objects_event.payload["pointing_candidates"][0]["object_id"] == "object_blue_1"
    none = VisionMockRuntime(scenario="no_hand").render_frame(0)
    empty = next(event for event in none if event.event_type == "vision.objects")
    assert empty.payload["pointing_candidates"] == []


def test_disappearance_drops_yellow_after_warmup() -> None:
    runtime = VisionMockRuntime(scenario="disappearance")
    early = next(e for e in runtime.render_frame(0) if e.event_type == "vision.objects")
    late = next(e for e in runtime.render_frame(24) if e.event_type == "vision.objects")
    assert any(item["object_id"] == "object_yellow_1" for item in early.payload["objects"])
    assert all(item["object_id"] != "object_yellow_1" for item in late.payload["objects"])


def test_two_close_targets() -> None:
    events = VisionMockRuntime(scenario="two_close").render_frame(0)
    payload = next(event for event in events if event.event_type == "vision.objects").payload
    blue = next(item for item in payload["objects"] if item["object_id"] == "object_blue_1")
    red = next(item for item in payload["objects"] if item["object_id"] == "object_red_1")
    dx = abs(blue["table_position_xy"][0] - red["table_position_xy"][0])
    assert dx < 0.1
    assert len(payload["pointing_candidates"]) == 2


def test_freeze_detector_and_helper() -> None:
    detector = FreezeDetector(timeout_ns=1_000_000_000)
    assert detector.observe(0, 0) is False
    assert detector.observe(0, 500_000_000) is False
    assert detector.observe(0, 1_000_000_000) is True
    runtime = VisionMockRuntime(scenario="all_visible")
    runtime.enable_freeze()
    events = runtime.render_frame(5, monotonic_ns=2_000_000_000, force_freeze=True)
    quality = next(event for event in events if event.event_type == "data.quality")
    assert "camera_frozen" in quality.payload["flags"]
    status = [event for event in events if event.event_type == "device.status"]
    assert any(event.payload["status"] == "degraded" for event in status)


def test_head_direction_is_not_gaze() -> None:
    events = VisionMockRuntime(scenario="pointing_blue").render_frame(0)
    types = {event.event_type for event in events}
    assert "vision.head_direction" in types
    assert "vision.gaze" not in types
    for event in events:
        assert "gaze" not in event.event_type
        assert all("gaze" not in str(key) for key in event.payload)


def test_vision_mock_events_pass_unnormalized_contract() -> None:
    runtime = VisionMockRuntime(scenario="pointing_blue")
    for event in runtime.render_frame(0):
        parse_unnormalized_event(event.to_unnormalized_dict())
