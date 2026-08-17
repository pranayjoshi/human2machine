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
| Local Network | Crown adapter (Python) | Neurosity Wi-Fi stream |
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

Hardware uses **BrainFlow OSC broadcast**. The Crown does **not** take a unicast `--ip`. BrainFlow binds UDP **9000** on this Mac and waits for OSC `*raw` packets.

```bash
python -m crown_adapter.main --hardware
```

Enable OSC on the Crown (Neurosity Developer Console → device settings → Open Sound Control). Email/password cloud login is not used. `Crown-995` is the nickname for logs; BrainFlow does not need it when only one Crown is on the LAN.

### Physical

1. Charge the Crown and wear it per Neurosity's fitting guide.
2. Update Crown OS through the official app.
3. Put the Crown and the Mac on the same Wi-Fi network.
4. Enable OSC as above.
5. Close the Neurosity app / console.neurosity.co if they hold the stream.

### Config

`configs/local.yaml`:

```yaml
devices:
  crown:
    enabled: true
    mock: false
    ip_address: null
    ip_port: 9000
    device_id: "Crown-995"
```

`configs/modalities.yaml` already sets `crown.shadow_only: true`. Do not change that for the MVP.

Print the resolved OSC target:

```bash
python -m crown_adapter.main --hardware --list-devices
```

### Run

```bash
python -m crown_adapter.main --hardware
```

Or rely on `configs/local.yaml` and `just run-hardware --confirm`.

Expected events: `biosignal.chunk` (8 channels, 256 Hz, 16 samples), `data.quality`, `device.status`, `service.heartbeat`. Quality drops when the headset moves.

### Troubleshooting

| Symptom | What to do |
|---|---|
| no OSC packets on UDP 9000 | Enable OSC on the Crown. Same Wi-Fi. Close the Neurosity app. Grant Local Network to Terminal/Cursor. `--ip` is not used. |
| No epochs / adapter stays degraded | Same Wi-Fi, OSC on, then restart `just run-hardware --confirm`. |
| Adapter retries | Exponential backoff is capped at 30s. `device.status=degraded` is expected during reconnect. Old samples are never replayed as live. |
| Want mock instead | `python -m crown_adapter.main --mock` |

## 4. OpenBCI Ganglion (EMG)

### Physical

1. Charge the approved battery **before** applying electrodes. Disconnect charge before wearing.
2. Map four forearm channels (example: flexor, extensor, pronator, aux). Write the mapping down; IDs stay in config, not in code comments only.
3. Use a short USB extension for the dongle, **or** skip the dongle and use native Bluetooth (below). Prefer `/dev/cu.*` on macOS for USB.
4. Open the OpenBCI GUI and confirm all four channels react to gentle contractions.
5. Record a one-minute GUI reference file before BrainFlow.

Gestures for the MVP (comfortable, not maximal):

- `rest` — forearm relaxed
- `confirm` — gentle wrist flexion
- `cancel` — gentle wrist extension

### Discover the serial port (USB dongle)

```bash
python -m ganglion_adapter.main --hardware --list-devices
```

Put the chosen port in `configs/local.yaml` (not in source):

```yaml
devices:
  ganglion:
    enabled: true
    mock: false
    transport: usb_dongle
    serial_port: /dev/cu.usbserial-XXXX
```

### Native Bluetooth (no dongle)

macOS Bluetooth permission is required (Terminal / Cursor). Power the Ganglion so the LED blinks, then:

```bash
python -m ganglion_adapter.main --hardware --list-devices
python -m ganglion_adapter.main --hardware --ble
```

Or persist it in `configs/local.yaml`:

```yaml
devices:
  ganglion:
    enabled: true
    mock: false
    transport: ble
    serial_port: null
    mac_address: null          # optional; empty = autodiscover Ganglion/Simblee
    serial_number: null        # optional advertised name
    timeout_seconds: 15
```

BrainFlow scans for an advertised name starting with `Ganglion` or `Simblee`. Set `mac_address` only if you have more than one board or autodiscover fails. On macOS the address may look like a UUID, not `AA:BB:CC:DD:EE:FF`.

### Run

```bash
python -m ganglion_adapter.main --hardware
```

Expected events: `biosignal.chunk` (4 channels, 200 Hz), `modality.feature` (`emg_gesture` = rest/confirm/cancel/unknown), quality, status, heartbeat.

A single classified window never becomes a gesture. Live inference uses dwell, hysteresis, and a refractory period. Low quality emits `UNKNOWN`.

### Calibration (UI)

1. Open `/calibrate/emg` in the developer console while the Ganglion adapter is streaming.
2. 30s rest, 20 confirm (wrist flexion), 20 cancel (wrist extension), then a randomized held-out block.
3. Train. The trainer fits logistic regression, LDA, and a small forest on grouped recording blocks — overlapping windows never leak into the test split.
4. Run the 10-minute false-trigger rest trial before trusting EMG in a demo. Mock/CI measures the same rate on a 60-second rest stream and scales to 10 minutes.
5. Promote only if cross-block balanced accuracy is at least 90% and the false-trigger trial has been measured. The live adapter reloads `models/emg/current.json`.

CI gate (synthetic, no board):

```bash
just eval-emg
pytest tests/end_to_end/test_milestone3_emg.py
```

Promoted models live under `models/emg/` with `model.joblib`, `metadata.json`, `feature_config.yaml`, `metrics.json`, and `training_session_ids.json`. Never commit real biometric recordings.

### Troubleshooting

| Symptom | What to do |
|---|---|
| Board not listed | **Quit OpenBCI GUI first** — it holds the BLE connection so Simblee stops advertising. Grant Bluetooth to Terminal. Re-run `python -m ganglion_adapter.main --hardware --list-devices`. USB: unplug/replug dongle. |
| GUI sees Simblee, this repo does not | Same exclusive-link issue. Disconnect/close the GUI, keep the board advertising, then list-devices (it now BLE-scans, not `system_profiler`). |
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

If no ASR model is installed, install local Whisper on Apple Silicon:

```bash
python -m pip install -e ".[audio-mlx]"
# or: python -m pip install -r requirements-audio-mlx.txt
```

Then restart the audio adapter. The first utterance downloads `whisper-tiny.en`. Microphone permission must be granted to Terminal / Cursor.

If ASR is still unavailable, use the operator phrase box or:

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

The live session page shows a JPEG preview (downscaled, not recorded) plus object overlays. Raw video is not stored unless the session was started with `record_video=true`.

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

## 10. Milestone 1 concurrent soak

Twenty-minute **equivalent** concurrent Crown + Ganglion recording. This milestone is acquisition and record only: no biosignal is used for control, and fusion/safety are not required.

### Mock / CI

```bash
just soak-biosignals
pytest tests/end_to_end/test_milestone1_soak.py
```

`just soak-biosignals` (and `scripts/soak_biosignals.py --fast`, the default) generates a 20-minute *timeline* of mock EEG + EMG as fast as possible. CI does not sleep for 20 wall-clock minutes. Packet loss (~1%) and a timestamp/sequence gap are injected so hub and recorder metrics can show them.

### Hardware

1. `just run-hardware --confirm` (hub + recorder + both adapters with `--hardware`).
2. Start a session with consent and record **20 wall-clock minutes**.
3. Confirm packet loss and timestamp/sequence gaps are visible in the developer console / recorded metrics.
4. Confirm EEG never drives an action (shadow-only). EMG is also not used for control in this soak.

`just soak-biosignals --hardware` prints this procedure and does not fake devices.

## 11. Milestone status

| Milestone | Meaning | Status |
|---|---|---|
| 0 | Synthetic closed loop, mock adapters, console | Implemented; `pytest tests/end_to_end` |
| 1 | Crown + Ganglion concurrent recording | Done in mock/CI (`pytest tests/end_to_end/test_milestone1_soak.py`); hardware 20-minute soak is documented above |
| 2 | Constrained voice + four-object vision | Hardware paths implemented; accuracy gates are manual |
| 3 | Personalized EMG | Done in mock/CI (`pytest tests/end_to_end/test_milestone3_emg.py`); hardware calibration is `/calibrate/emg` |
| 4 | Closed-loop multimodal demo | Mock demo + live UI; 100-trial eval is operator-run |
| 5 | EEG shadow experiment | Acquisition + quality only; live weight remains 0 |
| 6 | YC packaging | Launcher and this handbook; remaining polish tracked in README |
