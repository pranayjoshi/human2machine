from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import numpy as np
from numpy.typing import NDArray

CHANNEL_FEATURE_NAMES = ("rms", "mav", "var", "wl", "zc", "ssc", "iemg")
FEATURE_NAMES: tuple[str, ...] = tuple(
    f"ch{ch}_{name}" for ch in range(4) for name in CHANNEL_FEATURE_NAMES
) + tuple(f"ch{ch}_rms_ratio" for ch in range(4))


class WindowLike(Protocol):
    block_id: str
    start_idx: int
    end_idx: int


@dataclass(frozen=True)
class WindowRecord:
    block_id: str
    start_idx: int
    end_idx: int
    samples: NDArray[np.floating]
    start_ns: int
    end_ns: int
    features: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class LabeledExample:
    block_id: str
    session_id: str
    label: str
    start_idx: int
    end_idx: int
    features: dict[str, float]
    quality: float = 1.0
    start_ns: int = 0
    end_ns: int = 0


def feature_vector(
    features: dict[str, float],
    names: tuple[str, ...] | list[str] = FEATURE_NAMES,
) -> NDArray[np.floating]:
    return np.asarray([float(features.get(name, 0.0)) for name in names], dtype=float)


def rms(channel: NDArray[np.floating]) -> float:
    return float(np.sqrt(np.mean(np.square(channel))))


def mav(channel: NDArray[np.floating]) -> float:
    return float(np.mean(np.abs(channel)))


def variance(channel: NDArray[np.floating]) -> float:
    return float(np.var(channel))


def waveform_length(channel: NDArray[np.floating]) -> float:
    return float(np.sum(np.abs(np.diff(channel))))


def zero_crossings(channel: NDArray[np.floating], threshold: float = 5.0) -> float:
    if channel.size < 2:
        return 0.0
    signs = np.sign(channel)
    changes = (signs[1:] * signs[:-1]) < 0
    large = np.abs(np.diff(channel)) >= threshold
    return float(np.count_nonzero(changes & large))


def slope_sign_changes(channel: NDArray[np.floating], threshold: float = 5.0) -> float:
    if channel.size < 3:
        return 0.0
    d1 = np.diff(channel)
    changes = (d1[1:] * d1[:-1]) < 0
    large = (np.abs(d1[1:]) >= threshold) & (np.abs(d1[:-1]) >= threshold)
    return float(np.count_nonzero(changes & large))


def iemg(channel: NDArray[np.floating]) -> float:
    return float(np.sum(np.abs(channel)))


def channel_features(channel: NDArray[np.floating], prefix: str) -> dict[str, float]:
    return {
        f"{prefix}_rms": rms(channel),
        f"{prefix}_mav": mav(channel),
        f"{prefix}_var": variance(channel),
        f"{prefix}_wl": waveform_length(channel),
        f"{prefix}_zc": zero_crossings(channel),
        f"{prefix}_ssc": slope_sign_changes(channel),
        f"{prefix}_iemg": iemg(channel),
    }


def extract_window_features(samples: NDArray[np.floating]) -> dict[str, float]:
    feats: dict[str, float] = {}
    rms_values = []
    for ch, channel in enumerate(samples):
        ch_feats = channel_features(channel, f"ch{ch}")
        feats.update(ch_feats)
        rms_values.append(ch_feats[f"ch{ch}_rms"])
    total = float(sum(rms_values)) + 1e-9
    for ch, value in enumerate(rms_values):
        feats[f"ch{ch}_rms_ratio"] = value / total
    return feats


class WindowBuffer:
    """Causal sliding windows: a window is emitted only when enough past samples exist."""

    def __init__(self, window_samples: int, hop_samples: int) -> None:
        self.window_samples = window_samples
        self.hop_samples = hop_samples
        self._buf = np.zeros((0, 0), dtype=float)
        self._start_idx = 0
        self._consumed = 0
        self._first_ns: int | None = None
        self.sample_rate_hz = 200.0

    def reset(self) -> None:
        self._buf = np.zeros((0, 0), dtype=float)
        self._start_idx = 0
        self._consumed = 0
        self._first_ns = None

    def push(
        self,
        samples: NDArray[np.floating],
        first_sample_ns: int,
        sample_rate_hz: float,
        block_id: str = "live",
    ) -> list[WindowRecord]:
        data = np.asarray(samples, dtype=float)
        if self._buf.size == 0:
            self._buf = data.copy()
            self._first_ns = first_sample_ns
        else:
            self._buf = np.concatenate([self._buf, data], axis=1)
        self.sample_rate_hz = sample_rate_hz
        windows: list[WindowRecord] = []
        while self._buf.shape[1] - self._consumed >= self.window_samples:
            start = self._consumed
            end = start + self.window_samples
            chunk = self._buf[:, start:end]
            start_ns = int(first_sample_ns if self._first_ns is None else self._first_ns) + int(
                round(start * 1e9 / sample_rate_hz)
            )
            end_ns = start_ns + int(round(self.window_samples * 1e9 / sample_rate_hz))
            windows.append(
                WindowRecord(
                    block_id=block_id,
                    start_idx=self._start_idx + start,
                    end_idx=self._start_idx + end,
                    samples=chunk,
                    start_ns=start_ns,
                    end_ns=end_ns,
                    features=extract_window_features(chunk),
                )
            )
            self._consumed += self.hop_samples
        if self._consumed > self.window_samples:
            drop = self._consumed - self.hop_samples
            if drop > 0 and drop < self._buf.shape[1]:
                self._buf = self._buf[:, drop:]
                if self._first_ns is not None:
                    self._first_ns += int(round(drop * 1e9 / sample_rate_hz))
                self._start_idx += drop
                self._consumed -= drop
        return windows


def overlapping(a: WindowLike, b: WindowLike) -> bool:
    return a.block_id == b.block_id and a.start_idx < b.end_idx and b.start_idx < a.end_idx


def split_by_block[TWindow: WindowLike](
    windows: list[TWindow], test_blocks: set[str]
) -> tuple[list[TWindow], list[TWindow]]:
    """Grouped split: overlapping windows from one recording block stay together."""
    train = [window for window in windows if window.block_id not in test_blocks]
    test = [window for window in windows if window.block_id in test_blocks]
    return train, test


def validate_split_no_leak(train: list[WindowLike], test: list[WindowLike]) -> None:
    for left in train:
        for right in test:
            if overlapping(left, right):
                raise ValueError("overlapping-window leakage between train and test")


def random_window_split_leaks(windows: list[WindowLike], rng: np.random.Generator) -> bool:
    """Demonstrate that a random split of overlapping windows leaks. Not used for training."""
    if len(windows) < 2:
        return False
    order = rng.permutation(len(windows))
    mid = max(1, len(windows) // 2)
    train = [windows[i] for i in order[:mid]]
    test = [windows[i] for i in order[mid:]]
    try:
        validate_split_no_leak(train, test)
    except ValueError:
        return True
    return False
