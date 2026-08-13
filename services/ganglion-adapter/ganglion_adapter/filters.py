from __future__ import annotations

import numpy as np
from numpy.typing import NDArray
from scipy.signal import butter, iirnotch, lfilter


class CausalFilter:
    """Single-channel IIR with retained zi. Never uses future samples."""

    def __init__(self, b: NDArray[np.floating], a: NDArray[np.floating]) -> None:
        self.b = np.asarray(b, dtype=float)
        self.a = np.asarray(a, dtype=float)
        self.zi = np.zeros(max(len(self.a), len(self.b)) - 1, dtype=float)

    def reset(self) -> None:
        self.zi[:] = 0.0

    def process(self, samples: NDArray[np.floating]) -> NDArray[np.floating]:
        y, self.zi = lfilter(self.b, self.a, np.asarray(samples, dtype=float), zi=self.zi)
        return y


class CausalDcBlock:
    def __init__(self, alpha: float = 0.02) -> None:
        self.alpha = alpha
        self.dc = 0.0
        self._initialized = False

    def reset(self) -> None:
        self.dc = 0.0
        self._initialized = False

    def process(self, samples: NDArray[np.floating]) -> NDArray[np.floating]:
        out = np.empty_like(samples, dtype=float)
        dc = self.dc
        alpha = self.alpha
        for i, value in enumerate(samples):
            if not self._initialized:
                dc = float(value)
                self._initialized = True
            dc = (1.0 - alpha) * dc + alpha * float(value)
            out[i] = float(value) - dc
        self.dc = dc
        return out


class CausalEmgFilter:
    """DC block -> 60 Hz notch -> 20-90 Hz bandpass, per channel, causal."""

    def __init__(
        self,
        n_channels: int = 4,
        sample_rate_hz: float = 200.0,
        notch_hz: float = 60.0,
        bandpass_hz: tuple[float, float] = (20.0, 90.0),
    ) -> None:
        self.n_channels = n_channels
        self.sample_rate_hz = sample_rate_hz
        nyquist = sample_rate_hz / 2.0
        high = min(bandpass_hz[1], nyquist * 0.95)
        b_notch, a_notch = iirnotch(notch_hz / nyquist, Q=30.0)
        b_bp, a_bp = butter(2, [bandpass_hz[0] / nyquist, high / nyquist], btype="band")
        self.dc = [CausalDcBlock() for _ in range(n_channels)]
        self.notch = [CausalFilter(b_notch, a_notch) for _ in range(n_channels)]
        self.band = [CausalFilter(b_bp, a_bp) for _ in range(n_channels)]

    def reset(self) -> None:
        for dc, notch, band in zip(self.dc, self.notch, self.band, strict=True):
            dc.reset()
            notch.reset()
            band.reset()

    def process(self, samples: NDArray[np.floating]) -> NDArray[np.floating]:
        data = np.asarray(samples, dtype=float)
        if data.ndim != 2 or data.shape[0] != self.n_channels:
            raise ValueError("samples must be channel-major with shape (n_channels, n_samples)")
        out = np.empty_like(data)
        for ch in range(self.n_channels):
            stage = self.dc[ch].process(data[ch])
            stage = self.notch[ch].process(stage)
            out[ch] = self.band[ch].process(stage)
        return out
