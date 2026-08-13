# ruff: noqa: E402
import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "_fusion_runtime_path_setup", Path(__file__).with_name("path_setup.py")
)
assert _spec and _spec.loader
_spec.loader.exec_module(importlib.util.module_from_spec(_spec))

from fusion_runtime.state_machine import (
    advance_to,
    apply_transition,
    can_transition,
    reset_after_cancel,
    reset_after_outcome,
)
from intent_contracts.enums import FusionState


def test_happy_path_walk() -> None:
    state = FusionState.IDLE
    for dest in (
        FusionState.REQUEST_DETECTED,
        FusionState.TARGET_PROPOSED,
        FusionState.AWAITING_CONFIRMATION,
        FusionState.COMMIT_PROPOSED,
        FusionState.OUTCOME_OBSERVED,
        FusionState.IDLE,
    ):
        state = advance_to(state, dest)
        assert state == dest


def test_any_state_can_cancel() -> None:
    for current in FusionState:
        assert can_transition(current, FusionState.CANCELLED)
        assert apply_transition(current, FusionState.CANCELLED) == FusionState.CANCELLED


def test_cancelled_returns_to_idle() -> None:
    assert reset_after_cancel(FusionState.CANCELLED) == FusionState.IDLE
    assert advance_to(FusionState.CANCELLED, FusionState.IDLE) == FusionState.IDLE


def test_outcome_returns_to_idle() -> None:
    assert reset_after_outcome(FusionState.OUTCOME_OBSERVED) == FusionState.IDLE


def test_invalid_backward_transition() -> None:
    with pytest.raises(ValueError):
        apply_transition(FusionState.COMMIT_PROPOSED, FusionState.REQUEST_DETECTED)
