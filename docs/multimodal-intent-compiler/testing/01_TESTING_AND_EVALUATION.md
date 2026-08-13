# Testing and Evaluation

## Goal

Prove that the system is reliable, explainable, and more useful than simpler input combinations. Testing must cover software behavior, model quality, time synchronization, device failure, and human-task performance.

## 1. Test layers

### Unit tests

Test pure functions:

- Schemas and serialization
- Filtering and feature extraction
- Timestamp conversion
- Freshness decay
- Fusion scoring
- State transitions
- Safety checks
- Storage finalization

### Contract tests

- TypeScript/Python cross-validation
- Adapter fixtures accepted by event hub
- Runtime outputs accepted by UI and recorder
- Action commands accepted by simulator

### Replay tests

Use committed synthetic sessions for:

- Normal success
- Ambiguous target
- Spoken/pointed conflict
- EMG cancel
- Crown disconnect
- Ganglion packet loss
- Camera freeze
- Audio unknown command
- Simulator fault
- Emergency stop

Expected decisions and safety verdicts must be golden outputs reviewed in code.

### Integration tests

Run all services with mocks for at least one hour. Inject restarts, queue pressure, clock jumps, malformed events, and port failures.

### Hardware tests

Test one real device at a time, then concurrent acquisition, then full closed loop.

## 2. Model evaluation rules

- Split by session/block/day, never overlapping windows.
- Report class balance.
- Preserve a voice/video baseline.
- Keep a rule-based fusion baseline.
- Evaluate confidence calibration.
- Record model, config, code, and dataset versions.
- Never tune on the final test session.

## 3. Core metrics

### Task/product

- End-to-end task success
- Correct target selection
- Wrong action/target rate
- False commit rate per hour
- Human corrections per task
- Confirmation requests per task
- Hold/reject coverage
- Completion time
- Setup/calibration time

### Models

- Precision, recall, F1 by class
- Balanced accuracy
- Confusion matrix
- ROC/PR where appropriate
- Brier score
- Expected calibration error
- Top-two target margin

### Systems

- Event latency by pipeline stage
- End-to-end decision latency p50/p95/p99
- Packet loss
- Queue drops
- Adapter reconnect time
- CPU, memory, and energy use
- Session finalization time
- Clock offset and jitter

### Safety

- Unauthorized commands: target zero
- Duplicate execution: target zero
- Cancel success rate: target 100%
- Emergency-stop success: target 100%
- Stale-evidence execution: target zero

## 4. Evaluation protocol

### Phase A - Primary-user development

Run 100 trials:

- 25 explicit named-target requests
- 25 deictic requests with clear pointing
- 20 intentionally ambiguous target trials
- 10 spoken/pointed conflicts
- 10 cancel-before-commit trials
- 10 sensor-dropout/fault trials

### Phase B - Repeatability

Repeat across at least three days with sensors removed/reapplied. Do not reuse the same physical layout every day.

### Phase C - Additional users

Only after consent and any required university review, test whether setup and personalization work for others. Do not present primary-user performance as population performance.

## 5. Ablation matrix

For the same labeled trials evaluate:

| Variant | Voice | Vision | EMG | EEG |
|---|---:|---:|---:|---:|
| A | Yes | No | No | No |
| B | Yes | Yes | No | No |
| C | Yes | Yes | Yes | No |
| D | Yes | Yes | Yes | Shadow/offline |

Primary success criterion: C materially reduces wrong selections or corrections compared with B in ambiguous situations without unacceptable latency or setup burden.

EEG promotion criterion: D must add predictive value on held-out sessions after controlling for visible motion/EMG artifacts. If not, keep EEG optional.

## 6. Release gates

### Internal alpha

- Mock E2E suite passes.
- 20-minute real concurrent recording passes.
- No unauthorized action path.
- 100 primary-user trials completed.

### External research preview

- Guided setup under five minutes excluding electrode application.
- Cross-day EMG performance acceptable.
- Privacy/consent controls implemented.
- Crash recovery and deletion verified.
- Known limitations documented.

### Physical robot preview

- All simulator safety tests pass on hardware-in-loop.
- Physical emergency stop installed and tested.
- Workspace/speed limits configured.
- Operator remains present.
- No autonomous motion based on EEG.

## 7. YC evidence package

Produce:

- 60-90 second uninterrupted demo video
- Architecture diagram
- Dataset/trial count
- Baseline-versus-fusion table
- False commit and correction rates
- Latency breakdown
- Three representative failure replays
- User/design-partner feedback
- Clear statement of what EEG does and does not do

## Instructions to Codex

Create test fixtures and automated metrics alongside each component, not at the end. Refuse to report aggregate accuracy without sample count, split method, and false-commit rate.
