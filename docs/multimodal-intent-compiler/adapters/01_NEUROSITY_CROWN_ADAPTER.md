# Neurosity Crown Adapter

## Goal

Stream Crown EEG and accelerometer data into the local event hub with device timestamps, receive timestamps, quality metadata, reconnect behavior, and local session controls.

EEG remains `shadow_only=true` until offline evaluation proves incremental value.

## Technology

- Python 3.12
- BrainFlow `CROWN_BOARD` (OSC over local Wi-Fi; same `--ip` / `--device-id` as MindExecute)
- Shared Pydantic contracts
- ZeroMQ PUSH to the event hub
- Structured JSON logging

## Inputs

- Crown nickname (optional `--device-id` / `devices.crown.device_id`)
- OSC enabled on the headset (UDP 9000 broadcast)
- Session state from local console API

## Outputs

- `biosignal.chunk` for `eeg`
- `motion.chunk` for Crown accelerometer
- `device.status`
- `service.heartbeat`
- `data.quality`

## Implementation steps

### 1. Authentication and device selection

- Load optional nickname for logs (`--device-id` or `devices.crown.device_id`).
- Bind BrainFlow CROWN_BOARD on UDP 9000. Do not connect to a headset IP.
- Never print credentials or tokens.

### 2. Subscribe to streams

Poll BrainFlow `get_board_data()` for the eight Crown EEG channels at 256 Hz. Publish 16-sample epochs.

For each EEG epoch:

1. Read channel names, sampling rate, epoch start time, and samples.
2. Add `received_monotonic_ns` immediately.
3. Convert device milliseconds to `source_time_ns` without using floating point.
4. Preserve the eight native channel names.
5. Validate shape: eight channels and expected samples per epoch.
6. Assign a monotonically increasing sequence number.
7. Publish one chunk, not individual samples.

### 3. Data quality

Track:

- Epoch arrival interval and jitter
- Missing or duplicated epochs
- Non-finite values
- Flat channels
- Clipping/outlier ratio
- Crown motion magnitude
- Adapter-to-event-hub queue delay

Create a simple initial quality score:

```text
quality = packet_quality * channel_validity * motion_penalty
```

Keep the submetrics in payload metadata so the score is explainable. Do not infer electrode impedance unless the SDK exposes a validated measurement.

### 4. Reconnection

- Detect subscription errors and offline state.
- Retry with exponential backoff capped at 30 seconds.
- Emit `device.status=degraded` during retries.
- Never replay old samples as live data after reconnection.
- Reset clock-offset estimation after a long reconnect.
- Stop retrying cleanly when the process receives SIGINT/SIGTERM.

### 5. Features

The adapter may emit signal-level features but not semantic intent initially:

- Per-channel band power
- Global motion magnitude
- Artifact flag
- EEG quality

The later EEG experiment service may add readiness/error predictions. Keep those in a separately versioned model module so the acquisition adapter stays stable.

### 6. Mock mode

`--mock` must emit realistic Crown-shaped chunks:

- Eight channels
- 256 Hz
- Sixteen samples per chunk
- Configurable noise, alpha rhythm, motion artifacts, packet loss, and disconnects

Use a seeded random generator for reproducible replay tests.

## Configuration example

```yaml
crown:
  enabled: true
  stream: raw
  shadow_only: true
  reconnect_max_seconds: 30
  heartbeat_seconds: 2
  flatline_window_seconds: 2
  motion_artifact_threshold: 0.8
```

## Security and privacy

- Do not forward Crown data outside localhost.
- Do not upload session recordings automatically.
- Redact credentials and account identifiers.
- OSC stays on the local Wi-Fi; do not use the cloud SDK login path.
- Stop acquisition immediately when the user stops a session.

## Tests

### Unit

- Epoch conversion preserves sample shape.
- Millisecond timestamp conversion is exact.
- Non-finite data is rejected or marked invalid.
- Quality decreases under generated motion artifacts.

### Contract

- Every emitted message passes shared schema validation.

### Integration

- Mock stream runs for 20 minutes without sequence regression.
- Forced disconnect produces degraded status, reconnect, and new live samples.
- Event hub shutdown does not crash the adapter; bounded buffering or dropping is reported.

### Hardware acceptance

- Receive expected epochs for five continuous minutes.
- Measured average sample rate is within 1% of 256 Hz after accounting for chunks.
- Accelerometer movement is visible when the head moves.
- Closing the process releases subscriptions and exits within five seconds.

## Instructions to Codex

Implement mock mode and contract tests before authenticating to the real Crown. Keep Neurosity-specific objects inside this service and expose only shared contracts.
