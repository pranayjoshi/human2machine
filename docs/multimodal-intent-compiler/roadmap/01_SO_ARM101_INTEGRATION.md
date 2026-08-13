# SO-ARM101 Integration

## Goal

Replace the simulator with the physical SO-ARM101 while preserving the adapter, fusion, safety, UI, storage, and evaluation contracts.

Do not begin this document until the robotless closed loop passes its release gates.

## 1. Hardware intake

Inventory:

- Leader arm
- Follower arm
- Correct controllers
- Correct 5 V leader supply
- Correct 12 V follower supply for Pro kit
- USB cables
- Mounts/clamps
- Emergency-stop hardware
- Lightweight objects and clear workspace

Photograph and label power supplies to prevent interchange.

## 2. Software environment

Create a separate LeRobot Python 3.12 environment. Do not merge it into the intent-core environment until compatibility is proven.

Install the pinned LeRobot commit with core scripts and Feetech support. Confirm:

- Ports are discoverable.
- Leader and follower calibrate independently.
- Teleoperation works at reduced speed.
- Dataset recording and replay work.

Pin dependencies and save calibration files with stable arm IDs.

## 3. Physical setup

- Rigidly mount both arms.
- Clear at least one meter around follower during setup.
- Route cables away from joints.
- Install a reachable latching emergency stop that safely removes/blocks follower actuation according to the kit's electrical requirements.
- Start with foam blocks and no human handoff.
- Configure software speed, joint, and workspace limits.

## 4. Adapter implementation

Implement `SOArmMachineAdapter` using the shared `MachineAdapter` interface:

```text
connect
disconnect
get_state
execute
hold
cancel
emergency_stop
reset
```

Translate high-level actions into prevalidated skills. Initial skills:

- `home`
- `point_to_object`
- `pick_marked_object`
- `place_in_fixed_tray`

Do not begin with free-form VLA motion or human handoff.

## 5. Skill execution

The intent runtime selects what; the robot skill determines how.

Each skill declares:

- Supported target type
- Required perception state
- Start/end joint constraints
- Maximum duration
- Cancel/hold behavior
- Failure states
- Verification condition

Use prerecorded or deterministic planned trajectories initially. A learned policy may be introduced only after the deterministic path is safe and measurable.

## 6. Safety upgrades

Physical mode adds checks for:

- Operator arming
- Emergency-stop status
- Joint/velocity limits
- Workspace bounds
- Target pose reachability
- Robot state freshness
- Camera freshness
- No person in restricted workspace
- Skill timeout
- Controller/communication fault

Run the safety gateway on the same Mac initially, but do not represent it as a certified industrial safety controller.

## 7. Shadow and staged activation

### Stage 1 - Shadow

Runtime predicts; operator teleoperates. Compare proposed and actual target/skill.

### Stage 2 - Highlight only

Runtime selects/highlights object; operator confirms and initiates deterministic action.

### Stage 3 - Confirmed physical action

Every motion requires explicit UI/EMG confirmation after all safety checks.

### Stage 4 - Limited automatic action

Only after sufficient trials, allow high-confidence, low-risk actions in a fixed workspace. Keep an operator and emergency stop present.

## 8. Data collection

Use the leader arm to collect demonstrations and LeRobot-format episodes. Link each robot episode to the intent compiler session/trial ID.

Do not upload biometric-linked episodes publicly. If robot trajectories are published later, strip human identity and sensitive modality data.

## 9. Hardware acceptance matrix

- 100 repeated home motions
- 100 point-to-object motions
- 100 pick/place trials across four objects
- Cancel during approach, grasp, lift, and place
- Emergency stop during each stage
- Camera disconnect
- USB disconnect
- Stale command
- Duplicate command
- Object removed after approval
- Restart after fault

Acceptance requires zero duplicate/stale executions and complete state/outcome logs.

## 10. Demo progression

The first physical demo should be:

1. User names or indicates a marked foam object.
2. Runtime displays evidence and target.
3. EMG or UI confirms.
4. Safety gateway approves.
5. SO-ARM moves the object to a fixed tray.
6. A second ambiguous trial causes a confirmation request.
7. A cancel trial stops before motion completes.

Avoid placing the robot near a face or performing direct human handoff in the first public demo.

## Instructions to Codex

Implement the SO-ARM adapter behind the existing command contract. Do not change intent schemas to fit LeRobot joint commands; keep low-level robot details isolated inside the adapter/skill layer.
