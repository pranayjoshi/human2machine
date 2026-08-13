"""Intent fusion episode state machine.

IDLE
  -> REQUEST_DETECTED
  -> TARGET_PROPOSED
  -> AWAITING_CONFIRMATION (when required)
  -> COMMIT_PROPOSED
  -> OUTCOME_OBSERVED
  -> IDLE

Any state -> CANCELLED -> IDLE
"""

from __future__ import annotations

from intent_contracts.enums import FusionState

FORWARD: dict[FusionState, tuple[FusionState, ...]] = {
    FusionState.IDLE: (FusionState.REQUEST_DETECTED,),
    FusionState.REQUEST_DETECTED: (FusionState.TARGET_PROPOSED,),
    FusionState.TARGET_PROPOSED: (
        FusionState.AWAITING_CONFIRMATION,
        FusionState.COMMIT_PROPOSED,
    ),
    FusionState.AWAITING_CONFIRMATION: (FusionState.COMMIT_PROPOSED,),
    FusionState.COMMIT_PROPOSED: (FusionState.OUTCOME_OBSERVED,),
    FusionState.OUTCOME_OBSERVED: (FusionState.IDLE,),
    FusionState.CANCELLED: (FusionState.IDLE,),
}

_ORDER = (
    FusionState.IDLE,
    FusionState.REQUEST_DETECTED,
    FusionState.TARGET_PROPOSED,
    FusionState.AWAITING_CONFIRMATION,
    FusionState.COMMIT_PROPOSED,
    FusionState.OUTCOME_OBSERVED,
)


def allowed_transitions(current: FusionState) -> frozenset[FusionState]:
    allowed = {FusionState.CANCELLED, current}
    allowed.update(FORWARD.get(current, ()))
    if current == FusionState.OUTCOME_OBSERVED:
        allowed.add(FusionState.IDLE)
    return frozenset(allowed)


def can_transition(current: FusionState, dest: FusionState) -> bool:
    if dest == current:
        return True
    return dest in allowed_transitions(current)


def apply_transition(current: FusionState, dest: FusionState) -> FusionState:
    """Apply a single legal transition. Any state may enter CANCELLED."""
    if dest == current:
        return current
    if dest == FusionState.CANCELLED:
        return FusionState.CANCELLED
    if dest in FORWARD.get(current, ()):
        return dest
    raise ValueError(f"invalid fusion transition {current} -> {dest}")


def advance_to(current: FusionState, dest: FusionState) -> FusionState:
    """Walk forward along the happy path, or cancel, until `dest` is reached."""
    if dest == current:
        return current
    if dest == FusionState.CANCELLED:
        return FusionState.CANCELLED
    if current == FusionState.CANCELLED:
        if dest == FusionState.IDLE:
            return FusionState.IDLE
        current = FusionState.IDLE
        if dest == FusionState.IDLE:
            return current
    if current == FusionState.OUTCOME_OBSERVED and dest == FusionState.IDLE:
        return FusionState.IDLE

    try:
        start = _ORDER.index(current)
        end = _ORDER.index(dest)
    except ValueError as exc:
        raise ValueError(f"invalid fusion transition {current} -> {dest}") from exc
    if end < start:
        raise ValueError(f"invalid fusion transition {current} -> {dest}")

    state = current
    for nxt in _ORDER[start + 1 : end + 1]:
        state = apply_transition(state, nxt)
    return state


def reset_after_cancel(current: FusionState) -> FusionState:
    if current != FusionState.CANCELLED:
        raise ValueError(f"reset_after_cancel requires CANCELLED, got {current}")
    return FusionState.IDLE


def reset_after_outcome(current: FusionState) -> FusionState:
    if current != FusionState.OUTCOME_OBSERVED:
        raise ValueError(f"reset_after_outcome requires OUTCOME_OBSERVED, got {current}")
    return FusionState.IDLE
