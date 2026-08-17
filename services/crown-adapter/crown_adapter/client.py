"""Neurosity Crown client matching MindExecute's neurosity_streamer.

MindExecute:
    NeurositySDK({"deviceId": device_id})
    login({email, password})
    brainwaves_raw(callback)

The published Python SDK also requires `device_id`, so both keys are set.
"""

from __future__ import annotations

import atexit
import os
import queue
import re
import signal
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


class CrownAuthError(RuntimeError):
    """Login or credential failure. Message must never include secrets."""


@dataclass(frozen=True)
class CrownEpoch:
    data: list[list[float]]
    channel_names: list[str]
    sampling_rate: float
    start_time_ms: float | None


@dataclass
class CrownAccel:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


class CrownClient:
    """Test seam. Hardware uses NeurosityPythonClient; tests inject a fake."""

    def login(self) -> None:
        raise NotImplementedError

    def start(
        self, on_epoch: Callable[[CrownEpoch], None], on_accel: Callable[[CrownAccel], None]
    ) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError

    def device_info(self) -> dict[str, Any]:
        return {}

    def headset_status(self) -> dict[str, Any]:
        return {}

    def poll_epoch(self) -> CrownEpoch | None:
        return None


def load_crown_credentials(env: dict[str, str] | None = None) -> tuple[str, str, str]:
    source = env if env is not None else os.environ
    email = str(source.get("NEUROSITY_EMAIL") or "").strip()
    password = str(source.get("NEUROSITY_PASSWORD") or "").strip()
    device_id = str(source.get("NEUROSITY_DEVICE_ID") or "").strip()
    if not email or not password:
        raise CrownAuthError("NEUROSITY_EMAIL and NEUROSITY_PASSWORD are required")
    if not device_id:
        raise CrownAuthError("NEUROSITY_DEVICE_ID is required")
    return email, password, device_id


def sdk_options(device_id: str) -> dict[str, str]:
    """MindExecute passes `deviceId`. The published Python SDK also reads `device_id`."""
    return {"deviceId": device_id, "device_id": device_id}


def log_progress(message: str) -> None:
    print(f"crown-adapter: {message}", flush=True)


def public_exception_text(exc: BaseException) -> str:
    parts = [type(exc).__name__]
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None) if response is not None else getattr(exc, "code", None)
    if status is not None:
        parts.append(f"HTTP {status}")
    url = ""
    if response is not None:
        url = str(getattr(response, "url", "") or "")
    if not url:
        url = str(getattr(exc, "url", "") or "")
    path = url.split("?")[0]
    if "/devices/" in path:
        tail = path.split("/devices/", 1)[-1].replace(".json", "")
        parts.append(f"/devices/{tail[:100]}")
    body = ""
    if response is not None:
        try:
            body = str(getattr(response, "text", "") or "")
        except Exception:
            body = ""
    compact = re.sub(r"\s+", " ", body).strip()
    compact = re.sub(r"[^\s]+@[^\s]+", "[redacted]", compact)
    if re.search(r"permission|denied", compact, re.I):
        parts.append("permission denied")
    elif compact:
        parts.append(compact[:80])
    if len(parts) > 1:
        return " ".join(parts)
    text = str(exc)
    text = re.sub(r"[^\s]+@[^\s]+", "[redacted]", text)
    text = re.sub(r"(?i)([?&](?:auth|token|idToken)=)[^&\s]+", r"\1[redacted]", text)
    text = re.sub(
        r"(?i)(token|password|passwd|idToken|refreshToken|secret|authorization|auth)[=: ]\S+",
        "[redacted]",
        text,
    )
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > 180:
        text = text[:177] + "..."
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


def looks_like_firebase_device_id(value: str) -> bool:
    text = value.strip()
    if len(text) < 20:
        return False
    if "crown-" in text.lower():
        return False
    return text.replace("_", "").replace("-", "").isalnum()


def pick_device_id(wanted: str, devices: list[dict[str, str]]) -> str:
    wanted_l = wanted.strip().lower()
    if not devices:
        raise CrownAuthError("no claimed Crown on this Neurosity account")
    ids = [str(item.get("deviceId") or "").strip() for item in devices]
    if wanted.strip() in ids:
        return wanted.strip()
    matches: list[str] = []
    for item in devices:
        nick = str(item.get("deviceNickname") or "").strip()
        device_id = str(item.get("deviceId") or "").strip()
        if wanted_l in {nick.lower(), device_id.lower()}:
            matches.append(device_id)
    unique = list(dict.fromkeys(matches))
    if len(unique) == 1:
        return unique[0]
    if len(devices) == 1:
        only = str(devices[0].get("deviceId") or "").strip()
        if only:
            return only
    raise CrownAuthError("could not match Crown nickname to a claimed device")


def latest_metric_packet(raw: Any) -> dict[str, Any] | None:
    if isinstance(raw, dict) and "data" in raw:
        return raw
    if not isinstance(raw, dict):
        return None
    candidates = [value for value in raw.values() if isinstance(value, dict) and "data" in value]
    if not candidates:
        return None

    def start_of(item: dict[str, Any]) -> float:
        info = item.get("info") if isinstance(item.get("info"), dict) else {}
        try:
            return float(info.get("startTime") or 0)
        except (TypeError, ValueError):
            return 0.0

    candidates.sort(key=start_of)
    return candidates[-1]


def headset_idle_detail(status: dict[str, Any]) -> str:
    state = str(status.get("state") or "").strip().lower()
    if status.get("sleepMode") is True:
        return "Crown is in sleep mode; put it on until it wakes, then close the Neurosity app"
    if status.get("online") is False or state in {"offline", "updating", "booting"}:
        return (
            "Crown is offline; wake it on Wi-Fi and close the Neurosity app "
            "so this adapter can take the stream"
        )
    return "no EEG samples yet; close console.neurosity.co and the Neurosity app"


def prune_stale_device_nodes(sdk: Any) -> None:
    """Drop leftover Firebase clients/subscriptions from previous adapter runs."""
    token = getattr(sdk, "token", None)
    db = getattr(sdk, "db", None)
    options = getattr(sdk, "options", None) or {}
    device_id = str(options.get("device_id") or "")
    if not token or db is None or not device_id:
        return
    try:
        db.child("devices").child(device_id).child("subscriptions").remove(token)
    except Exception as exc:
        log_progress(f"could not clear stale subscriptions ({public_exception_text(exc)})")
    ours = getattr(sdk, "client_id", None)
    try:
        snap = db.child("devices").child(device_id).child("clients").get(token)
        clients = snap.val() if snap is not None else None
    except Exception:
        clients = None
    if not isinstance(clients, dict):
        return
    removed = 0
    for client_id in list(clients):
        if client_id == ours:
            continue
        try:
            db.child("devices").child(device_id).child("clients").child(str(client_id)).remove(token)
            removed += 1
        except Exception:
            pass
    if removed:
        log_progress(f"cleared {removed} stale Crown clients")


def fetch_claimed_devices(db: Any, user: dict[str, Any]) -> list[dict[str, str]]:
    """One-shot Firebase GET. Never use the JS SDK's hanging getDevices() listener."""
    uid = str(user.get("localId") or "").strip()
    token = str(user.get("idToken") or "").strip()
    if not uid or not token:
        raise CrownAuthError("Neurosity login failed")
    try:
        snapshot = db.child("users").child(uid).child("devices").get(token)
    except Exception as exc:
        raise CrownAuthError(
            f"could not list claimed Crowns ({public_exception_text(exc)})"
        ) from exc
    raw = snapshot.val() if snapshot is not None and hasattr(snapshot, "val") else None
    if not isinstance(raw, dict) or not raw:
        raise CrownAuthError("no claimed Crown on this Neurosity account")
    devices: list[dict[str, str]] = []
    for device_id in raw:
        nickname = ""
        try:
            info_snap = db.child("devices").child(str(device_id)).child("info").get(token)
            info = info_snap.val() if info_snap is not None and hasattr(info_snap, "val") else None
        except Exception:
            info = None
        if isinstance(info, dict):
            nickname = str(info.get("deviceNickname") or info.get("nickname") or "").strip()
        devices.append({"deviceId": str(device_id), "deviceNickname": nickname})
    return devices


def _disarm_sdk_process_hooks(sdk: Any, previous: dict[Any, Any]) -> None:
    if sdk is not None:
        handler = getattr(sdk, "exit_handler", None)
        if handler is not None:
            try:
                atexit.unregister(handler)
            except Exception:
                pass
    for sig, orig in previous.items():
        try:
            signal.signal(sig, orig)
        except Exception:
            pass


class NeurosityPythonClient(CrownClient):
    def __init__(self, *, env: dict[str, str] | None = None, device_id: str | None = None) -> None:
        self._env = env
        self._device_id_override = (device_id or "").strip()
        self._sdk: Any = None
        self._unsubs: list[Callable[[], None]] = []

    def login(self) -> None:
        """MindExecute `NeurositySDKStreamer.connect()` without brainwaves_raw.

        That method constructs the SDK, logs in, then subscribes — all on the
        main thread. `start()` is the subscribe step so the adapter can push
        epochs into the event hub instead of a ring buffer.
        """
        email, password, device_id = load_crown_credentials(self._env)
        if self._device_id_override:
            device_id = self._device_id_override
        try:
            from neurosity import NeurositySDK
        except ImportError as exc:
            raise CrownAuthError(
                "Neurosity SDK not installed. Run: python -m pip install -e '.[crown]'"
            ) from exc

        log_progress(f"Connecting to Neurosity SDK for device {device_id}...")
        previous = {
            signal.SIGINT: signal.getsignal(signal.SIGINT),
            signal.SIGTERM: signal.getsignal(signal.SIGTERM),
        }
        try:
            # MindExecute passes {"deviceId": ...}. Published SDK also needs device_id.
            self._sdk = NeurositySDK(sdk_options(device_id))
        except Exception as exc:
            raise CrownAuthError(
                f"Neurosity SDK init failed ({public_exception_text(exc)})"
            ) from exc
        finally:
            # The published SDK registers SIGINT/SIGTERM and an atexit handler
            # that os.kill()s the process. Restore our handlers so Ctrl+C works.
            _disarm_sdk_process_hooks(self._sdk, previous)

        try:
            self._sdk.login({"email": email, "password": password})
        except CrownAuthError:
            raise
        except Exception as exc:
            log_progress(f"Failed to connect to Neurosity SDK: {public_exception_text(exc)}")
            message = str(exc)
            if re.search(
                r"password|credential|unauthori[sz]ed|invalid.?email|user.?not.?found",
                message,
                re.I,
            ):
                raise CrownAuthError(
                    "Neurosity authentication failed; check .env.local (values are not logged)"
                ) from exc
            raise CrownAuthError(f"Neurosity login failed ({public_exception_text(exc)})") from exc
        self._bind_claimed_device(device_id)
        prune_stale_device_nodes(self._sdk)
        log_progress("Connected to Neurosity Crown via SDK")

    def _bind_claimed_device(self, wanted: str) -> None:
        """Map a nickname like Crown-995 onto the Firebase device id after login.

        MindExecute passes the nickname straight into NeurositySDK. The published
        SDK then writes `devices/{id}/subscriptions`, which Firebase rejects unless
        `{id}` is the claimed 32-character device id.
        """
        sdk = self._sdk
        if sdk is None:
            return
        info: Any = None
        get_info = getattr(sdk, "get_info", None)
        if callable(get_info):
            try:
                info = get_info()
            except Exception as exc:
                log_progress(f"device info unavailable ({public_exception_text(exc)})")
                info = None
        if looks_like_firebase_device_id(wanted) and isinstance(info, dict) and info:
            return
        user = getattr(sdk, "user", None)
        db = getattr(sdk, "db", None)
        if not isinstance(user, dict) or db is None:
            return
        log_progress("looking up claimed devices for nickname")
        devices = fetch_claimed_devices(db, user)
        real_id = pick_device_id(wanted, devices)
        current = str(sdk.options.get("device_id") or "")
        if real_id == current:
            return
        log_progress("resolved nickname to claimed device")
        if hasattr(sdk, "client_id"):
            try:
                sdk.remove_client()
            except Exception:
                pass
            try:
                del sdk.client_id
            except Exception:
                pass
        sdk.options["device_id"] = real_id
        sdk.options["deviceId"] = real_id
        sdk.add_client()

    def start(
        self, on_epoch: Callable[[CrownEpoch], None], on_accel: Callable[[CrownAccel], None]
    ) -> None:
        if self._sdk is None:
            raise CrownAuthError("not authenticated")
        log_progress("subscribing to brainwaves_raw")
        seen = {"n": 0}

        def on_raw(packet: Any) -> None:
            seen["n"] += 1
            if seen["n"] == 1:
                keys = sorted(packet.keys()) if isinstance(packet, dict) else type(packet).__name__
                log_progress(f"first brainwaves packet ({keys})")
            try:
                on_epoch(normalize_epoch(packet))
            except Exception as exc:
                log_progress(f"ignored malformed brainwaves packet ({public_exception_text(exc)})")

        try:
            self._unsubs.append(self._sdk.brainwaves_raw(on_raw))
        except CrownAuthError:
            raise
        except Exception as exc:
            raise CrownAuthError(
                f"brainwaves_raw failed ({public_exception_text(exc)})"
            ) from exc
        log_progress("subscribed to brainwaves_raw")
        try:
            accel_seen = {"n": 0}

            def on_acc(packet: Any) -> None:
                accel_seen["n"] += 1
                if accel_seen["n"] == 1:
                    log_progress("accelerometer live; waiting for EEG")
                on_accel(normalize_accel(packet))

            self._unsubs.append(self._sdk.accelerometer(on_acc))
        except Exception:
            # Accelerometer is optional in the Python SDK.
            pass

    def stop(self) -> None:
        unsubs = list(self._unsubs)
        self._unsubs.clear()
        for unsub in unsubs:
            try:
                unsub()
            except Exception:
                pass
        sdk = self._sdk
        self._sdk = None
        if sdk is None:
            return
        for method in ("remove_all_subscriptions",):
            fn = getattr(sdk, method, None)
            if fn is None:
                continue
            try:
                fn()
            except Exception:
                pass
        if hasattr(sdk, "client_id"):
            try:
                sdk.remove_client()
            except Exception:
                pass
        _disarm_sdk_process_hooks(sdk, {})

    def device_info(self) -> dict[str, Any]:
        if self._sdk is None:
            return {}
        info = {}
        for method in ("get_info", "status_once"):
            fn = getattr(self._sdk, method, None)
            if fn is None:
                continue
            try:
                value = fn()
            except Exception:
                continue
            if isinstance(value, dict):
                info[method] = _public_device_fields(value)
        return info

    def headset_status(self) -> dict[str, Any]:
        info = self.device_info()
        status = info.get("status_once")
        if isinstance(status, dict) and status:
            return status
        meta = info.get("get_info")
        return meta if isinstance(meta, dict) else {}

    def poll_epoch(self) -> CrownEpoch | None:
        if self._sdk is None:
            return None
        getter = getattr(self._sdk, "get_from_path", None)
        if not callable(getter):
            return None
        try:
            raw = getter("metrics/brainwaves/raw")
        except Exception as exc:
            log_progress(f"brainwaves poll failed ({public_exception_text(exc)})")
            return None
        packet = latest_metric_packet(raw)
        if packet is None:
            return None
        epoch = normalize_epoch(packet)
        if not epoch.data:
            return None
        return epoch


def _public_device_fields(raw: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "name",
        "deviceNickname",
        "nickname",
        "channelNames",
        "samplingRate",
        "manufacturer",
        "model",
        "osVersion",
        "state",
        "sleepMode",
        "sleepModeReason",
        "battery",
        "charging",
        "online",
    }
    return {key: raw[key] for key in allowed if key in raw}


def normalize_epoch(packet: Any) -> CrownEpoch:
    record = packet if isinstance(packet, dict) else {}
    data = record.get("data") or []
    info = record.get("info") if isinstance(record.get("info"), dict) else {}
    start = info.get("startTime")
    try:
        start_ms = float(start) if start is not None else None
    except (TypeError, ValueError):
        start_ms = None
    names = info.get("channelNames")
    rate = info.get("samplingRate")
    try:
        sampling_rate = float(rate) if rate is not None else 256.0
    except (TypeError, ValueError):
        sampling_rate = 256.0
    return CrownEpoch(
        data=to_channel_major(data, 8),
        channel_names=[str(name) for name in names]
        if isinstance(names, list) and len(names) == 8
        else [],
        sampling_rate=sampling_rate,
        start_time_ms=start_ms,
    )


def normalize_accel(packet: Any) -> CrownAccel:
    record = packet if isinstance(packet, dict) else {}
    nested = record.get("acceleration") if isinstance(record.get("acceleration"), dict) else None
    src = nested or record
    return CrownAccel(
        x=_as_float(src.get("x")),
        y=_as_float(src.get("y")),
        z=_as_float(src.get("z")),
    )


def to_channel_major(data: Any, expected_channels: int) -> list[list[float]]:
    if not isinstance(data, list) or not data:
        return []
    if len(data) == expected_channels and isinstance(data[0], list):
        return [[_as_float(value) for value in channel] for channel in data]
    if isinstance(data[0], list) and len(data[0]) == expected_channels:
        return [[_as_float(row[ch]) for row in data] for ch in range(expected_channels)]
    if isinstance(data[0], (int, float)):
        return []
    return [
        [_as_float(value) for value in channel] if isinstance(channel, list) else []
        for channel in data
    ]


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


@dataclass
class QueuedCrownClient(CrownClient):
    """In-process fake used by unit tests."""

    epochs: list[CrownEpoch] = field(default_factory=list)
    accel: CrownAccel = field(default_factory=lambda: CrownAccel(x=0.05, y=-0.02, z=0.99))
    login_error: Exception | None = None
    login_calls: int = 0
    stop_calls: int = 0
    _stop: threading.Event = field(default_factory=threading.Event)

    def login(self) -> None:
        self.login_calls += 1
        if self.login_error is not None:
            raise self.login_error

    def start(
        self, on_epoch: Callable[[CrownEpoch], None], on_accel: Callable[[CrownAccel], None]
    ) -> None:
        on_accel(self.accel)
        for epoch in self.epochs:
            if self._stop.is_set():
                return
            on_epoch(epoch)

    def stop(self) -> None:
        self.stop_calls += 1
        self._stop.set()


class EpochQueue:
    def __init__(self, maxsize: int = 64) -> None:
        self._epochs: queue.Queue[CrownEpoch] = queue.Queue(maxsize=maxsize)
        self._accel = CrownAccel()
        self._accel_lock = threading.Lock()
        self.dropped = 0

    def push_epoch(self, epoch: CrownEpoch) -> None:
        try:
            self._epochs.put_nowait(epoch)
        except queue.Full:
            try:
                self._epochs.get_nowait()
            except queue.Empty:
                pass
            self.dropped += 1
            try:
                self._epochs.put_nowait(epoch)
            except queue.Full:
                self.dropped += 1

    def push_accel(self, sample: CrownAccel) -> None:
        with self._accel_lock:
            self._accel = sample

    def drain_epochs(self) -> list[CrownEpoch]:
        items: list[CrownEpoch] = []
        while True:
            try:
                items.append(self._epochs.get_nowait())
            except queue.Empty:
                return items

    def accel(self) -> CrownAccel:
        with self._accel_lock:
            return self._accel
