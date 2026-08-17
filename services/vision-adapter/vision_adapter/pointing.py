from __future__ import annotations

from typing import Any

import numpy as np
from numpy.typing import NDArray

try:
    import cv2
except Exception:  # pragma: no cover - optional in some CI images
    cv2 = None  # type: ignore[assignment]

INDEX_MCP = 5
INDEX_TIP = 8
DEFAULT_MIN_CONFIDENCE = 0.55
DEFAULT_EMA_ALPHA = 0.55
DEFAULT_SCORE_DECAY = 0.62


def empty_hands(*, landmark_confidence: float = 0.0, handedness: str | None = "right") -> dict[str, Any]:
    return {
        "handedness": handedness,
        "landmark_confidence": float(landmark_confidence),
        "pointing": False,
        "table_intersection_xy": None,
    }


def pointing_from_index_ray(
    mcp_xy: tuple[float, float],
    tip_xy: tuple[float, float],
    objects: list[dict[str, Any]],
    image_size: tuple[int, int],
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    landmark_confidence: float | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Score table objects by an index MCP→tip ray.

    When ``landmark_confidence`` is provided and below ``min_confidence``, no
    pointing candidate is returned.
    """
    width, height = image_size
    measured = 0.0 if landmark_confidence is None else float(landmark_confidence)
    hands = empty_hands(
        landmark_confidence=measured,
        handedness="right",
    )
    if landmark_confidence is not None and measured < min_confidence:
        return [], hands

    mcp = np.array(mcp_xy, dtype=float)
    tip = np.array(tip_xy, dtype=float)
    direction = tip - mcp
    norm = float(np.linalg.norm(direction))
    if norm < 1e-6:
        return [], hands
    direction = direction / norm
    if norm < 8:
        hands["landmark_confidence"] = measured if landmark_confidence is not None else 0.4
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
    if landmark_confidence is None:
        hands["landmark_confidence"] = 0.9 if candidates else 0.6
    else:
        hands["landmark_confidence"] = measured
    hands["pointing"] = bool(candidates)
    hands["table_intersection_xy"] = table_xy if candidates else None
    return candidates, hands


class PointingSmoother:
    """Exponential moving average of pointing scores, keyed by object_id."""

    def __init__(
        self,
        *,
        alpha: float = DEFAULT_EMA_ALPHA,
        min_confidence: float = DEFAULT_MIN_CONFIDENCE,
        decay: float = DEFAULT_SCORE_DECAY,
    ) -> None:
        self.alpha = float(alpha)
        self.min_confidence = float(min_confidence)
        self.decay = float(decay)
        self._scores: dict[str, float] = {}

    def reset(self) -> None:
        self._scores.clear()

    def update(
        self,
        candidates: list[dict[str, Any]],
        *,
        landmark_confidence: float,
    ) -> list[dict[str, Any]]:
        if landmark_confidence < self.min_confidence:
            self._scores.clear()
            return []
        current = {str(row["object_id"]): float(row["confidence"]) for row in candidates}
        next_scores: dict[str, float] = {}
        for object_id in set(self._scores) | set(current):
            raw = current.get(object_id)
            prev = self._scores.get(object_id)
            if raw is None:
                value = (prev or 0.0) * self.decay
            elif prev is None:
                value = raw
            else:
                value = self.alpha * raw + (1.0 - self.alpha) * prev
            if value >= self.min_confidence * 0.45:
                next_scores[object_id] = min(0.99, value)
        self._scores = next_scores
        smoothed = [
            {"object_id": object_id, "confidence": confidence}
            for object_id, confidence in self._scores.items()
            if confidence >= self.min_confidence
        ]
        smoothed.sort(key=lambda row: row["confidence"], reverse=True)
        return smoothed


def try_mediapipe_pointing(
    frame_bgr: NDArray[np.uint8],
    objects: list[dict[str, Any]],
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    landmarker: Any | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    empty = empty_hands(landmark_confidence=0.0, handedness=None)
    if landmarker is None:
        return [], empty
    height, width = frame_bgr.shape[:2]
    try:
        if cv2 is None:
            return [], empty
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        result = landmarker.process(rgb)
    except Exception:
        return [], empty
    if not getattr(result, "multi_hand_landmarks", None):
        return [], empty
    hand = result.multi_hand_landmarks[0]
    mcp = hand.landmark[INDEX_MCP]
    tip = hand.landmark[INDEX_TIP]
    landmark_confidence = 0.0
    handedness = "right"
    if getattr(result, "multi_handedness", None):
        classification = result.multi_handedness[0].classification[0]
        landmark_confidence = float(classification.score)
        label = getattr(classification, "label", None)
        if label:
            handedness = str(label).lower()
    else:
        landmark_confidence = 0.85
    candidates, hands = pointing_from_index_ray(
        (mcp.x * width, mcp.y * height),
        (tip.x * width, tip.y * height),
        objects,
        (width, height),
        min_confidence,
        landmark_confidence=landmark_confidence,
    )
    hands["handedness"] = handedness
    return candidates, hands


def maybe_create_hands() -> Any | None:
    try:
        from vision_adapter.protobuf_compat import patch_protobuf_get_prototype

        patch_protobuf_get_prototype()
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
