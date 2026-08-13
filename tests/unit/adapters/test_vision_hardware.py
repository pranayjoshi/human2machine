from __future__ import annotations

import numpy as np
from intent_contracts.validation import parse_unnormalized_event
from vision_adapter.camera import VisionHardwareRuntime
from vision_adapter.color_detector import detect_colored_objects, pointing_from_index_ray
from vision_adapter.mock import FreezeDetector


def four_color_image(width: int = 320, height: int = 240) -> np.ndarray:
    image = np.zeros((height, width, 3), dtype=np.uint8)
    image[20:90, 20:90] = (255, 0, 0)  # blue in BGR
    image[20:90, 200:270] = (0, 0, 255)  # red
    image[150:220, 20:90] = (0, 255, 0)  # green
    image[150:220, 200:270] = (0, 255, 255)  # yellow
    return image


class FakeCamera:
    def __init__(self, frame: np.ndarray, source_time_ns: int = 1_000_000) -> None:
        self.frame = frame
        self.source_time_ns = source_time_ns

    def latest(self):
        return self.frame, self.source_time_ns, 0


def test_color_detector_finds_four_saturated_squares() -> None:
    image = four_color_image()
    objects = detect_colored_objects(image)
    ids = {item["object_id"] for item in objects}
    assert ids == {"object_blue_1", "object_red_1", "object_green_1", "object_yellow_1"}
    for item in objects:
        assert item["confidence"] > 0.5
        assert len(item["bbox_xyxy"]) == 4
        assert len(item["table_position_xy"]) == 2


def test_freeze_detector_flags_stalled_timestamp() -> None:
    detector = FreezeDetector(timeout_ns=1_000_000_000)
    assert detector.observe(10, 0) is False
    assert detector.observe(10, 500_000_000) is False
    assert detector.observe(10, 1_000_000_000) is True


def test_hardware_runtime_freeze_and_no_fake_gaze() -> None:
    camera = FakeCamera(four_color_image(), source_time_ns=42)
    runtime = VisionHardwareRuntime(camera, hands=None)
    first = runtime.render_frame(monotonic_ns=0)
    later = runtime.render_frame(monotonic_ns=1_200_000_000)
    quality = next(event for event in later if event.event_type == "data.quality")
    assert "camera_frozen" in quality.payload["flags"]
    objects_event = next(event for event in first if event.event_type == "vision.objects")
    assert objects_event.payload["pointing_candidates"] == []
    assert objects_event.payload["head_direction_candidates"] == []
    for event in [*first, *later]:
        parse_unnormalized_event(event.to_unnormalized_dict())
        assert "gaze" not in event.event_type
        assert "normalized_time_ns" not in event.to_unnormalized_dict()


def test_index_ray_scores_nearest_object() -> None:
    objects = detect_colored_objects(four_color_image())
    candidates, hands = pointing_from_index_ray(
        mcp_xy=(55.0, 20.0),
        tip_xy=(55.0, 70.0),
        objects=objects,
        image_size=(320, 240),
        min_confidence=0.55,
    )
    assert hands["pointing"] is True
    assert candidates
    assert candidates[0]["object_id"] in {item["object_id"] for item in objects}
