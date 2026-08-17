"""EMG calibration protocol: collect labeled windows, train, false-trigger, promote."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import numpy as np
from ganglion_adapter.dataset import (
    generate_gesture_burst,
    generate_labeled_windows,
    rest_trial_script,
)
from ganglion_adapter.features import LabeledExample, WindowBuffer, extract_window_features
from ganglion_adapter.filters import CausalEmgFilter
from ganglion_adapter.model import load_model, read_current_pointer, write_current_pointer
from ganglion_adapter.train import (
    CROSS_BLOCK_GATE,
    class_balance,
    measure_false_triggers,
    persist_train_result,
    train_emg_model,
)

EMG_PHASES = ("idle", "rest", "confirm", "cancel", "random", "train", "false_trigger", "complete")

PHASE_INSTRUCTIONS = {
    "idle": "Start the protocol when electrodes are seated and the Ganglion is streaming.",
    "rest": "Rest. Forearm relaxed. Do not flex or extend. A 30-second rest block is collected.",
    "confirm": (
        "Gentle wrist flexion. Repeat 20 times. Comfortable, not maximal. "
        "Click record for each repetition."
    ),
    "cancel": (
        "Gentle wrist extension. Repeat 20 times. Comfortable, not maximal. "
        "Click record for each repetition."
    ),
    "random": "Randomized block. Perform the prompted gesture, then record.",
    "train": "Labeled windows are ready. Train a model. Promotion requires held-out metrics.",
    "false_trigger": (
        "Keep the arm at rest or make ordinary movement. "
        "A 10-minute rest trial measures false confirm/cancel commits. "
        "EEG is not used in this calibration."
    ),
    "complete": (
        "Protocol complete. Promote only if cross-block balanced accuracy meets the gate "
        "and the false-trigger trial has been measured."
    ),
}

PHASE_TARGETS = {
    "rest": {"seconds": 30, "count": 0},
    "confirm": {"seconds": 0, "count": 20},
    "cancel": {"seconds": 0, "count": 20},
    "random": {"seconds": 0, "count": 20},
    "false_trigger": {"seconds": 600, "count": 0},
}


class EmgCalibrationSession:
    def __init__(
        self,
        *,
        mock: bool = True,
        models_dir: Path | None = None,
        config: dict[str, Any] | None = None,
        repo_root: Path | None = None,
    ) -> None:
        cfg = config or {}
        self.mock = mock
        self.models_dir = Path(models_dir) if models_dir is not None else Path("models/emg")
        self.repo_root = repo_root
        self.rest_seconds = float(cfg.get("rest_seconds", 30))
        self.gesture_repetitions = int(cfg.get("gesture_repetitions", 20))
        self.random_repetitions = int(cfg.get("random_block_repetitions", 20))
        self.gesture_capture_ms = float(cfg.get("gesture_capture_ms", 1500))
        self.false_trigger_seconds = float(cfg.get("false_trigger_seconds", 600))
        self.sample_rate_hz = float(cfg.get("sample_rate_hz", 200))
        self.window_ms = float(cfg.get("window_ms", 250))
        self.hop_ms = float(cfg.get("hop_ms", 50))
        self.promote_ba = float(cfg.get("promote_cross_block_balanced_accuracy", CROSS_BLOCK_GATE))
        self.phase = "idle"
        self.counts = {"rest": 0, "confirm": 0, "cancel": 0, "random": 0}
        self.examples: list[LabeledExample] = []
        self.session_id = "emg-calibration"
        self.training_job: str | None = None
        self.metrics: dict[str, Any] | None = None
        self.false_trigger: dict[str, Any] | None = None
        self.candidate_model_id: str | None = None
        self.promoted_model_id: str | None = None
        self.train_error: str | None = None
        self.prompt_label: str | None = None
        self._random_queue: list[str] = []
        self._phase_started_mono = 0.0
        self._capturing = False
        self._capture_until_mono = 0.0
        self._capture_label = "rest"
        self._capture_block = "block_rest"
        self._filters = CausalEmgFilter(sample_rate_hz=self.sample_rate_hz)
        self._windows = WindowBuffer(
            int(round(self.sample_rate_hz * self.window_ms / 1000.0)),
            int(round(self.sample_rate_hz * self.hop_ms / 1000.0)),
        )
        self._rng = np.random.default_rng(7)
        self._seed = 7

    def status(self) -> dict[str, Any]:
        target = PHASE_TARGETS.get(self.phase, {"seconds": 0, "count": 0})
        if self.phase == "rest":
            target = {"seconds": int(self.rest_seconds), "count": 0}
        elif self.phase == "confirm":
            target = {"seconds": 0, "count": self.gesture_repetitions}
        elif self.phase == "cancel":
            target = {"seconds": 0, "count": self.gesture_repetitions}
        elif self.phase == "random":
            target = {"seconds": 0, "count": self.random_repetitions}
        elif self.phase == "false_trigger":
            target = {"seconds": int(self.false_trigger_seconds), "count": 0}
        instruction = PHASE_INSTRUCTIONS[self.phase]
        if self.phase == "random" and self.prompt_label:
            instruction = f"Prompted gesture: {self.prompt_label.upper()}. Perform it, then record."
        elapsed = 0.0
        if self.phase in {"rest", "false_trigger"} and self._phase_started_mono:
            elapsed = max(0.0, time.monotonic() - self._phase_started_mono)
        remaining = max(0.0, float(target["seconds"]) - elapsed) if target["seconds"] else 0.0
        current = read_current_pointer(self.models_dir)
        return {
            "ok": True,
            "protocol": "emg",
            "phase": self.phase,
            "counts": dict(self.counts),
            "target_seconds": target["seconds"],
            "target_count": target["count"],
            "instruction": instruction,
            "eeg_used": False,
            "training_job": self.training_job,
            "class_balance": class_balance(self.examples),
            "window_count": len(self.examples),
            "prompt_label": self.prompt_label,
            "capturing": self._capturing,
            "elapsed_seconds": elapsed,
            "remaining_seconds": remaining,
            "metrics": self.metrics,
            "false_trigger": self.false_trigger,
            "candidate_model_id": self.candidate_model_id,
            "promoted_model_id": self.promoted_model_id,
            "current_model_id": None if current is None else current.get("model_id"),
            "can_promote": self._can_promote(),
            "train_error": self.train_error,
        }

    def start(self) -> dict[str, Any]:
        self.phase = "rest"
        self.counts = {"rest": 0, "confirm": 0, "cancel": 0, "random": 0}
        self.examples = []
        self.training_job = None
        self.metrics = None
        self.false_trigger = None
        self.candidate_model_id = None
        self.promoted_model_id = None
        self.train_error = None
        self.prompt_label = None
        self._random_queue = []
        self._reset_capture_pipeline()
        self._phase_started_mono = time.monotonic()
        self._capturing = True
        self._capture_label = "rest"
        self._capture_block = "block_rest"
        self._capture_until_mono = self._phase_started_mono + self.rest_seconds
        if self.mock:
            rest = generate_labeled_windows(
                rest_trial_script(
                    duration_s=self.rest_seconds,
                    session_id=self.session_id,
                    ordinary_every_s=self.rest_seconds + 1,
                ),
                seed=self._seed,
                session_id=self.session_id,
            )
            for example in rest:
                self.examples.append(
                    LabeledExample(
                        block_id="block_rest",
                        session_id=self.session_id,
                        label="rest",
                        start_idx=example.start_idx,
                        end_idx=example.end_idx,
                        features=example.features,
                        quality=example.quality,
                        start_ns=example.start_ns,
                        end_ns=example.end_ns,
                    )
                )
            self.counts["rest"] = len(self.examples)
            self._capturing = False
        return self.status()

    def record(self) -> dict[str, Any]:
        if self.phase == "confirm":
            return self._record_gesture("confirm", "block_confirm")
        if self.phase == "cancel":
            return self._record_gesture("cancel", "block_cancel")
        if self.phase == "random":
            label = self.prompt_label or "confirm"
            status = self._record_gesture(label, "block_random", count_key="random")
            self._advance_prompt()
            return status
        return self.status()

    def next_phase(self) -> dict[str, Any]:
        order = EMG_PHASES[1:]
        if self.phase == "idle":
            return self.start()
        if self.phase not in order:
            return self.status()
        index = order.index(self.phase)
        nxt = order[min(index + 1, len(order) - 1)]
        self._enter_phase(nxt)
        return self.status()

    def train(self) -> dict[str, Any]:
        if self.phase not in {"train", "random", "cancel", "false_trigger", "complete"}:
            return {**self.status(), "ok": False, "train_error": "finish labeling before training"}
        if self.phase == "random":
            self._enter_phase("train")
        self.training_job = "running"
        self.train_error = None
        try:
            result = train_emg_model(
                list(self.examples),
                repo_root=self.repo_root,
                sample_rate_hz=self.sample_rate_hz,
                window_ms=self.window_ms,
                hop_ms=self.hop_ms,
            )
            persist_train_result(result, self.models_dir)
            self.metrics = result.metrics
            self.candidate_model_id = result.model.model_id
            self.training_job = "complete"
            if self.phase != "complete":
                self.phase = "train"
        except Exception as exc:
            self.training_job = "failed"
            self.train_error = str(exc)
            return {**self.status(), "ok": False}
        return self.status()

    def run_false_trigger(self, *, duration_s: float | None = None) -> dict[str, Any]:
        if self.candidate_model_id is None:
            return {
                **self.status(),
                "ok": False,
                "train_error": "train a model before the false-trigger trial",
            }
        seconds = float(duration_s if duration_s is not None else self.false_trigger_seconds)
        if self.mock and seconds > 60:
            seconds = 60.0
        model = load_model(self.models_dir / self.candidate_model_id)
        report = measure_false_triggers(model, duration_s=seconds, seed=self._seed + 3)
        self.false_trigger = report.to_dict()
        if self.metrics is not None:
            self.metrics = {**self.metrics, "false_trigger": self.false_trigger}
            metrics_path = self.models_dir / self.candidate_model_id / "metrics.json"
            if metrics_path.exists():
                metrics_path.write_text(json.dumps(self.metrics, indent=2) + "\n")
        self.phase = "false_trigger"
        return self.status()

    def promote(self) -> dict[str, Any]:
        if not self._can_promote() or not self.candidate_model_id:
            return {
                **self.status(),
                "ok": False,
                "train_error": "held-out metrics and a false-trigger trial are required",
            }
        write_current_pointer(self.models_dir, self.candidate_model_id, self.metrics or {})
        self.promoted_model_id = self.candidate_model_id
        self.phase = "complete"
        return self.status()

    def ingest_chunk(
        self,
        samples: list[list[float]] | np.ndarray,
        *,
        sample_rate_hz: float,
        source_time_ns: int | None,
        quality: float,
    ) -> None:
        if self.mock or not self._capturing:
            return
        if self.phase not in {"rest", "confirm", "cancel", "random", "false_trigger"}:
            return
        if (
            self.phase in {"confirm", "cancel", "random"}
            and time.monotonic() > self._capture_until_mono
        ):
            self._capturing = False
            return
        data = np.asarray(samples, dtype=float)
        if data.ndim != 2:
            return
        filtered = self._filters.process(data)
        first_ns = int(source_time_ns or 0)
        windows = self._windows.push(
            filtered, first_ns, sample_rate_hz, block_id=self._capture_block
        )
        for window in windows:
            example = LabeledExample(
                block_id=self._capture_block,
                session_id=self.session_id,
                label=self._capture_label,
                start_idx=window.start_idx,
                end_idx=window.end_idx,
                features=window.features or extract_window_features(window.samples),
                quality=quality,
                start_ns=window.start_ns,
                end_ns=window.end_ns,
            )
            self.examples.append(example)
            if self.phase == "rest":
                self.counts["rest"] = sum(
                    1 for item in self.examples if item.block_id == "block_rest"
                )

    def _record_gesture(
        self, label: str, block_id: str, count_key: str | None = None
    ) -> dict[str, Any]:
        key = count_key or label
        if self.mock:
            burst = generate_gesture_burst(
                label,
                duration_s=self.gesture_capture_ms / 1000.0,
                seed=int(self._rng.integers(1, 10_000)),
                block_id=block_id,
                session_id=self.session_id,
            )
            self.examples.extend(burst)
        else:
            self._reset_capture_pipeline()
            self._capturing = True
            self._capture_label = label
            self._capture_block = block_id
            self._capture_until_mono = time.monotonic() + self.gesture_capture_ms / 1000.0
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.status()

    def _enter_phase(self, phase: str) -> None:
        self.phase = phase
        self._capturing = False
        self.prompt_label = None
        self._phase_started_mono = time.monotonic()
        if phase == "rest":
            self._capturing = True
            self._capture_label = "rest"
            self._capture_block = "block_rest"
        elif phase == "random":
            labels = ["confirm"] * (self.random_repetitions // 2) + ["cancel"] * (
                self.random_repetitions - self.random_repetitions // 2
            )
            self._rng.shuffle(labels)
            self._random_queue = labels
            self._advance_prompt()
        elif phase == "false_trigger":
            self._capturing = not self.mock
            self._capture_label = "rest"
            self._capture_block = "block_false_trigger"
            self._capture_until_mono = time.monotonic() + self.false_trigger_seconds

    def _advance_prompt(self) -> None:
        if self._random_queue:
            self.prompt_label = self._random_queue.pop(0)
        else:
            self.prompt_label = None

    def _can_promote(self) -> bool:
        if not self.candidate_model_id or not self.metrics:
            return False
        ba = float(self.metrics.get("cross_block_balanced_accuracy") or 0.0)
        return ba >= self.promote_ba and self.false_trigger is not None

    def _reset_capture_pipeline(self) -> None:
        self._filters = CausalEmgFilter(sample_rate_hz=self.sample_rate_hz)
        self._windows = WindowBuffer(
            int(round(self.sample_rate_hz * self.window_ms / 1000.0)),
            int(round(self.sample_rate_hz * self.hop_ms / 1000.0)),
        )


EmgCalibrationStub = EmgCalibrationSession
