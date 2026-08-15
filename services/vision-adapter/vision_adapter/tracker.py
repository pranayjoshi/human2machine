"""Stable object_id tracking with staleness after configured absence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

DEFAULT_OBJECT_STALE_MS = 400.0


def stale_ms_from_config(
    config: Mapping[str, Any] | None,
    default: float = DEFAULT_OBJECT_STALE_MS,
) -> float:
    """Read vision.object_stale_ms from a stacked config mapping."""
    if not config:
        return default
    vision = config.get("vision", config)
    if not isinstance(vision, Mapping):
        return default
    raw = vision.get("object_stale_ms", default)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


@dataclass
class TrackedObject:
    object_id: str
    class_name: str
    confidence: float
    bbox_xyxy: list[float]
    table_position_xy: list[float]
    last_seen_ns: int
    stale: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "object_id": self.object_id,
            "class_name": self.class_name,
            "confidence": self.confidence,
            "bbox_xyxy": list(self.bbox_xyxy),
            "table_position_xy": list(self.table_position_xy),
            "stale": self.stale,
        }


class ObjectTracker:
    """Track detections by object_id and mark them stale after absence.

    Small bbox jitter does not change IDs because identity comes from the
    detector catalog (color / ArUco), not from spatial association.
    """

    def __init__(self, stale_ms: float = DEFAULT_OBJECT_STALE_MS) -> None:
        self.stale_ms = float(stale_ms)
        self._tracks: dict[str, TrackedObject] = {}

    @property
    def stale_ns(self) -> int:
        return int(self.stale_ms * 1_000_000)

    def update(
        self,
        detections: list[dict[str, Any]],
        now_ns: int,
    ) -> list[dict[str, Any]]:
        seen: set[str] = set()
        for det in detections:
            object_id = str(det["object_id"])
            seen.add(object_id)
            self._tracks[object_id] = TrackedObject(
                object_id=object_id,
                class_name=str(det.get("class_name", object_id)),
                confidence=float(det.get("confidence", 0.0)),
                bbox_xyxy=[float(v) for v in det["bbox_xyxy"]],
                table_position_xy=[float(v) for v in det["table_position_xy"]],
                last_seen_ns=int(now_ns),
                stale=False,
            )
        stale_ns = self.stale_ns
        for object_id, track in self._tracks.items():
            if object_id in seen:
                continue
            if int(now_ns) - track.last_seen_ns >= stale_ns:
                track.stale = True
        return [track.as_dict() for track in self._tracks.values()]
