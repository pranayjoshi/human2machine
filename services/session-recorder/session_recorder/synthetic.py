"""Tiny synthetic session events for CI. Values are hand-written, not recordings."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from intent_contracts.enums import PRODUCER_VERSION, SCHEMA_VERSION

SYNTHETIC_SESSION_ID = "synthetic_success"
SYNTHETIC_USER_ID = "user_synthetic"
SYNTHETIC_TRIAL_ID = "trial_synthetic_1"


def _envelope(
    *,
    event_id: str,
    event_type: str,
    source: str,
    sequence: int,
    normalized_time_ns: int,
    payload: dict[str, Any],
    modality: str | None,
    quality: float = 1.0,
    trial_id: str | None = SYNTHETIC_TRIAL_ID,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "event_id": event_id,
        "event_type": event_type,
        "source": source,
        "modality": modality,
        "session_id": SYNTHETIC_SESSION_ID,
        "trial_id": trial_id,
        "sequence": sequence,
        "source_time_ns": 1_000_000_000 + normalized_time_ns,
        "received_monotonic_ns": 2_000_000_000 + normalized_time_ns,
        "normalized_time_ns": normalized_time_ns,
        "quality": quality,
        "producer_version": PRODUCER_VERSION,
        "payload": payload,
    }


def synthetic_success_events() -> list[dict[str, Any]]:
    """A few clearly fake events: no real EEG/EMG/audio/video."""
    return [
        _envelope(
            event_id="syn000000000000000000000001",
            event_type="session.started",
            source="event-hub",
            sequence=0,
            normalized_time_ns=0,
            modality=None,
            trial_id=None,
            payload={
                "state": "RECORDING",
                "config_hash": "synthetic-config",
                "contract_version": SCHEMA_VERSION,
                "commit": "synthetic",
                "model_versions": {"fusion": "late-fusion-v1", "emg": "emg-synthetic-v0"},
                "user_id": SYNTHETIC_USER_ID,
                "consent": True,
                "record_audio": False,
                "record_video": False,
            },
        ),
        _envelope(
            event_id="syn000000000000000000000002",
            event_type="trial.started",
            source="event-hub",
            sequence=1,
            normalized_time_ns=10_000_000,
            modality=None,
            payload={
                "instruction": "give me the blue block",
                "ground_truth_action": "REQUEST_HANDOFF",
                "ground_truth_target": "object_blue_1",
                "ambiguous": False,
                "notes": "synthetic fixture",
            },
        ),
        _envelope(
            event_id="syn000000000000000000000003",
            event_type="biosignal.chunk",
            source="ganglion-emg",
            sequence=2,
            normalized_time_ns=20_000_000,
            modality="emg",
            quality=1.0,
            payload={
                "sample_rate_hz": 200.0,
                "channel_names": ["synth_a", "synth_b"],
                "sample_count": 4,
                "samples": [[0.0, 0.25, 0.5, 0.25], [0.0, -0.25, 0.0, 0.25]],
                "units": "microvolts",
                "filters_applied": [],
                "packet_loss_count": 0,
                "clock_confidence": 1.0,
                "estimated_first_sample_ns": 0,
            },
        ),
        _envelope(
            event_id="syn000000000000000000000004",
            event_type="audio.intent_candidate",
            source="audio-adapter",
            sequence=3,
            normalized_time_ns=50_000_000,
            modality="audio",
            quality=0.94,
            payload={
                "transcript": "give me that one",
                "is_final": True,
                "action": "REQUEST_HANDOFF",
                "target_reference": "DEICTIC",
                "target_object_id": None,
                "confidence": 0.94,
                "utterance_start_ns": 10_000_000,
                "utterance_end_ns": 45_000_000,
                "model_id": "local-asr-v1",
            },
        ),
        _envelope(
            event_id="syn000000000000000000000005",
            event_type="vision.objects",
            source="vision-adapter",
            sequence=4,
            normalized_time_ns=60_000_000,
            modality="vision",
            quality=0.95,
            payload={
                "frame_id": 1,
                "objects": [
                    {
                        "object_id": "object_blue_1",
                        "class_name": "blue_block",
                        "confidence": 0.98,
                        "bbox_xyxy": [120.0, 90.0, 220.0, 210.0],
                        "table_position_xy": [0.31, 0.54],
                    }
                ],
                "pointing_candidates": [{"object_id": "object_blue_1", "confidence": 0.82}],
                "head_direction_candidates": [],
            },
        ),
        _envelope(
            event_id="syn000000000000000000000006",
            event_type="modality.feature",
            source="ganglion-emg",
            sequence=5,
            normalized_time_ns=80_000_000,
            modality="emg",
            quality=0.91,
            payload={
                "feature_name": "emg_gesture",
                "window_start_ns": 55_000_000,
                "window_end_ns": 80_000_000,
                "label": "confirm",
                "confidence": 0.91,
                "candidate_scores": {"rest": 0.04, "confirm": 0.91, "cancel": 0.05},
                "model_id": "emg-synthetic-v0",
                "shadow_only": False,
            },
        ),
        _envelope(
            event_id="syn000000000000000000000007",
            event_type="intent.decision",
            source="fusion-runtime",
            sequence=6,
            normalized_time_ns=90_000_000,
            modality="fusion",
            payload={
                "decision_id": "decision_synthetic_1",
                "action": "REQUEST_HANDOFF",
                "target_object_id": "object_blue_1",
                "confidence": 0.92,
                "status": "PROPOSED",
                "alternatives": [{"target_object_id": "object_red_1", "confidence": 0.06}],
                "evidence": [
                    {
                        "event_id": "syn000000000000000000000004",
                        "modality": "audio",
                        "contribution": 0.4,
                        "quality": 0.94,
                        "age_ms": 40,
                    }
                ],
                "fusion_model_id": "late-fusion-v1",
                "fusion_state": "COMMIT_PROPOSED",
                "expires_at_ns": 1_590_000_000,
                "conflicts": [],
                "reason_codes": [],
            },
        ),
        _envelope(
            event_id="syn000000000000000000000008",
            event_type="safety.decision",
            source="safety-gateway",
            sequence=7,
            normalized_time_ns=95_000_000,
            modality="safety",
            payload={
                "decision_id": "decision_synthetic_1",
                "verdict": "APPROVE",
                "reason_codes": [],
                "policy_version": "safety-policy-v1",
                "checks": {
                    "intent_fresh": True,
                    "target_visible": True,
                    "cancel_absent": True,
                    "machine_ready": True,
                    "session_active": True,
                    "schema_valid": True,
                    "no_unresolved_conflict": True,
                    "confirmation_satisfied": True,
                    "physical_robot_disarmed": True,
                },
                "command_id": "command_synthetic_1",
                "confirmation_id": None,
            },
        ),
        _envelope(
            event_id="syn000000000000000000000009",
            event_type="action.outcome",
            source="robot-simulator",
            sequence=8,
            normalized_time_ns=200_000_000,
            modality="machine",
            payload={
                "command_id": "command_synthetic_1",
                "decision_id": "decision_synthetic_1",
                "outcome": "COMPLETED",
                "duration_ms": 100.0,
                "user_correction": None,
            },
        ),
        _envelope(
            event_id="syn00000000000000000000000a",
            event_type="trial.completed",
            source="event-hub",
            sequence=9,
            normalized_time_ns=210_000_000,
            modality=None,
            payload={
                "instruction": "give me the blue block",
                "ground_truth_action": "REQUEST_HANDOFF",
                "ground_truth_target": "object_blue_1",
                "ambiguous": False,
                "outcome": "COMPLETED",
                "failure_reason": None,
                "user_correction": None,
            },
        ),
        _envelope(
            event_id="syn00000000000000000000000b",
            event_type="session.stopped",
            source="event-hub",
            sequence=10,
            normalized_time_ns=220_000_000,
            modality=None,
            trial_id=None,
            payload={
                "state": "STOPPING",
                "contract_version": SCHEMA_VERSION,
                "commit": "synthetic",
            },
        ),
    ]


GOLDEN_EVENT_TYPES = [event["event_type"] for event in synthetic_success_events()]


def write_synthetic_success_fixture(fixtures_sessions_dir: Path, **store_kwargs: Any) -> Path:
    """Write the committed CI fixture. Never includes real biometric recordings."""
    import shutil

    from session_recorder.store import SessionStore, is_session_stopped

    dest = Path(fixtures_sessions_dir)
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / SYNTHETIC_SESSION_ID
    if target.exists():
        shutil.rmtree(target)
    store_kwargs.setdefault("repo_dir", Path("/tmp"))
    store = SessionStore(dest, **store_kwargs)
    events = synthetic_success_events()
    store.open_from_started(events[0])
    assert store.paths is not None
    store.paths.events.joinpath("preview.json").write_text(json.dumps(events, indent=2) + "\n")
    (store.paths.media / ".gitkeep").write_text("")
    (store.paths.models / ".gitkeep").write_text("")
    for event in events[1:]:
        if is_session_stopped(event):
            store.ingest(event)
            store.finalize()
            break
        store.ingest(event)
    return target
