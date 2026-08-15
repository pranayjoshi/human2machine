#!/usr/bin/env python3
# ruff: noqa: E402
"""Milestone 1 concurrent Crown + Ganglion soak (acquisition + record only).

`--minutes` is simulated session length. `--fast` (default) covers that
timeline without sleeping wall-clock per chunk so CI stays under ~30s.
`--hardware` prints the operator procedure and does not fake devices.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for extra in (
    ROOT / "packages/contracts-python/src",
    ROOT / "packages/runtime-python/src",
    ROOT / "services/event-hub",
    ROOT / "services/session-recorder",
    ROOT / "services/ganglion-adapter",
):
    text = str(extra)
    if text not in sys.path:
        sys.path.insert(0, text)

from event_hub.hub import EventHub
from ganglion_adapter.mock import GanglionMockRuntime
from intent_contracts.control import ControlRequest
from intent_contracts.enums import ControlMethod, EventType, SessionState
from intent_contracts.envelope import EventEnvelope, new_event_id, now_monotonic_ns
from session_recorder.recorder import SessionRecorder

CROWN_SOURCE = "crown-adapter"
CROWN_CHANNELS = ["CP3", "C3", "F5", "PO3", "PO4", "F6", "C4", "CP4"]
EEG_RATE_HZ = 256
EEG_SAMPLES = 16
EEG_CHUNK_NS = EEG_SAMPLES * 1_000_000_000 // EEG_RATE_HZ
EMG_CHUNK_NS = 80_000_000
PACKET_LOSS_EVERY = 100
FULL_RATE_SECONDS = 60.0
NS_PER_MINUTE = 60 * 1_000_000_000
HARDWARE_MESSAGE = """Hardware 20-minute soak is not simulated by this script.

Run the real wall-clock soak with live devices:
  1. just run-hardware --confirm
  2. Start Crown and Ganglion adapters with --hardware
  3. Start a session and record 20 minutes
  4. Confirm packet loss and timestamp/sequence gaps are visible in the UI
  5. Confirm EEG never drives an action (shadow-only)

See docs/multimodal-intent-compiler/03_DEVICE_CONNECTION.md
(Milestone 1 concurrent soak).
"""

_EEG_CHANNEL = [0.1, 0.2, 0.1, 0.0, -0.1, 0.0, 0.1, 0.2, 0.1, 0.0, -0.1, 0.0, 0.1, 0.2, 0.1, 0.0]
_EEG_TEMPLATE = [_EEG_CHANNEL] * 8


@dataclass
class SoakReport:
    eeg_chunks: int = 0
    emg_chunks: int = 0
    packet_loss_count: int = 0
    sequence_gaps: int = 0
    duration_ns: int = 0
    ok: bool = False
    session_id: str | None = None
    session_finalized: bool = False
    fusion_required: bool = False
    safety_required: bool = False
    acquisition_only: bool = True
    hub_failed: bool = False
    timestamp_gaps: int = 0
    clock_jumps: int = 0
    invalid_events: int = 0
    eeg_features: int = 0
    emg_features: int = 0
    eeg_shadow_only: bool = True
    emg_shadow_only: bool = True
    packet_loss_visible: bool = False
    timeline_span_ns: int = 0
    wall_time_s: float = 0.0
    sessions_dir: str | None = None
    control_events: int = 0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Milestone 1 biosignal soak")
    parser.add_argument(
        "--minutes",
        type=float,
        default=20.0,
        help="Simulated session length (default 20). Not wall-clock in --fast.",
    )
    parser.add_argument(
        "--fast",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Generate the simulated timeline without per-chunk realtime sleep (default).",
    )
    parser.add_argument(
        "--hardware",
        action="store_true",
        help="Print the real 20-minute operator soak. Does not fake hardware.",
    )
    parser.add_argument("--sessions-dir", type=Path, default=None)
    parser.add_argument("--seed", type=int, default=7)
    return parser.parse_args(argv)


def _envelope(
    *,
    event_type: str,
    source: str,
    sequence: int,
    payload: dict[str, Any],
    modality: str | None,
    source_time_ns: int | None,
    quality: float = 1.0,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "event_id": new_event_id(),
        "event_type": event_type,
        "source": source,
        "modality": modality,
        "session_id": None,
        "trial_id": None,
        "sequence": sequence,
        "source_time_ns": source_time_ns,
        "received_monotonic_ns": now_monotonic_ns(),
        "quality": quality,
        "producer_version": "0.1.0",
        "payload": payload,
    }


def _eeg_chunk(sequence: int, source_time_ns: int, packet_loss_count: int) -> dict[str, Any]:
    return _envelope(
        event_type="biosignal.chunk",
        source=CROWN_SOURCE,
        sequence=sequence,
        modality="eeg",
        source_time_ns=source_time_ns,
        payload={
            "sample_rate_hz": EEG_RATE_HZ,
            "channel_names": list(CROWN_CHANNELS),
            "sample_count": EEG_SAMPLES,
            "samples": _EEG_TEMPLATE,
            "units": "microvolts",
            "filters_applied": ["crown-raw"],
            "packet_loss_count": packet_loss_count,
            "clock_confidence": 0.9,
            "estimated_first_sample_ns": source_time_ns,
        },
    )


def _eeg_feature(sequence: int, source_time_ns: int) -> dict[str, Any]:
    return _envelope(
        event_type="modality.feature",
        source=CROWN_SOURCE,
        sequence=sequence,
        modality="eeg",
        source_time_ns=source_time_ns,
        payload={
            "feature_name": "eeg_shadow",
            "window_start_ns": source_time_ns,
            "window_end_ns": source_time_ns + EEG_CHUNK_NS,
            "label": "ok",
            "confidence": 0.8,
            "candidate_scores": {"ok": 0.8, "artifact": 0.2},
            "model_id": "crown-shadow-v0",
            "shadow_only": True,
        },
    )


def _eeg_quality(sequence: int, source_time_ns: int, packet_loss_count: int) -> dict[str, Any]:
    flags = ["packet_loss"] if packet_loss_count else []
    return _envelope(
        event_type="data.quality",
        source=CROWN_SOURCE,
        sequence=sequence,
        modality="eeg",
        source_time_ns=source_time_ns,
        quality=0.88,
        payload={
            "score": 0.88,
            "components": {"packet_quality": 0.9, "channel_validity": 1.0},
            "flags": flags,
        },
    )


def _inject_emg_loss(runtime: GanglionMockRuntime) -> None:
    runtime._acq.packet_loss_count += 1
    runtime._acq.sample_index += runtime._acq.samples_per_chunk
    runtime.sequence += 1


def run_soak(
    *,
    minutes: float = 20.0,
    fast: bool = True,
    sessions_dir: Path | None = None,
    seed: int = 7,
) -> SoakReport:
    """In-process hub + recorder soak. Fusion and safety are not started."""
    _ = fast
    started = time.perf_counter()
    report = SoakReport(fusion_required=False, safety_required=False, acquisition_only=True)
    cleanup_dir: tempfile.TemporaryDirectory[str] | None = None
    if sessions_dir is None:
        cleanup_dir = tempfile.TemporaryDirectory(prefix="soak-biosignals-")
        sessions_dir = Path(cleanup_dir.name)
    sessions_dir.mkdir(parents=True, exist_ok=True)
    report.sessions_dir = str(sessions_dir)

    recorder = SessionRecorder(sessions_dir, repo_dir=ROOT)
    published: list[EventEnvelope] = []

    def on_publish(event: EventEnvelope) -> None:
        published.append(event)
        recorder.handle_event_sync(event.model_dump(mode="json"))

    hub = EventHub(retain_published=False, on_publish=on_publish)
    try:
        start = hub.handle_control(
            ControlRequest(
                method=ControlMethod.SESSION_START,
                request_id="soak-start",
                payload={"consent": True, "user_id": "soak"},
            )
        )
        if not start.ok or start.session_id is None:
            report.notes.append(start.error or "session.start failed")
            report.hub_failed = True
            return report
        report.session_id = start.session_id

        timeline_ns = max(1, int(minutes * NS_PER_MINUTE))
        full_rate_s = FULL_RATE_SECONDS if minutes >= 1 else max(1.0, minutes * 60.0)

        eeg_seq = 0
        eeg_loss = 0
        eeg_times: list[int] = []
        emg_runtime = GanglionMockRuntime(seed=seed, packet_loss=0.0, shadow_only=True)
        eeg_chunks_due = int(full_rate_s * EEG_RATE_HZ / EEG_SAMPLES)
        emg_ticks_due = int(round(full_rate_s * 1000.0 / 80.0))

        hub.ingest(
            _envelope(
                event_type="device.status",
                source=CROWN_SOURCE,
                sequence=eeg_seq,
                modality="eeg",
                source_time_ns=None,
                payload={
                    "status": "healthy",
                    "device_alias": "crown-mock",
                    "detail": "soak stream started",
                    "metadata": {"mode": "fast"},
                },
            )
        )
        eeg_seq += 1

        eeg_i = 0
        emg_i = 0
        eeg_t = 0
        emg_t = 0
        while eeg_i < eeg_chunks_due or emg_i < emg_ticks_due:
            emit_eeg = eeg_i < eeg_chunks_due and (emg_i >= emg_ticks_due or eeg_t <= emg_t)
            if emit_eeg:
                if (eeg_i + 1) % PACKET_LOSS_EVERY == 0:
                    eeg_loss += 1
                    eeg_seq += 1
                    eeg_t += EEG_CHUNK_NS
                    eeg_i += 1
                    continue
                source_time_ns = eeg_t
                ingested = hub.ingest(_eeg_chunk(eeg_seq, source_time_ns, eeg_loss))
                if ingested is not None:
                    report.eeg_chunks += 1
                    eeg_times.append(source_time_ns)
                eeg_seq += 1
                hub.ingest(_eeg_quality(eeg_seq, source_time_ns, eeg_loss))
                eeg_seq += 1
                if report.eeg_chunks > 0 and report.eeg_chunks % 16 == 0:
                    hub.ingest(_eeg_feature(eeg_seq, source_time_ns))
                    eeg_seq += 1
                eeg_t += EEG_CHUNK_NS
                eeg_i += 1
            else:
                if (emg_i + 1) % PACKET_LOSS_EVERY == 0:
                    _inject_emg_loss(emg_runtime)
                    emg_t += EMG_CHUNK_NS
                    emg_i += 1
                    continue
                for event in emg_runtime.tick():
                    raw = event.to_unnormalized_dict()
                    hub.ingest(raw)
                    if str(event.event_type) == EventType.BIOSIGNAL_CHUNK.value:
                        report.emg_chunks += 1
                emg_t += EMG_CHUNK_NS
                emg_i += 1

        if eeg_times:
            jump_from = eeg_times[-1]
            jump_to = timeline_ns
            if jump_to > jump_from + 2 * EEG_CHUNK_NS:
                report.timestamp_gaps += 1
            eeg_seq += 1
            span_eeg = hub.ingest(_eeg_chunk(eeg_seq, jump_to, eeg_loss))
            if span_eeg is not None:
                report.eeg_chunks += 1
                eeg_times.append(jump_to)
            eeg_seq += 1
            hub.ingest(_eeg_quality(eeg_seq, jump_to, eeg_loss))
            eeg_seq += 1
            hub.ingest(_eeg_feature(eeg_seq, jump_to))

            emg_runtime.sequence += 1
            for event in emg_runtime.tick():
                raw = event.to_unnormalized_dict()
                if str(event.event_type) == EventType.BIOSIGNAL_CHUNK.value:
                    raw["source_time_ns"] = jump_to
                    payload = dict(raw.get("payload") or {})
                    payload["estimated_first_sample_ns"] = jump_to
                    raw["payload"] = payload
                    report.emg_chunks += 1
                hub.ingest(raw)

        stop = hub.handle_control(
            ControlRequest(
                method=ControlMethod.SESSION_STOP,
                request_id="soak-stop",
                session_id=report.session_id,
            )
        )
        if not stop.ok:
            report.notes.append(stop.error or "session.stop failed")
            report.hub_failed = True

        report.sequence_gaps = hub.metrics.sequence_gaps
        report.clock_jumps = hub.metrics.clock_jumps
        report.invalid_events = hub.metrics.invalid
        report.hub_failed = report.hub_failed or hub.session.state is SessionState.FAILED
        report.session_finalized = (
            hub.session.state is SessionState.FINALIZED
            and recorder.store.manifest is not None
            and recorder.store.manifest.get("finalization_status") == "finalized"
        )
        if eeg_times:
            report.timeline_span_ns = eeg_times[-1] - eeg_times[0]
            report.duration_ns = report.timeline_span_ns
        report.packet_loss_count = eeg_loss + int(emg_runtime._acq.packet_loss_count)

        for event in published:
            event_type = str(event.event_type)
            if event_type in {EventType.INTENT_DECISION.value, EventType.SAFETY_DECISION.value}:
                report.control_events += 1
            if event_type != EventType.BIOSIGNAL_CHUNK.value:
                continue
            loss = int((event.payload or {}).get("packet_loss_count") or 0)
            if loss > 0:
                report.packet_loss_visible = True
            if event.modality == "eeg" or event.source == CROWN_SOURCE:
                report.packet_loss_count = max(report.packet_loss_count, loss)
        for event in published:
            if str(event.event_type) != EventType.MODALITY_FEATURE.value:
                continue
            shadow = bool((event.payload or {}).get("shadow_only"))
            if event.modality == "eeg" or event.source == CROWN_SOURCE:
                report.eeg_features += 1
                report.eeg_shadow_only = report.eeg_shadow_only and shadow
            elif event.modality == "emg":
                report.emg_features += 1
                report.emg_shadow_only = report.emg_shadow_only and shadow

        if report.timeline_span_ns + EEG_CHUNK_NS < timeline_ns:
            report.notes.append("timeline did not span the requested minutes")
        if report.eeg_chunks < int(full_rate_s * EEG_RATE_HZ / EEG_SAMPLES) * 0.9:
            report.notes.append("EEG full-rate window is short")
        if report.emg_chunks < int(full_rate_s * 1000.0 / 80.0) * 0.9:
            report.notes.append("EMG full-rate window is short")

        report.ok = (
            not report.hub_failed
            and report.invalid_events == 0
            and report.eeg_chunks > 0
            and report.emg_chunks > 0
            and report.sequence_gaps > 0
            and report.packet_loss_visible
            and report.timestamp_gaps > 0
            and report.session_finalized
            and report.control_events == 0
            and report.timeline_span_ns >= timeline_ns - EEG_CHUNK_NS
            and (report.eeg_features == 0 or report.eeg_shadow_only)
            and (report.emg_features == 0 or report.emg_shadow_only)
        )
        return report
    finally:
        report.wall_time_s = time.perf_counter() - started
        if not recorder.store._finalized:
            recorder.stop(finalize_open=True)
        if cleanup_dir is not None:
            cleanup_dir.cleanup()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.hardware:
        print(HARDWARE_MESSAGE)
        return 0
    report = run_soak(
        minutes=args.minutes,
        fast=args.fast,
        sessions_dir=args.sessions_dir,
        seed=args.seed,
    )
    print(json.dumps(report.to_dict(), indent=2))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
