"""Shared synthetic frames for vision unit and Milestone 2 tests."""

from __future__ import annotations

import numpy as np

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
