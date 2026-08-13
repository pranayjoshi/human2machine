from __future__ import annotations

import numpy as np
from ganglion_adapter.features import (
    WindowBuffer,
    WindowRecord,
    extract_window_features,
    random_window_split_leaks,
    split_by_block,
    validate_split_no_leak,
)


def test_window_features_include_required_names() -> None:
    rng = np.random.default_rng(7)
    samples = rng.normal(0, 10, size=(4, 50))
    feats = extract_window_features(samples)
    for ch in range(4):
        for name in ("rms", "mav", "var", "wl", "zc", "ssc", "iemg"):
            assert f"ch{ch}_{name}" in feats
        assert f"ch{ch}_rms_ratio" in feats


def test_window_buffer_is_causal() -> None:
    buf = WindowBuffer(window_samples=50, hop_samples=10)
    chunk = np.ones((4, 16), dtype=float)
    first = buf.push(chunk, first_sample_ns=0, sample_rate_hz=200.0)
    assert first == []
    acc = []
    t = 16
    while t < 80:
        acc.extend(buf.push(chunk, first_sample_ns=int(t * 1e9 / 200), sample_rate_hz=200.0))
        t += 16
    assert acc
    assert acc[0].end_idx - acc[0].start_idx == 50
    assert acc[0].start_idx == 0


def _windows_for_blocks() -> list[WindowRecord]:
    dummy = np.zeros((4, 50))
    windows = []
    for block in ("block_a", "block_b"):
        for start in (0, 10, 20, 30):
            windows.append(
                WindowRecord(
                    block_id=block,
                    start_idx=start,
                    end_idx=start + 50,
                    samples=dummy,
                    start_ns=start,
                    end_ns=start + 50,
                )
            )
    return windows


def test_grouped_split_does_not_leak_overlapping_windows() -> None:
    windows = _windows_for_blocks()
    train, test = split_by_block(windows, {"block_b"})
    validate_split_no_leak(train, test)
    assert {w.block_id for w in train} == {"block_a"}
    assert {w.block_id for w in test} == {"block_b"}


def test_random_overlapping_split_leaks() -> None:
    windows = [w for w in _windows_for_blocks() if w.block_id == "block_a"]
    rng = np.random.default_rng(3)
    assert random_window_split_leaks(windows, rng)
