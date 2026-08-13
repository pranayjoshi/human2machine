# Neurosity Crown Adapter

## Goal

Stream Crown EEG and accelerometer data into the local event hub with device timestamps, receive timestamps, quality metadata, reconnect behavior, and local session controls.

EEG remains `shadow_only=true` until offline evaluation proves incremental value.

## Technology

- TypeScript
- `@neurosity/sdk`
- RxJS
- Zod shared contracts
- Node ZeroMQ client
- Structured JSON logging

## Inputs

- `NEUROSITY_EMAIL`
- `NEUROSITY_PASSWORD` or a supported token workflow
- `NEUROSITY_DEVICE_ID`
- Stream mode in configuration
- Session state from local console API

## Outputs

- `biosignal.chunk` for `eeg`
- `motion.chunk` for Crown accelerometer
- `device.status`
- `service.heartbeat`
- `data.quality`

## Implementation steps

### 1. Authentication and device selection

- Load secrets at runtime.
- Authenticate once and never print credentials or tokens.
- If multiple devices exist, require an explicit device ID.
- Query device state and verify the selected device is online.
- Emit a status event containing safe metadata only: device alias, streaming mode, battery if exposed, and OS version if exposed.

### 2. Subscribe to streams

Subscribe to:

- `brainwaves("raw")` for filtered EEG.
- `accelerometer()` for motion/artifact context.

Add an optional configuration for `rawUnfiltered`, but do not enable it by default. The default raw stream is already filtered by the Crown and is appropriate for initial feature work.

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
- Show in the UI that the normal Wi-Fi/Node path may transit Neurosity infrastructure.
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
