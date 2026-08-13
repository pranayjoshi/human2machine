# OpenBCI Ganglion EMG Adapter

## Goal

Use all four Ganglion channels for forearm EMG acquisition and produce stable `rest`, `confirm`, and `cancel` gesture evidence for one calibrated user.

## Safety boundary

- Use only the approved Ganglion battery while electrodes are attached.
- Never wear the system while its battery is charging.
- Do not connect robot electronics, mains-powered triggers, or custom unisolated circuits to the board.
- Treat OpenBCI hardware as development/evaluation equipment.

## Technology

- Python 3.12
- BrainFlow
- NumPy/SciPy
- scikit-learn
- joblib or safe model serialization
- Pydantic contracts
- ZeroMQ

## Device modes

Support both:

1. USB dongle serial mode, default for stability.
2. Native BLE mode, optional.

On macOS serial mode must select the appropriate `/dev/cu.*` port. Never hard-code it; expose a device-list command and persist the selected port in local configuration.

## Outputs

- `biosignal.chunk` with four EMG channels
- `modality.feature` for `emg_gesture`
- `data.quality`
- `device.status`
- `service.heartbeat`

## Implementation steps

### 1. Hardware verification

Before application integration:

- Confirm the board and dongle in OpenBCI GUI.
- Confirm all four channels react to muscle contractions.
- Label the physical cable-to-muscle mapping.
- Secure electrodes and cables to reduce movement artifacts.
- Save one OpenBCI GUI reference recording.

### 2. BrainFlow acquisition

- Initialize the correct Ganglion board ID.
- Prepare the session, start the stream, and drain chunks on a dedicated acquisition thread.
- Request chunks every 50-100 ms.
- Preserve BrainFlow board timestamp when usable.
- Add a monotonic receive timestamp immediately.
- Track sample indices, missing samples, and buffer overruns.
- Always call stop/release in a `finally` block.

### 3. Signal processing

Because the Ganglion samples at 200 Hz, design filters below the 100 Hz Nyquist limit.

Initial pipeline:

1. Remove per-channel DC offset.
2. Apply a 60 Hz notch suitable for the local power environment.
3. Apply a conservative EMG bandpass, initially 20-90 Hz, validating stability on actual data.
4. Preserve the raw chunk separately from the derived/filtered features.
5. Rectify only for envelope/features, not for stored raw data.

Avoid zero-phase filtering in live mode because it requires future samples. Use causal filters with maintained state. Offline training may use zero-phase filters only if train and evaluation methodology explicitly accounts for the difference.

### 4. Windowing and features

Use a 250 ms window with a 50 ms hop as the initial configuration.

Per channel calculate:

- RMS
- Mean absolute value
- Variance
- Waveform length
- Zero-crossing count with noise threshold
- Slope sign changes
- Integrated EMG

Add cross-channel normalized ratios. Standardize using training-session statistics stored with the model.

### 5. Calibration protocol

The UI guides the user through:

1. Thirty seconds of relaxed rest.
2. Twenty `confirm` gestures, 1-2 seconds apart.
3. Twenty `cancel` gestures, 1-2 seconds apart.
4. A second randomized block.
5. A ten-minute rest/ordinary-movement false-trigger evaluation.

The exact physical gestures must be comfortable, distinct, and documented. Example: gentle wrist flex for confirm and extension for cancel. Avoid maximal contractions.

### 6. Model

Start with interpretable baselines:

- Logistic regression
- Linear discriminant analysis
- Random forest or gradient boosting

Evaluate using grouped splits by recording block and, later, by day. Never randomly split overlapping windows; that leaks nearly identical data into train and test.

Promote a model only if it improves balanced accuracy and false-trigger rate on a held-out session.

### 7. Live decision smoothing

A single classified window never becomes a gesture event.

Require:

- Minimum confidence threshold
- Sustained prediction for a configured dwell duration
- Hysteresis before changing states
- Refractory period after a committed gesture
- Immediate return to `rest` before another commit

`cancel` may use a lower latency threshold but must still reject isolated noise.

### 8. Quality scoring

Penalize:

- Flat channels
- Saturation or clipping
- Sudden baseline shifts
- Excessive line noise
- Missing samples
- Electrode/cable motion indicators

When quality is below threshold, emit `UNKNOWN` rather than forcing a class.

### 9. Mock mode

Generate four-channel synthetic EMG bursts with configurable labels, SNR, electrode shift, fatigue drift, packet loss, and artifacts. Seed all generators.

## Model artifact

Each model directory contains:

```text
model.joblib
metadata.json
feature_config.yaml
metrics.json
training_session_ids.json
```

Metadata includes code commit, subject pseudonym, electrode placement description, sampling rate, filter settings, window settings, and class definitions.

## Acceptance criteria

- Five-minute raw stream without unrecovered packet failures.
- Cross-block balanced accuracy of at least 90% during the first calibration session.
- Cross-day balanced accuracy of at least 85% before relying on EMG outside a demo.
- False confirm rate measured over ten minutes of rest/ordinary motion.
- Disconnect and reconnect never emits a stale gesture.
- Low-quality data produces `UNKNOWN`.
- `cancel` passes an end-to-end latency target of 500 ms or better after validation.

## Instructions to Codex

Build acquisition, offline feature extraction, model training, and live inference as separate modules. Unit-test live causal filtering against saved fixtures and prohibit overlapping-window leakage in evaluation utilities.
