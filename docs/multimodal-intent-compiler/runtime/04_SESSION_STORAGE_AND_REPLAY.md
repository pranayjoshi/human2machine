# Session Storage and Replay

## Goal

Record complete, synchronized, privacy-controlled sessions and replay them deterministically for debugging, model training, and evaluation.

## Session directory

```text
data/sessions/<session_id>/
├── manifest.json
├── events/
│   ├── normalized.parquet
│   ├── decisions.parquet
│   ├── safety.parquet
│   └── outcomes.parquet
├── biosignals/
│   ├── crown_eeg.zarr
│   └── ganglion_emg.zarr
├── media/
│   ├── audio.flac
│   └── video.mp4
├── labels/
│   └── trials.parquet
├── configs/
├── models/
└── checksums.json
```

Raw media files are optional. The manifest states whether each stream was recorded and why.

## Manifest

Include:

- Session ID and pseudonymous user ID
- Start/end wall time and duration
- Consent/recording selections
- Code commit and dirty-tree indicator
- Contract versions
- Configuration hashes
- Device aliases and safe metadata
- Model IDs and hashes
- Stream completeness and packet-loss summary
- Finalization status
- Encryption/retention settings

## Writer architecture

- Recorder subscribes to normalized event stream.
- Use bounded queues per output type.
- Flush incrementally.
- Write to temporary filenames and atomically finalize.
- On crash, leave recoverable partial data clearly marked.
- Never block safety or fusion processing on disk writes.
- Safety/decision/outcome events receive a durable priority queue.

## Storage choices

- Parquet: sparse structured events and labels.
- Zarr or chunked NumPy: dense EEG/EMG matrices.
- FLAC/WAV: audio.
- MP4/H.264: video.
- JSON: manifest/config snapshots.

Do not embed long raw arrays inside Parquet event JSON if doing so makes replay and analysis inefficient.

## Trial labels

Each trial records:

- Presented instruction
- Ground-truth action
- Ground-truth target
- Whether ambiguity was intentional
- User confirmation/correction
- Outcome
- Failure reason
- Operator notes

Ground truth must come from experiment design or explicit user correction, not the model's top prediction.

## Replay modes

- Real-time: preserve original intervals.
- Accelerated: multiply time by a configured factor.
- Step: advance one semantic event/window at a time.
- Deterministic evaluation: skip wall-clock sleeps and process by normalized timestamp.

Replay must support excluding selected modalities for ablation without rewriting source data.

## Privacy

- Local storage by default.
- Explicit opt-in for audio/video.
- Provide a session deletion command.
- Provide an export containing manifest and selected derived data.
- Use pseudonymous IDs.
- Never push data to Hugging Face, W&B, cloud storage, or Git automatically.
- Before external participants, define consent, retention, access, and institutional review requirements.

## Validation and finalization

At session stop:

1. Stop accepting trial actions.
2. Drain priority queues.
3. Flush writers.
4. Validate event counts, time ranges, array shapes, and media duration.
5. Generate checksums.
6. Write final manifest atomically.
7. Mark session finalized.

## Acceptance criteria

- Twenty-minute multimodal session finalizes without corrupt files.
- Forced recorder crash produces a detectable recoverable partial session.
- Replay reproduces the same decisions under the same code/config/model.
- Modality ablation is supported from one session.
- Deleting a session removes raw and derived data plus indexes.
- Checksums detect modified/corrupt artifacts.
- No session data appears in Git status.

## Instructions to Codex

Implement session manifest and normalized event recording before media. Add a tiny committed fixture session with synthetic data for CI; never commit real biometric data.
