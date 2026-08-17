from __future__ import annotations

import math
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from intent_contracts.envelope import EventEnvelope

from crown_adapter.client import (
    CrownAccel,
    CrownAuthError,
    CrownClient,
    CrownEpoch,
    EpochQueue,
    headset_idle_detail,
    log_progress,
)
from crown_adapter.events import device_status, heartbeat, make_event
from crown_adapter.quality import (
    CROWN_CHANNELS,
    device_ms_to_ns,
    sanitize_samples,
    score_quality,
)

DEVICE_ALIAS = "crown"
LOGIN_TIMEOUT_S = 60.0
IDLE_WARN_S = 8.0
MOTION_AXES = ("x", "y", "z")


@dataclass
class CrownConfig:
    sample_rate_hz: int = 256
    channels: int = 8
    samples_per_chunk: int = 16
    heartbeat_seconds: float = 2.0
    motion_artifact_threshold: float = 0.8
    shadow_only: bool = True
    reconnect_max_seconds: float = 30.0


@dataclass
class AccelState:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    magnitude: float = 0.0
    has_sample: bool = False


@dataclass
class ConvertedEpoch:
    events: list[EventEnvelope] = field(default_factory=list)
    rejected: bool = False
    clock_offset_ns: int | None = None


def backoff_s(attempt: int, cap_seconds: float) -> float:
    cap = max(1.0, cap_seconds)
    return min(cap, float(2 ** max(0, attempt)))


def is_missing_credentials(message: str) -> bool:
    return any(
        token in message
        for token in (
            "NEUROSITY_EMAIL",
            "NEUROSITY_PASSWORD",
            "NEUROSITY_DEVICE_ID",
            "Crown IP",
        )
    )


def is_auth_failure(message: str) -> bool:
    if is_missing_credentials(message):
        return False
    return bool(
        re.search(
            r"password|passwd|token|secret|authorization|unauthori[sz]ed|unauthenticated|invalid.?credential",
            message,
            re.I,
        )
    )


def update_accel(target: AccelState, sample: CrownAccel) -> None:
    target.x = float(sample.x)
    target.y = float(sample.y)
    target.z = float(sample.z)
    target.magnitude = math.sqrt(target.x**2 + target.y**2 + target.z**2)
    target.has_sample = math.isfinite(target.magnitude)


def convert_epoch(
    epoch: CrownEpoch,
    accel: AccelState,
    *,
    sequence: Callable[[], int],
    packet_loss_count: int,
    chunks_emitted: int,
    motion_artifact_threshold: float,
    expected_channels: int,
    expected_samples: int,
    sample_rate_hz: float,
    shadow_only: bool,
    clock_offset_ns: int | None,
) -> ConvertedEpoch:
    samples = epoch.data if len(epoch.data) == expected_channels else []
    sample_count = len(samples[0]) if samples else 0
    if not samples or sample_count == 0:
        return ConvertedEpoch(rejected=True, clock_offset_ns=clock_offset_ns)
    channel_names = (
        epoch.channel_names
        if len(epoch.channel_names) == expected_channels
        else list(CROWN_CHANNELS)
    )
    cleaned, invalid = sanitize_samples(samples)
    source_time_ns = None
    offset = clock_offset_ns
    if epoch.start_time_ms is not None and math.isfinite(epoch.start_time_ms):
        source_time_ns = device_ms_to_ns(epoch.start_time_ms)
        if offset is None:
            offset = time.time_ns() - source_time_ns
    motion_magnitude = accel.magnitude if accel.has_sample else 0.0
    quality = score_quality(
        samples=cleaned,
        packet_loss_count=packet_loss_count,
        chunks_since_loss=chunks_emitted,
        motion_magnitude=motion_magnitude,
        motion_artifact_threshold=motion_artifact_threshold,
    )
    if invalid:
        quality.flags.append("sanitized_non_finite")
    if sample_count != expected_samples:
        quality.flags.append("unexpected_epoch_length")
    rate = epoch.sampling_rate or sample_rate_hz
    events: list[EventEnvelope] = [
        make_event(
            event_type="biosignal.chunk",
            sequence=sequence(),
            source_time_ns=source_time_ns,
            quality=quality.score,
            payload={
                "sample_rate_hz": rate,
                "channel_names": channel_names,
                "sample_count": sample_count,
                "samples": cleaned,
                "units": "microvolts",
                "filters_applied": ["crown_raw_filtered"],
                "packet_loss_count": packet_loss_count,
                "clock_confidence": 0.2 if source_time_ns is None else 1,
                "estimated_first_sample_ns": source_time_ns,
            },
        )
    ]
    if accel.has_sample:
        events.append(
            make_event(
                event_type="motion.chunk",
                modality="imu",
                sequence=sequence(),
                source_time_ns=source_time_ns,
                quality=quality.score,
                payload={
                    "sample_rate_hz": rate / max(sample_count, 1),
                    "axes": list(MOTION_AXES),
                    "sample_count": 1,
                    "samples": [[accel.x], [accel.y], [accel.z]],
                    "units": "g",
                    "magnitude": accel.magnitude,
                },
            )
        )
    events.append(
        make_event(
            event_type="data.quality",
            sequence=sequence(),
            source_time_ns=source_time_ns,
            quality=quality.score,
            payload={
                "score": quality.score,
                "components": {
                    "packet_quality": quality.packet_quality,
                    "channel_validity": quality.channel_validity,
                    "motion_penalty": quality.motion_penalty,
                },
                "flags": quality.flags,
            },
        )
    )
    if chunks_emitted > 0 and chunks_emitted % 16 == 0 and source_time_ns is not None:
        artifact = motion_magnitude > motion_artifact_threshold
        events.append(
            make_event(
                event_type="modality.feature",
                sequence=sequence(),
                source_time_ns=source_time_ns,
                quality=quality.score,
                payload={
                    "feature_name": "eeg_shadow",
                    "window_start_ns": source_time_ns,
                    "window_end_ns": source_time_ns + device_ms_to_ns(62),
                    "label": "artifact" if artifact else "ok",
                    "confidence": quality.score,
                    "candidate_scores": {
                        "ok": max(0.0, 1.0 - quality.score) if artifact else quality.score,
                        "artifact": quality.score if artifact else max(0.0, 1.0 - quality.score),
                    },
                    "model_id": "crown-shadow-v0",
                    "shadow_only": shadow_only,
                },
            )
        )
    return ConvertedEpoch(events=events, rejected=False, clock_offset_ns=offset)


class _Seq:
    def __init__(self) -> None:
        self.value = 0

    def next(self) -> int:
        current = self.value
        self.value += 1
        return current


def run_crown_hardware(
    *,
    client: CrownClient,
    send: Callable[[EventEnvelope], None],
    config: CrownConfig,
    stopped: Callable[[], bool],
    duration_s: float = 0.0,
    login_timeout_s: float = LOGIN_TIMEOUT_S,  # kept for call-site compatibility
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] | None = None,
) -> None:
    clock = now or time.monotonic
    started = clock()
    _ = login_timeout_s
    deadline = started + duration_s if duration_s > 0 else 0.0
    seq = _Seq()
    last_heartbeat = float("-inf")
    attempt = 0

    def halt() -> bool:
        if stopped():
            return True
        return deadline > 0 and clock() >= deadline

    def maybe_heartbeat(status: str, last_data: float | None, dropped: int) -> None:
        nonlocal last_heartbeat
        t = clock()
        if t - last_heartbeat < config.heartbeat_seconds:
            return
        age = None if last_data is None else (t - last_data) * 1000.0
        send(heartbeat(seq.next(), t - started, age, dropped, status))
        last_heartbeat = t

    send(
        device_status(seq.next(), "degraded", "connecting to Neurosity", device_alias=DEVICE_ALIAS)
    )
    log_progress("connecting to Neurosity")
    maybe_heartbeat("degraded", None, 0)
    try:
        while not halt():
            try:
                # MindExecute connect() is blocking on the main thread.
                client.login()
                attempt = 0
                _consume_stream(
                    client=client,
                    config=config,
                    send=send,
                    seq=seq,
                    halt=halt,
                    maybe_heartbeat=maybe_heartbeat,
                    sleep=sleep,
                    clock=clock,
                )
                if halt():
                    break
                send(
                    device_status(
                        seq.next(),
                        "degraded",
                        "crown stream ended; reconnecting",
                        device_alias=DEVICE_ALIAS,
                    )
                )
            except CrownAuthError as exc:
                detail = str(exc)
                log_progress(detail)
                if is_missing_credentials(detail):
                    send(
                        device_status(
                            seq.next(),
                            "offline",
                            "missing Crown OSC IP",
                            device_alias=DEVICE_ALIAS,
                        )
                    )
                    print(_safe_error(detail), flush=True)
                    return
                if "timed out" in detail.lower():
                    send(
                        device_status(
                            seq.next(),
                            "degraded",
                            "Crown connect timed out",
                            {"reconnect_attempt": attempt + 1},
                            DEVICE_ALIAS,
                        )
                    )
                elif is_auth_failure(detail) or "authentication failed" in detail.lower():
                    send(
                        device_status(
                            seq.next(),
                            "degraded",
                            "neurosity authentication failed; reconnecting",
                            {"reconnect_attempt": attempt + 1},
                            DEVICE_ALIAS,
                        )
                    )
                else:
                    send(
                        device_status(
                            seq.next(),
                            "degraded",
                            detail,
                            {"reconnect_attempt": attempt + 1},
                            DEVICE_ALIAS,
                        )
                    )
            except Exception as exc:
                log_progress(f"crown disconnected ({type(exc).__name__})")
                send(
                    device_status(
                        seq.next(),
                        "degraded",
                        "crown disconnected; reconnecting",
                        {"reconnect_attempt": attempt + 1},
                        DEVICE_ALIAS,
                    )
                )
                _ = exc
            if halt():
                break
            wait_s = backoff_s(attempt, config.reconnect_max_seconds)
            attempt += 1
            log_progress(f"retry in {wait_s:.0f}s")
            try:
                client.stop()
            except Exception:
                pass
            wait_end = clock() + wait_s
            while not halt() and clock() < wait_end:
                maybe_heartbeat("degraded", None, 0)
                sleep(min(0.2, wait_end - clock()))
    finally:
        send(device_status(seq.next(), "offline", "adapter stopping", device_alias=DEVICE_ALIAS))
        try:
            client.stop()
        except Exception:
            pass


def _consume_stream(
    *,
    client: CrownClient,
    config: CrownConfig,
    send: Callable[[EventEnvelope], None],
    seq: _Seq,
    halt: Callable[[], bool],
    maybe_heartbeat: Callable[[str, float | None, int], None],
    sleep: Callable[[float], None],
    clock: Callable[[], float],
) -> None:
    pending = EpochQueue()
    accel = AccelState()
    last_start = float("-inf")
    chunks_emitted = 0
    packet_loss_count = 0
    clock_offset_ns: int | None = None
    last_data: float | None = None
    waiting_since = clock()
    idle_notified = False
    send(
        device_status(
            seq.next(),
            "degraded",
            "logged in; waiting for EEG samples",
            device_alias=DEVICE_ALIAS,
        )
    )
    client.start(pending.push_epoch, pending.push_accel)
    poll_logged = False
    try:
        while not halt():
            update_accel(accel, pending.accel())
            epochs = pending.drain_epochs()
            if not epochs:
                try:
                    polled = client.poll_epoch()
                except Exception:
                    polled = None
                if polled is not None:
                    if not poll_logged:
                        log_progress("receiving EEG via Firebase poll (live stream idle)")
                        poll_logged = True
                    epochs = [polled]
            if (
                not epochs
                and chunks_emitted == 0
                and not idle_notified
                and clock() - waiting_since >= IDLE_WARN_S
            ):
                idle_notified = True
                try:
                    status = client.headset_status()
                except Exception:
                    status = {}
                if accel.has_sample:
                    detail = (
                        "Crown is online but not publishing EEG; "
                        "put it on your head until the sensors make contact"
                    )
                else:
                    detail = headset_idle_detail(status if isinstance(status, dict) else {})
                log_progress(detail)
                send(
                    device_status(
                        seq.next(),
                        "degraded",
                        detail,
                        device_alias=DEVICE_ALIAS,
                    )
                )
            for epoch in epochs:
                start = epoch.start_time_ms
                if start is not None and math.isfinite(start) and start <= last_start:
                    continue
                if start is not None and math.isfinite(start):
                    last_start = start
                converted = convert_epoch(
                    epoch,
                    accel,
                    sequence=seq.next,
                    packet_loss_count=packet_loss_count + pending.dropped,
                    chunks_emitted=chunks_emitted,
                    motion_artifact_threshold=config.motion_artifact_threshold,
                    expected_channels=config.channels,
                    expected_samples=config.samples_per_chunk,
                    sample_rate_hz=config.sample_rate_hz,
                    shadow_only=config.shadow_only,
                    clock_offset_ns=clock_offset_ns,
                )
                if converted.rejected:
                    packet_loss_count += 1
                    continue
                clock_offset_ns = converted.clock_offset_ns
                for event in converted.events:
                    send(event)
                if chunks_emitted == 0:
                    send(
                        device_status(
                            seq.next(), "healthy", "crown stream started", device_alias=DEVICE_ALIAS
                        )
                    )
                    log_progress("EEG stream started (8 ch, 256 Hz)")
                chunks_emitted += 1
                last_data = clock()
            maybe_heartbeat(
                "healthy" if chunks_emitted else "degraded",
                last_data,
                packet_loss_count + pending.dropped,
            )
            if chunks_emitted > 0 and not epochs:
                # Live SDK pushes from a background thread; sleep between polls.
                # Fake clients dump epochs during start(); one extra drain pass is enough.
                if pending.drain_epochs():
                    continue
                if not hasattr(client, "epochs"):
                    sleep(0.05)
                else:
                    return
            elif not epochs:
                sleep(0.05)
            elif not hasattr(client, "epochs"):
                sleep(0.05)
    finally:
        try:
            client.stop()
        except Exception:
            pass


def _safe_error(raw: str) -> str:
    if is_missing_credentials(raw):
        return (
            '{"level":"error","service":"crown-adapter",'
            '"msg":"missing Crown OSC IP; pass --ip or set devices.crown.ip_address '
            '(same as MindExecute --ip)"}'
        )
    if is_auth_failure(raw) or "authentication failed" in raw.lower():
        return (
            '{"level":"error","service":"crown-adapter",'
            '"msg":"Neurosity authentication failed; check .env.local (values are not logged)"}'
        )
    return raw
