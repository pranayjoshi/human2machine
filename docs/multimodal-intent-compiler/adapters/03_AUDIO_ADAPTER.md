# Audio Adapter

## Goal

Convert local microphone input into a constrained, confidence-scored intent candidate without sending audio to a remote service by default.

## Initial vocabulary

Actions:

- `REQUEST_HANDOFF`
- `SELECT_OBJECT`
- `CONFIRM`
- `CANCEL`
- `STOP`

Target references:

- Explicit color/name: "the blue block"
- Deictic: "that one"
- Ordinal: "the second object"
- None

## Technology

- Python
- `sounddevice` or equivalent CoreAudio binding
- Voice activity detection
- Local ASR: MLX Whisper on Apple Silicon or a CPU-compatible Whisper implementation
- Rule/grammar parser first; small local language model only as a fallback
- ZeroMQ and shared contracts

## Implementation steps

### 1. Device selection

- List microphones with stable human-readable names.
- Let the user choose one during setup.
- Store the selection in local YAML.
- Record 16 kHz mono PCM for ASR unless the selected model requires something else.

### 2. Audio capture

- Use a bounded ring buffer.
- Timestamp each audio block on receipt.
- Detect overflow and report dropped frames.
- Keep capture separate from transcription so slow inference cannot block the audio callback.

### 3. Utterance segmentation

- Use VAD to detect start/end.
- Retain 200-300 ms pre-roll so initial consonants are not lost.
- End after a configurable silence interval.
- Limit maximum utterance duration.
- Emit an audio-level indicator to the UI, but do not stream raw audio samples to the browser.

### 4. Transcription

- Transcribe completed utterances locally.
- Preserve transcript, timing, ASR confidence if available, and model ID.
- Mark partial transcripts separately and never allow partial text to commit an action.

### 5. Intent parsing

Implement deterministic parsing for the initial command set:

- Normalize case and punctuation.
- Detect stop/cancel before all other intents.
- Extract action verbs.
- Extract known object color/name.
- Mark pronouns such as "that" as `DEICTIC`.
- Return `UNKNOWN` for unsupported requests.

If an LLM fallback is later used, require JSON schema output and restrict it to the supported vocabulary. It may propose an intent but cannot approve execution.

### 6. Confidence

Combine:

- ASR confidence
- Grammar match strength
- Target extraction confidence
- Acoustic quality

Never invent high confidence when the ASR backend lacks token confidence. Use conservative defaults and calibrate on recorded commands.

### 7. Priority commands

`STOP` and `CANCEL` should publish immediately after a final recognized utterance and receive special treatment in the safety gateway. Test common variants such as "stop", "cancel", "never mind", and "don't do that".

### 8. Privacy

- Raw audio recording is opt-in per session.
- Transcripts may be stored when session recording is enabled.
- Default retention policy deletes raw audio after feature extraction unless the user explicitly selects research recording.

### 9. Mock mode

Read scripted utterances with timestamps from a fixture file. Include ambiguous text, noise flags, deictic targets, and cancel commands.

## Acceptance criteria

- At least 95% action accuracy over 100 scripted commands from the primary user in the expected environment.
- `STOP` and `CANCEL` recall is 100% in the scripted safety set.
- Unsupported language produces `UNKNOWN` or confirmation, not an invented command.
- End-of-utterance to final intent p95 latency is measured and under 1.5 seconds for the MVP.
- Microphone disconnect produces degraded health without crashing other services.

## Instructions to Codex

Implement and test deterministic parsing before introducing any LLM. Provide prerecorded fixtures so CI never requires a microphone or model download.
