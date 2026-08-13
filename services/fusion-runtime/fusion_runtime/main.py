"""Fusion runtime transport loop.

Subscribes to the normalized hub stream and pushes derived intent events
back to the hub. `--mock` is required; the engine stays deterministic.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

from intent_contracts.enums import EventType
from intent_runtime.config import load_stacked_config
from intent_runtime.heartbeat import heartbeat_event
from intent_runtime.logging import configure_logging
from intent_runtime.zmq_bus import AdapterPush, NormalizedSubscriber

from fusion_runtime.engine import FusionConfig, FusionRuntimeState, UserProfile, step

SOURCE = "fusion-runtime"
HUB_SUB = "tcp://127.0.0.1:5556"
HUB_PUSH = "tcp://127.0.0.1:5555"
WINDOW_CAP = 256
KEEP_TYPES = {
    EventType.AUDIO_INTENT_CANDIDATE,
    EventType.VISION_OBJECTS,
    EventType.VISION_HANDS,
    EventType.VISION_HEAD_DIRECTION,
    EventType.MODALITY_FEATURE,
    EventType.MACHINE_STATE,
    EventType.ACTION_OUTCOME,
    EventType.SESSION_STARTED,
    EventType.SESSION_STOPPED,
    EventType.SESSION_FAILED,
    EventType.TRIAL_STARTED,
    EventType.TRIAL_COMPLETED,
    EventType.TRIAL_ABORTED,
    EventType.DATA_QUALITY,
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Intent fusion runtime")
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Required. Transport still runs; the engine is deterministic.",
    )
    parser.add_argument("--config-dir", type=Path, default=Path("configs"))
    return parser.parse_args(argv)


def _event_time_ns(event: dict[str, Any]) -> int:
    value = event.get("normalized_time_ns")
    if value is not None:
        return int(value)
    return int(event.get("received_monotonic_ns") or 0)


def _prune_window(
    window: list[dict[str, Any]],
    now_ns: int,
    config: FusionConfig,
) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    for event in window:
        etype = str(event.get("event_type") or "")
        lifecycle = etype.startswith("session.") or etype.startswith("trial.")
        if lifecycle or etype == EventType.ACTION_OUTCOME:
            kept.append(event)
            continue
        key = etype
        if etype == EventType.MODALITY_FEATURE:
            name = (event.get("payload") or {}).get("feature_name")
            if name:
                key = f"modality.feature.{name}"
        limit = config.max_age_ms(key)
        if limit is None:
            kept.append(event)
            continue
        age_ms = max(0.0, (now_ns - _event_time_ns(event)) / 1_000_000)
        if age_ms <= limit:
            kept.append(event)
    return kept[-WINDOW_CAP:]


def run(config: FusionConfig, *, heartbeat_seconds: float) -> None:
    subscriber = NormalizedSubscriber(HUB_SUB)
    publisher = AdapterPush(HUB_PUSH)
    state = FusionRuntimeState()
    profile = UserProfile()
    window: list[dict[str, Any]] = []
    started = time.monotonic()
    last_beat = 0.0
    last_input_monotonic = started
    heartbeat_seq = 0
    try:
        while True:
            raw = subscriber.recv_event(timeout_ms=100)
            now_mono = time.monotonic()
            if raw is not None and raw.get("source") != SOURCE:
                etype = str(raw.get("event_type") or "")
                if etype in KEEP_TYPES:
                    window.append(raw)
                    last_input_monotonic = now_mono
                    now_ns = _event_time_ns(raw)
                    window[:] = _prune_window(window, now_ns, config)
                    result = step(state, window, profile, config, now_ns=now_ns)
                    state = result.state
                    profile = result.user_profile
                    for event in result.events:
                        publisher.send_event(event)
            if now_mono - last_beat >= heartbeat_seconds:
                heartbeat_seq += 1
                last_data_age_ms = (now_mono - last_input_monotonic) * 1000.0
                publisher.send_event(
                    heartbeat_event(
                        SOURCE,
                        uptime_seconds=now_mono - started,
                        last_data_age_ms=last_data_age_ms,
                        sequence=heartbeat_seq,
                        session_id=state.session_id,
                    )
                )
                last_beat = now_mono
    except KeyboardInterrupt:
        return
    finally:
        subscriber.close()
        publisher.close()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.mock:
        print("fusion-runtime requires --mock", file=sys.stderr)
        return 2
    configure_logging(SOURCE)
    stacked = load_stacked_config(args.config_dir)
    config = FusionConfig.from_mapping(stacked)
    heartbeat = float(stacked.get("runtime", {}).get("heartbeat_seconds", 2))
    run(config, heartbeat_seconds=heartbeat)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
