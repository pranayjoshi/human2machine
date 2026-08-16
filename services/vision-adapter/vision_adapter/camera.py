from __future__ import annotations

import threading
import time
from typing import Any

import numpy as np
from intent_contracts.envelope import EventEnvelope, now_monotonic_ns
from intent_runtime.heartbeat import heartbeat_event as runtime_heartbeat
from numpy.typing import NDArray

from vision_adapter.calibration import CalibrationMismatchError, CameraCalibration
from vision_adapter.color_detector import (
    DEFAULT_CATALOG,
    detect_colored_objects,
    maybe_create_hands,
    try_mediapipe_pointing,
)
from vision_adapter.mock import FreezeDetector, make_event
from vision_adapter.tracker import DEFAULT_OBJECT_STALE_MS, ObjectTracker, stale_ms_from_config

SOURCE = "vision-adapter"


class LatestFrameCamera:
    """Dedicated capture thread; keeps only the newest frame."""

    def __init__(
        self,
        camera_index: int = 0,
        width: int = 1280,
        height: int = 720,
        fps: int = 30,
        capture_factory: Any | None = None,
    ) -> None:
        self.camera_index = camera_index
        self.width = width
        self.height = height
        self.fps = fps
        self._capture_factory = capture_factory
        self._lock = threading.Lock()
        self._frame: NDArray[np.uint8] | None = None
        self._source_time_ns: int | None = None
        self._received_ns: int | None = None
        self._running = False
        self._thread: threading.Thread | None = None
        self._cap: Any | None = None

    def start(self) -> None:
        factory = self._capture_factory
        if factory is None:
            import cv2

            factory = cv2.VideoCapture
        self._cap = factory(self.camera_index)
        if hasattr(self._cap, "set"):
            try:
                import cv2

                self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
                self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
                self._cap.set(cv2.CAP_PROP_FPS, self.fps)
            except Exception:
                pass
        opened = bool(getattr(self._cap, "isOpened", lambda: True)())
        if not opened:
            raise RuntimeError(f"camera index {self.camera_index} failed to open")
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="vision-capture", daemon=True)
        self._thread.start()

    def latest(self) -> tuple[NDArray[np.uint8], int, int] | None:
        with self._lock:
            if self._frame is None or self._source_time_ns is None or self._received_ns is None:
                return None
            return self._frame, self._source_time_ns, self._received_ns

    def stop(self) -> None:
        self._running = False
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        self._thread = None
        cap = self._cap
        self._cap = None
        if cap is not None:
            release = getattr(cap, "release", None)
            if release is not None:
                try:
                    release()
                except Exception:
                    pass

    def _loop(self) -> None:
        assert self._cap is not None
        while self._running:
            try:
                ok, frame = self._cap.read()
            except Exception:
                time.sleep(0.01)
                continue
            received_ns = time.monotonic_ns()
            if not ok or frame is None:
                time.sleep(0.01)
                continue
            source_time_ns = time.time_ns()
            with self._lock:
                self._frame = frame
                self._source_time_ns = source_time_ns
                self._received_ns = received_ns


def list_cameras(max_index: int = 5) -> list[int]:
    try:
        import cv2
    except Exception:
        return []
    found: list[int] = []
    for index in range(max_index):
        cap = cv2.VideoCapture(index)
        try:
            if cap.isOpened():
                found.append(index)
        finally:
            cap.release()
    return found


def _apply_table_plane(
    objects: list[dict[str, Any]],
    calibration: CameraCalibration,
) -> list[dict[str, Any]]:
    if not calibration.homography:
        return objects
    homography = np.array(calibration.homography, dtype=float)
    updated: list[dict[str, Any]] = []
    for obj in objects:
        item = dict(obj)
        bbox = item.get("bbox_xyxy") or [0.0, 0.0, 0.0, 0.0]
        cx = (float(bbox[0]) + float(bbox[2])) / 2.0
        cy = (float(bbox[1]) + float(bbox[3])) / 2.0
        vec = homography @ np.array([cx, cy, 1.0], dtype=float)
        denom = float(vec[2]) if abs(float(vec[2])) > 1e-9 else 1.0
        item["table_position_xy"] = [float(vec[0] / denom), float(vec[1] / denom)]
        updated.append(item)
    return updated


class VisionHardwareRuntime:
    def __init__(
        self,
        camera: Any,
        *,
        catalog: list[dict[str, Any]] | None = None,
        pointing_confidence_min: float = 0.55,
        publish_hz: float = 12.0,
        hands: Any | None = ...,
        object_stale_ms: float | None = None,
        calibration: CameraCalibration | None = None,
        config: dict[str, Any] | None = None,
    ) -> None:
        self.camera = camera
        self.catalog = catalog or [dict(row) for row in DEFAULT_CATALOG]
        self.pointing_confidence_min = pointing_confidence_min
        self.publish_hz = publish_hz
        self.sequence = 0
        self.frame_id = 0
        self._started = False
        self._detector = FreezeDetector()
        self._last_frozen = False
        self._hands = maybe_create_hands() if hands is ... else hands
        stale_ms = (
            DEFAULT_OBJECT_STALE_MS
            if object_stale_ms is None
            else float(object_stale_ms)
        )
        if object_stale_ms is None and config is not None:
            stale_ms = stale_ms_from_config(config)
        self.object_stale_ms = stale_ms
        self.calibration = calibration
        self._tracker = ObjectTracker(stale_ms=stale_ms)

    def render_frame(self, monotonic_ns: int | None = None) -> list[EventEnvelope]:
        latest = self.camera.latest()
        mono = monotonic_ns if monotonic_ns is not None else now_monotonic_ns()
        events: list[EventEnvelope] = []
        if latest is None:
            if not self._started:
                events.append(self._device_status("degraded", "waiting for camera frame"))
                self._started = True
            return events
        frame, source_time_ns, _received_ns = latest
        frozen = self._detector.observe(source_time_ns, mono)
        self._last_frozen = frozen
        if self.calibration is not None:
            height, width = frame.shape[:2]
            if int(self.calibration.width) != int(width) or int(self.calibration.height) != int(
                height
            ):
                raise CalibrationMismatchError(
                    "calibration mismatch: stored "
                    f"camera_id={self.calibration.camera_id!r} "
                    f"{self.calibration.width}x{self.calibration.height}, "
                    f"frame {width}x{height}. "
                    "Refuse to load at a different resolution without an explicit transform."
                )
        objects = detect_colored_objects(frame, self.catalog)
        if self.calibration is not None:
            objects = _apply_table_plane(objects, self.calibration)
        objects = self._tracker.update(objects, source_time_ns)
        visible = [item for item in objects if not item.get("stale")]
        pointing: list[dict[str, Any]] = []
        hands_payload = {
            "handedness": None,
            "landmark_confidence": 0.0,
            "pointing": False,
            "table_intersection_xy": None,
        }
        if self._hands is not None:
            pointing, hands_payload = try_mediapipe_pointing(
                frame, visible, self.pointing_confidence_min, self._hands
            )
        quality = 0.35 if frozen else 0.96
        flags = ["camera_frozen"] if frozen else []
        if any(item.get("stale") for item in objects):
            flags.append("object_stale")
        if not self._started:
            status = "degraded" if frozen else "healthy"
            events.append(self._device_status(status, "camera capture started"))
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
                    "frame_id": self.frame_id,
                    "objects": objects,
                    "pointing_candidates": pointing,
                    "head_direction_candidates": [],
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
                    "frame_id": self.frame_id,
                    "handedness": hands_payload.get("handedness"),
                    "landmark_confidence": hands_payload.get("landmark_confidence", 0.0),
                    "pointing": bool(hands_payload.get("pointing")),
                    "table_intersection_xy": hands_payload.get("table_intersection_xy"),
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
                    "frame_id": self.frame_id,
                    "yaw_deg": None,
                    "pitch_deg": None,
                    "confidence": 0.0,
                    "candidates": [],
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
                        "hand_landmark_confidence": float(
                            hands_payload.get("landmark_confidence") or 0.0
                        ),
                        "calibration_available": 1.0 if self.calibration is not None else 0.0,
                        "stale_object_count": float(
                            sum(1 for item in objects if item.get("stale"))
                        ),
                    },
                    "flags": flags,
                },
            )
        )
        self.frame_id += 1
        return events

    def heartbeat(self, uptime_seconds: float, dropped: int) -> EventEnvelope:
        return runtime_heartbeat(
            SOURCE,
            uptime_seconds=uptime_seconds,
            last_data_age_ms=1200.0 if self._last_frozen else 40.0,
            error_count=dropped,
            sequence=self._next_seq(),
            status="degraded" if dropped or self._last_frozen else "healthy",
        )

    def shutdown(self) -> EventEnvelope:
        if self._hands is not None:
            close = getattr(self._hands, "close", None)
            if close is not None:
                try:
                    close()
                except Exception:
                    pass
        return self._device_status("offline", "adapter stopping")

    def _device_status(self, status: str, detail: str) -> EventEnvelope:
        return make_event(
            event_type="device.status",
            sequence=self._next_seq(),
            payload={
                "status": status,
                "device_alias": "vision-camera",
                "detail": detail,
                "metadata": {"detector": "hsv_color"},
            },
        )

    def _next_seq(self) -> int:
        value = self.sequence
        self.sequence += 1
        return value
