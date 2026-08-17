"""Milestone 2: four marked objects, tracking, calibration, frozen camera.

Frames are generated in-process. No webcam, MediaPipe, or network.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
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
)
from vision_adapter.mock import FreezeDetector
from vision_adapter.tracker import ObjectTracker

from tests.helpers.vision_images import (
    EXPECTED_IDS,
    FakeCamera,
    aruco_four_markers_image,
    four_color_image,
)

STATIONARY_FRAMES = 24
RECALL_THRESHOLD = 0.95


def _stationary_color_frame(frame_index: int, width: int = 320, height: int = 240) -> np.ndarray:
    image = four_color_image(width, height)
    rng = np.random.default_rng(frame_index)
    noise = rng.integers(0, 6, size=image.shape, dtype=np.uint8)
    background = image.sum(axis=2) == 0
    image[background] = noise[background]
    return image


def test_stationary_color_recall_at_least_95_percent() -> None:
    hits = 0
    expected = 0
    for index in range(STATIONARY_FRAMES):
        objects = detect_colored_objects(_stationary_color_frame(index))
        found = {item["object_id"] for item in objects}
        for object_id in EXPECTED_IDS:
            expected += 1
            if object_id in found:
                hits += 1
    recall = hits / expected
    assert expected == STATIONARY_FRAMES * 4
    assert recall >= RECALL_THRESHOLD, f"detection recall {recall:.3f} < {RECALL_THRESHOLD}"


def test_generated_aruco_frames_recover_ids_0_to_3() -> None:
    catalog = [dict(row) for row in DEFAULT_CATALOG]
    for _ in range(4):
        objects = detect_aruco_objects(aruco_four_markers_image(), catalog)
        assert {item["object_id"] for item in objects} == EXPECTED_IDS


def test_tracker_keeps_ids_when_squares_jitter_by_a_few_pixels() -> None:
    tracker = ObjectTracker(stale_ms=400)
    ids_over_time: list[set[str]] = []
    for dx, dy, now_ns in ((0, 0, 0), (2, -1, 33_000_000), (-3, 2, 66_000_000)):
        detections = detect_colored_objects(four_color_image(dx=dx, dy=dy))
        tracked = tracker.update(detections, now_ns)
        visible = {item["object_id"] for item in tracked if not item["stale"]}
        ids_over_time.append(visible)
    assert ids_over_time[0] == EXPECTED_IDS
    assert ids_over_time[1] == ids_over_time[0]
    assert ids_over_time[2] == ids_over_time[0]


def test_object_marked_stale_after_configured_absence() -> None:
    camera = FakeCamera(four_color_image(), source_time_ns=0)
    runtime = VisionHardwareRuntime(camera, hands=None, object_stale_ms=400)
    first = runtime.render_frame(monotonic_ns=0)
    objects_event = next(event for event in first if event.event_type == "vision.objects")
    assert {item["object_id"] for item in objects_event.payload["objects"]} == EXPECTED_IDS

    camera.frame = four_color_image(omit="yellow")
    camera.source_time_ns = 400_000_000
    later = runtime.render_frame(monotonic_ns=400_000_000)
    objects_event = next(event for event in later if event.event_type == "vision.objects")
    yellow = next(
        item for item in objects_event.payload["objects"] if item["object_id"] == "object_yellow_1"
    )
    assert yellow["stale"] is True
    quality = next(event for event in later if event.event_type == "data.quality")
    assert "object_stale" in quality.payload["flags"]
    parse_unnormalized_event(objects_event.to_unnormalized_dict())


def test_calibration_resolution_mismatch_raises(tmp_path: Path) -> None:
    path = tmp_path / "calibration.json"
    save_calibration(
        CameraCalibration(
            camera_id="vision-camera-0",
            width=1280,
            height=720,
            homography=None,
            workspace_polygon=[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]],
            marker_size_m=0.05,
        ),
        path,
    )
    with pytest.raises(CalibrationMismatchError, match="explicit transform"):
        load_calibration(path, camera_id="vision-camera-0", width=640, height=360)
    with pytest.raises(CalibrationMismatchError):
        load_calibration(path, camera_id="other-camera", width=1280, height=720)
    matched = load_calibration(path, camera_id="vision-camera-0", width=1280, height=720)
    assert matched.key() == ("vision-camera-0", 1280, 720)

    camera = FakeCamera(four_color_image())
    runtime = VisionHardwareRuntime(
        camera,
        hands=None,
        calibration=CameraCalibration(camera_id="cam0", width=1280, height=720),
    )
    with pytest.raises(CalibrationMismatchError, match="calibration mismatch"):
        runtime.render_frame(monotonic_ns=0)


def test_frozen_camera_detected_within_one_second() -> None:
    detector = FreezeDetector(timeout_ns=1_000_000_000)
    assert detector.observe(10, 0) is False
    assert detector.observe(10, 1_000_000_000) is True

    camera = FakeCamera(four_color_image(), source_time_ns=7)
    runtime = VisionHardwareRuntime(camera, hands=None)
    runtime.render_frame(monotonic_ns=0)
    later = runtime.render_frame(monotonic_ns=1_000_000_000)
    quality = next(event for event in later if event.event_type == "data.quality")
    assert "camera_frozen" in quality.payload["flags"]
    for event in later:
        assert "gaze" not in event.event_type
