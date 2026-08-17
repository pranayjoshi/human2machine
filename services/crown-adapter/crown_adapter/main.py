from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from intent_runtime.config import load_stacked_config

from crown_adapter.brainflow_client import (
    BrainFlowCrownClient,
    FallbackCrownClient,
    connection_from_mapping,
)
from crown_adapter.client import CrownAuthError, NeurosityPythonClient, log_progress
from crown_adapter.events import device_status
from crown_adapter.hardware import CrownConfig, run_crown_hardware
from crown_adapter.mock import SAMPLE_RATE_HZ, SAMPLES_PER_CHUNK, CrownMockRuntime
from crown_adapter.publisher import BoundedAdapterPush, ListSink


def find_repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in [here, *here.parents]:
        if (parent / "configs" / "local.yaml").exists():
            return parent
    return Path.cwd()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Neurosity Crown EEG adapter (MindExecute neurosity SDK path)"
    )
    parser.add_argument("--mock", action="store_true", default=True)
    parser.add_argument("--hardware", action="store_true")
    parser.add_argument("--list-devices", action="store_true")
    parser.add_argument(
        "--ip",
        default=None,
        help="Ignored. BrainFlow Crown OSC does not connect to a headset IP.",
    )
    parser.add_argument(
        "--ip-port",
        type=int,
        default=None,
        help="UDP listen port (default 9000)",
    )
    parser.add_argument(
        "--device-id",
        default=None,
        help="Optional nickname for logs (BrainFlow does not need it for one Crown)",
    )
    parser.add_argument(
        "--backend",
        choices=("auto", "osc", "sdk"),
        default="sdk",
        help="sdk: MindExecute neurosity path (default); osc: UDP 9000; auto: OSC then SDK",
    )
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--motion", action="store_true")
    parser.add_argument("--packet-loss", type=float, default=0.0)
    parser.add_argument("--endpoint", default=None)
    parser.add_argument("--duration-seconds", type=float, default=0.0)
    parser.add_argument("--disconnect-after-ms", type=float, default=0.0)
    return parser


def _crown_config(raw: dict) -> CrownConfig:
    return CrownConfig(
        sample_rate_hz=int(raw.get("sample_rate_hz", 256)),
        channels=int(raw.get("channels", 8)),
        samples_per_chunk=int(raw.get("samples_per_chunk", 16)),
        heartbeat_seconds=float(raw.get("heartbeat_seconds", 2)),
        motion_artifact_threshold=float(raw.get("motion_artifact_threshold", 0.8)),
        shadow_only=bool(raw.get("shadow_only", True)),
        reconnect_max_seconds=float(raw.get("reconnect_max_seconds", 30)),
    )


def main(argv: list[str] | None = None, sink: BoundedAdapterPush | ListSink | None = None) -> int:
    args = build_parser().parse_args(argv)
    mock = not args.hardware
    root = find_repo_root()
    load_dotenv(root / ".env.local", override=False)
    config = load_stacked_config(root / "configs")
    endpoint = args.endpoint or config.get("runtime", {}).get("ports", {}).get(
        "adapter_push", "tcp://127.0.0.1:5555"
    )
    crown_cfg = _crown_config(config.get("crown", {}))
    devices_crown = config.get("devices", {}).get("crown", {})
    connection = connection_from_mapping(
        devices_crown,
        ip_address=args.ip,
        ip_port=args.ip_port,
        device_id=args.device_id,
    )

    if args.list_devices:
        print(
            json.dumps(
                {
                    "event": "crown_osc",
                    "ip_address": connection.ip_address or None,
                    "ip_port": connection.ip_port or None,
                    "device_id": connection.device_id or None,
                    "backend": args.backend,
                    "msg": (
                        "Default --backend auto tries OSC on UDP 9000, then the Neurosity SDK. "
                        "Enable OSC or keep NEUROSITY_* in .env.local."
                    ),
                }
            )
        )
        return 0

    publisher = sink or BoundedAdapterPush(endpoint)
    stop = False

    def _halt(_signum=None, _frame=None) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _halt)
    signal.signal(signal.SIGTERM, _halt)

    try:
        if mock:
            runtime = CrownMockRuntime(
                seed=args.seed,
                motion=args.motion,
                packet_loss=args.packet_loss,
                motion_artifact_threshold=crown_cfg.motion_artifact_threshold,
                shadow_only=crown_cfg.shadow_only,
            )
            started = time.monotonic()
            last_heartbeat = 0.0
            chunk_s = SAMPLES_PER_CHUNK / SAMPLE_RATE_HZ
            disconnect_fired = False
            while not stop:
                now = time.monotonic()
                if (
                    args.disconnect_after_ms > 0
                    and not disconnect_fired
                    and (now - started) * 1000.0 >= args.disconnect_after_ms
                ):
                    for event in runtime.simulate_disconnect():
                        publisher.send_event(event)
                    disconnect_fired = True
                for event in runtime.tick():
                    publisher.send_event(event)
                if now - last_heartbeat >= crown_cfg.heartbeat_seconds:
                    publisher.send_event(runtime.heartbeat_event(publisher.dropped_count))
                    last_heartbeat = now
                if args.duration_seconds > 0 and (now - started) >= args.duration_seconds:
                    break
                time.sleep(chunk_s)
            publisher.send_event(runtime.shutdown_event())
            return 0

        if args.backend == "osc":
            client = BrainFlowCrownClient(connection)
        elif args.backend == "auto":
            client = FallbackCrownClient(connection)
        else:
            client = NeurosityPythonClient(device_id=connection.device_id)
        log_progress(f"hardware backend={args.backend}")
        run_crown_hardware(
            client=client,
            send=publisher.send_event,
            config=crown_cfg,
            stopped=lambda: stop,
            duration_s=args.duration_seconds,
        )
        return 0
    except CrownAuthError as exc:
        publisher.send_event(device_status(0, "offline", str(exc), device_alias="crown"))
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        publisher.close()


if __name__ == "__main__":
    raise SystemExit(main())
