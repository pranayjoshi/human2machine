# Multimodal Intent Compiler

Local-first research prototype that converts synchronized human signals into confidence-scored, machine-readable intentions. The current loop drives a software robot simulator; a physical SO-ARM101 is out of scope until the robotless closed loop passes its gates.

This is **not** a thought reader. It estimates a small explicit intent vocabulary and exposes uncertainty.

## Loop

`human signals -> synchronized evidence -> confidence-scored intent -> deterministic safety decision -> simulated machine action -> outcome and correction`

Supported actions: `SELECT_OBJECT`, `REQUEST_HANDOFF`, `CONFIRM`, `CANCEL`, `STOP`.

## Layout

See `docs/multimodal-intent-compiler/` for the implementation handbook. Runtime code lives in:

- `packages/contracts-python`, `packages/contracts-ts` — shared schemas
- `packages/runtime-python` — ZeroMQ helpers, logging, config
- `services/` — event hub, adapters, fusion, safety, simulator, recorder, console API
- `apps/developer-console` — Next.js operator UI
- `configs/` — versioned thresholds (never hide these in UI code)

## Quick start

```bash
python -m pip install -e ".[dev]"
pnpm install
just run-mocks
```

Then open the developer console at `http://127.0.0.1:3000`. The API gateway is `http://127.0.0.1:8000`.

`just run-mocks` starts the complete stack without hardware. Then either click **Demo: success** on the live session page or run `just demo`. `just run-hardware` requires explicit confirmation and is documented in the device handbook.

## Operator docs

- [Device connection and manual integration](docs/multimodal-intent-compiler/03_DEVICE_CONNECTION.md) — Crown, Ganglion, mic, camera, ports, permissions, and what you must configure by hand
- [Implementation handbook](docs/multimodal-intent-compiler/README.md)

## Milestone status

| Milestone | Status |
|---|---|
| 0 Synthetic closed loop | Done — `pytest tests/end_to_end` and `just run-mocks` |
| 1 Biosignal acquisition | Done in mock/CI (`pytest tests/end_to_end/test_milestone1_soak.py`); hardware 20-minute soak is `just soak-biosignals` plus real devices documented. |
| 2 Audio + vision | CI gates pass (`pytest tests/end_to_end/test_milestone2_*.py`); hardware accuracy remains operator-run |
| 3 EMG personalization | Done in mock/CI (`pytest tests/end_to_end/test_milestone3_emg.py`); hardware calibration is `/calibrate/emg` plus `just eval-emg` |
| 4 Closed-loop demo | Mock demo trial in the console; 100-trial eval is operator-run |
| 5 EEG shadow experiment | Acquisition + quality only; live fusion weight is 0 |
| 6 YC packaging | Launcher + handbook; physical SO-ARM101 still disabled |

Milestone 0 exit: synthetic voice + target + confirm produces one simulated action; contradiction produces `ASK_CONFIRMATION` or `HOLD`; cancel stops the simulator; sessions replay.
