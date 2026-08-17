"""Seeded synthetic EMG recordings for calibration, training, and evaluation."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from ganglion_adapter.features import LabeledExample, WindowBuffer, extract_window_features
from ganglion_adapter.filters import CausalEmgFilter

GESTURE_LABELS = ("rest", "confirm", "cancel")
LABEL_TO_INT = {name: index for index, name in enumerate(GESTURE_LABELS)}


@dataclass(frozen=True)
class ScriptEvent:
    label: str
    duration_s: float
    block_id: str
    session_id: str = "session"


def calibration_script(
    *,
    session_id: str = "session",
    rest_seconds: float = 30.0,
    gesture_repetitions: int = 20,
    gesture_s: float = 1.2,
    rest_between_s: float = 0.8,
    random_repetitions: int = 20,
    seed: int = 7,
) -> list[ScriptEvent]:
    events = [
        ScriptEvent("rest", rest_seconds, "block_rest", session_id),
    ]
    for _ in range(gesture_repetitions):
        events.append(ScriptEvent("confirm", gesture_s, "block_confirm", session_id))
        events.append(ScriptEvent("rest", rest_between_s, "block_confirm", session_id))
    for _ in range(gesture_repetitions):
        events.append(ScriptEvent("cancel", gesture_s, "block_cancel", session_id))
        events.append(ScriptEvent("rest", rest_between_s, "block_cancel", session_id))
    rng = np.random.default_rng(seed)
    random_labels = ["confirm"] * (random_repetitions // 2) + ["cancel"] * (
        random_repetitions - random_repetitions // 2
    )
    rng.shuffle(random_labels)
    for label in random_labels:
        events.append(ScriptEvent(label, gesture_s, "block_random", session_id))
        events.append(ScriptEvent("rest", rest_between_s, "block_random", session_id))
    return events


def rest_trial_script(
    *,
    duration_s: float = 600.0,
    session_id: str = "false_trigger",
    ordinary_every_s: float = 3.0,
    ordinary_s: float = 0.2,
) -> list[ScriptEvent]:
    events: list[ScriptEvent] = []
    elapsed = 0.0
    while elapsed < duration_s:
        rest_s = min(ordinary_every_s, duration_s - elapsed)
        events.append(ScriptEvent("rest", rest_s, "block_false_trigger", session_id))
        elapsed += rest_s
        if elapsed >= duration_s:
            break
        move_s = min(ordinary_s, duration_s - elapsed)
        events.append(ScriptEvent("ordinary", move_s, "block_false_trigger", session_id))
        elapsed += move_s
    return events


def render_samples(
    events: list[ScriptEvent],
    *,
    sample_rate_hz: float = 200.0,
    n_channels: int = 4,
    snr_db: float = 12.0,
    electrode_shift: float = 0.0,
    fatigue: float = 0.0,
    artifact_rate: float = 0.0,
    seed: int = 7,
) -> tuple[NDArray[np.floating], NDArray[np.int8], list[str], list[str]]:
    """Return channel-major samples, per-sample class ids, block ids, and session ids."""
    n_samples = sum(max(1, int(round(event.duration_s * sample_rate_hz))) for event in events)
    rng = np.random.default_rng(seed)
    samples = np.zeros((n_channels, n_samples), dtype=float)
    class_ids = np.zeros(n_samples, dtype=np.int8)
    block_ids: list[str] = [""] * n_samples
    session_ids: list[str] = [""] * n_samples
    cursor = 0
    t0 = 0.0
    for event in events:
        n = max(1, int(round(event.duration_s * sample_rate_hz)))
        t = t0 + np.arange(n) / sample_rate_hz
        progress = cursor / max(n_samples, 1)
        amplitude = 80.0 * (1.0 - fatigue * progress)
        burst = np.sin(2 * np.pi * 40.0 * t) * amplitude
        label = event.label
        if label == "ordinary":
            samples[:, cursor : cursor + n] += np.sin(2 * np.pi * 25.0 * t) * 18.0
            label = "rest"
        elif label == "confirm":
            samples[0:2, cursor : cursor + n] += burst
            if electrode_shift:
                samples[2:4, cursor : cursor + n] += burst * electrode_shift
        elif label == "cancel":
            samples[2:4, cursor : cursor + n] += burst
            if electrode_shift:
                samples[0:2, cursor : cursor + n] += burst * electrode_shift
        if artifact_rate > 0 and float(rng.random()) < artifact_rate:
            spike_at = int(rng.integers(0, n))
            samples[:, cursor + spike_at] += rng.normal(0.0, 250.0, size=n_channels)
        class_ids[cursor : cursor + n] = LABEL_TO_INT[label]
        for i in range(n):
            block_ids[cursor + i] = event.block_id
            session_ids[cursor + i] = event.session_id
        cursor += n
        t0 += n / sample_rate_hz
    snr_lin = 10 ** (snr_db / 20.0)
    samples += rng.normal(0.0, 8.0, size=samples.shape) / max(snr_lin, 1e-3)
    return samples, class_ids, block_ids, session_ids


def windows_from_samples(
    samples: NDArray[np.floating],
    class_ids: NDArray[np.int8],
    block_ids: list[str],
    session_ids: list[str],
    *,
    sample_rate_hz: float = 200.0,
    window_ms: float = 250.0,
    hop_ms: float = 50.0,
    mix_fraction_max: float = 0.1,
) -> list[LabeledExample]:
    """Causal windows labeled by majority class. Mixed-boundary windows are dropped."""
    filt = CausalEmgFilter(n_channels=samples.shape[0], sample_rate_hz=sample_rate_hz)
    filtered = filt.process(samples)
    window_samples = int(round(sample_rate_hz * window_ms / 1000.0))
    hop_samples = int(round(sample_rate_hz * hop_ms / 1000.0))
    buffer = WindowBuffer(window_samples, hop_samples)
    records = buffer.push(
        filtered, first_sample_ns=0, sample_rate_hz=sample_rate_hz, block_id="live"
    )
    examples: list[LabeledExample] = []
    for record in records:
        ids = class_ids[record.start_idx : record.end_idx]
        if ids.size == 0:
            continue
        counts = np.bincount(ids, minlength=len(GESTURE_LABELS))
        majority = int(np.argmax(counts))
        if counts[majority] / ids.size < (1.0 - mix_fraction_max):
            continue
        block = block_ids[record.start_idx]
        session = session_ids[record.start_idx]
        if any(block_ids[i] != block for i in range(record.start_idx, record.end_idx)):
            continue
        examples.append(
            LabeledExample(
                block_id=block,
                session_id=session,
                label=GESTURE_LABELS[majority],
                start_idx=record.start_idx,
                end_idx=record.end_idx,
                features=record.features or extract_window_features(record.samples),
                start_ns=record.start_ns,
                end_ns=record.end_ns,
            )
        )
    return examples


def generate_labeled_windows(
    events: list[ScriptEvent] | None = None,
    *,
    seed: int = 7,
    sample_rate_hz: float = 200.0,
    window_ms: float = 250.0,
    hop_ms: float = 50.0,
    snr_db: float = 12.0,
    electrode_shift: float = 0.0,
    fatigue: float = 0.0,
    artifact_rate: float = 0.0,
    session_id: str = "session",
) -> list[LabeledExample]:
    script = events or calibration_script(session_id=session_id, seed=seed)
    samples, class_ids, block_ids, session_ids = render_samples(
        script,
        sample_rate_hz=sample_rate_hz,
        snr_db=snr_db,
        electrode_shift=electrode_shift,
        fatigue=fatigue,
        artifact_rate=artifact_rate,
        seed=seed,
    )
    return windows_from_samples(
        samples,
        class_ids,
        block_ids,
        session_ids,
        sample_rate_hz=sample_rate_hz,
        window_ms=window_ms,
        hop_ms=hop_ms,
    )


def generate_gesture_burst(
    label: str,
    *,
    duration_s: float = 1.2,
    seed: int = 7,
    block_id: str = "live",
    session_id: str = "calibration",
    **kwargs,
) -> list[LabeledExample]:
    events = [
        ScriptEvent("rest", 0.15, block_id, session_id),
        ScriptEvent(label, duration_s, block_id, session_id),
        ScriptEvent("rest", 0.15, block_id, session_id),
    ]
    return [
        example
        for example in generate_labeled_windows(events, seed=seed, session_id=session_id, **kwargs)
        if example.label == label
    ]
