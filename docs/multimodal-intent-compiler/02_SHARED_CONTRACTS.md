# Shared Contracts

## Goal

Define the only supported communication format between adapters, runtime services, the UI, recorder, simulator, and future robots.

## 1. Contract rules

- All timestamps are integers in nanoseconds.
- All probabilities and quality values are floats in `[0, 1]`.
- Every event has a globally unique `event_id`.
- Recordable normalized data belongs to a `session_id`; trial-scoped data also has `trial_id`.
- Adapter preview and health events may set these IDs to `null`; the event hub attaches active IDs during normalization.
- Every event declares `schema_version` and `producer_version`.
- Units appear in field names or metadata.
- Raw samples are chunked; never emit one transport message per sample.
- Unknown fields may be retained, but unknown schema major versions are rejected.

## 2. Base event envelope

```json
{
  "schema_version": "1.0.0",
  "event_id": "01J...",
  "event_type": "biosignal.chunk",
  "source": "ganglion-emg",
  "modality": "emg",
  "session_id": "session_...",
  "trial_id": "trial_...",
  "sequence": 981,
  "source_time_ns": 0,
  "received_monotonic_ns": 0,
  "normalized_time_ns": 0,
  "quality": 0.93,
  "producer_version": "0.1.0",
  "payload": {}
}
```

`source_time_ns` may be `null` when the device supplies no usable clock. `normalized_time_ns` is added by the event hub and must be absent from unnormalized adapter messages. `session_id` and `trial_id` may be null only for unrecorded preview/health events or session-control events.

## 2.1 Session and trial control contracts

The console API sends typed requests over the dedicated control plane:

- `session.start`
- `session.stop`
- `trial.start`
- `trial.complete`
- `trial.abort`

The event hub returns an acknowledged response containing the new state and generated IDs. Adapters do not generate session/trial IDs. The event hub publishes resulting lifecycle events onto the normalized stream so every subscriber observes the same boundary.

## 3. Biosignal chunk

```json
{
  "event_type": "biosignal.chunk",
  "payload": {
    "sample_rate_hz": 200,
    "channel_names": ["emg_flexor", "emg_extensor", "emg_pronator", "emg_aux"],
    "sample_count": 20,
    "samples": [[0.1, 0.2], [0.2, 0.3]],
    "units": "microvolts",
    "filters_applied": [],
    "packet_loss_count": 0
  }
}
```

Choose and document sample orientation once. Recommended: `samples[channel][sample]`.

## 4. Modality feature event

```json
{
  "event_type": "modality.feature",
  "payload": {
    "feature_name": "emg_gesture",
    "window_start_ns": 0,
    "window_end_ns": 0,
    "label": "confirm",
    "confidence": 0.91,
    "candidate_scores": {
      "rest": 0.04,
      "confirm": 0.91,
      "cancel": 0.05
    },
    "model_id": "emg-primary-user-v3",
    "shadow_only": false
  }
}
```

## 5. Object observation

```json
{
  "event_type": "vision.objects",
  "payload": {
    "frame_id": 551,
    "objects": [
      {
        "object_id": "object_blue_1",
        "class_name": "blue_block",
        "confidence": 0.98,
        "bbox_xyxy": [120, 90, 220, 210],
        "table_position_xy": [0.31, 0.54]
      }
    ],
    "pointing_candidates": [
      {"object_id": "object_blue_1", "confidence": 0.82}
    ],
    "head_direction_candidates": []
  }
}
```

Do not call head direction `gaze` unless a validated eye tracker is actually used.

## 6. Voice intent candidate

```json
{
  "event_type": "audio.intent_candidate",
  "payload": {
    "transcript": "give me that one",
    "is_final": true,
    "action": "REQUEST_HANDOFF",
    "target_reference": "DEICTIC",
    "target_object_id": null,
    "confidence": 0.94,
    "utterance_start_ns": 0,
    "utterance_end_ns": 0,
    "model_id": "local-asr-v1"
  }
}
```

## 7. Intent decision

```json
{
  "event_type": "intent.decision",
  "payload": {
    "decision_id": "decision_...",
    "action": "REQUEST_HANDOFF",
    "target_object_id": "object_blue_1",
    "confidence": 0.92,
    "status": "PROPOSED",
    "alternatives": [
      {"target_object_id": "object_red_1", "confidence": 0.06}
    ],
    "evidence": [
      {
        "event_id": "01J...",
        "modality": "vision",
        "contribution": 0.38,
        "quality": 0.95,
        "age_ms": 40
      }
    ],
    "fusion_model_id": "late-fusion-v1",
    "expires_at_ns": 0
  }
}
```

## 8. Safety decision

```json
{
  "event_type": "safety.decision",
  "payload": {
    "decision_id": "decision_...",
    "verdict": "ASK_CONFIRMATION",
    "reason_codes": ["TARGET_MARGIN_LOW"],
    "policy_version": "safety-policy-v1",
    "checks": {
      "intent_fresh": true,
      "target_visible": true,
      "cancel_absent": true,
      "machine_ready": true
    }
  }
}
```

Valid verdicts:

- `APPROVE`
- `ASK_CONFIRMATION`
- `HOLD`
- `REJECT`
- `EMERGENCY_STOP`

## 9. Approved action command

```json
{
  "schema_version": "1.0.0",
  "command_id": "command_...",
  "decision_id": "decision_...",
  "action": "REQUEST_HANDOFF",
  "target_object_id": "object_blue_1",
  "issued_at_ns": 0,
  "expires_at_ns": 0,
  "safety_policy_version": "safety-policy-v1",
  "idempotency_key": "decision_...:REQUEST_HANDOFF:object_blue_1"
}
```

Only the safety gateway may create this object.

## 10. Machine state and outcome

Required state values:

- `DISCONNECTED`
- `IDLE`
- `READY`
- `EXECUTING`
- `HOLDING`
- `COMPLETED`
- `CANCELLED`
- `FAULT`
- `ESTOPPED`

The machine adapter emits state transitions and an `action.outcome` containing command ID, outcome, duration, and optional user correction.

## 11. Health and heartbeat

Every process emits `service.heartbeat` every two seconds:

```json
{
  "event_type": "service.heartbeat",
  "payload": {
    "status": "healthy",
    "uptime_seconds": 720,
    "last_data_age_ms": 42,
    "error_count": 0
  }
}
```

The console considers a service degraded after two missed heartbeats and offline after five.

## 12. Contract tests

Implement fixtures for every event type in both Python and TypeScript. Tests must prove:

- Python emits JSON accepted by Zod.
- TypeScript emits JSON accepted by Pydantic.
- Invalid probability, timestamp, enum, or major schema version fails.
- Serialization preserves IDs and integer timestamps.
- An older minor version can be read when required fields are present.

## Instructions to Codex

Implement contracts as standalone packages before adapters. Generate JSON Schema from the Pydantic definitions and validate the TypeScript mirror against it in CI.
