# Safety Gateway

## Goal

Apply deterministic, auditable policy to every proposed intent and create an `ActionCommand` only when all required checks pass.

No ML model, LLM, adapter, UI component, or fusion service may bypass this gateway.

## Inputs

- Immutable `IntentDecision`
- Current machine state
- Current visible targets
- Fresh cancel/stop evidence
- Session/trial state
- Safety policy configuration
- User confirmation state

## Outputs

- `safety.decision`
- Approved `ActionCommand`
- Hold/cancel/emergency-stop commands
- Safety audit log

## Risk tiers

For the simulator:

- Tier 0: UI-only highlight; may occur at moderate confidence.
- Tier 1: simulated selection/movement; requires stronger evidence.
- Tier 2: future physical robot motion; disabled until SO-ARM integration.

The current product must distinguish simulator approval from physical-robot approval so an accidental configuration change cannot enable hardware.

## Required checks

### General

- Schema valid
- Decision not expired
- Session active
- Trial active where required
- Machine connected and ready
- Action allowed in current mode
- No active fault or emergency stop
- Idempotency key not previously executed

### Intent

- Confidence meets action threshold
- Top-two target margin meets threshold
- Required evidence modalities present
- No unresolved conflict
- Target currently visible and stable
- Explicit confirmation present when required

### Cancellation

- Recent stop/cancel always overrides an action proposal.
- Cancel remains latched until acknowledged by the machine adapter.
- A new request cannot clear emergency stop.

## Initial policy

Example only; tune through testing:

```yaml
safety:
  mode: simulator_only
  auto_approve_threshold: 0.92
  confirmation_threshold: 0.65
  minimum_target_margin: 0.20
  require_emg_confirmation_for_deictic: true
  max_intent_age_ms: 1000
  max_machine_state_age_ms: 500
  stop_latch: true
```

Verdict logic:

- Safety-critical failure or stop -> `EMERGENCY_STOP`/`REJECT`.
- Expired, unavailable, or machine not ready -> `HOLD`.
- Moderate confidence or insufficient margin -> `ASK_CONFIRMATION`.
- All checks pass -> `APPROVE` and create one command.

## Confirmation lifecycle

When confirmation is requested:

1. Freeze the proposed action/target and issue a confirmation ID.
2. Display the proposal clearly.
3. Accept confirm/cancel only within a short timeout.
4. Reject confirmation if the target disappears or intent changes.
5. Re-run all safety checks immediately before command issuance.

## Physical robot feature flag

The physical robot transport is disabled by default through two independent controls:

- Build/runtime mode must equal `physical_robot`.
- A local operator must arm the system through an explicit preflight.

Do not rely on a hidden UI toggle. The future adapter also requires its physical emergency stop and workspace check.

## Audit record

For every verdict store:

- Decision ID and evidence IDs
- Policy version and config hash
- All check results
- Reason codes
- Machine state snapshot
- Confirmation event if used
- Command ID if approved
- Processing latency

## Test matrix

Test at minimum:

- Valid high-confidence request
- Medium-confidence request
- Low-confidence request
- Two close targets
- Spoken/pointed conflict
- Missing target
- Target disappears during confirmation
- Stale voice/vision/EMG
- Machine busy/faulted/disconnected
- Duplicate decision
- Cancel before approval
- Cancel during execution
- Stop during every state
- Gateway restart
- Simulator mode accidentally given physical adapter config

## Acceptance criteria

- No unapproved intent reaches command port 5557.
- Every verdict is explained with reason codes.
- Duplicate decisions never create duplicate commands.
- Cancel/stop overrides all action paths.
- Confirmation revalidates state and freshness.
- Physical robot commands are impossible in simulator mode.
- Mutation/property tests cannot find an unchecked action path.

## Instructions to Codex

Keep policy evaluation pure and deterministic. Add exhaustive table-driven tests before connecting the gateway to the simulator.
