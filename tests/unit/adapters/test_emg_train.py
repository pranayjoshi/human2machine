from __future__ import annotations

from pathlib import Path

import numpy as np
from ganglion_adapter.dataset import generate_labeled_windows
from ganglion_adapter.features import (
    random_window_split_leaks,
    split_by_block,
    validate_split_no_leak,
)
from ganglion_adapter.live_inference import GestureClassifier, LiveSmoother
from ganglion_adapter.model import load_model
from ganglion_adapter.train import (
    CROSS_BLOCK_GATE,
    persist_train_result,
    temporal_holdout,
    train_from_synthetic,
)


def test_grouped_split_used_for_training() -> None:
    examples = generate_labeled_windows(seed=7, session_id="day1")
    train, test = split_by_block(examples, {"block_random"})
    validate_split_no_leak(train, test)
    assert train
    assert test
    assert {item.block_id for item in test} == {"block_random"}


def test_random_overlapping_split_is_rejected() -> None:
    examples = [
        item for item in generate_labeled_windows(seed=3) if item.block_id == "block_confirm"
    ]
    rng = np.random.default_rng(3)
    assert random_window_split_leaks(examples, rng)


def test_temporal_holdout_does_not_leak() -> None:
    examples = generate_labeled_windows(seed=5)
    train, test = temporal_holdout(examples)
    validate_split_no_leak(train, test)
    assert train and test


def test_train_writes_versioned_artifacts(tmp_path: Path) -> None:
    result = train_from_synthetic(seed=7, model_id="emg-test-v1")
    directory = persist_train_result(result, tmp_path)
    for name in (
        "model.joblib",
        "metadata.json",
        "feature_config.yaml",
        "metrics.json",
        "training_session_ids.json",
    ):
        assert (directory / name).exists(), name
    loaded = load_model(directory)
    assert loaded.model_id == "emg-test-v1"
    assert loaded.metadata["class_definitions"]["confirm"] == "gentle wrist flexion"
    assert result.metrics["split_method"] == "grouped_by_recording_block"


def test_cross_block_balanced_accuracy_gate() -> None:
    result = train_from_synthetic(seed=7)
    ba = float(result.metrics["cross_block_balanced_accuracy"])
    assert ba >= CROSS_BLOCK_GATE, result.metrics
    assert result.passed_cross_block
    assert result.metrics["n_train"] > 0
    assert result.metrics["n_test"] > 0
    assert result.metrics["train_class_balance"]["rest"] > 0
    assert result.metrics["held_out"]["class_balance"]["confirm"] > 0
    assert result.metrics["held_out"]["class_balance"]["cancel"] > 0


def test_trained_classifier_still_requires_dwell() -> None:
    result = train_from_synthetic(seed=7)
    classifier = GestureClassifier(result.model)
    confirm = next(item for item in result.examples if item.label == "confirm")
    smoother = LiveSmoother(dwell_ms=200, confidence_threshold=0.5)
    raw, scores = classifier.predict(confirm.features)
    label, _conf = smoother.update(raw, scores, 0.9, now_ns=0)
    assert label == "rest"
    label, _conf = smoother.update(raw, scores, 0.9, now_ns=50_000_000)
    assert label == "rest"
