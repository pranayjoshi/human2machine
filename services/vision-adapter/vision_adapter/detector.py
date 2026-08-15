from __future__ import annotations

from typing import Any, Protocol

from vision_adapter.color_detector import DEFAULT_CATALOG, detect_colored_objects


class ObjectDetector(Protocol):
    def detect_objects(self, frame: Any) -> list[dict[str, Any]]:
        """Return stable-id object detections for one frame."""


class PointingEstimator(Protocol):
    def estimate(self, frame: Any) -> dict[str, Any]:
        """Return pointing/head-direction evidence. Never labeled gaze."""


class ColorArucoDetector:
    """HSV color plus ArUco 4x4 IDs 0-3. Not open-world recognition."""

    def __init__(self, catalog: list[dict[str, Any]] | None = None) -> None:
        self.catalog = catalog or [dict(row) for row in DEFAULT_CATALOG]

    def detect_objects(self, frame: Any) -> list[dict[str, Any]]:
        return detect_colored_objects(frame, self.catalog)
