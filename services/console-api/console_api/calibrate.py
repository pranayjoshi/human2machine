"""EMG calibration protocol stub: record phase, do not train a model."""

from __future__ import annotations

from typing import Any

EMG_PHASES = ("idle", "rest", "confirm", "cancel", "false_trigger", "complete")

PHASE_INSTRUCTIONS = {
    "idle": "Start the protocol when electrodes are seated and the Ganglion is streaming.",
    "rest": "Rest 30 seconds. Forearm relaxed. Do not flex or extend.",
    "confirm": "Gentle wrist flexion. Repeat 20 times. Comfortable, not maximal.",
    "cancel": "Gentle wrist extension. Repeat 20 times. Comfortable, not maximal.",
    "false_trigger": (
        "Keep the arm at rest. Watch for false confirm/cancel labels. "
        "A 10-minute rest trial is required before trusting EMG in a demo. "
        "EEG is not used in this calibration."
    ),
    "complete": (
        "Protocol complete. Promote a model only after held-out metrics, not from this stub."
    ),
}

PHASE_TARGETS = {
    "rest": {"seconds": 30, "count": 0},
    "confirm": {"seconds": 0, "count": 20},
    "cancel": {"seconds": 0, "count": 20},
    "false_trigger": {"seconds": 0, "count": 0},
}


class EmgCalibrationStub:
    def __init__(self) -> None:
        self.phase = "idle"
        self.counts = {"rest": 0, "confirm": 0, "cancel": 0}

    def status(self) -> dict[str, Any]:
        target = PHASE_TARGETS.get(self.phase, {"seconds": 0, "count": 0})
        return {
            "ok": True,
            "protocol": "emg",
            "phase": self.phase,
            "counts": dict(self.counts),
            "target_seconds": target["seconds"],
            "target_count": target["count"],
            "instruction": PHASE_INSTRUCTIONS[self.phase],
            "eeg_used": False,
            "training_job": None,
        }

    def start(self) -> dict[str, Any]:
        self.phase = "rest"
        self.counts = {"rest": 0, "confirm": 0, "cancel": 0}
        return self.status()

    def record(self) -> dict[str, Any]:
        if self.phase in self.counts:
            self.counts[self.phase] += 1
        return self.status()

    def next_phase(self) -> dict[str, Any]:
        order = EMG_PHASES[1:]
        if self.phase == "idle":
            return self.start()
        if self.phase in order:
            index = order.index(self.phase)
            self.phase = order[min(index + 1, len(order) - 1)]
        return self.status()
