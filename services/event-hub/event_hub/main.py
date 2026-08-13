from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import structlog
from intent_runtime.config import load_stacked_config
from intent_runtime.logging import configure_logging

from event_hub.hub import EventHub
from event_hub.server import EventHubServer, install_signal_handlers


def _config_dir(explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit
    candidates = [
        Path.cwd() / "configs",
        Path(__file__).resolve().parents[3] / "configs",
    ]
    for path in candidates:
        if path.is_dir():
            return path
    return Path("configs")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Multimodal intent compiler event hub")
    parser.add_argument("--mock", action="store_true", help="Run without hardware adapters")
    parser.add_argument(
        "--fixture",
        type=Path,
        default=None,
        help="JSONL of unnormalized events to inject (mock/replay)",
    )
    parser.add_argument("--config-dir", type=Path, default=None)
    return parser.parse_args(argv)


def build_server(args: argparse.Namespace) -> EventHubServer:
    stacked = load_stacked_config(_config_dir(args.config_dir))
    runtime = stacked.get("runtime") or {}
    ports = runtime.get("ports") or {}
    max_event_bytes = int(runtime.get("max_event_bytes") or 262144)
    heartbeat_seconds = float(runtime.get("heartbeat_seconds") or 2)
    hub = EventHub(config=stacked, max_event_bytes=max_event_bytes)
    fixture = args.fixture
    if fixture is not None and not fixture.is_file():
        raise FileNotFoundError(f"fixture not found: {fixture}")
    return EventHubServer(
        hub,
        pull_endpoint=str(ports.get("adapter_push") or "tcp://127.0.0.1:5555"),
        pub_endpoint=str(ports.get("normalized_pub") or "tcp://127.0.0.1:5556"),
        rep_endpoint=str(ports.get("control_rep") or "tcp://127.0.0.1:5558"),
        heartbeat_seconds=heartbeat_seconds,
        fixture_path=fixture,
    )


async def amain(argv: list[str] | None = None) -> int:
    configure_logging("event-hub")
    args = parse_args(argv)
    try:
        server = build_server(args)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.mock:
        structlog.get_logger("event-hub").info(
            "event_hub_mock_mode",
            fixture=str(args.fixture or ""),
        )
    install_signal_handlers(server.request_stop)
    await server.run()
    return 0


def main(argv: list[str] | None = None) -> None:
    raise SystemExit(asyncio.run(amain(argv)))


if __name__ == "__main__":
    main()
