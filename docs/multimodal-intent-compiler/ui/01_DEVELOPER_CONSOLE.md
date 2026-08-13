# Developer Console UI

## Goal

Provide one browser interface for preflight, session control, live observability, intent explanation, confirmation, labeling, replay, and experiments.

The UI must expose uncertainty and failure; it must not make the system look more confident than it is.

## Technology

- Next.js and TypeScript
- Shared Zod contracts
- FastAPI console gateway
- WebSocket live stream
- A performant plotting library such as uPlot for biosignals
- Accessible component system

## Backend boundary

Browser requests go only to the console API.

Required endpoints:

```text
GET  /api/health
GET  /api/services
GET  /api/config/public
POST /api/preflight
POST /api/sessions
POST /api/sessions/{id}/stop
POST /api/sessions/{id}/trials
POST /api/trials/{id}/label
POST /api/confirmations/{id}/confirm
POST /api/confirmations/{id}/cancel
POST /api/machine/estop
POST /api/machine/reset
GET  /api/sessions
GET  /api/sessions/{id}
POST /api/replay
WS   /api/live
```

The API validates all requests and publishes corresponding command/marker events. React components never write directly to ZeroMQ.

## Screens

### 1. Preflight

Show a checklist for:

- Crown online and streaming
- Ganglion connected and four channels active
- Microphone permission/device
- Camera permission/device/calibration
- Event hub
- Fusion runtime
- Safety gateway
- Simulator
- Recorder storage space

Each item shows status, last event age, and an actionable recovery message.

The Start Session button remains disabled until required checks pass. EEG may be optional because it is shadow-only.

### 2. Live session

Layout:

- Top: session timer, recording indicators, simulator/physical mode badge, emergency stop.
- Left: device/service health.
- Center: camera view with object IDs and pointing candidates.
- Right: current request, candidate targets, confidence, conflicts, and safety verdict.
- Bottom: downsampled EEG/EMG plots, audio status, machine timeline.

Color alone must not communicate safety state. Use text and icons.

### 3. Intent inspector

For the selected decision display:

- Proposed action and target
- Confidence and expiry countdown
- Alternatives and margin
- Evidence event IDs
- Contribution by modality
- Evidence age and quality
- Conflict/reason codes
- Fusion model/config version
- Safety checks and verdict

The evidence view is essential for debugging and the YC demo.

### 4. Confirmation

When required:

- Display action and target prominently.
- Show a live target thumbnail or highlight.
- Offer Confirm and Cancel buttons.
- Explain why confirmation was requested.
- Auto-expire visibly.
- Support EMG confirmation while retaining a clickable fallback.

### 5. Calibration

#### EMG

- Explain electrode/gesture setup.
- Show raw/envelope quality.
- Guide timed blocks.
- Display sample counts and class balance.
- Trigger offline training.
- Show held-out metrics and false-trigger test.

#### Vision

- Select camera.
- Define table corners/workspace.
- Verify markers and IDs.
- Test pointing accuracy.

#### EEG

- Show Crown connection and motion artifacts.
- Record shadow experiment blocks.
- Clearly state EEG is not driving action.

### 6. Session review

- Trial table with ground truth, prediction, verdict, outcome, and correction.
- Filter failures and conflicts.
- Play synchronized video/audio when recorded.
- Scrub timeline and inspect biosignal windows.
- Add/correct labels with an audit record.
- Export derived metrics.

### 7. Experiment comparison

Compare voice-only, voice+vision, voice+vision+EMG, and offline EEG variants:

- Accuracy
- Task success
- False commits
- Corrections
- Coverage/hold rate
- Latency
- Confidence calibration

Never report only accuracy.

## Live-stream design

- Console API subscribes to normalized events.
- Downsample signals server-side before WebSocket delivery.
- Send semantic events immediately.
- Send plot data at 10-15 Hz maximum.
- Apply per-client bounded buffers.
- The UI reconnects and requests a state snapshot after disconnect.

## Safety UX

- Emergency stop is always visible during a session.
- Stale or disconnected state is visually explicit.
- Physical and simulator modes use unmistakable labels.
- UI cannot reset an emergency stop without an explicit confirmation dialog.
- A browser disconnect never changes machine state.

## Acceptance criteria

- Preflight accurately reflects all services.
- Live view remains responsive during 20-minute sessions.
- Plotting does not accumulate unbounded data in browser memory.
- Every decision can be inspected with evidence and safety reasons.
- Confirmation expiry/cancel is correctly represented.
- Browser refresh recovers current state without restarting services.
- Session review reproduces event order.
- Keyboard-only operation and basic screen-reader labels work.

## Instructions to Codex

Build the UI against synthetic fixture events first. Keep business logic in the API/runtime, and add end-to-end browser tests for preflight, session start, confirmation, cancel, stop, and replay.
