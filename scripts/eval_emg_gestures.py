#!/usr/bin/env python3
"""Evaluate personalized EMG models on synthetic grouped-split sessions.

Does not open a Ganglion. Hardware calibration remains operator-run.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for extra in (
    ROOT / "packages/contracts-python/src",
    ROOT / "packages/runtime-python/src",
    ROOT / "services/ganglion-adapter",
):
    path = str(extra)
    if path not in sys.path:
        sys.path.insert(0, path)

from ganglion_adapter.dataset import generate_labeled_windows  # noqa: E402
from ganglion_adapter.train import (  # noqa: E402
    CANCEL_LATENCY_GATE_MS,
    CROSS_BLOCK_GATE,
    CROSS_SESSION_GATE,
    evaluate_examples,
    measure_cancel_latency_ms,
    measure_false_triggers,
    persist_train_result,
    train_from_synthetic,
)


def evaluate_milestone3(models_dir: Path, *, false_trigger_seconds: float = 60.0) -> dict[str, Any]:
    result = train_from_synthetic(
        seed=7, session_id="synthetic_day1", model_id="emg-eval-synthetic"
    )
    persist_train_result(result, models_dir)
    day2 = generate_labeled_windows(
        seed=21,
        session_id="synthetic_day2",
        electrode_shift=0.15,
        fatigue=0.08,
    )
    cross = evaluate_examples(result.model, day2)
    false_trigger = measure_false_triggers(result.model, duration_s=false_trigger_seconds, seed=11)
    latency = measure_cancel_latency_ms(result.model)
    report = {
        "model_id": result.model.model_id,
        "estimator": result.model.estimator_name,
        "split_method": result.metrics["split_method"],
        "n_train": result.metrics["n_train"],
        "n_test": result.metrics["n_test"],
        "train_class_balance": result.metrics["train_class_balance"],
        "test_class_balance": result.metrics["test_class_balance"],
        "cross_block_balanced_accuracy": result.metrics["cross_block_balanced_accuracy"],
        "cross_session_balanced_accuracy": cross["balanced_accuracy"],
        "cross_session_n": cross["n"],
        "cross_session_class_balance": cross["class_balance"],
        "false_trigger": false_trigger.to_dict(),
        "cancel_latency_ms": latency,
        "gates": {
            "cross_block_balanced_accuracy": CROSS_BLOCK_GATE,
            "cross_session_balanced_accuracy": CROSS_SESSION_GATE,
            "cancel_latency_ms": CANCEL_LATENCY_GATE_MS,
        },
        "ok": (
            float(result.metrics["cross_block_balanced_accuracy"]) >= CROSS_BLOCK_GATE
            and float(cross["balanced_accuracy"]) >= CROSS_SESSION_GATE
            and latency <= CANCEL_LATENCY_GATE_MS
        ),
    }
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate synthetic EMG personalization gates")
    parser.add_argument(
        "--models-dir",
        type=Path,
        default=ROOT / "data" / "runtime" / "emg-eval",
        help="Where to write the evaluation model artifacts",
    )
    parser.add_argument("--false-trigger-seconds", type=float, default=60.0)
    args = parser.parse_args(argv)
    args.models_dir.mkdir(parents=True, exist_ok=True)
    report = evaluate_milestone3(args.models_dir, false_trigger_seconds=args.false_trigger_seconds)
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
