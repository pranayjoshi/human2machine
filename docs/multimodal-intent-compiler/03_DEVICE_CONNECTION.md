# Device Connection and Manual Integration

This is the operator handbook for connecting real devices to the Multimodal Intent Compiler. The mock stack (`just run-mocks`) does not need any of this.

Hardware mode is opt-in. `just run-hardware --confirm` prints which devices will be accessed and refuses to start without `--confirm`.

EEG is **shadow-only**. It never approves or executes an action.

## Safety first

- Use only the approved Ganglion battery while electrodes are on skin.
- Never wear the Ganglion while it is charging.
- Do not attach robot electronics, mains-powered triggers, or unisolated circuits to the board.
- The physical SO-ARM101 path is disabled until `docs/multimodal-intent-compiler/roadmap/01_SO_ARM101_INTEGRATION.md` is completed. Simulator mode cannot emit physical robot commands.

## 1. One-time Mac setup

Follow [Local Mac setup](01_LOCAL_SETUP.md), then:

```bash
python -m pip install -e ".[dev]"
pnpm install
cp .env.example .env.local
just preflight
```

Grant permissions only when macOS prompts:

| Permission | Who needs it | Why |
|---|---|---|
| Microphone | Terminal / VS Code / audio adapter | Voice commands |
| Camera | Terminal / VS Code / vision adapter | Tabletop objects and pointing |
| Local Network | Crown adapter (Node) | Neurosity Wi-Fi stream |
| Bluetooth | Ganglion BLE mode only | Optional; USB dongle is the default |

Do not disable macOS security controls.

## 2. Ports

These must be free on localhost:

| Port | Service |
|---:|---|
| 5555 | Adapter / runtime PUSH into the event hub |
| 5556 | Normalized PUB stream |
| 5557 | Approved `ActionCommand` queue |
| 5558 | Session / trial control plane |
| 8000 | Console API |
| 3000 | Developer console |

`just preflight` fails with a useful message if a required port is occupied.

## 3. Neurosity Crown (EEG, shadow-only)

### Physical

1. Charge the Crown and wear it per Neurosity's fitting guide.
2. Update Crown OS through the official app.
3. Claim the device in the [Neurosity Developer Console](https://console.neurosity.co/).
4. Put the Crown and the Mac on the same reliable Wi-Fi network.
5. Confirm the official Neurosity sample receives `brainwaves` and accelerometer events before using this repo.

### Credentials

Edit ignored `.env.local` (never commit it):

```text
NEUROSITY_EMAIL=you@example.com
NEUROSITY_PASSWORD=...
NEUROSITY_DEVICE_ID=...
```

If more than one Crown is on the account, `NEUROSITY_DEVICE_ID` is required.

### Config

`configs/local.yaml`:

```yaml
devices:
  crown:
    enabled: true
    mock: false
```

`configs/modalities.yaml` already sets `crown.shadow_only: true`. Do not change that for the MVP.

### Run

```bash
set -a && source .env.local && set +a
pnpm --filter @intent/crown-adapter start -- --hardware
```

Expected events: `biosignal.chunk` (8 channels, 256 Hz, 16 samples), `motion.chunk`, `data.quality`, `device.status`, `service.heartbeat`. Quality drops when the headset moves.

### Troubleshooting

| Symptom | What to do |
|---|---|
| Login error | Recheck `.env.local`. Tokens and emails must never appear in logs. |
| No epochs | Crown offline, wrong Wi-Fi, or stale Crown OS. Use the official app first. |
| Adapter retries | Exponential backoff is capped at 30s. `device.status=degraded` is expected during reconnect. Old samples are never replayed as live. |
| Want mock instead | `pnpm --filter @intent/crown-adapter start -- --mock` |

## 4. OpenBCI Ganglion (EMG)

### Physical

1. Charge the approved battery **before** applying electrodes. Disconnect charge before wearing.
2. Map four forearm channels (example: flexor, extensor, pronator, aux). Write the mapping down; IDs stay in config, not in code comments only.
3. Use a short USB extension for the dongle. Prefer `/dev/cu.*` on macOS.
4. Open the OpenBCI GUI and confirm all four channels react to gentle contractions.
5. Record a one-minute GUI reference file before BrainFlow.

Gestures for the MVP (comfortable, not maximal):

- `rest` — forearm relaxed
- `confirm` — gentle wrist flexion
- `cancel` — gentle wrist extension

### Discover the serial port

```bash
python -m ganglion_adapter.main --hardware --list-devices
```

Put the chosen port in `configs/local.yaml` (not in source):

```yaml
devices:
  ganglion:
    enabled: true
    mock: false
    serial_port: /dev/cu.usbserial-XXXX
```

### Run

```bash
python -m ganglion_adapter.main --hardware
```

Expected events: `biosignal.chunk` (4 channels, 200 Hz), `modality.feature` (`emg_gesture` = rest/confirm/cancel/unknown), quality, status, heartbeat.

A single classified window never becomes a gesture. Live inference uses dwell, hysteresis, and a refractory period. Low quality emits `UNKNOWN`.

### Calibration (UI)

1. Open `/calibrate/emg` in the developer console.
2. 30s rest, 20 confirm, 20 cancel, then a randomized block.
3. Run the 10-minute false-trigger rest trial before trusting EMG in a demo.
4. Promoted models live under `models/emg/` with `metadata.json`. Never commit real biometric recordings.

### Troubleshooting

| Symptom | What to do |
|---|---|
| Board not listed | Unplug/replug dongle, try another USB port, confirm OpenBCI GUI first. |
| Flat channels | Re-seat electrodes, check gel/skin, cable strain. |
| Line noise | Keep 60 Hz notch; move away from chargers and the laptop PSU. |
| Stale gesture after unplug | Adapter must emit `UNKNOWN` / degraded status, never the last confirm. |

## 5. Microphone (audio)

### Physical

Use the built-in mic or a close USB mic in a quiet room. Constrained vocabulary only:

- Actions: `give me` / `hand me` / `select` / `confirm` / `cancel` / `stop`
- Named targets: `blue` `red` `green` `yellow` block
- Deictic: `that` / `that one` / `this`

### Device index

```bash
ffmpeg -f avfoundation -list_devices true -i ""
python -m audio_adapter.main --hardware --list-devices
```

Store the name or index in `configs/local.yaml`:

```yaml
devices:
  audio:
    enabled: true
    mock: false
    device_name: MacBook Pro Microphone
    sample_rate_hz: 16000
```

### Run

```bash
python -m audio_adapter.main --hardware
```

The adapter captures locally, runs VAD, transcribes locally when a Whisper backend is installed (MLX Whisper on Apple Silicon, otherwise a CPU Whisper if present), then applies the deterministic grammar parser. Partial transcripts have `is_final=false` and cannot commit.

If no ASR model is installed, use the operator phrase box in the UI or:

```bash
python -m audio_adapter.main --hardware --phrase "give me the blue block"
```

Raw audio is **not** recorded unless the session was started with `record_audio=true`.

### Troubleshooting

| Symptom | What to do |
|---|---|
| Permission denied | Grant Microphone to Terminal/VS Code, restart the adapter. |
| Wrong device | Re-list devices; names change when Bluetooth headsets connect. |
| Invented commands | Parser must return `UNKNOWN`. Do not enable an LLM fallback for the MVP. |
| Slow commits | Partials are ignored; wait for end-of-utterance (silence ~400 ms). |

## 6. Camera (vision)

This adapter does **not** claim eye-gaze tracking. It reports objects, pointing, and coarse head direction.

### Table setup

1. Fix the camera so the full table is visible (1280×720 / 30 FPS to start).
2. Place four lightweight, visually distinct objects: blue, red, green, yellow.
3. Print or tape ArUco markers **or** rely on saturated color blocks under consistent lighting.
4. Mark table corners for workspace calibration.
5. Frame so you do not capture unnecessary background or other people.

### Device index

```bash
ffmpeg -f avfoundation -list_devices true -i ""
python -m vision_adapter.main --hardware --list-devices
```

```yaml
devices:
  vision:
    enabled: true
    mock: false
    camera_index: 0
    width: 1280
    height: 720
    fps: 30
```

### Run

```bash
python -m vision_adapter.main --hardware
```

Calibrate at `/calibrate/vision`: camera, table homography, marker IDs, pointing test. A calibration saved at a different resolution must fail instead of silently warping.

Privacy: default is features-only (no MP4). Research recording requires explicit session consent.

### Troubleshooting

| Symptom | What to do |
|---|---|
| Black frames | Grant Camera permission; close Zoom/Photo Booth. |
| IDs swap | Use markers, not color alone, or increase object separation. |
| No pointing candidate | Hand confidence below threshold; that is correct behavior. |
| Frozen camera | Adapter must flag freeze within ~1s and stop emitting stale targets. |

## 7. Robot simulator (always on for MVP)

No physical robot. The simulator consumes **only** approved `ActionCommand` objects on port 5557.

```bash
python -m robot_simulator.main --mock
```

The UI shows an unmistakable **SIMULATOR MODE** badge. There is no hidden toggle to enable the SO-ARM.

## 8. Starting a real session

1. `just preflight`
2. `just run-hardware --confirm` **or** start each service yourself (hub first, then runtime, then adapters, then console).
3. Open `http://127.0.0.1:3000`.
4. Preflight must show required services healthy. Crown may stay optional.
5. Start session (consent). Start a trial with an instruction.
6. Speak a command, point if deictic, confirm with EMG or the UI.
7. Inspect the decision (evidence IDs, contributions, safety reasons).
8. Stop session. Review and optionally replay.

Demo without hardware:

```bash
just run-mocks
# then in the UI: Start session → Run demo trial
# or: python scripts/demo_mvp.py
```

## 9. What you must configure by hand

Nothing in this list belongs in Git as a secret or a machine-specific path:

- `.env.local` Neurosity credentials
- `configs/local.yaml` camera index, mic name, Ganglion `serial_port`
- macOS permission grants
- Electrode-to-channel mapping written in the EMG calibration notes
- Table calibration saved after `/calibrate/vision`
- Promoted EMG model directory after a successful calibration day

Thresholds (fusion weights, safety cutoffs, dwell times) stay in versioned YAML under `configs/`.

## 10. Milestone status

| Milestone | Meaning | Status |
|---|---|---|
| 0 | Synthetic closed loop, mock adapters, console | Implemented; `pytest tests/end_to_end` |
| 1 | Crown + Ganglion concurrent recording | Hardware paths implemented; 20-minute soak is a manual gate |
| 2 | Constrained voice + four-object vision | Hardware paths implemented; accuracy gates are manual |
| 3 | Personalized EMG | Calibration UI + training hook; promote only after held-out metrics |
| 4 | Closed-loop multimodal demo | Mock demo + live UI; 100-trial eval is operator-run |
| 5 | EEG shadow experiment | Acquisition + quality only; live weight remains 0 |
| 6 | YC packaging | Launcher and this handbook; remaining polish tracked in README |
