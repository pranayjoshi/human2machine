from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

CHANNEL_NAMES = ["emg_ch1", "emg_ch2", "emg_ch3", "emg_ch4"]


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


class BrainFlowAcquisition:
    """Hardware path stub. Real BrainFlow session lives behind `if not mock`."""

    def __init__(self, serial_port: str | None = None) -> None:
        self.serial_port = serial_port

    def start(self) -> None:
        raise RuntimeError("BrainFlow hardware path is stubbed; use --mock")

    def read_chunk(self) -> None:
        raise RuntimeError("BrainFlow hardware path is stubbed; use --mock")

    def stop(self) -> None:
        return
