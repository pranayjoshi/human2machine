# Intent Fusion Runtime

## Goal

Combine recent, quality-weighted evidence into an explainable `IntentDecision` without directly controlling a machine.

## MVP intent state machine

```text
IDLE
  -> REQUEST_DETECTED
  -> TARGET_PROPOSED
  -> AWAITING_CONFIRMATION (when required)
  -> COMMIT_PROPOSED
  -> OUTCOME_OBSERVED
  -> IDLE

Any state -> CANCELLED -> IDLE
```

## Inputs

- Final audio intent candidates
- Current visible object set
- Pointing/head-direction target scores
- EMG `rest/confirm/cancel/unknown`
- EEG shadow features
- Current machine state
- Session/trial state
- User profile and modality reliability

## Outputs

- `intent.candidate_set`
- `intent.decision`
- `intent.conflict`
- `intent.timeout`
- `service.heartbeat`

## Initial fusion approach

Use late fusion, not an end-to-end multimodal transformer.

For each candidate action/target pair, calculate:

```text
evidence_contribution =
    configured_weight
  * feature_confidence
  * modality_quality
  * freshness_decay
  * user_reliability
```

Where:

```text
freshness_decay = exp(-age_ms / modality_time_constant_ms)
```

Aggregate candidate scores, normalize them, and report the top candidate plus alternatives. Keep negative evidence and conflicts explicit rather than forcing all features to be positive votes.

## Initial modality roles

### Audio

- Strong evidence for requested action.
- Strong evidence for explicitly named target.
- Deictic language requires external target evidence.

### Vision

- Defines currently available objects.
- Strong/medium evidence for hand pointing.
- Weak evidence for head direction.

### EMG

- Strong evidence for explicit confirm or cancel after dwell logic.
- Does not select an object initially.

### EEG

- Shadow only.
- Included in logs and offline features.
- Contribution to live score is exactly zero until promotion criteria pass.

### Machine state

- Filters impossible actions but does not imply human intent.

## Hard rules before scoring

- `STOP` and validated `CANCEL` create an immediate cancellation proposal.
- A target must be present in the current object set.
- Expired evidence is excluded.
- Low-quality/unknown modality output contributes zero.
- No active session means no actionable decision.
- A machine that is not ready cannot receive a commit proposal.

## Conflict detection

Create a conflict when:

- Spoken target differs from high-confidence pointing target.
- Two targets have a margin below threshold.
- Confirm and cancel occur within the same decision window.
- The target disappears.
- The action changes during confirmation.

Conflicts reduce confidence and add reason codes. They are not silently averaged away.

## Confirmation policy inputs

Fusion does not decide final safety, but it supplies:

- Top confidence
- Top-two margin
- Evidence diversity count
- Explicit confirmation presence
- Conflict flags
- Unavailable/stale modalities
- Decision expiry

## User personalization

Store a pseudonymous profile containing:

- EMG model ID
- Typical modality quality
- Learned reliability calibration
- Preferred confirmation method
- Accessibility settings

Start weights globally. Update them only from labeled trial outcomes, never from the system's own predictions.

## Model evolution

### Version 1

Rules + quality-weighted scores.

### Version 2

Logistic regression/gradient boosting over event-window features.

### Version 3

Small temporal model after sufficient multi-session data.

Every learned version must beat the rule baseline on held-out sessions and retain calibrated confidence.

## Confidence calibration

Measure expected calibration error, Brier score, reliability plots, and action-specific precision. A 0.9 score should correspond to roughly 90% correctness in the applicable test population; otherwise it is not a useful safety input.

## Decision lifecycle

- Every decision has an expiry.
- New conflicting evidence supersedes but does not mutate the old decision.
- Decisions are immutable audit events.
- The fusion runtime never creates `ActionCommand`.
- The runtime waits for action outcome/correction before closing the episode.

## Baseline experiment

Evaluate:

1. Voice only
2. Voice + vision
3. Voice + vision + EMG
4. Voice + vision + EMG + EEG shadow offline

Use identical trials and labels. Report task success, target accuracy, false commits, corrections, latency, and coverage.

## Acceptance criteria

- Deterministic output for identical ordered input and config.
- Cancel proposal generated within configured latency.
- Deictic request without target evidence does not commit.
- Conflicting target evidence produces a conflict.
- Missing EEG does not degrade live behavior.
- Each decision lists evidence event IDs and contributions.
- Learned model, when introduced, improves held-out metrics and confidence calibration.

## Instructions to Codex

Implement the state machine and rule baseline first. Make fusion a pure deterministic function over state, evidence, user profile, and configuration wherever possible; wrap transport separately.
