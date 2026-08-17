"""Local Crown EEG via BrainFlow OSC broadcast.

BrainFlow's CROWN_BOARD (NotionOSC) binds UDP 9000 and waits for OSC `*raw`
packets. It does not connect to the headset IP. Official params are empty:

    params = BrainFlowInputParams()
    board = BoardShim(BoardIds.CROWN_BOARD, params)

`--ip` is ignored. `--device-id` is optional and maps to BrainFlow
`serial_number` only when you have more than one Crown on the LAN.

Enable OSC on the Crown (Neurosity console → device settings). No cloud login.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np

from crown_adapter.client import (
    CrownAccel,
    CrownAuthError,
    CrownClient,
    CrownEpoch,
    NeurosityPythonClient,
)
from crown_adapter.quality import CROWN_CHANNELS

CROWN_BOARD_ID = 23
SAMPLES_PER_CHUNK = 16
SAMPLE_RATE_HZ = 256
OSC_PORT = 9000


@dataclass
class CrownOscConnection:
    ip_address: str = ""
    ip_port: int = 0
    device_id: str = ""
    timeout_seconds: int = 15

    def validate(self) -> None:
        return None


def connection_from_mapping(
    devices_crown: dict[str, Any] | None = None,
    *,
    ip_address: str | None = None,
    ip_port: int | None = None,
    device_id: str | None = None,
    env: dict[str, str] | None = None,
) -> CrownOscConnection:
    cfg = devices_crown or {}
    source = env if env is not None else os.environ
    ip = (
        ip_address
        or str(cfg.get("ip_address") or "").strip()
        or str(source.get("CROWN_IP") or source.get("NEUROSITY_IP") or "").strip()
    )
    port_raw = ip_port if ip_port is not None else cfg.get("ip_port", OSC_PORT)
    try:
        port = int(port_raw or 0)
    except (TypeError, ValueError):
        port = 0
    if port <= 0:
        port = OSC_PORT
    nick = (
        device_id
        or str(cfg.get("device_id") or "").strip()
        or str(source.get("NEUROSITY_DEVICE_ID") or "").strip()
    )
    timeout_raw = cfg.get("timeout_seconds", 15)
    try:
        timeout = int(timeout_raw)
    except (TypeError, ValueError):
        timeout = 15
    return CrownOscConnection(
        ip_address=ip,
        ip_port=port,
        device_id=nick,
        timeout_seconds=max(1, timeout),
    )


def _first_sample_ms(data: np.ndarray, timestamp_channel: int | None) -> float | None:
    if timestamp_channel is None or data.ndim != 2 or data.shape[1] == 0:
        return None
    if timestamp_channel < 0 or timestamp_channel >= data.shape[0]:
        return None
    value = float(data[timestamp_channel, 0])
    if not np.isfinite(value) or value <= 0:
        return None
    if value > 1e14:
        return value / 1_000_000.0
    if value > 1e11:
        return value / 1_000.0
    return value * 1000.0


class BrainFlowCrownClient(CrownClient):
    def __init__(
        self,
        connection: CrownOscConnection,
        *,
        board_shim: Any | None = None,
        board_id: int = CROWN_BOARD_ID,
        eeg_channels: list[int] | None = None,
        timestamp_channel: int | None = None,
        samples_per_chunk: int = SAMPLES_PER_CHUNK,
        poll_s: float = 0.05,
    ) -> None:
        self.connection = connection
        self._board_shim = board_shim
        self._board_id = board_id
        self._eeg_channels = eeg_channels
        self._timestamp_channel = timestamp_channel
        self.samples_per_chunk = samples_per_chunk
        self.poll_s = poll_s
        self._board: Any = None
        self._running = False
        self._thread: threading.Thread | None = None
        self._on_epoch: Callable[[CrownEpoch], None] | None = None
        self._on_accel: Callable[[CrownAccel], None] | None = None
        self._pending = np.zeros((8, 0), dtype=float)
        self._pending_start_ms: float | None = None

    def login(self) -> None:
        self.connection.validate()
        board_shim, params_cls = self._resolve_brainflow()
        disabler = getattr(board_shim, "disable_board_logger", None)
        if callable(disabler):
            try:
                disabler()
            except Exception:
                pass
        params = params_cls()
        # NotionOSC ignores ip_address. It binds INADDR_ANY on UDP 9000.
        params.ip_port = int(self.connection.ip_port or OSC_PORT)
        params.timeout = int(self.connection.timeout_seconds)
        self._board = board_shim(self._board_id, params)
        try:
            self._board.prepare_session()
            self._board.start_stream(45000)
        except Exception as exc:
            self._safe_release()
            raise CrownAuthError(
                "no OSC packets on UDP 9000 in 5s; enable OSC on the Crown "
                "(console → device settings), same Wi-Fi, close the Neurosity app"
            ) from exc
        if self._eeg_channels is None:
            getter = getattr(board_shim, "get_eeg_channels", None)
            self._eeg_channels = list(getter(self._board_id)) if getter else list(range(1, 9))
        if self._timestamp_channel is None:
            getter = getattr(board_shim, "get_timestamp_channel", None)
            if getter is not None:
                try:
                    self._timestamp_channel = int(getter(self._board_id))
                except Exception:
                    self._timestamp_channel = None

    def start(
        self, on_epoch: Callable[[CrownEpoch], None], on_accel: Callable[[CrownAccel], None]
    ) -> None:
        if self._board is None:
            raise CrownAuthError("not connected")
        self._on_epoch = on_epoch
        self._on_accel = on_accel
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="crown-osc", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        self._thread = None
        self._safe_release()

    def device_info(self) -> dict[str, Any]:
        return {
            "backend": "brainflow-osc",
            "board_id": self._board_id,
            "ip_port": int(self.connection.ip_port or OSC_PORT),
            "device_id": self.connection.device_id,
        }

    def _loop(self) -> None:
        assert self._board is not None
        channels = self._eeg_channels or list(range(1, 9))
        while self._running:
            try:
                data = np.asarray(self._board.get_board_data(), dtype=float)
            except Exception:
                time.sleep(self.poll_s)
                continue
            if data.size == 0 or data.ndim != 2 or data.shape[1] == 0:
                time.sleep(self.poll_s)
                continue
            try:
                eeg = np.vstack([data[ch] for ch in channels])
            except Exception:
                time.sleep(self.poll_s)
                continue
            if eeg.shape[0] != 8:
                padded = np.zeros((8, eeg.shape[1]), dtype=float)
                padded[: min(8, eeg.shape[0])] = eeg[: min(8, eeg.shape[0])]
                eeg = padded
            if self._pending.shape[1] == 0:
                self._pending_start_ms = _first_sample_ms(data, self._timestamp_channel)
            self._pending = np.hstack([self._pending, eeg])
            while self._pending.shape[1] >= self.samples_per_chunk:
                chunk = self._pending[:, : self.samples_per_chunk]
                self._pending = self._pending[:, self.samples_per_chunk :]
                start_ms = self._pending_start_ms
                self._pending_start_ms = _first_sample_ms(data, self._timestamp_channel)
                if self._on_epoch is not None:
                    self._on_epoch(
                        CrownEpoch(
                            data=chunk.tolist(),
                            channel_names=list(CROWN_CHANNELS),
                            sampling_rate=float(SAMPLE_RATE_HZ),
                            start_time_ms=start_ms,
                        )
                    )

    def _resolve_brainflow(self) -> tuple[Any, Any]:
        if self._board_shim is not None:
            return self._board_shim, _InputParams
        from brainflow.board_shim import BoardShim, BrainFlowInputParams

        return BoardShim, BrainFlowInputParams

    def _safe_release(self) -> None:
        board = self._board
        self._board = None
        if board is None:
            return
        try:
            for method in ("stop_stream", "release_session"):
                fn = getattr(board, method, None)
                if fn is None:
                    continue
                try:
                    fn()
                except Exception:
                    pass
        finally:
            # Failed start_stream can leave is_prepared() true while release_session
            # raises BOARD_NOT_CREATED_ERROR from BrainFlow's __del__.
            if hasattr(board, "is_prepared"):
                board.is_prepared = lambda: False


class FallbackCrownClient(CrownClient):
    """Try OSC first; if UDP 9000 is silent, use the Neurosity cloud SDK."""

    def __init__(
        self,
        connection: CrownOscConnection,
        *,
        osc_client: CrownClient | None = None,
        sdk_client: CrownClient | None = None,
    ) -> None:
        self.connection = connection
        self._osc_client = osc_client
        self._sdk_client = sdk_client
        self._inner: CrownClient | None = None
        self.backend = "auto"

    def login(self) -> None:
        if self.backend == "sdk" and self._inner is not None:
            self._inner.login()
            return
        osc = self._osc_client or BrainFlowCrownClient(self.connection)
        try:
            osc.login()
            self._inner = osc
            self.backend = "osc"
            return
        except CrownAuthError:
            try:
                osc.stop()
            except Exception:
                pass
        sdk = self._sdk_client or NeurosityPythonClient()
        sdk.login()
        self._inner = sdk
        self.backend = "sdk"
        print(
            '{"level":"info","service":"crown-adapter",'
            '"msg":"OSC silent on UDP 9000; using Neurosity SDK from .env.local"}',
            flush=True,
        )

    def start(
        self, on_epoch: Callable[[CrownEpoch], None], on_accel: Callable[[CrownAccel], None]
    ) -> None:
        if self._inner is None:
            raise CrownAuthError("not connected")
        self._inner.start(on_epoch, on_accel)

    def stop(self) -> None:
        inner = self._inner
        if inner is None:
            return
        try:
            inner.stop()
        except Exception:
            pass

    def device_info(self) -> dict[str, Any]:
        info = self._inner.device_info() if self._inner is not None else {}
        info["backend"] = self.backend
        return info


class _InputParams:
    def __init__(self) -> None:
        self.ip_address = ""
        self.ip_port = 0
        self.serial_number = ""
        self.other_info = ""
        self.timeout = 0
