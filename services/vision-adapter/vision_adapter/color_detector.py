from __future__ import annotations

from typing import Any

import numpy as np
from numpy.typing import NDArray

try:
    import cv2
except Exception:  # pragma: no cover - optional in some CI images
    cv2 = None  # type: ignore[assignment]

HSV_RANGES: dict[str, list[tuple[tuple[int, int, int], tuple[int, int, int]]]] = {
    "blue": [((100, 80, 80), (130, 255, 255))],
    "red": [((0, 80, 80), (10, 255, 255)), ((170, 80, 80), (179, 255, 255))],
    "green": [((40, 80, 80), (85, 255, 255))],
    "yellow": [((18, 80, 80), (38, 255, 255))],
}

COLOR_FROM_CLASS = {
    "blue_block": "blue",
    "red_block": "red",
    "green_block": "green",
    "yellow_block": "yellow",
}

DEFAULT_CATALOG = (
    {"object_id": "object_blue_1", "class_name": "blue_block", "color": "blue"},
    {"object_id": "object_red_1", "class_name": "red_block", "color": "red"},
    {"object_id": "object_green_1", "class_name": "green_block", "color": "green"},
    {"object_id": "object_yellow_1", "class_name": "yellow_block", "color": "yellow"},
)

ARUCO_ID_TO_OBJECT = {
    0: "object_blue_1",
    1: "object_red_1",
    2: "object_green_1",
    3: "object_yellow_1",
}

INDEX_MCP = 5
INDEX_TIP = 8


def detect_colored_objects(
    frame_bgr: NDArray[np.uint8],
    catalog: list[dict[str, Any]] | None = None,
    min_area: int = 200,
) -> list[dict[str, Any]]:
    if cv2 is None:
        raise RuntimeError("opencv-python is required for color detection")
    items = catalog or [dict(row) for row in DEFAULT_CATALOG]
    hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
    height, width = frame_bgr.shape[:2]
    found: list[dict[str, Any]] = []
    for item in items:
        color = str(item.get("color") or COLOR_FROM_CLASS.get(item.get("class_name", ""), ""))
        ranges = HSV_RANGES.get(color)
        if not ranges:
            continue
        mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
        for low, high in ranges:
            mask = cv2.bitwise_or(mask, cv2.inRange(hsv, np.array(low), np.array(high)))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            continue
        contour = max(contours, key=cv2.contourArea)
        area = float(cv2.contourArea(contour))
        if area < min_area:
            continue
        x, y, bw, bh = cv2.boundingRect(contour)
        cx = x + bw / 2.0
        cy = y + bh / 2.0
        confidence = min(0.99, 0.55 + area / max(width * height, 1) * 8.0)
        found.append(
            {
                "object_id": item["object_id"],
                "class_name": item.get("class_name", item["object_id"]),
                "confidence": float(confidence),
                "bbox_xyxy": [float(x), float(y), float(x + bw), float(y + bh)],
                "table_position_xy": [cx / max(width, 1), cy / max(height, 1)],
            }
        )
    by_aruco = detect_aruco_objects(frame_bgr, items)
    if by_aruco:
        merged = {item["object_id"]: item for item in found}
        merged.update({item["object_id"]: item for item in by_aruco})
        return list(merged.values())
    return found


def detect_aruco_objects(
    frame_bgr: NDArray[np.uint8], catalog: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    if cv2 is None or not hasattr(cv2, "aruco"):
        return []
    try:
        dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
        detector = cv2.aruco.ArucoDetector(dictionary, cv2.aruco.DetectorParameters())
        corners, ids, _rejected = detector.detectMarkers(frame_bgr)
    except Exception:
        try:
            dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
            corners, ids, _rejected = cv2.aruco.detectMarkers(frame_bgr, dictionary)
        except Exception:
            return []
    if ids is None or len(ids) == 0:
        return []
    catalog_by_id = {item["object_id"]: item for item in catalog}
    height, width = frame_bgr.shape[:2]
    found: list[dict[str, Any]] = []
    for marker_id, corner in zip(ids.flatten(), corners, strict=False):
        object_id = ARUCO_ID_TO_OBJECT.get(int(marker_id))
        if object_id is None or object_id not in catalog_by_id:
            continue
        pts = corner.reshape(-1, 2)
        x_min, y_min = np.min(pts, axis=0)
        x_max, y_max = np.max(pts, axis=0)
        cx = float((x_min + x_max) / 2.0)
        cy = float((y_min + y_max) / 2.0)
        item = catalog_by_id[object_id]
        found.append(
            {
                "object_id": object_id,
                "class_name": item.get("class_name", object_id),
                "confidence": 0.98,
                "bbox_xyxy": [float(x_min), float(y_min), float(x_max), float(y_max)],
                "table_position_xy": [cx / max(width, 1), cy / max(height, 1)],
            }
        )
    return found


def pointing_from_index_ray(
    mcp_xy: tuple[float, float],
    tip_xy: tuple[float, float],
    objects: list[dict[str, Any]],
    image_size: tuple[int, int],
    min_confidence: float = 0.55,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    width, height = image_size
    mcp = np.array(mcp_xy, dtype=float)
    tip = np.array(tip_xy, dtype=float)
    direction = tip - mcp
    norm = float(np.linalg.norm(direction))
    hands = {
        "handedness": "right",
        "landmark_confidence": 0.0,
        "pointing": False,
        "table_intersection_xy": None,
    }
    if norm < 1e-6:
        return [], hands
    direction = direction / norm
    if norm < 8:
        hands["landmark_confidence"] = 0.4
        return [], hands
    ahead = tip + direction * (norm * 0.25)
    table_xy = [
        float(np.clip(ahead[0] / max(width, 1), 0.0, 1.0)),
        float(np.clip(ahead[1] / max(height, 1), 0.0, 1.0)),
    ]
    candidates: list[dict[str, Any]] = []
    for obj in objects:
        pos = np.array(obj.get("table_position_xy") or [0.5, 0.5], dtype=float)
        dist = float(np.linalg.norm(pos - np.array(table_xy)))
        confidence = max(0.0, min(0.99, 1.0 - dist / 0.35))
        if confidence >= min_confidence:
            candidates.append({"object_id": obj["object_id"], "confidence": confidence})
    candidates.sort(key=lambda row: row["confidence"], reverse=True)
    hands["landmark_confidence"] = 0.9 if candidates else 0.6
    hands["pointing"] = bool(candidates)
    hands["table_intersection_xy"] = table_xy if candidates else None
    return candidates, hands


def try_mediapipe_pointing(
    frame_bgr: NDArray[np.uint8],
    objects: list[dict[str, Any]],
    min_confidence: float = 0.55,
    landmarker: Any | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    empty_hands = {
        "handedness": None,
        "landmark_confidence": 0.0,
        "pointing": False,
        "table_intersection_xy": None,
    }
    if landmarker is None:
        return [], empty_hands
    height, width = frame_bgr.shape[:2]
    try:
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        result = landmarker.process(rgb)
    except Exception:
        return [], empty_hands
    if not getattr(result, "multi_hand_landmarks", None):
        return [], empty_hands
    hand = result.multi_hand_landmarks[0]
    mcp = hand.landmark[INDEX_MCP]
    tip = hand.landmark[INDEX_TIP]
    return pointing_from_index_ray(
        (mcp.x * width, mcp.y * height),
        (tip.x * width, tip.y * height),
        objects,
        (width, height),
        min_confidence,
    )


def maybe_create_hands() -> Any | None:
    try:
        import mediapipe as mp
    except Exception:
        return None
    try:
        return mp.solutions.hands.Hands(
            static_image_mode=False,
            max_num_hands=1,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )
    except Exception:
        return None
