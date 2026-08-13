"""In-process console gateway: health, sessions, live snapshot, and event I/O."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import shutil
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

from intent_contracts.control import ControlRequest, ControlResponse, PreflightResult
from intent_contracts.enums import (
    PRODUCER_VERSION,
    SCHEMA_VERSION,
    Action,
    ControlMethod,
    DeviceHealth,
    EventType,
    SessionState,
)
from intent_contracts.envelope import EventEnvelope, new_event_id, now_monotonic_ns, now_wall_ns
from intent_contracts.validation import parse_unnormalized_event
from intent_runtime.config import load_stacked_config
from intent_runtime.zmq_bus import AdapterPush, NormalizedSubscriber

from console_api.calibrate import EmgCalibrationStub
from console_api.catalog import SERVICE_CATALOG, resolve_service_id
from console_api.control_plane import ControlPlane, ControlTransport
from console_api.demo import load_scenario_spec, materialize_demo_events
from console_api.device_setup import DOC_FILES, public_setup

LOGGER = logging.getLogger("console_api")

SECRET_KEY_PARTS = ("password", "token", "secret", "credential", "email", "api_key", "auth")
SEMANTIC_EVENT_TYPES = {
    EventType.MODALITY_FEATURE,
    EventType.VISION_OBJECTS,
    EventType.VISION_HANDS,
    EventType.VISION_HEAD_DIRECTION,
    EventType.AUDIO_INTENT_CANDIDATE,
    EventType.INTENT_CANDIDATE_SET,
    EventType.INTENT_DECISION,
    EventType.INTENT_CONFLICT,
    EventType.INTENT_TIMEOUT,
    EventType.SAFETY_DECISION,
    EventType.MACHINE_STATE,
    EventType.ACTION_OUTCOME,
    EventType.DEVICE_STATUS,
    EventType.DATA_QUALITY,
    EventType.SESSION_STARTED,
    EventType.SESSION_STOPPED,
    EventType.SESSION_FAILED,
    EventType.TRIAL_STARTED,
    EventType.TRIAL_INSTRUCTION,
    EventType.TRIAL_LABEL,
    EventType.TRIAL_COMPLETED,
    EventType.TRIAL_ABORTED,
}
PLOT_HZ = 12.0
PLOT_HISTORY = 150
CLIENT_QUEUE_MAX = 128
TIMELINE_MAX = 40
MIN_FREE_GB = 1.0


def find_repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "configs" / "local.yaml").exists():
            return parent
    return Path.cwd()


def _strip_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(part in lowered for part in SECRET_KEY_PARTS):
                continue
            cleaned[key] = _strip_secrets(item)
        return cleaned
    if isinstance(value, list):
        return [_strip_secrets(item) for item in value]
    return value


class ConsoleRuntime:
    def __init__(
        self,
        *,
        mock: bool = False,
        control_transport: ControlTransport | None = None,
        config_dir: Path | None = None,
        event_push: AdapterPush | Any | None = None,
    ) -> None:
        self.mock = mock
        self.root = find_repo_root()
        self.config = load_stacked_config(config_dir or self.root / "configs")
        self._injected_push = event_push
        runtime_cfg = self.config.get("runtime", {})
        ports = runtime_cfg.get("ports", {})
        self.heartbeat_seconds = float(runtime_cfg.get("heartbeat_seconds", 2))
        self.degraded_missed = int(runtime_cfg.get("degraded_missed_heartbeats", 2))
        self.offline_missed = int(runtime_cfg.get("offline_missed_heartbeats", 5))
        self.push_endpoint = str(ports.get("adapter_push", "tcp://127.0.0.1:5555"))
        self.sub_endpoint = str(ports.get("normalized_pub", "tcp://127.0.0.1:5556"))
        self.control_endpoint = str(ports.get("control_rep", "tcp://127.0.0.1:5558"))
        self.machine_mode = str(runtime_cfg.get("machine_mode", "simulator_only"))

        self.control = ControlPlane(
            self.control_endpoint,
            mock=mock,
            transport=control_transport,
        )
        self._push: AdapterPush | None = None
        self._started = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._clients: list[asyncio.Queue[dict[str, Any]]] = []
        self._clients_lock = threading.Lock()
        self._seq = 0
        self._seen_event_ids: deque[str] = deque(maxlen=4096)
        self._seen_set: set[str] = set()
        self._lock = threading.RLock()

        now = time.monotonic()
        self._services: dict[str, dict[str, Any]] = {}
        for item in SERVICE_CATALOG:
            self._services[item["id"]] = {
                "id": item["id"],
                "name": item["name"],
                "required": item["required"],
                "status": DeviceHealth.HEALTHY if mock else DeviceHealth.OFFLINE,
                "last_seen_mono": now if mock else None,
                "seen_real": False,
                "uptime_seconds": 0.0,
                "error_count": 0,
                "last_data_age_ms": None,
                "source": "mock" if mock else None,
            }

        self.sessions: dict[str, dict[str, Any]] = {}
        self.active_session_id: str | None = None
        self.active_trial_id: str | None = None
        self.estop_latched = False
        self.vision: dict[str, Any] | None = None
        self.audio: dict[str, Any] | None = None
        self.intent: dict[str, Any] | None = None
        self.safety: dict[str, Any] | None = None
        self.machine: dict[str, Any] | None = None
        self.confirmation: dict[str, Any] | None = None
        self.timeline: deque[dict[str, Any]] = deque(maxlen=TIMELINE_MAX)
        self.eeg = self._empty_plot(["C3", "C4", "Cz", "F3", "F4", "P3", "P4", "Oz"])
        self.emg = self._empty_plot(["emg_flexor", "emg_extensor", "emg_pronator", "emg_aux"])
        self._last_plot_emit = 0.0
        self._mock_t = 0.0
        self.emg_calibration = EmgCalibrationStub()
        self.vision_calibration_complete = False
        self.eeg_calibration_acknowledged = False

    @staticmethod
    def _empty_plot(channels: list[str]) -> dict[str, Any]:
        return {
            "channel_names": channels,
            "samples": {name: deque(maxlen=PLOT_HISTORY) for name in channels},
            "t_ms": deque(maxlen=PLOT_HISTORY),
        }

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def start(self) -> None:
        if self._started:
            return
        if self._injected_push is not None:
            self._push = self._injected_push
        else:
            try:
                self._push = AdapterPush(self.push_endpoint)
            except Exception:
                LOGGER.warning("adapter push unavailable", exc_info=True)
                self._push = None
        self._stop.clear()
        self._thread = threading.Thread(target=self._run_bus, name="console-api-bus", daemon=True)
        self._thread.start()
        self._started = True

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None
        if self._push is not None and self._injected_push is None:
            self._push.close()
            self._push = None
        elif self._injected_push is not None:
            self._push = None
        self.control.close()
        self._started = False

    def add_client(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        with self._clients_lock:
            self._clients.append(queue)

    def remove_client(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        with self._clients_lock:
            if queue in self._clients:
                self._clients.remove(queue)

    def _broadcast(self, message: dict[str, Any]) -> None:
        loop = self._loop
        if loop is None:
            return
        with self._clients_lock:
            clients = list(self._clients)
        for queue in clients:
            loop.call_soon_threadsafe(self._enqueue, queue, message)

    @staticmethod
    def _enqueue(queue: asyncio.Queue[dict[str, Any]], message: dict[str, Any]) -> None:
        if queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        try:
            queue.put_nowait(message)
        except asyncio.QueueFull:
            pass

    def _run_bus(self) -> None:
        subscriber: NormalizedSubscriber | None = None
        try:
            subscriber = NormalizedSubscriber(self.sub_endpoint)
        except Exception:
            LOGGER.warning("normalized subscriber unavailable", exc_info=True)
        while not self._stop.is_set():
            event = None
            if subscriber is not None:
                try:
                    event = subscriber.recv_event(timeout_ms=50)
                except Exception:
                    event = None
            if event:
                self.ingest_event(event, from_bus=True)
            now = time.monotonic()
            if self.mock:
                self._tick_mock(now)
            if now - self._last_plot_emit >= 1.0 / PLOT_HZ:
                self._last_plot_emit = now
                self._emit_plots()
            time.sleep(0.005)
        if subscriber is not None:
            subscriber.close()

    def _tick_mock(self, now: float) -> None:
        with self._lock:
            for service in self._services.values():
                if not service["seen_real"]:
                    service["last_seen_mono"] = now
                    service["status"] = DeviceHealth.HEALTHY
                    service["uptime_seconds"] = float(service.get("uptime_seconds", 0.0)) + 0.05
            self._mock_t += 0.05
            t_ms = int(now * 1000)
            for index, name in enumerate(self.eeg["channel_names"]):
                sample = math.sin(self._mock_t * 2.0 + index) * 12.0
                self.eeg["samples"][name].append(sample)
            self.eeg["t_ms"].append(t_ms)
            for index, name in enumerate(self.emg["channel_names"]):
                sample = abs(math.sin(self._mock_t * 4.0 + index)) * 40.0
                self.emg["samples"][name].append(sample)
            self.emg["t_ms"].append(t_ms)

    def _emit_plots(self) -> None:
        self._broadcast({"type": "plot", "payload": self._plot_payload("eeg", self.eeg)})
        self._broadcast({"type": "plot", "payload": self._plot_payload("emg", self.emg)})

    @staticmethod
    def _plot_payload(stream: str, plot: dict[str, Any]) -> dict[str, Any]:
        latest = {}
        for name, values in plot["samples"].items():
            latest[name] = list(values)[-8:]
        t_ms = list(plot["t_ms"])[-8:]
        return {
            "stream": stream,
            "channel_names": plot["channel_names"],
            "samples": latest,
            "t_ms": t_ms,
        }

    def ingest_event(self, raw: dict[str, Any], *, from_bus: bool = False) -> None:
        event_id = str(raw.get("event_id") or "")
        with self._lock:
            if event_id and event_id in self._seen_set:
                return
            if event_id:
                if len(self._seen_event_ids) == self._seen_event_ids.maxlen:
                    old = self._seen_event_ids[0]
                    self._seen_set.discard(old)
                self._seen_event_ids.append(event_id)
                self._seen_set.add(event_id)
            self._apply_event(raw, from_bus=from_bus)
        event_type = str(raw.get("event_type", ""))
        skipped = {
            EventType.BIOSIGNAL_CHUNK,
            EventType.MOTION_CHUNK,
            EventType.SERVICE_HEARTBEAT,
        }
        if event_type in skipped:
            return
        if event_type in SEMANTIC_EVENT_TYPES or event_type in {
            item.value for item in SEMANTIC_EVENT_TYPES
        }:
            slim = dict(raw)
            if event_type == EventType.BIOSIGNAL_CHUNK:
                return
            self._broadcast({"type": "event", "payload": slim})

    def _apply_event(self, raw: dict[str, Any], *, from_bus: bool) -> None:
        event_type = str(raw.get("event_type", ""))
        source = str(raw.get("source", ""))
        payload = raw.get("payload") if isinstance(raw.get("payload"), dict) else {}
        session_id = raw.get("session_id")
        trial_id = raw.get("trial_id")
        if session_id:
            if self._is_active_state(session_id):
                self.active_session_id = session_id
            self._ensure_session(str(session_id))
        if trial_id:
            self.active_trial_id = str(trial_id)

        if event_type == EventType.SERVICE_HEARTBEAT:
            self._apply_heartbeat(source, payload, from_bus=from_bus)
            return
        if event_type == EventType.DEVICE_STATUS:
            self._apply_device_status(source, payload, from_bus=from_bus)
            return
        if event_type == EventType.BIOSIGNAL_CHUNK:
            self._apply_biosignal(raw, payload)
            return
        if event_type == EventType.VISION_OBJECTS:
            self.vision = payload
            return
        if event_type == EventType.AUDIO_INTENT_CANDIDATE:
            self.audio = payload
            return
        if event_type == EventType.INTENT_DECISION:
            self.intent = payload
            if session_id:
                self._update_trial(str(session_id), trial_id, prediction=payload)
            return
        if event_type == EventType.SAFETY_DECISION:
            self.safety = payload
            verdict = str(payload.get("verdict", ""))
            if verdict == "EMERGENCY_STOP":
                self.estop_latched = True
            confirmation_id = payload.get("confirmation_id")
            if verdict == "ASK_CONFIRMATION" and confirmation_id:
                intent = self.intent or {}
                timeout_ms = int(self.config.get("safety", {}).get("confirmation_timeout_ms", 4000))
                self.confirmation = {
                    "confirmation_id": confirmation_id,
                    "decision_id": payload.get("decision_id"),
                    "action": intent.get("action"),
                    "target_object_id": intent.get("target_object_id"),
                    "reason_codes": payload.get("reason_codes", []),
                    "expires_at_ms": int(time.time() * 1000) + timeout_ms,
                    "why": self._confirmation_why(payload.get("reason_codes", [])),
                }
            elif verdict != "ASK_CONFIRMATION":
                self.confirmation = None
            if session_id:
                self._update_trial(str(session_id), trial_id, safety=payload)
            self._push_timeline("safety", verdict, payload)
            return
        if event_type == EventType.MACHINE_STATE:
            self.machine = payload
            if str(payload.get("state")) == "ESTOPPED":
                self.estop_latched = True
            self._push_timeline("machine", str(payload.get("state")), payload)
            return
        if event_type == EventType.ACTION_OUTCOME:
            if session_id:
                self._update_trial(str(session_id), trial_id, outcome=payload)
            self._push_timeline("outcome", str(payload.get("outcome")), payload)
            return
        if event_type == EventType.SESSION_STARTED:
            if session_id:
                record = self._ensure_session(str(session_id))
                record["state"] = SessionState.RECORDING
                self.active_session_id = str(session_id)
            return
        if event_type in {EventType.SESSION_STOPPED, EventType.SESSION_FAILED}:
            if session_id and session_id in self.sessions:
                failed = event_type == EventType.SESSION_FAILED
                self.sessions[str(session_id)]["state"] = (
                    SessionState.FAILED if failed else SessionState.FINALIZED
                )
            if self.active_session_id == session_id:
                self.active_session_id = None
                self.active_trial_id = None
            return
        if event_type == EventType.TRIAL_STARTED and session_id:
            self._upsert_trial(str(session_id), str(trial_id or ""), payload, state="STARTED")
            return
        if event_type == EventType.TRIAL_LABEL and session_id:
            self._update_trial(str(session_id), trial_id, label=payload)
            return
        if event_type in {EventType.TRIAL_COMPLETED, EventType.TRIAL_ABORTED} and session_id:
            state = "COMPLETED" if event_type == EventType.TRIAL_COMPLETED else "ABORTED"
            self._update_trial(str(session_id), trial_id, extra={"state": state})

    def _is_active_state(self, session_id: str) -> bool:
        record = self.sessions.get(session_id)
        if record is None:
            return True
        return record.get("state") in {
            SessionState.RECORDING,
            SessionState.READY,
            SessionState.PREFLIGHT,
            "RECORDING",
            "READY",
        }

    def _apply_heartbeat(self, source: str, payload: dict[str, Any], *, from_bus: bool) -> None:
        service_id = resolve_service_id(source)
        if service_id is None:
            return
        service = self._services[service_id]
        service["last_seen_mono"] = time.monotonic()
        service["seen_real"] = bool(from_bus)
        service["source"] = source
        service["uptime_seconds"] = payload.get("uptime_seconds", service.get("uptime_seconds"))
        service["error_count"] = payload.get("error_count", 0)
        service["last_data_age_ms"] = payload.get("last_data_age_ms")
        reported = str(payload.get("status") or DeviceHealth.HEALTHY)
        service["reported_status"] = reported

    def _apply_device_status(self, source: str, payload: dict[str, Any], *, from_bus: bool) -> None:
        alias = str(payload.get("device_alias", ""))
        service_id = resolve_service_id(source) or resolve_service_id(alias)
        if service_id is None:
            return
        service = self._services[service_id]
        service["last_seen_mono"] = time.monotonic()
        service["seen_real"] = service["seen_real"] or from_bus
        service["detail"] = payload.get("detail")
        service["reported_status"] = str(payload.get("status") or DeviceHealth.HEALTHY)

    def _apply_biosignal(self, raw: dict[str, Any], payload: dict[str, Any]) -> None:
        modality = str(raw.get("modality") or "")
        source = str(raw.get("source") or "")
        names = payload.get("channel_names") or []
        samples = payload.get("samples") or []
        target = None
        if modality == "eeg" or "crown" in source:
            target = self.eeg
        elif modality == "emg" or "ganglion" in source:
            target = self.emg
        if target is None or not samples:
            return
        t_ms = int(time.monotonic() * 1000)
        if names:
            target["channel_names"] = list(names)
            for name in names:
                target["samples"].setdefault(name, deque(maxlen=PLOT_HISTORY))
        # channel-major: samples[channel][sample]; downsample to last value per channel
        for index, channel_samples in enumerate(samples):
            if index >= len(target["channel_names"]):
                break
            name = target["channel_names"][index]
            if not channel_samples:
                continue
            step = max(1, len(channel_samples) // 4)
            if step == 1:
                value = float(channel_samples[-1])
            else:
                reduced = channel_samples[::step]
                value = float(sum(reduced) / max(1, len(reduced)))
            target["samples"].setdefault(name, deque(maxlen=PLOT_HISTORY)).append(value)
        target["t_ms"].append(t_ms)

    def _push_timeline(self, kind: str, label: str, payload: dict[str, Any]) -> None:
        self.timeline.appendleft(
            {
                "t_ms": int(time.time() * 1000),
                "kind": kind,
                "label": label,
                "detail": payload,
            }
        )

    def _ensure_session(self, session_id: str) -> dict[str, Any]:
        if session_id not in self.sessions:
            self.sessions[session_id] = {
                "session_id": session_id,
                "state": SessionState.RECORDING,
                "user_id": "primary",
                "record_audio": False,
                "record_video": False,
                "consent": True,
                "started_at_ms": int(time.time() * 1000),
                "stopped_at_ms": None,
                "trials": [],
            }
        return self.sessions[session_id]

    def _upsert_trial(
        self,
        session_id: str,
        trial_id: str,
        payload: dict[str, Any],
        *,
        state: str,
    ) -> dict[str, Any]:
        record = self._ensure_session(session_id)
        for trial in record["trials"]:
            if trial.get("trial_id") == trial_id:
                trial.update(payload)
                trial["state"] = state
                return trial
        trial = {
            "trial_id": trial_id,
            "instruction": payload.get("instruction"),
            "ground_truth_action": payload.get("ground_truth_action"),
            "ground_truth_target": payload.get("ground_truth_target"),
            "ambiguous": payload.get("ambiguous", False),
            "state": state,
        }
        record["trials"].append(trial)
        return trial

    def _update_trial(
        self,
        session_id: str,
        trial_id: str | None,
        *,
        prediction: dict[str, Any] | None = None,
        safety: dict[str, Any] | None = None,
        outcome: dict[str, Any] | None = None,
        label: dict[str, Any] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        record = self._ensure_session(session_id)
        trial = None
        if trial_id:
            for item in record["trials"]:
                if item.get("trial_id") == trial_id:
                    trial = item
                    break
        if trial is None and record["trials"]:
            trial = record["trials"][-1]
        if trial is None:
            return
        if prediction:
            trial["prediction_action"] = prediction.get("action")
            trial["prediction_target"] = prediction.get("target_object_id")
            trial["prediction_confidence"] = prediction.get("confidence")
        if safety:
            trial["verdict"] = safety.get("verdict")
            trial["reason_codes"] = safety.get("reason_codes")
        if outcome:
            trial["outcome"] = outcome.get("outcome")
            trial["user_correction"] = outcome.get("user_correction")
        if label:
            trial.update({k: v for k, v in label.items() if v is not None})
        if extra:
            trial.update(extra)

    @staticmethod
    def _confirmation_why(reason_codes: list[Any]) -> str:
        if not reason_codes:
            return "Safety policy requested an explicit confirmation before any machine action."
        return "Confirmation required: " + ", ".join(str(code) for code in reason_codes)

    def service_views(self) -> list[dict[str, Any]]:
        now = time.monotonic()
        views = []
        for item in SERVICE_CATALOG:
            service = self._services[item["id"]]
            last_seen = service.get("last_seen_mono")
            age_ms = None if last_seen is None else (now - last_seen) * 1000.0
            missed = 0 if last_seen is None else int(age_ms / (self.heartbeat_seconds * 1000.0))
            computed = DeviceHealth.HEALTHY
            if last_seen is None or missed >= self.offline_missed:
                computed = DeviceHealth.OFFLINE
            elif missed >= self.degraded_missed:
                computed = DeviceHealth.DEGRADED
            reported = str(service.get("reported_status") or computed)
            rank = {DeviceHealth.HEALTHY: 0, DeviceHealth.DEGRADED: 1, DeviceHealth.OFFLINE: 2}
            status = computed if rank.get(computed, 0) >= rank.get(reported, 0) else reported
            views.append(
                {
                    "id": item["id"],
                    "name": item["name"],
                    "required": item["required"],
                    "status": status,
                    "last_heartbeat_age_ms": None if age_ms is None else round(age_ms, 1),
                    "missed_heartbeats": missed if last_seen is not None else self.offline_missed,
                    "uptime_seconds": service.get("uptime_seconds"),
                    "error_count": service.get("error_count", 0),
                    "last_data_age_ms": service.get("last_data_age_ms"),
                    "recovery": item["recovery"],
                }
            )
        return views

    def public_config(self) -> dict[str, Any]:
        runtime_cfg = self.config.get("runtime", {})
        ports = runtime_cfg.get("ports", {})
        devices = _strip_secrets(self.config.get("devices", {}))
        safety = _strip_secrets(self.config.get("safety", {}))
        fusion = _strip_secrets(self.config.get("fusion", {}))
        storage = _strip_secrets(self.config.get("storage", {}))
        return {
            "schema_version": runtime_cfg.get("schema_version", SCHEMA_VERSION),
            "producer_version": runtime_cfg.get("producer_version", PRODUCER_VERSION),
            "machine_mode": self.machine_mode,
            "mock": self.mock,
            "heartbeat_seconds": self.heartbeat_seconds,
            "degraded_missed_heartbeats": self.degraded_missed,
            "offline_missed_heartbeats": self.offline_missed,
            "ports": {
                "console_api": ports.get("console_api", 8000),
                "developer_console": ports.get("developer_console", 3000),
            },
            "devices": devices,
            "safety": safety,
            "fusion": {
                "model_id": fusion.get("model_id"),
                "eeg_shadow_only": fusion.get("eeg_shadow_only", True),
            },
            "storage": {
                "record_audio": storage.get("record_audio", False),
                "record_video": storage.get("record_video", False),
            },
        }

    def preflight(self) -> PreflightResult:
        checks: list[dict[str, Any]] = []
        for view in self.service_views():
            age = view["last_heartbeat_age_ms"]
            if view["status"] == DeviceHealth.HEALTHY:
                age_s = 0 if age is None else round(age / 1000.0, 2)
                message = f"Online. Last heartbeat {age_s}s ago."
                recovery = None
            elif view["status"] == DeviceHealth.DEGRADED:
                message = f"Degraded after missed heartbeats ({view['missed_heartbeats']})."
                recovery = view["recovery"]
            else:
                message = "Offline or never seen."
                recovery = view["recovery"]
            if view["id"] == "crown-adapter":
                message += " EEG is shadow-only and does not drive actions."
            if view["id"] == "ganglion-adapter" and view["status"] == DeviceHealth.HEALTHY:
                message = "Connected; four EMG channels expected. " + message
            if view["id"] == "robot-simulator":
                message += f" Machine mode: {self.machine_mode}."
            checks.append(
                {
                    "id": view["id"],
                    "name": view["name"],
                    "required": view["required"],
                    "status": view["status"],
                    "last_event_age_ms": age,
                    "message": message,
                    "recovery": recovery,
                }
            )
        storage_check = self._recorder_storage_check()
        checks.append(storage_check)
        ready = all(
            check["status"] in {DeviceHealth.HEALTHY, "healthy"}
            for check in checks
            if check.get("required")
        )
        return PreflightResult(ready=ready, checks=checks)

    def _recorder_storage_check(self) -> dict[str, Any]:
        storage_cfg = self.config.get("storage", {})
        sessions_dir = self.root / str(storage_cfg.get("sessions_dir", "data/sessions"))
        try:
            sessions_dir.mkdir(parents=True, exist_ok=True)
            usage = shutil.disk_usage(sessions_dir)
            free_gb = usage.free / (1024**3)
            ok = free_gb >= MIN_FREE_GB
            return {
                "id": "recorder-storage",
                "name": "Recorder storage",
                "required": True,
                "status": DeviceHealth.HEALTHY if ok else DeviceHealth.DEGRADED,
                "last_event_age_ms": 0,
                "message": f"{free_gb:.1f} GiB free at {sessions_dir}.",
                "recovery": None
                if ok
                else "Free disk space under data/sessions before starting a recorded session.",
            }
        except OSError as exc:
            return {
                "id": "recorder-storage",
                "name": "Recorder storage",
                "required": True,
                "status": DeviceHealth.OFFLINE,
                "last_event_age_ms": None,
                "message": f"Storage check failed: {exc}",
                "recovery": "Create a writable data/sessions directory.",
            }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            session = self.sessions.get(self.active_session_id) if self.active_session_id else None
            return {
                "mock": self.mock,
                "machine_mode": self.machine_mode,
                "estop_latched": self.estop_latched,
                "session": self._public_session(session) if session else None,
                "active_trial_id": self.active_trial_id,
                "services": self.service_views(),
                "vision": self.vision,
                "audio": self.audio,
                "intent": self.intent,
                "safety": self.safety,
                "machine": self.machine,
                "confirmation": self.confirmation,
                "timeline": list(self.timeline),
                "eeg": self._plot_snapshot(self.eeg),
                "emg": self._plot_snapshot(self.emg),
                "server_time_ms": int(time.time() * 1000),
            }

    @staticmethod
    def _plot_snapshot(plot: dict[str, Any]) -> dict[str, Any]:
        return {
            "channel_names": plot["channel_names"],
            "samples": {name: list(values) for name, values in plot["samples"].items()},
            "t_ms": list(plot["t_ms"]),
        }

    @staticmethod
    def _public_session(session: dict[str, Any] | None) -> dict[str, Any] | None:
        if session is None:
            return None
        return {
            "session_id": session["session_id"],
            "state": session.get("state"),
            "user_id": session.get("user_id"),
            "record_audio": session.get("record_audio", False),
            "record_video": session.get("record_video", False),
            "consent": session.get("consent", True),
            "started_at_ms": session.get("started_at_ms"),
            "stopped_at_ms": session.get("stopped_at_ms"),
            "trials": list(session.get("trials", [])),
        }

    def list_sessions(self) -> list[dict[str, Any]]:
        with self._lock:
            return [self._public_session(item) for item in self.sessions.values() if item]

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._public_session(self.sessions.get(session_id))

    def start_session(self, payload: dict[str, Any]) -> ControlResponse:
        if not payload.get("consent", True):
            return ControlResponse(
                ok=False,
                request_id=new_event_id(),
                method=ControlMethod.SESSION_START,
                state=SessionState.NO_SESSION,
                error="consent is required to start a session",
            )
        response = self.control.request(ControlMethod.SESSION_START, payload=payload)
        if response.ok and response.session_id:
            with self._lock:
                record = self._ensure_session(response.session_id)
                record.update(
                    {
                        "state": response.state,
                        "user_id": payload.get("user_id", "primary"),
                        "record_audio": payload.get("record_audio", False),
                        "record_video": payload.get("record_video", False),
                        "consent": True,
                        "started_at_ms": int(time.time() * 1000),
                    }
                )
                self.active_session_id = response.session_id
            self._publish_lifecycle(
                EventType.SESSION_STARTED,
                response.session_id,
                None,
                {"state": str(response.state), "contract_version": SCHEMA_VERSION},
            )
        return response

    def stop_session(self, session_id: str) -> ControlResponse:
        response = self.control.request(ControlMethod.SESSION_STOP, session_id=session_id)
        if response.ok:
            with self._lock:
                if session_id in self.sessions:
                    self.sessions[session_id]["state"] = response.state
                    self.sessions[session_id]["stopped_at_ms"] = int(time.time() * 1000)
                if self.active_session_id == session_id:
                    self.active_session_id = None
                    self.active_trial_id = None
                    self.confirmation = None
            self._publish_lifecycle(
                EventType.SESSION_STOPPED,
                session_id,
                None,
                {"state": str(response.state)},
            )
        return response

    def start_trial(self, session_id: str, payload: dict[str, Any]) -> ControlResponse:
        response = self.control.request(
            ControlMethod.TRIAL_START,
            session_id=session_id,
            payload=payload,
        )
        if response.ok and response.trial_id:
            with self._lock:
                self.active_trial_id = response.trial_id
                self._upsert_trial(session_id, response.trial_id, payload, state="STARTED")
            self._publish_lifecycle(EventType.TRIAL_STARTED, session_id, response.trial_id, payload)
        return response

    def label_trial(self, trial_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        session_id = self._session_for_trial(trial_id) or self.active_session_id
        if session_id:
            with self._lock:
                self._update_trial(session_id, trial_id, label=payload)
        event = self._make_event(
            EventType.TRIAL_LABEL,
            payload,
            session_id=session_id,
            trial_id=trial_id,
        )
        self.publish_event(event)
        return {"ok": True, "trial_id": trial_id, "session_id": session_id}

    def _session_for_trial(self, trial_id: str) -> str | None:
        for session in self.sessions.values():
            for trial in session.get("trials", []):
                if trial.get("trial_id") == trial_id:
                    return session["session_id"]
        return None

    def confirm(self, confirmation_id: str) -> dict[str, Any]:
        return self._emit_ui_feature(
            confirmation_id,
            label="confirm",
            feature_name="ui_confirmation",
        )

    def cancel_confirmation(self, confirmation_id: str) -> dict[str, Any]:
        result = self._emit_ui_feature(
            confirmation_id,
            label="cancel",
            feature_name="ui_confirmation",
        )
        with self._lock:
            self.confirmation = None
        return result

    def estop(self) -> dict[str, Any]:
        with self._lock:
            self.estop_latched = True
            session_id = self.active_session_id
            trial_id = self.active_trial_id
        now = now_monotonic_ns()
        feature = self._make_event(
            EventType.MODALITY_FEATURE,
            {
                "feature_name": "ui_estop",
                "window_start_ns": now,
                "window_end_ns": now,
                "label": "stop",
                "confidence": 1.0,
                "candidate_scores": {"stop": 1.0},
                "model_id": "console-api",
                "shadow_only": False,
            },
            modality="ui",
            session_id=session_id,
            trial_id=trial_id,
        )
        stop_intent = self._make_event(
            EventType.AUDIO_INTENT_CANDIDATE,
            {
                "transcript": "emergency stop",
                "is_final": True,
                "action": Action.STOP,
                "target_reference": "NONE",
                "target_object_id": None,
                "confidence": 1.0,
                "utterance_start_ns": now,
                "utterance_end_ns": now,
                "model_id": "console-api",
            },
            modality="ui",
            session_id=session_id,
            trial_id=trial_id,
        )
        self.publish_event(feature)
        self.publish_event(stop_intent)
        self._push_timeline("control", "EMERGENCY_STOP", {"source": "console-api"})
        return {"ok": True, "estop_latched": True}

    def reset_estop(self) -> dict[str, Any]:
        now = now_monotonic_ns()
        event = self._make_event(
            EventType.MODALITY_FEATURE,
            {
                "feature_name": "ui_control",
                "window_start_ns": now,
                "window_end_ns": now,
                "label": "reset_estop",
                "confidence": 1.0,
                "candidate_scores": {"reset_estop": 1.0},
                "model_id": "console-api",
                "shadow_only": False,
            },
            modality="ui",
            session_id=self.active_session_id,
            trial_id=self.active_trial_id,
        )
        self.publish_event(event)
        with self._lock:
            self.estop_latched = False
        self._push_timeline("control", "RESET_ESTOP", {"source": "console-api"})
        return {"ok": True, "estop_latched": False}

    def _emit_ui_feature(
        self, confirmation_id: str, *, label: str, feature_name: str
    ) -> dict[str, Any]:
        now = now_monotonic_ns()
        event = self._make_event(
            EventType.MODALITY_FEATURE,
            {
                "feature_name": feature_name,
                "window_start_ns": now,
                "window_end_ns": now,
                "label": label,
                "confidence": 1.0,
                "candidate_scores": {label: 1.0},
                "model_id": "console-api",
                "shadow_only": False,
                "confirmation_id": confirmation_id,
            },
            modality="ui",
            session_id=self.active_session_id,
            trial_id=self.active_trial_id,
        )
        self.publish_event(event)
        if label == "confirm":
            with self._lock:
                self.confirmation = None
        return {"ok": True, "confirmation_id": confirmation_id, "label": label}

    def replay(self, body: dict[str, Any]) -> dict[str, Any]:
        source = str(body.get("source") or "fixtures")
        if source != "fixtures":
            session_id = body.get("session_id")
            return {
                "ok": False,
                "error": "session replay is owned by the recorder; fixture replay is available now",
                "session_id": session_id,
            }
        storage_cfg = self.config.get("storage", {})
        fixtures_dir = self.root / str(storage_cfg.get("fixtures_dir", "data/fixtures"))
        events_dir = fixtures_dir / "events"
        loaded = 0
        if events_dir.exists():
            for path in sorted(events_dir.glob("*.json")):
                try:
                    raw = json.loads(path.read_text())
                except json.JSONDecodeError:
                    continue
                if "event_type" not in raw:
                    continue
                self.ingest_event(raw, from_bus=False)
                if self._push is not None:
                    try:
                        outgoing = {k: v for k, v in raw.items() if k != "normalized_time_ns"}
                        self._push.send_event(outgoing)
                    except Exception:
                        LOGGER.debug("fixture push skipped", exc_info=True)
                loaded += 1
        self._broadcast({"type": "snapshot", "payload": self.snapshot()})
        return {"ok": True, "events_queued": loaded, "source": "fixtures"}

    def _publish_lifecycle(
        self,
        event_type: EventType,
        session_id: str | None,
        trial_id: str | None,
        payload: dict[str, Any],
    ) -> None:
        event = self._make_event(event_type, payload, session_id=session_id, trial_id=trial_id)
        self.publish_event(event)

    def _make_event(
        self,
        event_type: EventType | str,
        payload: dict[str, Any],
        *,
        modality: str | None = None,
        session_id: str | None = None,
        trial_id: str | None = None,
    ) -> EventEnvelope:
        self._seq += 1
        return EventEnvelope(
            schema_version=SCHEMA_VERSION,
            event_id=new_event_id(),
            event_type=event_type,
            source="console-api",
            modality=modality,
            session_id=session_id,
            trial_id=trial_id,
            sequence=self._seq,
            source_time_ns=now_wall_ns(),
            received_monotonic_ns=now_monotonic_ns(),
            quality=1.0,
            producer_version=PRODUCER_VERSION,
            payload=payload,
        )

    def publish_event(self, event: EventEnvelope) -> None:
        if self._push is not None:
            try:
                self._push.send_event(event)
            except Exception:
                LOGGER.warning("failed to publish event to hub", exc_info=True)
        self.ingest_event(event.model_dump(mode="json"), from_bus=False)

    def last_control_request(self) -> ControlRequest | None:
        return self.control.last_request

    def setup_status(self) -> dict[str, Any]:
        return public_setup(self.root, self.config, mock=self.mock)

    def doc_path(self, slug: str) -> Path | None:
        relative = DOC_FILES.get(slug)
        if relative is None:
            return None
        path = self.root / relative
        return path if path.is_file() else None

    def run_demo(self, scenario: str) -> dict[str, Any]:
        spec = load_scenario_spec(self.root, scenario)
        with self._lock:
            session_id = self.active_session_id
            trial_id = self.active_trial_id
            sequence_start = self._seq + 1
        prepared = materialize_demo_events(
            spec,
            session_id=session_id,
            trial_id=trial_id,
            sequence_start=sequence_start,
        )
        started = time.monotonic()
        injected = 0
        for delay_ms, event in prepared:
            wait_s = (delay_ms / 1000.0) - (time.monotonic() - started)
            if wait_s > 0:
                time.sleep(wait_s)
            self._inject_unnormalized(event)
            injected += 1
        with self._lock:
            self._seq = sequence_start + injected - 1
        self._broadcast({"type": "snapshot", "payload": self.snapshot()})
        return {
            "ok": True,
            "scenario": scenario,
            "events_injected": injected,
            "pushed": self._push is not None,
            "mock": self.mock,
        }

    def _inject_unnormalized(self, event: dict[str, Any]) -> None:
        outgoing = {k: v for k, v in event.items() if k != "normalized_time_ns"}
        parse_unnormalized_event(outgoing)
        pushed = False
        if self._push is not None:
            try:
                self._push.send_event(outgoing)
                pushed = True
            except Exception:
                LOGGER.warning("demo push to hub failed", exc_info=True)
        if self.mock or not pushed:
            self.ingest_event(outgoing, from_bus=False)

    def calibrate_emg_status(self) -> dict[str, Any]:
        return self.emg_calibration.status()

    def calibrate_emg_start(self) -> dict[str, Any]:
        status = self.emg_calibration.start()
        self._emit_calibration_instruction(status["instruction"])
        return status

    def calibrate_emg_next(self) -> dict[str, Any]:
        status = self.emg_calibration.next_phase()
        self._emit_calibration_instruction(status["instruction"])
        return status

    def calibrate_emg_record(self) -> dict[str, Any]:
        return self.emg_calibration.record()

    def _emit_calibration_instruction(self, instruction: str) -> None:
        event = self._make_event(
            EventType.TRIAL_INSTRUCTION,
            {
                "instruction": instruction,
                "notes": "emg_calibration",
                "ambiguous": False,
            },
            session_id=self.active_session_id,
            trial_id=self.active_trial_id,
        )
        self.publish_event(event)

    def complete_vision_calibration(self) -> dict[str, Any]:
        self.vision_calibration_complete = True
        return {
            "ok": True,
            "protocol": "vision",
            "complete": True,
            "camera_index": self.config.get("devices", {}).get("vision", {}).get("camera_index"),
            "object_ids": [
                "object_blue_1",
                "object_red_1",
                "object_green_1",
                "object_yellow_1",
            ],
        }

    def acknowledge_eeg_calibration(self) -> dict[str, Any]:
        self.eeg_calibration_acknowledged = True
        return {
            "ok": True,
            "protocol": "eeg",
            "acknowledged": True,
            "shadow_only": True,
            "drives_action": False,
        }
