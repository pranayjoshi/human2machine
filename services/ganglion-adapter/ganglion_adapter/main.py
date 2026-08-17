from __future__ import annotations

import argparse
import signal
import sys
import time
from pathlib import Path

from intent_runtime.config import load_stacked_config

from ganglion_adapter.acquisition import (
    TRANSPORT_BLE,
    BrainFlowAcquisition,
    connection_from_mapping,
)
from ganglion_adapter.ble_scan import is_ganglion_advertisement, scan_ble_devices
from ganglion_adapter.events import heartbeat, make_event
from ganglion_adapter.mock import GanglionMockRuntime
from ganglion_adapter.publisher import BoundedAdapterPush, ListSink


def _models_dir(root: Path, ganglion: dict) -> Path:
    raw = str(ganglion.get("model_dir") or "models/emg")
    path = Path(raw)
    return path if path.is_absolute() else root / path


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
    parser.add_argument("--port", default=None, help="Ganglion USB dongle serial port override")
    parser.add_argument(
        "--transport",
        choices=("usb_dongle", "ble"),
        default=None,
        help="usb_dongle (BLED112) or ble (native Bluetooth)",
    )
    parser.add_argument(
        "--ble",
        action="store_true",
        help="Shortcut for --transport ble (native Bluetooth, no USB dongle)",
    )
    parser.add_argument("--mac", default=None, help="Optional BLE MAC / CoreBluetooth UUID")
    parser.add_argument(
        "--serial-number",
        default=None,
        help="Optional advertised BLE name if it is not Ganglion or Simblee",
    )
    parser.add_argument("--timeout", type=int, default=None, help="BLE scan timeout in seconds")
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


def main(argv: list[str] | None = None, sink: BoundedAdapterPush | ListSink | None = None) -> int:
    args = build_parser().parse_args(argv)
    mock = not args.hardware
    config = load_stacked_config(find_repo_root() / "configs")
    endpoint = args.endpoint or config.get("runtime", {}).get("ports", {}).get(
        "adapter_push", "tcp://127.0.0.1:5555"
    )
    ganglion = config.get("ganglion", {})
    devices_ganglion = config.get("devices", {}).get("ganglion", {})
    transport_flag = "ble" if args.ble else args.transport
    connection = connection_from_mapping(
        devices_ganglion,
        transport=transport_flag,
        serial_port=args.port,
        mac_address=args.mac,
        serial_number=args.serial_number,
        timeout_seconds=args.timeout,
    )

    if args.list_devices:
        if mock:
            print("mock")
            return 0
        print("usb_dongle:")
        ports = list_serial_candidates()
        if ports:
            for port in ports:
                print(f"  {port}")
        else:
            print("  (none found under /dev/cu.usb* / ttyUSB* / ttyACM*)")
        print("ble:")
        print("  Quit OpenBCI GUI first; a connected GUI holds the BLE link and hides Simblee.")
        scan_timeout = float(args.timeout or 8)
        try:
            advertisements = scan_ble_devices(timeout_s=scan_timeout)
        except Exception as exc:
            print(f"  scan failed: {exc}")
            print("  Grant Bluetooth to Terminal/Cursor, then retry.")
            return 0
        matches = [row for row in advertisements if is_ganglion_advertisement(row.get("name"))]
        print(f"  scan {scan_timeout:.0f}s, {len(advertisements)} advertisement(s)")
        if matches:
            for row in matches:
                name = row.get("name") or "(unnamed)"
                address = row.get("address") or ""
                rssi = row.get("rssi")
                rssi_bit = f" rssi={rssi}" if rssi is not None else ""
                print(f"  {name}  {address}{rssi_bit}")
            address = matches[0].get("address")
            name = matches[0].get("name")
            if address:
                print(f"  persist with devices.ganglion.mac_address: {address}")
            if name:
                print(f"  or devices.ganglion.serial_number: {name}")
        else:
            print("  (no Ganglion/Simblee advertisement)")
            if advertisements:
                print("  nearby named devices:")
                named = [row for row in advertisements if row.get("name")][:8]
                for row in named:
                    print(f"    {row.get('name')}  {row.get('address')}")
                if not named:
                    print("    (advertisements were unnamed; Bluetooth scan is working)")
            else:
                print("  no BLE advertisements at all.")
                print("  Check Bluetooth permission and that the board LED is blinking.")
        return 0

    publisher = sink or BoundedAdapterPush(endpoint)
    stop = False

    def _halt(_signum=None, _frame=None) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _halt)
    signal.signal(signal.SIGTERM, _halt)

    acquisition = None
    try:
        if not mock:
            try:
                connection.validate()
            except RuntimeError as exc:
                _emit_offline(publisher, str(exc))
                return 1
            if connection.transport == TRANSPORT_BLE:
                print(
                    "scanning for Ganglion over Bluetooth "
                    f"(timeout {connection.timeout_seconds}s; "
                    "grant Bluetooth to Terminal if prompted; "
                    "quit OpenBCI GUI if it holds the link)",
                    file=sys.stderr,
                )
            acquisition = BrainFlowAcquisition(
                connection=connection,
                sample_rate_hz=float(ganglion.get("sample_rate_hz", 200)),
                chunk_ms=float(ganglion.get("chunk_ms", 80)),
            )
            started_wait = time.monotonic()
            seq = 0
            while not stop:
                try:
                    acquisition.start()
                    break
                except Exception as exc:
                    _emit_offline(
                        publisher,
                        f"failed to start Ganglion: {exc}; retrying "
                        "(quit OpenBCI GUI, keep the board advertising, grant Bluetooth)",
                    )
                    try:
                        acquisition.stop()
                    except Exception:
                        pass
                    seq += 1
                    publisher.send_event(
                        heartbeat(
                            seq,
                            time.monotonic() - started_wait,
                            None,
                            seq,
                            "degraded",
                        )
                    )
                    wait_end = time.monotonic() + max(1.0, float(connection.timeout_seconds))
                    while not stop and time.monotonic() < wait_end:
                        time.sleep(0.5)
            if stop:
                return 0

        runtime = GanglionMockRuntime(
            seed=args.seed,
            sample_rate_hz=float(ganglion.get("sample_rate_hz", 200)),
            chunk_ms=float(ganglion.get("chunk_ms", 80)),
            window_ms=float(ganglion.get("window_ms", 250)),
            hop_ms=float(ganglion.get("hop_ms", 50)),
            dwell_ms=float(ganglion.get("dwell_ms", 200)),
            cancel_dwell_ms=float(ganglion.get("cancel_dwell_ms", 150)),
            hysteresis=float(ganglion.get("hysteresis", 0.12)),
            refractory_ms=float(ganglion.get("refractory_ms", 400)),
            confidence_threshold=float(ganglion.get("confidence_threshold", 0.7)),
            snr_db=args.snr_db,
            packet_loss=args.packet_loss,
            device_alias="ganglion-mock" if mock else "ganglion",
            capture_mode="usb_dongle_mock" if mock else connection.capture_mode,
            model_id="emg-mock-rms-v0" if mock else "emg-rms-v0",
            shadow_only=bool(ganglion.get("shadow_only", True)),
            acquisition=acquisition,
            models_dir=_models_dir(find_repo_root(), ganglion),
        )
        started = time.monotonic()
        last_heartbeat = 0.0
        chunk_s = runtime.chunk_ms / 1000.0
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
        return 0
    finally:
        if acquisition is not None:
            acquisition.stop()
        publisher.close()


def _emit_offline(publisher: BoundedAdapterPush | ListSink, detail: str) -> None:
    print(detail, file=sys.stderr)
    publisher.send_event(
        make_event(
            event_type="device.status",
            sequence=0,
            payload={
                "status": "offline",
                "device_alias": "ganglion",
                "detail": detail,
                "metadata": {},
            },
            quality=0.0,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
