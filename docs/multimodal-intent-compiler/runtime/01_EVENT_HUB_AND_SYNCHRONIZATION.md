# Event Hub and Synchronization Runtime

## Goal

Receive independently clocked modality events, validate them, normalize them onto a common session timeline, and distribute them without interpreting human intent.

## Technology

- Python 3.12
- `asyncio`
- PyZMQ
- Pydantic
- Structlog
- Prometheus-compatible metrics

## Responsibilities

- Own adapter ingestion port 5555.
- Validate every event against shared contracts.
- Add a normalized timestamp.
- Attach the active session/trial IDs to recordable adapter events.
- Detect duplicates, sequence gaps, staleness, and clock jumps.
- Publish normalized events on port 5556.
- Own the local session/trial `REQ/REP` control plane on port 5558.
- Emit health and timing metrics.
- Create session and trial markers through the control API.

It does not filter EEG/EMG, transcribe audio, infer intent, or approve actions.

## Clock model

Use the Mac monotonic clock as the runtime reference.

At session start store:

```text
session_wall_time_ns
session_monotonic_time_ns
```

For each adapter event:

```text
normalized_time_ns = received_monotonic_ns - session_monotonic_time_ns
```

If a trustworthy source timestamp exists, maintain a rolling mapping between source time and arrival monotonic time. Use it to estimate sample positions inside chunks and detect network jitter, but do not rewrite history based on unstable clock estimates.

Each biosignal chunk includes:

- Source epoch start
- Normalized arrival time
- Sampling rate
- Sample count
- Estimated normalized time for first sample
- Clock confidence

## Session lifecycle

States:

- `NO_SESSION`
- `PREFLIGHT`
- `READY`
- `RECORDING`
- `STOPPING`
- `FINALIZED`
- `FAILED`

The API owns state changes. Adapters may stream health while no session exists, but biosignal/sample events are either discarded or placed in a non-recorded preview channel.

The console API is the only normal control-plane client. It requests lifecycle transitions over port 5558 and receives the generated IDs/state. The hub then publishes the corresponding lifecycle event on port 5556. Adapters never create their own session or trial IDs.

### Start session

1. Generate session ID.
2. Capture wall and monotonic anchors.
3. Snapshot config, code commit, contract version, and active model versions.
4. Check required services.
5. Publish `session.started`.
6. Allow recorder to persist events.

### Trials

Trials are explicit markers inside a session:

- `trial.started`
- `trial.instruction`
- `trial.label`
- `trial.completed`
- `trial.aborted`

The UI or experiment runner creates trials; adapters never manufacture trial IDs.

## Ingestion behavior

- Bounded queue per producer.
- Reject malformed events with a structured error counter.
- Deduplicate by event ID.
- Detect sequence regression and gaps.
- Use a maximum event size to prevent accidental video/audio payloads entering JSON transport.
- Backpressure policy favors dropping old high-rate preview events over blocking device acquisition.
- Never silently drop decisions, safety events, session markers, or action outcomes.

## Freshness defaults

Configure by event/feature type, for example:

| Evidence | Initial maximum age |
|---|---:|
| Voice final intent | 5,000 ms |
| Vision target | 500 ms |
| EMG gesture | 750 ms |
| EEG shadow feature | 1,000 ms |
| Machine state | 500 ms |
| Service heartbeat | 5,000 ms |

These limits belong in YAML and should be tuned using measured latency.

## Monitoring

Expose:

- Events per second by source/type
- Invalid events
- Duplicate events
- Sequence gaps
- Arrival latency where calculable
- Queue depth and drops
- Clock offset/jitter
- Last event age
- Session state

## Failure handling

- One dead adapter must not stop the hub.
- Hub restart ends the active session as failed; do not pretend the timeline is continuous.
- Publisher outage is reported to adapters through local health, not unbounded buffering.
- Disk-recorder failure triggers a visible session warning but does not permit unsafe actions.

## Mock and replay

- Mock mode accepts fixture event files.
- Replay mode publishes normalized historical events at real time, accelerated time, or step mode.
- Replayed events receive a new replay session ID while preserving original IDs in metadata.

## Acceptance criteria

- Sustains at least 10x expected MVP event throughput for one hour.
- No unbounded queue or memory growth.
- Duplicate events are published once.
- Sequence gaps are observable.
- Cross-language event validation passes.
- Session-relative timestamps never go backward within a producer.
- Replaying a fixture yields the same ordered semantic events.

## Instructions to Codex

Write property-based tests for timestamp and sequence handling. Build the hub before hardware adapters and use it as the single entry point for all future services.
