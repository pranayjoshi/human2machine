# Robot Simulator Adapter

## Goal

Close the human-to-machine loop before physical robot hardware arrives. The simulator must consume the exact `ActionCommand` contract that the SO-ARM adapter will later consume.

## Scope

The required simulator is a deterministic task-state simulator, not a physics engine. A MuJoCo/PyBullet visualization may be added later but must not delay end-to-end testing.

## Machine model

Objects exist on a virtual table. The simulated robot can:

- Move to an object
- Pick it
- Move to handoff zone
- Complete handoff
- Hold
- Cancel
- Emergency stop
- Report faults

## States

```text
DISCONNECTED -> IDLE -> READY -> EXECUTING -> COMPLETED -> READY
                           |          |
                           |          +-> HOLDING -> CANCELLED -> READY
                           +-> FAULT
Any active state -> ESTOPPED
```

State transitions must be explicit and validated. Invalid transitions produce a fault event.

## Implementation steps

### 1. Command consumer

- `PULL` only approved commands from port 5557.
- Validate schema, expiry, and idempotency key.
- Reject duplicate or expired commands.
- Never listen to raw intent proposals.

### 2. Execution model

For `REQUEST_HANDOFF`:

1. Verify target exists.
2. Transition `READY -> EXECUTING`.
3. Simulate approach duration.
4. Simulate grasp success/failure.
5. Simulate handoff duration.
6. Transition to `COMPLETED` and then `READY`.

Use configurable seeded failure probabilities, but default the demo to deterministic results.

### 3. Hold/cancel/stop

- `HOLD` pauses progress but preserves the command.
- `CANCEL` terminates the active command and returns to a safe ready state.
- `EMERGENCY_STOP` immediately enters `ESTOPPED` and requires an explicit reset through the console API.
- New action commands are rejected while faulted or estopped.

### 4. Visual state

Publish enough state for the UI to render:

- Object positions
- Robot stage/path progress
- Held object
- Target object
- Active command
- Last outcome
- Machine health

### 5. Timing and faults

Configuration can inject:

- Slow action
- Unreachable object
- Object missing
- Grasp failure
- Command timeout
- Adapter disconnect
- Duplicate command

### 6. Mock versus future hardware

Define a common `MachineAdapter` interface:

```text
connect()
disconnect()
get_state()
execute(command)
hold(reason)
cancel(command_id)
emergency_stop(reason)
reset()
```

The SO-ARM implementation must conform to this interface and contract.

## Acceptance criteria

- Only approved, unexpired commands execute.
- Duplicate command IDs execute once.
- Cancel interrupts every execution stage.
- Emergency stop blocks all later commands until reset.
- Every transition emits a state event.
- Replaying the same command/fault seed yields identical outcomes.
- Full mock stack can complete 1,000 commands without memory growth or state corruption.

## Instructions to Codex

Keep the simulator headless and deterministic. Let the web UI provide visualization. Do not couple simulator state to React components.
