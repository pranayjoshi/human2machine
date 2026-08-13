from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray

CHANNEL_NAMES = ["emg_ch1", "emg_ch2", "emg_ch3", "emg_ch4"]
GANGLION_BOARD_ID = 1
EEG_CHANNEL_COUNT = 4


@dataclass
class MockAcquisition:
    sample_rate_hz: float = 200.0
    n_channels: int = 4
    chunk_ms: float = 80.0
    seed: int = 7
    snr_db: float = 12.0
    packet_loss: float = 0.0
    disconnected: bool = False

    def __post_init__(self) -> None:
        self.rng = np.random.default_rng(self.seed)
        self.sample_index = 0
        self.packet_loss_count = 0
        self.script = self._default_script()
        self.last_receive_ns: int | None = None

    def _default_script(self) -> list[tuple[str, float]]:
        pattern: list[tuple[str, float]] = []
        for _ in range(8):
            pattern.extend(
                [("rest", 0.6), ("confirm", 0.45), ("rest", 0.5), ("cancel", 0.45), ("rest", 0.4)]
            )
        return pattern

    def set_disconnected(self, disconnected: bool) -> None:
        self.disconnected = disconnected

    def next_chunk(self) -> tuple[NDArray[np.floating], int, str] | None:
        if self.disconnected:
            return None
        if self.packet_loss > 0 and float(self.rng.random()) < self.packet_loss:
            self.packet_loss_count += 1
            self.sample_index += self.samples_per_chunk
            return None
        n = self.samples_per_chunk
        label = self._label_at(self.sample_index)
        t0 = self.sample_index / self.sample_rate_hz
        t = t0 + np.arange(n) / self.sample_rate_hz
        noise = self.rng.normal(0.0, 8.0, size=(self.n_channels, n))
        signal = np.zeros((self.n_channels, n), dtype=float)
        burst = np.sin(2 * np.pi * 40.0 * t) * 80.0
        if label == "confirm":
            signal[0:2] = burst
        elif label == "cancel":
            signal[2:4] = burst
        snr_lin = 10 ** (self.snr_db / 20.0)
        mixed = signal + noise / max(snr_lin, 1e-3)
        first_ns = int(self.sample_index * 1_000_000_000 // int(self.sample_rate_hz))
        self.sample_index += n
        self.last_receive_ns = time.monotonic_ns()
        return mixed, first_ns, label

    @property
    def samples_per_chunk(self) -> int:
        return max(1, int(round(self.sample_rate_hz * self.chunk_ms / 1000.0)))

    def _label_at(self, sample_index: int) -> str:
        elapsed = 0.0
        t = sample_index / self.sample_rate_hz
        for label, duration in self.script:
            elapsed += duration
            if t < elapsed:
                return label
        return "rest"


def board_timestamp_to_ns(value: float) -> int | None:
    if not np.isfinite(value) or value <= 0:
        return None
    if value > 1e14:
        return int(value)
    if value > 1e11:
        return int(value * 1_000_000)
    return int(value * 1_000_000_000)


class BrainFlowAcquisition:
    """Live Ganglion session via BrainFlow. Tests inject a fake BoardShim."""

    def __init__(
        self,
        serial_port: str | None = None,
        *,
        sample_rate_hz: float = 200.0,
        n_channels: int = EEG_CHANNEL_COUNT,
        chunk_ms: float = 80.0,
        board_shim: Any | None = None,
        board_id: int | None = None,
        eeg_channels: list[int] | None = None,
        timestamp_channel: int | None = None,
        poll_s: float = 0.05,
    ) -> None:
        self.serial_port = serial_port
        self.sample_rate_hz = sample_rate_hz
        self.n_channels = n_channels
        self.chunk_ms = chunk_ms
        self.poll_s = poll_s
        self.disconnected = False
        self.packet_loss_count = 0
        self.last_receive_ns: int | None = None
        self._board_shim = board_shim
        self._board_id = board_id
        self._eeg_channels = eeg_channels
        self._timestamp_channel = timestamp_channel
        self._board: Any | None = None
        self._running = False
        self._thread: threading.Thread | None = None
        self._queue: queue.Queue[tuple[NDArray[np.floating], int, int]] = queue.Queue(maxsize=8)
        self._error: str | None = None

    def start(self) -> None:
        if not self.serial_port:
            raise RuntimeError("Ganglion serial_port is not set")
        board_shim, board_id, params_cls = self._resolve_brainflow()
        params = params_cls()
        params.serial_port = self.serial_port
        self._board = board_shim(board_id, params)
        try:
            self._board.prepare_session()
            self._board.start_stream()
        except Exception:
            self._safe_release()
            raise
        if self._eeg_channels is None:
            getter = getattr(board_shim, "get_eeg_channels", None)
            self._eeg_channels = list(getter(board_id)) if getter else list(range(1, 5))
        if self._timestamp_channel is None:
            getter = getattr(board_shim, "get_timestamp_channel", None)
            if getter is not None:
                try:
                    self._timestamp_channel = int(getter(board_id))
                except Exception:
                    self._timestamp_channel = None
        self._running = True
        self.disconnected = False
        self._thread = threading.Thread(target=self._acquire_loop, name="ganglion-acq", daemon=True)
        self._thread.start()

    def read_chunk(self) -> tuple[NDArray[np.floating], int, str] | None:
        return self.next_chunk()

    def next_chunk(self) -> tuple[NDArray[np.floating], int, str] | None:
        if self.disconnected:
            return None
        try:
            samples, first_ns, received_ns = self._queue.get(timeout=self.poll_s)
        except queue.Empty:
            return None
        self.last_receive_ns = received_ns
        return samples, first_ns, "live"

    def set_disconnected(self, disconnected: bool) -> None:
        self.disconnected = disconnected
        if disconnected:
            self.stop()

    def stop(self) -> None:
        self._running = False
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        self._thread = None
        self._safe_release()

    def _acquire_loop(self) -> None:
        assert self._board is not None
        eeg_channels = self._eeg_channels or list(range(1, 5))
        while self._running:
            try:
                data = np.asarray(self._board.get_board_data(), dtype=float)
                received_ns = time.monotonic_ns()
            except Exception as exc:
                self._error = str(exc)
                self.disconnected = True
                break
            if data.size == 0 or data.ndim != 2 or data.shape[1] == 0:
                time.sleep(self.poll_s)
                continue
            try:
                eeg = np.vstack([data[ch] for ch in eeg_channels])
            except Exception:
                self.packet_loss_count += 1
                time.sleep(self.poll_s)
                continue
            if eeg.shape[0] != self.n_channels:
                if eeg.shape[0] > self.n_channels:
                    eeg = eeg[: self.n_channels]
                else:
                    padded = np.zeros((self.n_channels, eeg.shape[1]), dtype=float)
                    padded[: eeg.shape[0]] = eeg
                    eeg = padded
            first_ns = self._first_sample_ns(data, received_ns)
            item = (np.asarray(eeg, dtype=float), first_ns, received_ns)
            try:
                self._queue.put_nowait(item)
            except queue.Full:
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    pass
                try:
                    self._queue.put_nowait(item)
                except queue.Full:
                    pass
            time.sleep(self.poll_s)

    def _first_sample_ns(self, data: NDArray[np.floating], received_ns: int) -> int:
        channel = self._timestamp_channel
        if channel is not None and 0 <= channel < data.shape[0] and data.shape[1] > 0:
            converted = board_timestamp_to_ns(float(data[channel, 0]))
            if converted is not None:
                return converted
        return received_ns

    def _resolve_brainflow(self) -> tuple[Any, int, Any]:
        if self._board_shim is not None:
            board_id = GANGLION_BOARD_ID if self._board_id is None else int(self._board_id)
            return self._board_shim, board_id, _SessionParams
        try:
            from brainflow.board_shim import BoardIds, BoardShim, BrainFlowInputParams
        except ImportError as exc:
            raise RuntimeError("brainflow is not installed") from exc
        board_id = int(BoardIds.GANGLION_BOARD) if self._board_id is None else int(self._board_id)
        return BoardShim, board_id, BrainFlowInputParams

    def _safe_release(self) -> None:
        board = self._board
        if board is None:
            return
        try:
            stop = getattr(board, "stop_stream", None)
            if stop is not None:
                stop()
        except Exception:
            pass
        try:
            release = getattr(board, "release_session", None)
            if release is not None:
                release()
        finally:
            self._board = None


class _SessionParams:
    def __init__(self) -> None:
        self.serial_port: str | None = None
