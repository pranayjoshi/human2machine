from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import yaml
from intent_contracts.validation import parse_unnormalized_event
from vision_adapter.calibration import (
    CalibrationMismatchError,
    CameraCalibration,
    load_calibration,
    save_calibration,
)
from vision_adapter.camera import VisionHardwareRuntime
from vision_adapter.color_detector import (
    DEFAULT_CATALOG,
    detect_aruco_objects,
    detect_colored_objects,
    pointing_from_index_ray,
)
from vision_adapter.detector import ColorArucoDetector
from vision_adapter.mock import FreezeDetector
from vision_adapter.tracker import ObjectTracker, stale_ms_from_config

EXPECTED_IDS = {"object_blue_1", "object_red_1", "object_green_1", "object_yellow_1"}

SQUARES = {
    "blue": ((20, 20), (90, 90), (255, 0, 0)),
    "red": ((200, 20), (270, 90), (0, 0, 255)),
    "green": ((20, 150), (90, 220), (0, 255, 0)),
    "yellow": ((200, 150), (270, 220), (0, 255, 255)),
}


def four_color_image(
    width: int = 320,
    height: int = 240,
    *,
    dx: int = 0,
    dy: int = 0,
    omit: str | tuple[str, ...] | None = None,
) -> np.ndarray:
    image = np.zeros((height, width, 3), dtype=np.uint8)
    skipped = omit if isinstance(omit, tuple) else ((omit,) if omit else ())
    for name, ((x0, y0), (x1, y1), bgr) in SQUARES.items():
        if name in skipped:
            continue
        image[y0 + dy : y1 + dy, x0 + dx : x1 + dx] = bgr
    return image


def aruco_four_markers_image(
    width: int = 320,
    height: int = 240,
    marker_size: int = 70,
) -> np.ndarray:
    import cv2

    image = np.full((height, width, 3), 255, dtype=np.uint8)
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    placements = ((20, 20, 0), (200, 20, 1), (20, 150, 2), (200, 150, 3))
    for x, y, marker_id in placements:
        if hasattr(cv2.aruco, "generateImageMarker"):
            marker = cv2.aruco.generateImageMarker(dictionary, marker_id, marker_size)
        else:
            marker = cv2.aruco.drawMarker(dictionary, marker_id, marker_size)
        if marker.ndim == 2:
            marker = cv2.cvtColor(marker, cv2.COLOR_GRAY2BGR)
        image[y : y + marker_size, x : x + marker_size] = marker
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


def test_color_aruco_detector_protocol_finds_catalog() -> None:
    detector = ColorArucoDetector()
    objects = detector.detect_objects(four_color_image())
    assert {item["object_id"] for item in objects} == EXPECTED_IDS


def test_generated_aruco_markers_map_ids_0_to_3() -> None:
    objects = detect_aruco_objects(aruco_four_markers_image(), [dict(row) for row in DEFAULT_CATALOG])
    assert {item["object_id"] for item in objects} == EXPECTED_IDS


def test_tracker_keeps_ids_across_few_pixel_jitter() -> None:
    tracker = ObjectTracker(stale_ms=400)
    first = tracker.update(detect_colored_objects(four_color_image()), 0)
    second = tracker.update(detect_colored_objects(four_color_image(dx=3, dy=-2)), 33_000_000)
    assert {item["object_id"] for item in first} == EXPECTED_IDS
    assert {item["object_id"] for item in second} == EXPECTED_IDS
    assert all(not item["stale"] for item in second)


def test_tracker_marks_object_stale_after_absence() -> None:
    tracker = ObjectTracker(stale_ms=400)
    tracker.update(detect_colored_objects(four_color_image()), 0)
    missing = detect_colored_objects(four_color_image(omit="yellow"))
    still_fresh = tracker.update(missing, 200_000_000)
    yellow = next(item for item in still_fresh if item["object_id"] == "object_yellow_1")
    assert yellow["stale"] is False
    gone = tracker.update(missing, 400_000_000)
    yellow = next(item for item in gone if item["object_id"] == "object_yellow_1")
    assert yellow["stale"] is True


def test_object_stale_ms_matches_modalities_yaml() -> None:
    root = Path(__file__).resolve().parents[3]
    config = yaml.safe_load((root / "configs" / "modalities.yaml").read_text())
    assert config["vision"]["object_stale_ms"] == 400
    assert stale_ms_from_config(config) == 400.0
    camera = FakeCamera(four_color_image())
    runtime = VisionHardwareRuntime(camera, hands=None, config=config)
    assert runtime.object_stale_ms == 400.0


def test_calibration_resolution_mismatch_raises(tmp_path: Path) -> None:
    path = tmp_path / "cal.json"
    save_calibration(
        CameraCalibration(
            camera_id="cam0",
            width=1280,
            height=720,
            workspace_polygon=[[0.05, 0.05], [0.95, 0.05], [0.95, 0.95], [0.05, 0.95]],
            marker_size_m=0.04,
        ),
        path,
    )
    with pytest.raises(CalibrationMismatchError, match="calibration mismatch"):
        load_calibration(path, camera_id="cam0", width=640, height=480)
    loaded = load_calibration(
        path,
        camera_id="cam0",
        width=640,
        height=480,
        explicit_transform=[[2.0, 0.0, 0.0], [0.0, 2.0, 0.0], [0.0, 0.0, 1.0]],
    )
    assert loaded.width == 1280
    assert loaded.height == 720
