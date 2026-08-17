"""Offline EMG training. Grouped by recording block; never randomly split overlapping windows."""

from __future__ import annotations

import subprocess
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import balanced_accuracy_score, confusion_matrix
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from ganglion_adapter.dataset import GESTURE_LABELS, generate_labeled_windows, rest_trial_script
from ganglion_adapter.features import (
    FEATURE_NAMES,
    LabeledExample,
    feature_vector,
    split_by_block,
    validate_split_no_leak,
)
from ganglion_adapter.live_inference import LiveSmoother
from ganglion_adapter.model import EmgModel, save_model

CROSS_BLOCK_GATE = 0.90
CROSS_SESSION_GATE = 0.85
CANCEL_LATENCY_GATE_MS = 500.0
HELD_OUT_BLOCK = "block_random"


def temporal_holdout(
    examples: list[LabeledExample], fraction: float = 0.3
) -> tuple[list[LabeledExample], list[LabeledExample]]:
    """Per-block later-window holdout that drops the overlapping cut region."""
    train: list[LabeledExample] = []
    test: list[LabeledExample] = []
    grouped: dict[str, list[LabeledExample]] = {}
    for example in examples:
        grouped.setdefault(example.block_id, []).append(example)
    for items in grouped.values():
        ordered = sorted(items, key=lambda item: item.start_idx)
        if len(ordered) < 4:
            train.extend(ordered)
            continue
        cut = max(1, min(len(ordered) - 1, int(round(len(ordered) * (1.0 - fraction)))))
        cut_start = ordered[cut].start_idx
        for item in ordered:
            if item.end_idx <= cut_start:
                train.append(item)
            elif item.start_idx >= cut_start:
                test.append(item)
    validate_split_no_leak(train, test)
    return train, test


def git_commit(root: Path | None = None) -> str:
    try:
        output = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=root or Path.cwd(),
            text=True,
            timeout=2,
        )
        return output.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def class_balance(examples: list[LabeledExample]) -> dict[str, int]:
    counts = Counter(example.label for example in examples)
    return {label: int(counts.get(label, 0)) for label in GESTURE_LABELS}


def _matrix(
    examples: list[LabeledExample], names: tuple[str, ...] = FEATURE_NAMES
) -> tuple[np.ndarray, np.ndarray]:
    x = np.vstack([feature_vector(example.features, names) for example in examples])
    y = np.asarray([example.label for example in examples])
    return x, y


def _estimators() -> dict[str, Any]:
    return {
        "logistic_regression": LogisticRegression(
            max_iter=400,
            class_weight="balanced",
            solver="lbfgs",
        ),
        "lda": LinearDiscriminantAnalysis(),
        "random_forest": RandomForestClassifier(
            n_estimators=80,
            max_depth=8,
            min_samples_leaf=4,
            class_weight="balanced",
            random_state=7,
        ),
    }


def _pipeline(estimator: Any) -> Pipeline:
    return Pipeline([("scaler", StandardScaler()), ("clf", estimator)])


def _confusion(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, dict[str, int]]:
    labels = list(GESTURE_LABELS)
    matrix = confusion_matrix(y_true, y_pred, labels=labels)
    return {
        actual: {predicted: int(matrix[i, j]) for j, predicted in enumerate(labels)}
        for i, actual in enumerate(labels)
    }


@dataclass
class FalseTriggerReport:
    duration_s: float
    n_windows: int
    confirm_commits: int
    cancel_commits: int
    unknown_windows: int

    @property
    def false_confirm_per_10min(self) -> float:
        return self.confirm_commits * 600.0 / max(self.duration_s, 1e-9)

    @property
    def false_cancel_per_10min(self) -> float:
        return self.cancel_commits * 600.0 / max(self.duration_s, 1e-9)

    def to_dict(self) -> dict[str, Any]:
        return {
            "duration_s": self.duration_s,
            "n_windows": self.n_windows,
            "confirm_commits": self.confirm_commits,
            "cancel_commits": self.cancel_commits,
            "unknown_windows": self.unknown_windows,
            "false_confirm_per_10min": self.false_confirm_per_10min,
            "false_cancel_per_10min": self.false_cancel_per_10min,
        }


@dataclass
class TrainResult:
    model: EmgModel
    metrics: dict[str, Any]
    feature_config: dict[str, Any]
    training_session_ids: list[str]
    examples: list[LabeledExample] = field(default_factory=list)

    @property
    def passed_cross_block(self) -> bool:
        return float(self.metrics.get("cross_block_balanced_accuracy") or 0.0) >= CROSS_BLOCK_GATE


def evaluate_examples(model: EmgModel, examples: list[LabeledExample]) -> dict[str, Any]:
    if not examples:
        return {
            "n": 0,
            "balanced_accuracy": 0.0,
            "confusion_matrix": {},
            "class_balance": class_balance([]),
        }
    _x, y_true = _matrix(examples, model.feature_names)
    predicted = [model.predict(example.features)[0] for example in examples]
    y_pred = np.asarray(predicted)
    return {
        "n": len(examples),
        "balanced_accuracy": float(balanced_accuracy_score(y_true, y_pred)),
        "confusion_matrix": _confusion(y_true, y_pred),
        "class_balance": class_balance(examples),
        "split_method": "grouped_by_block",
    }


def measure_false_triggers(
    model: EmgModel,
    *,
    duration_s: float = 600.0,
    seed: int = 11,
    dwell_ms: float = 200.0,
    cancel_dwell_ms: float = 150.0,
    hysteresis: float = 0.12,
    refractory_ms: float = 400.0,
    confidence_threshold: float = 0.7,
    electrode_shift: float = 0.0,
) -> FalseTriggerReport:
    examples = generate_labeled_windows(
        rest_trial_script(duration_s=duration_s, session_id="false_trigger"),
        seed=seed,
        electrode_shift=electrode_shift,
    )
    smoother = LiveSmoother(
        dwell_ms=dwell_ms,
        cancel_dwell_ms=cancel_dwell_ms,
        hysteresis=hysteresis,
        refractory_ms=refractory_ms,
        confidence_threshold=confidence_threshold,
    )
    confirm_commits = 0
    cancel_commits = 0
    unknown_windows = 0
    committed = "rest"
    for example in examples:
        raw, scores = model.predict(example.features)
        label, _conf = smoother.update(raw, scores, example.quality, example.end_ns)
        if label == "unknown":
            unknown_windows += 1
        if label != committed and label in {"confirm", "cancel"}:
            if label == "confirm":
                confirm_commits += 1
            else:
                cancel_commits += 1
        committed = label
    return FalseTriggerReport(
        duration_s=duration_s,
        n_windows=len(examples),
        confirm_commits=confirm_commits,
        cancel_commits=cancel_commits,
        unknown_windows=unknown_windows,
    )


def measure_cancel_latency_ms(
    model: EmgModel,
    *,
    seed: int = 13,
    dwell_ms: float = 200.0,
    cancel_dwell_ms: float = 150.0,
) -> float:
    from ganglion_adapter.dataset import ScriptEvent

    examples = generate_labeled_windows(
        [
            ScriptEvent("rest", 1.0, "lat_rest", "latency"),
            ScriptEvent("cancel", 1.5, "lat_cancel", "latency"),
        ],
        seed=seed,
    )
    smoother = LiveSmoother(dwell_ms=dwell_ms, cancel_dwell_ms=cancel_dwell_ms)
    onset_ns: int | None = None
    for example in examples:
        if example.label == "cancel" and onset_ns is None:
            onset_ns = example.start_ns
        raw, scores = model.predict(example.features)
        label, _conf = smoother.update(raw, scores, example.quality, example.end_ns)
        if label == "cancel" and onset_ns is not None:
            return (example.end_ns - onset_ns) / 1_000_000.0
    return float("inf")


def train_emg_model(
    examples: list[LabeledExample],
    *,
    held_out_blocks: set[str] | None = None,
    model_id: str | None = None,
    subject_pseudonym: str = "primary",
    electrode_placement: str = "forearm flexor/extensor/pronator/aux",
    sample_rate_hz: float = 200.0,
    window_ms: float = 250.0,
    hop_ms: float = 50.0,
    bandpass_hz: tuple[float, float] = (20.0, 90.0),
    notch_hz: float = 60.0,
    repo_root: Path | None = None,
    false_trigger_seconds: float = 0.0,
    false_trigger_seed: int = 11,
) -> TrainResult:
    if not examples:
        raise ValueError("no labeled EMG windows to train on")
    labels_present = {example.label for example in examples}
    missing = [label for label in GESTURE_LABELS if label not in labels_present]
    if missing:
        raise ValueError(f"training requires rest, confirm, and cancel; missing {missing}")

    test_blocks = held_out_blocks or {HELD_OUT_BLOCK}
    if any(example.block_id in test_blocks for example in examples):
        train, test = split_by_block(examples, test_blocks)
        validate_split_no_leak(train, test)
    else:
        train, test = temporal_holdout(examples)
        test_blocks = {item.block_id for item in test}
    if not train or not test:
        raise ValueError("grouped split produced an empty train or test set")

    x_train, y_train = _matrix(train)
    best_name = ""
    best_pipeline: Pipeline | None = None
    best_ba = -1.0
    candidates: dict[str, float] = {}
    for name, estimator in _estimators().items():
        pipeline = _pipeline(estimator)
        pipeline.fit(x_train, y_train)
        probe = EmgModel(
            pipeline=pipeline,
            feature_names=FEATURE_NAMES,
            classes=GESTURE_LABELS,
            model_id="probe",
            estimator_name=name,
            metadata={},
        )
        ba = float(evaluate_examples(probe, test)["balanced_accuracy"])
        candidates[name] = ba
        if ba > best_ba:
            best_ba = ba
            best_name = name
            best_pipeline = pipeline
    if best_pipeline is None:
        raise RuntimeError("no estimator fitted")

    created = datetime.now(UTC)
    stamp = created.strftime("%Y%m%dT%H%M%SZ")
    resolved_id = model_id or f"emg-{subject_pseudonym}-{stamp}"
    metadata = {
        "model_id": resolved_id,
        "created_at": created.isoformat(),
        "code_commit": git_commit(repo_root),
        "subject_pseudonym": subject_pseudonym,
        "electrode_placement": electrode_placement,
        "sample_rate_hz": sample_rate_hz,
        "filter_settings": {"notch_hz": notch_hz, "bandpass_hz": list(bandpass_hz)},
        "window_settings": {"window_ms": window_ms, "hop_ms": hop_ms},
        "class_definitions": {
            "rest": "forearm relaxed",
            "confirm": "gentle wrist flexion",
            "cancel": "gentle wrist extension",
        },
        "estimator": best_name,
        "split_method": "grouped_by_recording_block",
        "held_out_blocks": sorted(test_blocks),
    }
    model = EmgModel(
        pipeline=best_pipeline,
        feature_names=FEATURE_NAMES,
        classes=GESTURE_LABELS,
        model_id=resolved_id,
        estimator_name=best_name,
        metadata=metadata,
    )
    held_out = evaluate_examples(model, test)
    false_trigger = None
    if false_trigger_seconds > 0:
        false_trigger = measure_false_triggers(
            model, duration_s=false_trigger_seconds, seed=false_trigger_seed
        )
    cancel_latency_ms = measure_cancel_latency_ms(model)
    metrics = {
        "estimator": best_name,
        "estimator_balanced_accuracy": candidates,
        "cross_block_balanced_accuracy": held_out["balanced_accuracy"],
        "held_out": held_out,
        "train_class_balance": class_balance(train),
        "test_class_balance": class_balance(test),
        "n_train": len(train),
        "n_test": len(test),
        "split_method": "grouped_by_recording_block",
        "held_out_blocks": sorted(test_blocks),
        "false_trigger": false_trigger.to_dict() if false_trigger is not None else None,
        "cancel_latency_ms": cancel_latency_ms,
        "gates": {
            "cross_block_balanced_accuracy": CROSS_BLOCK_GATE,
            "cross_session_balanced_accuracy": CROSS_SESSION_GATE,
            "cancel_latency_ms": CANCEL_LATENCY_GATE_MS,
        },
        "passed_cross_block": held_out["balanced_accuracy"] >= CROSS_BLOCK_GATE,
    }
    feature_config = {
        "sample_rate_hz": sample_rate_hz,
        "window_ms": window_ms,
        "hop_ms": hop_ms,
        "bandpass_hz": list(bandpass_hz),
        "notch_hz": notch_hz,
        "feature_names": list(FEATURE_NAMES),
        "classes": list(GESTURE_LABELS),
        "windowing": "causal",
        "standardize": "StandardScaler fitted on train blocks only",
    }
    session_ids = sorted({example.session_id for example in train})
    return TrainResult(
        model=model,
        metrics=metrics,
        feature_config=feature_config,
        training_session_ids=session_ids,
        examples=examples,
    )


def persist_train_result(result: TrainResult, models_dir: Path) -> Path:
    directory = models_dir / result.model.model_id
    save_model(
        result.model,
        directory,
        feature_config=result.feature_config,
        metrics=result.metrics,
        training_session_ids=result.training_session_ids,
    )
    return directory


def train_from_synthetic(
    *,
    seed: int = 7,
    session_id: str = "synthetic_day1",
    electrode_shift: float = 0.0,
    fatigue: float = 0.0,
    **kwargs,
) -> TrainResult:
    examples = generate_labeled_windows(
        seed=seed,
        session_id=session_id,
        electrode_shift=electrode_shift,
        fatigue=fatigue,
    )
    return train_emg_model(examples, **kwargs)
