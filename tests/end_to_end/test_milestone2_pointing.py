"""Milestone 2: pointing top-1 accuracy and coarse head direction.

Head direction is supporting evidence only. It is never labeled as eye tracking.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from intent_contracts.validation import parse_unnormalized_event
from vision_adapter.camera import VisionHardwareRuntime
from vision_adapter.head_direction import (
    head_direction_from_landmarks,
    synthetic_face_landmarks,
)
from vision_adapter.pointing import pointing_from_index_ray

IMAGE_SIZE = (320, 240)
OBJECT_IDS = ("object_blue_1", "object_red_1", "object_green_1", "object_yellow_1")
BASE_POSITIONS = (
    (0.22, 0.24),
    (0.78, 0.24),
    (0.22, 0.78),
    (0.78, 0.78),
)


class FakeCamera:
    def __init__(self, frame: np.ndarray, source_time_ns: int = 1_000_000) -> None:
        self.frame = frame
        self.source_time_ns = source_time_ns

    def latest(self):
        return self.frame, self.source_time_ns, 0


def _four_color_image(width: int = 320, height: int = 240) -> np.ndarray:
    image = np.zeros((height, width, 3), dtype=np.uint8)
    image[20:90, 20:90] = (255, 0, 0)
    image[20:90, 200:270] = (0, 0, 255)
    image[150:220, 20:90] = (0, 255, 0)
    image[150:220, 200:270] = (0, 255, 255)
    return image


def _place_objects(rng: np.random.Generator) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    for object_id, (bx, by) in zip(OBJECT_IDS, BASE_POSITIONS, strict=True):
        objects.append(
            {
                "object_id": object_id,
                "class_name": object_id.replace("object_", "").replace("_1", "_block"),
                "table_position_xy": [
                    float(np.clip(bx + rng.uniform(-0.03, 0.03), 0.08, 0.92)),
                    float(np.clip(by + rng.uniform(-0.03, 0.03), 0.08, 0.92)),
                ],
            }
        )
    return objects


def _aim_ray(
    target_xy: list[float],
    rng: np.random.Generator,
    *,
    image_size: tuple[int, int] = IMAGE_SIZE,
) -> tuple[tuple[float, float], tuple[float, float]]:
    width, height = image_size
    target = np.array([target_xy[0] * width, target_xy[1] * height], dtype=float)
    angle = float(rng.uniform(0.0, 2.0 * math.pi))
    back_px = float(rng.uniform(36.0, 72.0))
    direction = np.array([math.cos(angle), math.sin(angle)], dtype=float) * back_px
    jitter = rng.normal(0.0, 3.5, size=2)
    mcp = target - direction * 1.25 + jitter
    tip = target - direction * 0.25 + jitter * 0.4
    return (float(mcp[0]), float(mcp[1])), (float(tip[0]), float(tip[1]))


def _assert_no_gaze(event: Any) -> None:
    assert "gaze" not in event.event_type
    for key in event.payload:
        assert "gaze" not in str(key)


def test_pointing_top1_accuracy_meets_milestone() -> None:
    rng = np.random.default_rng(20260815)
    hits = 0
    trials = 100
    for index in range(trials):
        objects = _place_objects(rng)
        target = objects[index % 4]
        mcp, tip = _aim_ray(target["table_position_xy"], rng)
        candidates, _hands = pointing_from_index_ray(
            mcp,
            tip,
            objects,
            IMAGE_SIZE,
            min_confidence=0.55,
            landmark_confidence=0.92,
        )
        if candidates and candidates[0]["object_id"] == target["object_id"]:
            hits += 1
    accuracy = hits / trials
    assert accuracy >= 0.85, f"pointing top-1 accuracy {accuracy:.2f} below 0.85 ({hits}/{trials})"


def test_low_landmark_confidence_emits_no_pointing_candidates() -> None:
    objects = [
        {"object_id": object_id, "table_position_xy": list(pos)}
        for object_id, pos in zip(OBJECT_IDS, BASE_POSITIONS, strict=True)
    ]
    mcp, tip = _aim_ray(objects[0]["table_position_xy"], np.random.default_rng(1))
    candidates, hands = pointing_from_index_ray(
        mcp,
        tip,
        objects,
        IMAGE_SIZE,
        landmark_confidence=0.18,
    )
    assert candidates == []
    assert hands["pointing"] is False

    runtime = VisionHardwareRuntime(
        FakeCamera(_four_color_image()),
        hands=None,
        face=None,
        hand_landmarks={
            "mcp_xy": mcp,
            "tip_xy": tip,
            "landmark_confidence": 0.18,
        },
    )
    events = runtime.render_frame(monotonic_ns=0)
    objects_event = next(event for event in events if event.event_type == "vision.objects")
    assert objects_event.payload["pointing_candidates"] == []
    for event in events:
        parse_unnormalized_event(event.to_unnormalized_dict())
        _assert_no_gaze(event)


def test_two_close_targets_return_ranked_candidates() -> None:
    objects = [
        {"object_id": "object_blue_1", "table_position_xy": [0.41, 0.50]},
        {"object_id": "object_red_1", "table_position_xy": [0.47, 0.52]},
        {"object_id": "object_green_1", "table_position_xy": [0.20, 0.82]},
        {"object_id": "object_yellow_1", "table_position_xy": [0.82, 0.82]},
    ]
    mcp, tip = _aim_ray([0.44, 0.51], np.random.default_rng(3))
    candidates, hands = pointing_from_index_ray(mcp, tip, objects, IMAGE_SIZE, landmark_confidence=0.9)
    assert hands["pointing"] is True
    assert len(candidates) >= 2
    assert candidates[0]["confidence"] >= candidates[1]["confidence"]
    assert {row["object_id"] for row in candidates[:2]} <= {
        "object_blue_1",
        "object_red_1",
        "object_green_1",
        "object_yellow_1",
    }


def test_head_direction_supports_candidate_and_is_never_gaze() -> None:
    objects = [
        {"object_id": object_id, "table_position_xy": list(pos)}
        for object_id, pos in zip(OBJECT_IDS, BASE_POSITIONS, strict=True)
    ]
    landmarks = synthetic_face_landmarks(-24.0, 14.0, image_size=IMAGE_SIZE)
    head = head_direction_from_landmarks(landmarks, objects, IMAGE_SIZE)
    assert head["yaw_deg"] is not None
    assert head["pitch_deg"] is not None
    assert head["candidates"]
    assert any(row["object_id"] == "object_blue_1" for row in head["candidates"])
    assert all(row["confidence"] < 0.5 for row in head["candidates"])
    assert all("gaze" not in row for row in head)

    mcp, tip = _aim_ray(objects[0]["table_position_xy"], np.random.default_rng(9))
    runtime = VisionHardwareRuntime(
        FakeCamera(_four_color_image()),
        hands=None,
        face=None,
        hand_landmarks={"mcp_xy": mcp, "tip_xy": tip, "landmark_confidence": 0.91},
        face_landmarks=landmarks,
    )
    events = runtime.render_frame(monotonic_ns=0)
    types = {event.event_type for event in events}
    assert "vision.head_direction" in types
    head_event = next(event for event in events if event.event_type == "vision.head_direction")
    assert head_event.payload["yaw_deg"] is not None
    assert head_event.payload["pitch_deg"] is not None
    assert head_event.payload["candidates"]
    assert all(row["confidence"] < 0.5 for row in head_event.payload["candidates"])
    objects_event = next(event for event in events if event.event_type == "vision.objects")
    assert objects_event.payload["pointing_candidates"]
    for event in events:
        parse_unnormalized_event(event.to_unnormalized_dict())
        _assert_no_gaze(event)
        for key in event.to_unnormalized_dict():
            assert "gaze" not in str(key)
