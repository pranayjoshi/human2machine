"""Rule-based late-fusion runtime."""

from fusion_runtime.engine import (
    EngineResult,
    FusionConfig,
    FusionRuntimeState,
    UserProfile,
    step,
)
from fusion_runtime.scoring import evidence_contribution, freshness_decay
from fusion_runtime.state_machine import advance_to, apply_transition

__all__ = [
    "EngineResult",
    "FusionConfig",
    "FusionRuntimeState",
    "UserProfile",
    "advance_to",
    "apply_transition",
    "evidence_contribution",
    "freshness_decay",
    "step",
]
