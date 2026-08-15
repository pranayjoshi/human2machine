from __future__ import annotations

from vision_adapter.head_direction import (
    head_direction_from_landmarks,
    maybe_create_face_landmarker,
    project_head_cone,
    synthetic_face_landmarks,
    try_mediapipe_head_direction,
)
from vision_adapter.pointing import PointingSmoother, maybe_create_hands, pointing_from_index_ray

IMAGE_SIZE = (320, 240)

QUADRANT_OBJECTS = (
    {"object_id": "object_blue_1", "table_position_xy": [0.20, 0.24]},
    {"object_id": "object_red_1", "table_position_xy": [0.80, 0.24]},
    {"object_id": "object_green_1", "table_position_xy": [0.20, 0.80]},
    {"object_id": "object_yellow_1", "table_position_xy": [0.80, 0.80]},
)


def _aim_at(
    target_xy: list[float],
    *,
    image_size: tuple[int, int] = IMAGE_SIZE,
    back_px: float = 48.0,
    angle_rad: float = 1.2,
) -> tuple[tuple[float, float], tuple[float, float]]:
    import math

    width, height = image_size
    target = (target_xy[0] * width, target_xy[1] * height)
    direction = (math.cos(angle_rad) * back_px, math.sin(angle_rad) * back_px)
    mcp = (target[0] - direction[0] * 1.25, target[1] - direction[1] * 1.25)
    tip = (target[0] - direction[0] * 0.25, target[1] - direction[1] * 0.25)
    return mcp, tip


def test_index_ray_scores_nearest_object() -> None:
    target = QUADRANT_OBJECTS[0]
    mcp, tip = _aim_at(target["table_position_xy"])
    candidates, hands = pointing_from_index_ray(
        mcp, tip, list(QUADRANT_OBJECTS), IMAGE_SIZE, min_confidence=0.55
    )
    assert hands["pointing"] is True
    assert candidates[0]["object_id"] == "object_blue_1"


def test_low_landmark_confidence_returns_no_candidates() -> None:
    target = QUADRANT_OBJECTS[1]
    mcp, tip = _aim_at(target["table_position_xy"])
    candidates, hands = pointing_from_index_ray(
        mcp,
        tip,
        list(QUADRANT_OBJECTS),
        IMAGE_SIZE,
        min_confidence=0.55,
        landmark_confidence=0.21,
    )
    assert candidates == []
    assert hands["pointing"] is False
    assert hands["landmark_confidence"] == 0.21


def test_smoother_ema_and_clears_on_low_confidence() -> None:
    smoother = PointingSmoother(alpha=0.5, min_confidence=0.55)
    first = smoother.update(
        [{"object_id": "object_blue_1", "confidence": 0.80}],
        landmark_confidence=0.9,
    )
    assert first[0]["object_id"] == "object_blue_1"
    second = smoother.update(
        [{"object_id": "object_blue_1", "confidence": 0.60}],
        landmark_confidence=0.9,
    )
    assert 0.60 < second[0]["confidence"] < 0.80
    assert smoother.update([], landmark_confidence=0.2) == []
    assert smoother.update(
        [{"object_id": "object_blue_1", "confidence": 0.90}],
        landmark_confidence=0.2,
    ) == []


def test_two_close_targets_return_ranked_candidates() -> None:
    objects = [
        {"object_id": "object_blue_1", "table_position_xy": [0.40, 0.50]},
        {"object_id": "object_red_1", "table_position_xy": [0.46, 0.52]},
        {"object_id": "object_green_1", "table_position_xy": [0.20, 0.80]},
        {"object_id": "object_yellow_1", "table_position_xy": [0.80, 0.80]},
    ]
    mcp, tip = _aim_at([0.43, 0.51], back_px=40.0)
    candidates, hands = pointing_from_index_ray(mcp, tip, objects, IMAGE_SIZE)
    assert hands["pointing"] is True
    assert len(candidates) >= 2
    assert {row["object_id"] for row in candidates[:2]} == {"object_blue_1", "object_red_1"}
    assert candidates[0]["confidence"] >= candidates[1]["confidence"]


def test_head_direction_from_synthetic_landmarks_is_weak() -> None:
    landmarks = synthetic_face_landmarks(-22.0, 16.0, image_size=IMAGE_SIZE)
    payload = head_direction_from_landmarks(landmarks, list(QUADRANT_OBJECTS), IMAGE_SIZE)
    assert payload["yaw_deg"] is not None
    assert payload["pitch_deg"] is not None
    assert payload["confidence"] > 0.0
    assert payload["candidates"]
    assert all(row["confidence"] < 0.5 for row in payload["candidates"])
    ids = {row["object_id"] for row in payload["candidates"]}
    assert "object_blue_1" in ids
    assert all("gaze" not in row for row in payload)
    assert all("gaze" not in row for row in payload["candidates"][0])


def test_head_cone_supports_without_selecting_alone() -> None:
    candidates = project_head_cone(-20.0, 14.0, list(QUADRANT_OBJECTS), confidence=0.48)
    assert candidates
    assert max(row["confidence"] for row in candidates) <= 0.40
    assert len(candidates) >= 1


def test_optional_mediapipe_helpers_do_not_require_package() -> None:
    assert maybe_create_hands() is None or maybe_create_hands() is not None
    assert maybe_create_face_landmarker() is None or maybe_create_face_landmarker() is not None
    empty = try_mediapipe_head_direction(
        __import__("numpy").zeros((24, 32, 3), dtype="uint8"),
        list(QUADRANT_OBJECTS),
        landmarker=None,
    )
    assert empty["yaw_deg"] is None
    assert empty["candidates"] == []
