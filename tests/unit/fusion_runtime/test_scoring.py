# ruff: noqa: E402
import importlib.util
import math
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "_fusion_runtime_path_setup", Path(__file__).with_name("path_setup.py")
)
assert _spec and _spec.loader
_spec.loader.exec_module(importlib.util.module_from_spec(_spec))

from fusion_runtime.scoring import (
    EEG_LIVE_WEIGHT,
    eeg_live_contribution,
    evidence_contribution,
    freshness_decay,
)


def test_freshness_decay_at_zero_age() -> None:
    assert freshness_decay(0.0, 2500.0) == 1.0


def test_freshness_decay_matches_exponential() -> None:
    age_ms = 250.0
    tau = 250.0
    assert freshness_decay(age_ms, tau) == math.exp(-age_ms / tau)


def test_evidence_contribution_formula() -> None:
    expected = 0.8 * 0.9 * 0.95 * 0.5 * 1.0
    assert evidence_contribution(0.8, 0.9, 0.95, 0.5, 1.0) == expected


def test_zero_quality_or_unknown_confidence_is_zero() -> None:
    assert evidence_contribution(1.0, 0.0, 1.0, 1.0, 1.0) == 0.0
    assert evidence_contribution(1.0, 0.9, 0.0, 1.0, 1.0) == 0.0


def test_eeg_live_contribution_is_exactly_zero() -> None:
    assert EEG_LIVE_WEIGHT == 0.0
    assert eeg_live_contribution(1.0, 1.0, 1.0, 1.0) == 0.0
    assert eeg_live_contribution(1.0, 1.0, 1.0, 1.0, weight=0.0) == 0.0
