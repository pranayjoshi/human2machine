from __future__ import annotations

from dataclasses import dataclass

LABELS = ("rest", "confirm", "cancel", "unknown")


def classify_by_rms(
    features: dict[str, float],
    rest_threshold: float = 12.0,
    burst_threshold: float = 25.0,
) -> tuple[str, dict[str, float]]:
    confirm_energy = (features.get("ch0_rms", 0.0) + features.get("ch1_rms", 0.0)) / 2.0
    cancel_energy = (features.get("ch2_rms", 0.0) + features.get("ch3_rms", 0.0)) / 2.0
    rest_energy = min(confirm_energy, cancel_energy)

    if confirm_energy < rest_threshold and cancel_energy < rest_threshold:
        scores = {"rest": 0.92, "confirm": 0.04, "cancel": 0.04, "unknown": 0.0}
        return "rest", scores
    if confirm_energy >= burst_threshold and confirm_energy > cancel_energy * 1.25:
        conf = min(0.99, 0.55 + confirm_energy / 200.0)
        scores = {
            "rest": max(0.0, 1.0 - conf),
            "confirm": conf,
            "cancel": min(0.2, cancel_energy / max(confirm_energy, 1.0) * 0.2),
            "unknown": 0.0,
        }
        return "confirm", _normalize(scores)
    if cancel_energy >= burst_threshold and cancel_energy > confirm_energy * 1.25:
        conf = min(0.99, 0.55 + cancel_energy / 200.0)
        scores = {
            "rest": max(0.0, 1.0 - conf),
            "cancel": conf,
            "confirm": min(0.2, confirm_energy / max(cancel_energy, 1.0) * 0.2),
            "unknown": 0.0,
        }
        return "cancel", _normalize(scores)
    scores = {
        "unknown": 0.6,
        "rest": 0.15,
        "confirm": min(0.4, confirm_energy / max(burst_threshold, 1.0) * 0.3),
        "cancel": min(0.4, cancel_energy / max(burst_threshold, 1.0) * 0.3),
    }
    _ = rest_energy
    return "unknown", _normalize(scores)


def _normalize(scores: dict[str, float]) -> dict[str, float]:
    total = sum(max(0.0, v) for v in scores.values()) or 1.0
    out = {key: max(0.0, min(1.0, value / total)) for key, value in scores.items()}
    for label in LABELS:
        out.setdefault(label, 0.0)
    return out


@dataclass
class LiveSmoother:
    dwell_ms: float = 200.0
    hysteresis: float = 0.12
    refractory_ms: float = 400.0
    confidence_threshold: float = 0.7
    quality_threshold: float = 0.4

    committed: str = "rest"
    committed_confidence: float = 0.5
    pending_label: str | None = None
    pending_since_ns: int | None = None
    refractory_until_ns: int = 0
    awaiting_rest: bool = False

    def reset(self) -> None:
        self.committed = "rest"
        self.committed_confidence = 0.5
        self.pending_label = None
        self.pending_since_ns = None
        self.refractory_until_ns = 0
        self.awaiting_rest = False

    def update(
        self, label: str, scores: dict[str, float], quality: float, now_ns: int
    ) -> tuple[str, float]:
        if quality < self.quality_threshold:
            self.pending_label = None
            self.pending_since_ns = None
            self.committed = "unknown"
            self.committed_confidence = 0.0
            return self.committed, self.committed_confidence

        if label != self.pending_label:
            self.pending_label = label
            self.pending_since_ns = now_ns
            return self.committed, self.committed_confidence

        assert self.pending_since_ns is not None
        dwell_ns = int(self.dwell_ms * 1_000_000)
        if now_ns - self.pending_since_ns < dwell_ns:
            return self.committed, self.committed_confidence

        confidence = float(scores.get(label, 0.0))
        runner_up = max((value for key, value in scores.items() if key != label), default=0.0)
        if confidence < self.confidence_threshold:
            return self.committed, self.committed_confidence
        if label in {"confirm", "cancel"} and (confidence - runner_up) < self.hysteresis:
            return self.committed, self.committed_confidence
        if label in {"confirm", "cancel"} and now_ns < self.refractory_until_ns:
            return self.committed, self.committed_confidence
        if label in {"confirm", "cancel"} and self.awaiting_rest:
            return self.committed, self.committed_confidence

        if label in {"confirm", "cancel"}:
            self.committed = label
            self.committed_confidence = confidence
            self.awaiting_rest = True
            self.refractory_until_ns = now_ns + int(self.refractory_ms * 1_000_000)
        elif label == "rest":
            self.committed = "rest"
            self.committed_confidence = confidence
            self.awaiting_rest = False
        else:
            self.committed = "unknown"
            self.committed_confidence = confidence
        return self.committed, self.committed_confidence
