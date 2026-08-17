"""Serialized EMG gesture models. Joblib stores a sklearn pipeline only."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import yaml
from sklearn.pipeline import Pipeline

from ganglion_adapter.features import FEATURE_NAMES, feature_vector

GESTURE_CLASSES = ("rest", "confirm", "cancel")
LABELS = ("rest", "confirm", "cancel", "unknown")


def _normalize(scores: dict[str, float]) -> dict[str, float]:
    total = sum(max(0.0, value) for value in scores.values()) or 1.0
    out = {key: max(0.0, min(1.0, value / total)) for key, value in scores.items()}
    for label in LABELS:
        out.setdefault(label, 0.0)
    return out


@dataclass
class EmgModel:
    pipeline: Pipeline
    feature_names: tuple[str, ...]
    classes: tuple[str, ...]
    model_id: str
    estimator_name: str
    metadata: dict[str, Any]

    def predict(self, features: dict[str, float]) -> tuple[str, dict[str, float]]:
        vector = feature_vector(features, self.feature_names).reshape(1, -1)
        if hasattr(self.pipeline, "predict_proba"):
            proba = self.pipeline.predict_proba(vector)[0]
            class_labels = [str(item) for item in self.pipeline.classes_]
        else:
            predicted = str(self.pipeline.predict(vector)[0])
            proba = np.array(
                [1.0 if item == predicted else 0.0 for item in self.classes],
                dtype=float,
            )
            class_labels = list(self.classes)
        scores = {label: 0.0 for label in LABELS}
        for label, value in zip(class_labels, proba, strict=False):
            scores[label] = float(value)
        ranked = [label for label in self.classes if label in scores]
        label = max(ranked, key=lambda name: scores.get(name, 0.0), default="unknown")
        return label, _normalize(scores)


def save_model(
    model: EmgModel,
    directory: Path,
    *,
    feature_config: dict[str, Any],
    metrics: dict[str, Any],
    training_session_ids: list[str],
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {
            "pipeline": model.pipeline,
            "feature_names": list(model.feature_names),
            "classes": list(model.classes),
            "model_id": model.model_id,
            "estimator_name": model.estimator_name,
        },
        directory / "model.joblib",
    )
    (directory / "metadata.json").write_text(json.dumps(model.metadata, indent=2) + "\n")
    (directory / "feature_config.yaml").write_text(yaml.safe_dump(feature_config, sort_keys=False))
    (directory / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
    (directory / "training_session_ids.json").write_text(
        json.dumps({"session_ids": training_session_ids}, indent=2) + "\n"
    )
    return directory


def load_model(directory: Path) -> EmgModel:
    payload = joblib.load(directory / "model.joblib")
    metadata_path = directory / "metadata.json"
    metadata = json.loads(metadata_path.read_text()) if metadata_path.exists() else {}
    return EmgModel(
        pipeline=payload["pipeline"],
        feature_names=tuple(payload.get("feature_names") or FEATURE_NAMES),
        classes=tuple(payload.get("classes") or GESTURE_CLASSES),
        model_id=str(payload.get("model_id") or directory.name),
        estimator_name=str(payload.get("estimator_name") or "unknown"),
        metadata=metadata,
    )


def write_current_pointer(
    models_dir: Path, model_id: str, metrics: dict[str, Any] | None = None
) -> Path:
    models_dir.mkdir(parents=True, exist_ok=True)
    pointer = {
        "model_id": model_id,
        "promoted_at": datetime.now(UTC).isoformat(),
        "metrics": metrics or {},
    }
    path = models_dir / "current.json"
    path.write_text(json.dumps(pointer, indent=2) + "\n")
    return path


def read_current_pointer(models_dir: Path) -> dict[str, Any] | None:
    path = models_dir / "current.json"
    if not path.exists():
        return None
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict) or not payload.get("model_id"):
        return None
    return payload


def load_current_model(models_dir: Path) -> EmgModel | None:
    pointer = read_current_pointer(models_dir)
    if pointer is None:
        return None
    directory = models_dir / str(pointer["model_id"])
    if not (directory / "model.joblib").exists():
        return None
    return load_model(directory)


def pointer_mtime(models_dir: Path) -> float | None:
    path = models_dir / "current.json"
    if not path.exists():
        return None
    return path.stat().st_mtime
