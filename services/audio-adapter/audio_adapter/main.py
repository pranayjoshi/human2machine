from __future__ import annotations

import argparse
import signal
import time

from intent_runtime.config import load_stacked_config

from audio_adapter.mock import AudioMockRuntime, find_repo_root
from audio_adapter.publisher import BoundedAdapterPush, ListSink


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local audio intent adapter")
    parser.add_argument("--mock", action="store_true", default=True)
    parser.add_argument("--hardware", action="store_true")
    parser.add_argument("--endpoint", default=None)
    parser.add_argument("--duration-seconds", type=float, default=0.0)
    parser.add_argument("--list-devices", action="store_true")
    return parser


def main(argv: list[str] | None = None, sink: BoundedAdapterPush | ListSink | None = None) -> None:
    args = build_parser().parse_args(argv)
    mock = not args.hardware
    config = load_stacked_config(find_repo_root() / "configs")
    endpoint = args.endpoint or config.get("runtime", {}).get("ports", {}).get(
        "adapter_push", "tcp://127.0.0.1:5555"
    )
    if args.list_devices:
        print("mock-fixture" if mock else "hardware microphone listing is stubbed")
        return
    if not mock:
        print("hardware microphone path is stubbed; use --mock")
        return

    publisher = sink or BoundedAdapterPush(endpoint)
    runtime = AudioMockRuntime(model_id=str(config.get("audio", {}).get("parser", "grammar_v1")))
    stop = False

    def _halt(_signum=None, _frame=None) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _halt)
    signal.signal(signal.SIGTERM, _halt)

    started = time.monotonic()
    last_heartbeat = 0.0
    last_at = max(int(row["at_ms"]) for row in runtime.utterances) if runtime.utterances else 0
    try:
        while not stop:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            for event in runtime.events_due(elapsed_ms):
                publisher.send_event(event)
            now = time.monotonic()
            if now - last_heartbeat >= 2.0:
                publisher.send_event(runtime.heartbeat(now - started, publisher.dropped_count))
                last_heartbeat = now
            if args.duration_seconds > 0 and (now - started) >= args.duration_seconds:
                break
            if args.duration_seconds == 0 and elapsed_ms > last_at + 500:
                # Keep heartbeating until interrupted; default long-running mock.
                time.sleep(0.2)
                continue
            time.sleep(0.05)
        publisher.send_event(runtime.shutdown())
    finally:
        publisher.close()


if __name__ == "__main__":
    main()
