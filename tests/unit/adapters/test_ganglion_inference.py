from __future__ import annotations

import numpy as np
from ganglion_adapter.live_inference import LiveSmoother, classify_by_rms
from ganglion_adapter.mock import GanglionMockRuntime, score_emg_quality
from intent_contracts.validation import parse_unnormalized_event


def test_single_window_does_not_commit() -> None:
    smoother = LiveSmoother(dwell_ms=200, confidence_threshold=0.7, hysteresis=0.12)
    scores = {"confirm": 0.95, "rest": 0.03, "cancel": 0.02, "unknown": 0.0}
    label, _conf = smoother.update("confirm", scores, quality=0.9, now_ns=0)
    assert label == "rest"
    label, _conf = smoother.update("confirm", scores, quality=0.9, now_ns=50_000_000)
    assert label == "rest"


def test_dwell_then_commit_and_refractory() -> None:
    smoother = LiveSmoother(
        dwell_ms=200, confidence_threshold=0.7, hysteresis=0.12, refractory_ms=400
    )
    scores = {"confirm": 0.95, "rest": 0.03, "cancel": 0.02, "unknown": 0.0}
    now = 0
    label = "rest"
    for _ in range(6):
        label, _conf = smoother.update("confirm", scores, quality=0.9, now_ns=now)
        now += 50_000_000
    assert label == "confirm"
    cancel_scores = {"cancel": 0.96, "rest": 0.02, "confirm": 0.02, "unknown": 0.0}
    label, _conf = smoother.update("cancel", cancel_scores, quality=0.9, now_ns=now)
    now += 50_000_000
    for _ in range(6):
        label, _conf = smoother.update("cancel", cancel_scores, quality=0.9, now_ns=now)
        now += 50_000_000
    assert label != "cancel"


def test_low_quality_emits_unknown() -> None:
    smoother = LiveSmoother()
    scores = {"confirm": 0.95, "rest": 0.03, "cancel": 0.02, "unknown": 0.0}
    label, conf = smoother.update("confirm", scores, quality=0.1, now_ns=1_000_000)
    assert label == "unknown"
    assert conf == 0.0


def test_disconnect_does_not_emit_stale_gesture() -> None:
    runtime = GanglionMockRuntime(seed=7)
    confirm_seen = False
    for _ in range(40):
        events = runtime.tick()
        for event in events:
            if event.event_type == "modality.feature" and event.payload["label"] == "confirm":
                confirm_seen = True
    runtime.set_disconnected(True)
    after = []
    for _ in range(5):
        after.extend(runtime.tick())
    feature_labels = [e.payload["label"] for e in after if e.event_type == "modality.feature"]
    assert confirm_seen
    assert feature_labels == []
    assert any(e.event_type == "device.status" and e.payload["status"] == "offline" for e in after)


def test_rms_rule_separates_confirm_and_cancel() -> None:
    confirm = classify_by_rms({"ch0_rms": 80, "ch1_rms": 70, "ch2_rms": 8, "ch3_rms": 7})
    cancel = classify_by_rms({"ch0_rms": 8, "ch1_rms": 7, "ch2_rms": 80, "ch3_rms": 70})
    rest = classify_by_rms({"ch0_rms": 4, "ch1_rms": 4, "ch2_rms": 4, "ch3_rms": 4})
    assert confirm[0] == "confirm"
    assert cancel[0] == "cancel"
    assert rest[0] == "rest"


def test_quality_penalizes_flat_channels() -> None:
    flat = np.zeros((4, 16))
    score, _components, flags = score_emg_quality(flat, packet_loss_count=2)
    assert score < 0.5
    assert any(flag.startswith("flat:") for flag in flags)


def test_mock_stream_events_are_unnormalized() -> None:
    runtime = GanglionMockRuntime(seed=7)
    events = []
    for _ in range(12):
        events.extend(runtime.tick())
    assert events
    for event in events:
        parse_unnormalized_event(event.to_unnormalized_dict())
