"""Session recorder service entrypoint.

``python -m session_recorder.main --mock`` subscribes to the normalized event
stream on 5556, records sessions, and heartbeats on 5555 every 2s.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from intent_contracts.envelope import EventEnvelope
from intent_runtime.config import load_stacked_config
from intent_runtime.heartbeat import heartbeat_event
from intent_runtime.logging import configure_logging
from intent_runtime.zmq_bus import AdapterPush, NormalizedSubscriber

from session_recorder.constants import ADAPTER_PUSH, NORMALIZED_PUB, SOURCE_NAME
from session_recorder.recorder import SessionRecorder, heartbeat_interval


def build_recorder(config: dict, *, sessions_dir: Path | None = None) -> SessionRecorder:
    storage = config.get("storage") or {}
    root = Path(sessions_dir or storage.get("sessions_dir") or "data/sessions")
    config_dir = Path("configs")
    return SessionRecorder(
        root,
        config_dir=config_dir if config_dir.is_dir() else None,
        config=config,
        repo_dir=Path.cwd(),
    )


def run_loop(
    recorder: SessionRecorder,
    *,
    config: dict,
    mock: bool = False,
) -> None:
    runtime = config.get("runtime") or {}
    ports = runtime.get("ports") or {}
    sub_endpoint = str(ports.get("normalized_pub") or NORMALIZED_PUB)
    push_endpoint = str(ports.get("adapter_push") or ADAPTER_PUSH)
    interval = heartbeat_interval(config)
    subscriber = NormalizedSubscriber(sub_endpoint)
    push = AdapterPush(push_endpoint)
    recorder.start()
    started = time.monotonic()
    last_heartbeat = 0.0
    sequence = 0
    print(
        f"session-recorder listening on {sub_endpoint} "
        f"(heartbeat {push_endpoint} every {interval}s, mock={mock})"
    )
    try:
        while True:
            now = time.monotonic()
            if now - last_heartbeat >= interval:
                event: EventEnvelope = heartbeat_event(
                    SOURCE_NAME,
                    uptime_seconds=now - started,
                    last_data_age_ms=recorder.data_age_ms(),
                    sequence=sequence,
                    session_id=recorder.store.session_id,
                )
                push.send_event(event)
                sequence += 1
                last_heartbeat = now
            incoming = subscriber.recv_event(timeout_ms=100)
            if incoming is not None:
                recorder.handle_event(incoming)
    except KeyboardInterrupt:
        print("session-recorder shutting down")
    finally:
        recorder.stop()
        subscriber.close()
        push.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Session recorder")
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Subscribe and record without hardware (same loop; for mock stacks)",
    )
    parser.add_argument("--sessions-dir", default=None)
    args = parser.parse_args(argv)
    configure_logging("session-recorder")
    config = load_stacked_config()
    sessions_dir = Path(args.sessions_dir) if args.sessions_dir else None
    recorder = build_recorder(config, sessions_dir=sessions_dir)
    run_loop(recorder, config=config, mock=args.mock)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
