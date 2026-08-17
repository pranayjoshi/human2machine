# Local Mac Setup

## Goal

Prepare one MacBook to run the complete robotless prototype without changing the host Python installation.

## 1. Confirm hardware and OS

Record:

```bash
sw_vers
uname -m
system_profiler SPHardwareDataType
```

Use the output to distinguish Apple Silicon (`arm64`) from Intel (`x86_64`). Prefer Apple Silicon acceleration where available, but every required service must have a CPU fallback.

## 2. Install system tools

```bash
xcode-select --install
```

Install Homebrew if absent, then:

```bash
brew install git git-lfs ffmpeg cmake pkg-config portaudio libomp jq just
brew install node pnpm
brew install --cask miniforge visual-studio-code openbci
```

If the OpenBCI GUI cask is unavailable, install the current signed macOS release from OpenBCI manually.

## 3. Create isolated environments

### Python runtime

```bash
conda create -n intent-core python=3.12 -y
conda activate intent-core
python -m pip install --upgrade pip
```

The eventual `pyproject.toml` should include:

```text
pydantic
pyyaml
pyzmq
fastapi
uvicorn[standard]
numpy
scipy
polars
pyarrow
zarr
brainflow
mne
scikit-learn
joblib
torch
opencv-python
mediapipe
sounddevice
webrtcvad-wheels
rerun-sdk
structlog
prometheus-client
pytest
pytest-asyncio
hypothesis
```

Install from the project rather than manually once `pyproject.toml` exists:

```bash
pip install -e ".[dev]"
```

### Node workspace

Use Node 22 LTS or the current supported LTS. The workspace needs:

```text
zeromq
zod
tsx
typescript
next
react
react-dom
```

Install from the project root:

```bash
pnpm install
```

## 4. macOS permissions

Grant only when requested:

- Microphone access to Terminal/VS Code and the local audio process.
- Camera access to Terminal/VS Code and the vision process.
- Bluetooth access if testing native BLE.
- Accessibility access only if a keyboard-capture tool requires it.
- Local Network access to Crown/phone services where prompted.

Document permissions in the troubleshooting guide. Do not instruct users to disable macOS security controls.

## 5. Secret management

Create `.env.example` with names only. Crown OSC prefers `configs/local.yaml` (`devices.crown.ip_address`, `devices.crown.device_id`). Optional env overrides:

```text
CROWN_IP=
NEUROSITY_DEVICE_ID=
```

For development, load values from an ignored `.env.local`. Never log access tokens, email addresses, or raw credentials.

## 6. Device preflight

### Crown

- Update Crown OS through its supported workflow.
- Enable OSC in the Neurosity Developer Console (device settings → Open Sound Control).
- Put the Crown and Mac on the same Wi-Fi.
- BrainFlow listens on UDP 9000; a headset IP is not required.

### Ganglion

- Charge the approved battery before wearing electrodes.
- Never stream from a body-connected board while charging it.
- Connect the Ganglion dongle through a short USB extension.
- Launch OpenBCI GUI and verify all four channels.
- Record a one-minute test file before using BrainFlow.

### Audio/video

```bash
ffmpeg -f avfoundation -list_devices true -i ""
```

Record selected device indices in `configs/local.yaml`, not source code.

## 7. Local ports

Reserve:

| Port | Purpose |
|---:|---|
| 5555 | Raw adapter event ingestion |
| 5556 | Normalized event publication |
| 5557 | Approved robot command queue |
| 5558 | Event-hub session/trial control plane |
| 8000 | Console/API service |
| 3000 | Next.js developer console |

The startup preflight must fail with a useful message when a required port is occupied.

## 8. Developer commands to provide

Create a `justfile` or `Makefile` with:

```text
just bootstrap
just contracts-test
just run-mocks
just run-hardware
just preflight
just test
just replay SESSION=<id>
just lint
just format
```

`run-mocks` must start the complete stack without physical hardware. `run-hardware` must require an explicit confirmation and print which devices will be accessed.

## 9. Acceptance checks

- A fresh shell can activate the Python environment.
- Node and pnpm versions match repository constraints.
- OpenBCI GUI sees the Ganglion.
- A Neurosity SDK test receives Crown epochs.
- The camera returns frames at the configured resolution.
- The microphone records and plays a ten-second sample.
- Ports are available.
- `just run-mocks` starts all mock services and the UI.

## Instructions to Codex

Generate repeatable setup scripts only after testing commands on the target Mac. Pin direct dependencies, commit lockfiles, and never modify the user's global Python packages.
