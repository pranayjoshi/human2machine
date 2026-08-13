from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from intent_contracts.enums import PRODUCER_VERSION, SCHEMA_VERSION
from intent_contracts.envelope import EventEnvelope, new_event_id, now_monotonic_ns
from intent_runtime.heartbeat import heartbeat_event as runtime_heartbeat

SOURCE = "vision-adapter"

DEFAULT_OBJECTS = (
    {
        "object_id": "object_blue_1",
        "class_name": "blue_block",
        "table_position_xy": [0.25, 0.40],
        "bbox_xyxy": [100.0, 80.0, 200.0, 180.0],
    },
    {
        "object_id": "object_red_1",
        "class_name": "red_block",
        "table_position_xy": [0.55, 0.40],
        "bbox_xyxy": [300.0, 80.0, 400.0, 180.0],
    },
    {
        "object_id": "object_green_1",
        "class_name": "green_block",
        "table_position_xy": [0.25, 0.70],
        "bbox_xyxy": [100.0, 250.0, 200.0, 350.0],
    },
    {
        "object_id": "object_yellow_1",
        "class_name": "yellow_block",
        "table_position_xy": [0.55, 0.70],
        "bbox_xyxy": [300.0, 250.0, 400.0, 350.0],
    },
)


def make_event(
    *,
    event_type: str,
    sequence: int,
    payload: dict[str, Any],
    modality: str | None = "vision",
    source_time_ns: int | None = None,
    quality: float = 1.0,
) -> EventEnvelope:
    return EventEnvelope(
        schema_version=SCHEMA_VERSION,
        event_id=new_event_id(),
        event_type=event_type,
        source=SOURCE,
        modality=modality,
        session_id=None,
        trial_id=None,
        sequence=sequence,
        source_time_ns=source_time_ns,
        received_monotonic_ns=now_monotonic_ns(),
        quality=quality,
        producer_version=PRODUCER_VERSION,
        payload=payload,
    )


@dataclass
class FreezeDetector:
    timeout_ns: int = 1_000_000_000
    last_progress_monotonic_ns: int | None = None
    last_source_time_ns: int | None = None

    def observe(self, source_time_ns: int, monotonic_ns: int) -> bool:
        if self.last_source_time_ns is None or source_time_ns > self.last_source_time_ns:
            self.last_source_time_ns = source_time_ns
            self.last_progress_monotonic_ns = monotonic_ns
            return False
        if self.last_progress_monotonic_ns is None:
            self.last_progress_monotonic_ns = monotonic_ns
            return False
        return (monotonic_ns - self.last_progress_monotonic_ns) >= self.timeout_ns


@dataclass
class VisionMockRuntime:
    objects: list[dict[str, Any]] = field(
        default_factory=lambda: [dict(item) for item in DEFAULT_OBJECTS]
    )
    scenario: str = "all_visible"
    pointing_confidence_min: float = 0.55
    publish_hz: float = 12.0
    freeze: bool = False
    freeze_after_ms: float = 1000.0
    hand_confidence_override: float | None = None

    sequence: int = 0
    frame_id: int = 0
    frozen: bool = False
    freeze_started_monotonic_ns: int | None = None
    _started: bool = False
    _detector: FreezeDetector = field(default_factory=FreezeDetector)
    _frozen_source_time_ns: int | None = None

    def enable_freeze(self) -> None:
        self.freeze = True
        self.frozen = True
        self._frozen_source_time_ns = self.frame_id * int(1_000_000_000 / self.publish_hz)

    def render_frame(
        self,
        frame_id: int | None = None,
        *,
        scenario: str | None = None,
        hand_confidence: float | None = None,
        monotonic_ns: int | None = None,
        force_freeze: bool | None = None,
    ) -> list[EventEnvelope]:
        scenario = scenario or self.scenario
        fid = self.frame_id if frame_id is None else frame_id
        if force_freeze is None:
            force_freeze = self.frozen or self.freeze
        interval_ns = int(1_000_000_000 / self.publish_hz)
        source_time_ns = fid * interval_ns
        if force_freeze and self._frozen_source_time_ns is not None:
            source_time_ns = self._frozen_source_time_ns
        elif force_freeze:
            source_time_ns = self._frozen_source_time_ns or source_time_ns
            self._frozen_source_time_ns = source_time_ns
        mono = monotonic_ns if monotonic_ns is not None else now_monotonic_ns()
        frozen = self._detector.observe(source_time_ns, mono) or bool(force_freeze and fid > 0)
        objects = self._objects_for(scenario, fid)
        hand_conf = (
            hand_confidence
            if hand_confidence is not None
            else self.hand_confidence_override
            if self.hand_confidence_override is not None
            else self._hand_confidence(scenario)
        )
        pointing = self._pointing(scenario, objects, hand_conf)
        head = self._head(scenario, objects)
        quality = 0.35 if frozen else 0.96
        flags = ["camera_frozen"] if frozen else []
        events = []
        if not self._started:
            events.append(self._device_status("degraded" if frozen else "healthy", "mock camera"))
            self._started = True
        elif frozen:
            events.append(self._device_status("degraded", "frozen camera"))
        events.append(
            make_event(
                event_type="vision.objects",
                sequence=self._next_seq(),
                source_time_ns=source_time_ns,
                quality=quality,
                payload={
                    "frame_id": (
                        fid
                        if not force_freeze
                        else (self._frozen_source_time_ns or 0) // max(interval_ns, 1)
                    ),
                    "objects": objects,
                    "pointing_candidates": pointing,
                    "head_direction_candidates": head,
                },
            )
        )
        events.append(
            make_event(
                event_type="vision.hands",
                sequence=self._next_seq(),
                source_time_ns=source_time_ns,
                quality=quality,
                payload={
                    "frame_id": fid,
                    "handedness": "right" if hand_conf >= self.pointing_confidence_min else None,
                    "landmark_confidence": hand_conf,
                    "pointing": bool(pointing),
                    "table_intersection_xy": objects[0]["table_position_xy"] if pointing else None,
                },
            )
        )
        events.append(
            make_event(
                event_type="vision.head_direction",
                sequence=self._next_seq(),
                source_time_ns=source_time_ns,
                quality=quality,
                payload={
                    "frame_id": fid,
                    "yaw_deg": -12.0 if head else 0.0,
                    "pitch_deg": -8.0 if head else 0.0,
                    "confidence": 0.45 if head else 0.2,
                    "candidates": head,
                },
            )
        )
        events.append(
            make_event(
                event_type="data.quality",
                sequence=self._next_seq(),
                source_time_ns=source_time_ns,
                quality=quality,
                payload={
                    "score": quality,
                    "components": {
                        "frame_age_ms": 1200.0 if frozen else 40.0,
                        "camera_fps": 0.0 if frozen else self.publish_hz,
                        "hand_landmark_confidence": hand_conf,
                    },
                    "flags": flags,
                },
            )
        )
        if frame_id is None:
            self.frame_id += 1
        return events

    def heartbeat(self, uptime_seconds: float, dropped: int) -> EventEnvelope:
        return runtime_heartbeat(
            SOURCE,
            uptime_seconds=uptime_seconds,
            last_data_age_ms=1200.0 if self.frozen else 40.0,
            error_count=dropped,
            sequence=self._next_seq(),
            status="degraded" if self.frozen or dropped else "healthy",
        )

    def shutdown(self) -> EventEnvelope:
        return self._device_status("offline", "adapter stopping")

    def _objects_for(self, scenario: str, frame_id: int) -> list[dict[str, Any]]:
        catalog = [self._vision_object(item) for item in self.objects]
        if scenario == "disappearance" and frame_id >= 24:
            catalog = [item for item in catalog if item["object_id"] != "object_yellow_1"]
        if scenario == "two_close":
            for item in catalog:
                if item["object_id"] == "object_red_1":
                    item["table_position_xy"] = [
                        catalog[0]["table_position_xy"][0] + 0.04,
                        catalog[0]["table_position_xy"][1] + 0.02,
                    ]
                    item["bbox_xyxy"] = [
                        catalog[0]["bbox_xyxy"][0] + 30,
                        catalog[0]["bbox_xyxy"][1],
                        catalog[0]["bbox_xyxy"][2] + 30,
                        catalog[0]["bbox_xyxy"][3],
                    ]
        return catalog

    def _vision_object(self, item: dict[str, Any]) -> dict[str, Any]:
        pos = item.get("table_position_xy") or [0.5, 0.5]
        bbox = item.get("bbox_xyxy") or [0.0, 0.0, 80.0, 80.0]
        return {
            "object_id": item["object_id"],
            "class_name": item.get("class_name", item["object_id"]),
            "confidence": 0.97,
            "bbox_xyxy": list(bbox),
            "table_position_xy": list(pos),
        }

    def _hand_confidence(self, scenario: str) -> float:
        if scenario == "no_hand":
            return 0.12
        if scenario in {"pointing_blue", "two_close"}:
            return 0.91
        return 0.7

    def _pointing(
        self, scenario: str, objects: list[dict[str, Any]], hand_conf: float
    ) -> list[dict[str, Any]]:
        if hand_conf < self.pointing_confidence_min or scenario == "no_hand":
            return []
        if scenario == "pointing_blue":
            return [{"object_id": "object_blue_1", "confidence": 0.86}]
        if scenario == "two_close":
            return [
                {"object_id": "object_blue_1", "confidence": 0.61},
                {"object_id": "object_red_1", "confidence": 0.58},
            ]
        return []

    def _head(self, scenario: str, objects: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if scenario == "pointing_blue":
            return [{"object_id": "object_blue_1", "confidence": 0.34}]
        if objects:
            return [{"object_id": objects[0]["object_id"], "confidence": 0.22}]
        return []

    def _device_status(self, status: str, detail: str) -> EventEnvelope:
        return make_event(
            event_type="device.status",
            sequence=self._next_seq(),
            payload={
                "status": status,
                "device_alias": "vision-mock",
                "detail": detail,
                "metadata": {"detector": "marker_mock"},
            },
        )

    def _next_seq(self) -> int:
        value = self.sequence
        self.sequence += 1
        return value
