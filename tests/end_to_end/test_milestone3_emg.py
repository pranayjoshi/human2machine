"""Milestone 3: personalized EMG rest/confirm/cancel with grouped splits and smoothing."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from ganglion_adapter.dataset import generate_labeled_windows
from ganglion_adapter.features import split_by_block, validate_split_no_leak
from ganglion_adapter.live_inference import GestureClassifier, LiveSmoother
from ganglion_adapter.mock import GanglionMockRuntime
from ganglion_adapter.model import write_current_pointer
from ganglion_adapter.train import (
    CANCEL_LATENCY_GATE_MS,
    CROSS_BLOCK_GATE,
    CROSS_SESSION_GATE,
    evaluate_examples,
    measure_cancel_latency_ms,
    measure_false_triggers,
    persist_train_result,
    train_from_synthetic,
)
from intent_contracts.validation import parse_unnormalized_event

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from eval_emg_gestures import evaluate_milestone3  # noqa: E402


def test_cross_block_and_cross_session_gates(tmp_path: Path) -> None:
    result = train_from_synthetic(seed=7, session_id="synthetic_day1", model_id="emg-day1")
    persist_train_result(result, tmp_path)
    write_current_pointer(tmp_path, result.model.model_id, result.metrics)
    assert result.metrics["cross_block_balanced_accuracy"] >= CROSS_BLOCK_GATE, result.metrics
    assert result.metrics["split_method"] == "grouped_by_recording_block"

    day2 = generate_labeled_windows(
        seed=21,
        session_id="synthetic_day2",
        electrode_shift=0.15,
        fatigue=0.08,
    )
    cross = evaluate_examples(result.model, day2)
    assert cross["n"] > 0
    assert cross["balanced_accuracy"] >= CROSS_SESSION_GATE, cross
    assert cross["split_method"] == "grouped_by_block"


def test_false_trigger_rate_is_measured() -> None:
    result = train_from_synthetic(seed=7)
    report = measure_false_triggers(result.model, duration_s=60.0, seed=11)
    payload = report.to_dict()
    assert payload["n_windows"] > 0
    assert payload["duration_s"] == 60.0
    assert "false_confirm_per_10min" in payload
    assert "false_cancel_per_10min" in payload
    assert payload["false_confirm_per_10min"] < 5.0, payload
    assert payload["false_cancel_per_10min"] < 5.0, payload


def test_cancel_latency_under_500ms() -> None:
    result = train_from_synthetic(seed=7)
    latency = measure_cancel_latency_ms(result.model)
    assert latency <= CANCEL_LATENCY_GATE_MS, latency


def test_predictions_use_dwell_not_single_windows() -> None:
    result = train_from_synthetic(seed=7)
    classifier = GestureClassifier(result.model)
    smoother = LiveSmoother(dwell_ms=200, confidence_threshold=0.5)
    confirm = next(item for item in result.examples if item.label == "confirm")
    raw, scores = classifier.predict(confirm.features)
    first, _ = smoother.update(raw, scores, 0.95, now_ns=0)
    second, _ = smoother.update(raw, scores, 0.95, now_ns=80_000_000)
    assert first == "rest"
    assert second == "rest"


def test_live_runtime_loads_promoted_model(tmp_path: Path) -> None:
    result = train_from_synthetic(seed=7, model_id="emg-live-v1")
    persist_train_result(result, tmp_path)
    write_current_pointer(tmp_path, result.model.model_id, result.metrics)
    runtime = GanglionMockRuntime(seed=7, models_dir=tmp_path, shadow_only=True)
    events = []
    for _ in range(40):
        events.extend(runtime.tick())
    features = [event for event in events if event.event_type == "modality.feature"]
    assert features
    assert features[0].payload["model_id"] == "emg-live-v1"
    for event in events:
        parse_unnormalized_event(event.to_unnormalized_dict())


def test_eval_script_gates(tmp_path: Path) -> None:
    report = evaluate_milestone3(tmp_path)
    assert report["ok"], report
    assert report["cross_block_balanced_accuracy"] >= CROSS_BLOCK_GATE
    assert report["cross_session_balanced_accuracy"] >= CROSS_SESSION_GATE
    assert report["cancel_latency_ms"] <= CANCEL_LATENCY_GATE_MS
    assert (tmp_path / report["model_id"] / "metrics.json").exists()
    metrics = json.loads((tmp_path / report["model_id"] / "metrics.json").read_text())
    assert metrics["n_train"] >= 1


def test_held_out_block_has_no_overlap() -> None:
    examples = generate_labeled_windows(seed=9)
    train, test = split_by_block(examples, {"block_random"})
    validate_split_no_leak(train, test)
