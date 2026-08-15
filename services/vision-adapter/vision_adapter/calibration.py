"""Camera calibration store keyed by camera_id and resolution."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

TransformLike = Mapping[str, Any] | Sequence[Sequence[float]] | Sequence[float]


class CalibrationMismatchError(ValueError):
    """Raised when stored calibration does not match the active camera/resolution."""


@dataclass
class CameraCalibration:
    camera_id: str
    width: int
    height: int
    homography: list[list[float]] | None = None
    workspace_polygon: list[list[float]] | None = None
    marker_size_m: float | None = None
    lens_intrinsics: dict[str, Any] | None = None

    def key(self) -> tuple[str, int, int]:
        return (str(self.camera_id), int(self.width), int(self.height))

    def to_dict(self) -> dict[str, Any]:
        return {
            "camera_id": self.camera_id,
            "width": int(self.width),
            "height": int(self.height),
            "homography": self.homography,
            "workspace_polygon": self.workspace_polygon,
            "marker_size_m": self.marker_size_m,
            "lens_intrinsics": self.lens_intrinsics,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> CameraCalibration:
        homography = data.get("homography")
        workspace = data.get("workspace_polygon")
        return cls(
            camera_id=str(data["camera_id"]),
            width=int(data["width"]),
            height=int(data["height"]),
            homography=_matrix_or_none(homography),
            workspace_polygon=_points_or_none(workspace),
            marker_size_m=_optional_float(data.get("marker_size_m")),
            lens_intrinsics=_mapping_or_none(data.get("lens_intrinsics")),
        )


def save_calibration(calibration: CameraCalibration, path: str | Path) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(calibration.to_dict(), indent=2) + "\n")


def load_calibration(
    path: str | Path,
    *,
    camera_id: str | None = None,
    width: int | None = None,
    height: int | None = None,
    explicit_transform: TransformLike | None = None,
) -> CameraCalibration:
    """Load JSON calibration.

    If camera_id/width/height are provided they must match the stored file
    unless ``explicit_transform`` is supplied. A resolution or camera mismatch
    without that transform fails instead of silently warping.
    """
    stored = CameraCalibration.from_dict(json.loads(Path(path).read_text()))
    requested_id = stored.camera_id if camera_id is None else str(camera_id)
    requested_width = stored.width if width is None else int(width)
    requested_height = stored.height if height is None else int(height)
    requested = (requested_id, requested_width, requested_height)
    if requested == stored.key():
        return stored
    if explicit_transform is None:
        raise CalibrationMismatchError(
            "calibration mismatch: stored "
            f"camera_id={stored.camera_id!r} {stored.width}x{stored.height}, "
            f"requested camera_id={requested_id!r} {requested_width}x{requested_height}. "
            "Refuse to load at a different resolution without an explicit transform."
        )
    return stored


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _mapping_or_none(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise TypeError("lens_intrinsics must be a mapping")
    return dict(value)


def _matrix_or_none(value: Any) -> list[list[float]] | None:
    if value is None:
        return None
    return [[float(cell) for cell in row] for row in value]


def _points_or_none(value: Any) -> list[list[float]] | None:
    if value is None:
        return None
    return [[float(coord) for coord in point] for point in value]
