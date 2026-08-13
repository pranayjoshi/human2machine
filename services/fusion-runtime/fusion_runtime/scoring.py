"""Late-fusion scoring primitives.

Live EEG contribution is forced to 0.0 by configuration (`fusion.weights.eeg_shadow`).
"""

from __future__ import annotations

import math

EEG_LIVE_WEIGHT = 0.0


def freshness_decay(age_ms: float, time_constant_ms: float) -> float:
    """Exponential freshness: exp(-age_ms / time_constant_ms)."""
    if time_constant_ms <= 0:
        return 0.0 if age_ms > 0 else 1.0
    if age_ms < 0:
        return 1.0
    return math.exp(-age_ms / time_constant_ms)


def evidence_contribution(
    weight: float,
    feature_confidence: float,
    modality_quality: float,
    decay: float,
    user_reliability: float,
) -> float:
    """Quality-weighted late-fusion contribution for one evidence item."""
    if weight == 0.0:
        return 0.0
    if feature_confidence <= 0.0 or modality_quality <= 0.0 or decay <= 0.0:
        return 0.0
    if user_reliability <= 0.0:
        return 0.0
    return weight * feature_confidence * modality_quality * decay * user_reliability


def eeg_live_contribution(
    feature_confidence: float,
    modality_quality: float,
    decay: float,
    user_reliability: float,
    *,
    weight: float = EEG_LIVE_WEIGHT,
) -> float:
    """EEG is shadow-only; live contribution is exactly 0.0 until promoted."""
    del feature_confidence, modality_quality, decay, user_reliability
    if weight != 0.0:
        return 0.0
    return 0.0
