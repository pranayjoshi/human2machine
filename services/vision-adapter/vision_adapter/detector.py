from __future__ import annotations

from typing import Any, Protocol


class ObjectDetector(Protocol):
    def detect_objects(self, frame: Any) -> list[dict[str, Any]]:
        """Return stable-id object detections for one frame."""


class PointingEstimator(Protocol):
    def estimate(self, frame: Any) -> dict[str, Any]:
        """Return pointing/head-direction evidence. Never labeled gaze."""
