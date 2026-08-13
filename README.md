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

`just run-mocks` starts the complete stack without hardware. `just run-hardware` requires explicit confirmation.

## Milestone 0

Synthetic voice + target + confirm produces one simulated action. Contradiction produces `ASK_CONFIRMATION`. Cancel stops the simulator. Event history replays deterministically.
