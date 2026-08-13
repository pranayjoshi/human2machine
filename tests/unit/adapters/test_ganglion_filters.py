from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from ganglion_adapter.filters import CausalEmgFilter
from scipy.signal import filtfilt

FIXTURE = Path("data/fixtures/emg/causal_impulse.json")


def _impulse_from_fixture() -> tuple[np.ndarray, int]:
    spec = json.loads(FIXTURE.read_text())
    n_ch = int(spec["n_channels"])
    n = int(spec["n_samples"])
    idx = int(spec["impulse_index"])
    amp = float(spec["impulse_amplitude_uv"])
    samples = np.zeros((n_ch, n), dtype=float)
    samples[:, idx] = amp
    return samples, idx


def test_causal_filter_does_not_use_future_samples() -> None:
    samples, impulse_index = _impulse_from_fixture()
    filt = CausalEmgFilter(n_channels=samples.shape[0], sample_rate_hz=200.0)
    causal = filt.process(samples)
    pre = causal[:, : impulse_index - 2]
    assert float(np.max(np.abs(pre))) < 1e-9

    b = filt.band[0].b
    a = filt.band[0].a
    zero_phase = np.vstack([filtfilt(b, a, samples[ch]) for ch in range(samples.shape[0])])
    pre_zero = zero_phase[:, : impulse_index - 2]
    assert float(np.linalg.norm(pre_zero)) > float(np.linalg.norm(pre))


def test_causal_filter_state_is_maintained_across_chunks() -> None:
    samples, _idx = _impulse_from_fixture()
    full = CausalEmgFilter()
    once = full.process(samples)
    streamed = CausalEmgFilter()
    parts = [streamed.process(samples[:, i : i + 16]) for i in range(0, samples.shape[1], 16)]
    joined = np.concatenate(parts, axis=1)
    np.testing.assert_allclose(once, joined, atol=1e-9)
