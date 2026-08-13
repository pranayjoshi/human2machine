from __future__ import annotations

import argparse
import signal
import time
from pathlib import Path

from intent_runtime.config import load_stacked_config

from ganglion_adapter.acquisition import BrainFlowAcquisition
from ganglion_adapter.mock import GanglionMockRuntime
from ganglion_adapter.publisher import BoundedAdapterPush, ListSink


def find_repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in [here, *here.parents]:
        if (parent / "configs" / "local.yaml").exists():
            return parent
    return Path.cwd()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OpenBCI Ganglion EMG adapter")
    parser.add_argument("--mock", action="store_true", default=True)
    parser.add_argument("--hardware", action="store_true")
    parser.add_argument("--list-devices", action="store_true")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--endpoint", default=None)
    parser.add_argument("--duration-seconds", type=float, default=0.0)
    parser.add_argument("--disconnect-after-ms", type=float, default=0.0)
    parser.add_argument("--snr-db", type=float, default=12.0)
    parser.add_argument("--packet-loss", type=float, default=0.0)
    return parser


def list_serial_candidates() -> list[str]:
    import glob

    return sorted(glob.glob("/dev/cu.usb*") + glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*"))


def main(argv: list[str] | None = None, sink: BoundedAdapterPush | ListSink | None = None) -> None:
    args = build_parser().parse_args(argv)
    mock = not args.hardware
    config = load_stacked_config(find_repo_root() / "configs")
    endpoint = args.endpoint or config.get("runtime", {}).get("ports", {}).get(
        "adapter_push", "tcp://127.0.0.1:5555"
    )
    ganglion = config.get("ganglion", {})

    if args.list_devices:
        ports = ["mock"] if mock else list_serial_candidates()
        for port in ports:
            print(port)
        return

    if not mock:
        serial_port = config.get("devices", {}).get("ganglion", {}).get("serial_port")
        board = BrainFlowAcquisition(serial_port)
        print("hardware Ganglion path is stubbed; use --mock")
        try:
            board.start()
        except RuntimeError as exc:
            print(exc)
        return

    publisher = sink or BoundedAdapterPush(endpoint)
    runtime = GanglionMockRuntime(
        seed=args.seed,
        sample_rate_hz=float(ganglion.get("sample_rate_hz", 200)),
        chunk_ms=float(ganglion.get("chunk_ms", 80)),
        window_ms=float(ganglion.get("window_ms", 250)),
        hop_ms=float(ganglion.get("hop_ms", 50)),
        dwell_ms=float(ganglion.get("dwell_ms", 200)),
        hysteresis=float(ganglion.get("hysteresis", 0.12)),
        refractory_ms=float(ganglion.get("refractory_ms", 400)),
        confidence_threshold=float(ganglion.get("confidence_threshold", 0.7)),
        snr_db=args.snr_db,
        packet_loss=args.packet_loss,
    )
    stop = False

    def _halt(_signum=None, _frame=None) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _halt)
    signal.signal(signal.SIGTERM, _halt)

    started = time.monotonic()
    last_heartbeat = 0.0
    chunk_s = runtime.chunk_ms / 1000.0
    try:
        while not stop:
            now = time.monotonic()
            disconnect_ms = args.disconnect_after_ms
            if disconnect_ms > 0 and (now - started) * 1000.0 >= disconnect_ms:
                runtime.set_disconnected(True)
            for event in runtime.tick():
                publisher.send_event(event)
            if now - last_heartbeat >= 2.0:
                publisher.send_event(
                    runtime.heartbeat_event(now - started, publisher.dropped_count)
                )
                last_heartbeat = now
            if args.duration_seconds > 0 and (now - started) >= args.duration_seconds:
                break
            time.sleep(chunk_s)
        publisher.send_event(runtime.shutdown_event())
    finally:
        publisher.close()


if __name__ == "__main__":
    main()
