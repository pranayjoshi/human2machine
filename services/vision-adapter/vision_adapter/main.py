from __future__ import annotations

import argparse
import signal
import time
from pathlib import Path

from intent_runtime.config import load_stacked_config

from vision_adapter.camera import LatestFrameCamera, VisionHardwareRuntime, list_cameras
from vision_adapter.color_detector import DEFAULT_CATALOG
from vision_adapter.mock import VisionMockRuntime
from vision_adapter.publisher import BoundedAdapterPush, ListSink


def find_repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in [here, *here.parents]:
        if (parent / "configs" / "local.yaml").exists():
            return parent
    return Path.cwd()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Tabletop vision adapter")
    parser.add_argument("--mock", action="store_true", default=True)
    parser.add_argument("--hardware", action="store_true")
    parser.add_argument("--scenario", default="all_visible")
    parser.add_argument("--freeze", action="store_true")
    parser.add_argument("--freeze-after-ms", type=float, default=1000.0)
    parser.add_argument("--endpoint", default=None)
    parser.add_argument("--duration-seconds", type=float, default=0.0)
    parser.add_argument("--list-devices", action="store_true")
    return parser


def main(argv: list[str] | None = None, sink: BoundedAdapterPush | ListSink | None = None) -> int:
    args = build_parser().parse_args(argv)
    mock = not args.hardware
    config = load_stacked_config(find_repo_root() / "configs")
    endpoint = args.endpoint or config.get("runtime", {}).get("ports", {}).get(
        "adapter_push", "tcp://127.0.0.1:5555"
    )
    vision_cfg = config.get("vision", {})
    devices_cfg = config.get("devices", {}).get("vision", {})
    if args.list_devices:
        if mock:
            print("mock-camera")
            return 0
        found = list_cameras()
        if not found:
            print("no OpenCV cameras opened on indices 0-4")
            return 0
        for index in found:
            print(index)
        return 0

    objects = vision_cfg.get("objects") or None
    catalog = None
    if objects:
        catalog = []
        layout = {
            "object_blue_1": ([0.25, 0.40], [100.0, 80.0, 200.0, 180.0]),
            "object_red_1": ([0.55, 0.40], [300.0, 80.0, 400.0, 180.0]),
            "object_green_1": ([0.25, 0.70], [100.0, 250.0, 200.0, 350.0]),
            "object_yellow_1": ([0.55, 0.70], [300.0, 250.0, 400.0, 350.0]),
        }
        for item in objects:
            pos, bbox = layout.get(item["object_id"], ([0.5, 0.5], [0.0, 0.0, 80.0, 80.0]))
            catalog.append(
                {
                    "object_id": item["object_id"],
                    "class_name": item.get("class_name", item["object_id"]),
                    "table_position_xy": pos,
                    "bbox_xyxy": bbox,
                    "color": item.get("class_name", "").replace("_block", ""),
                }
            )

    publisher = sink or BoundedAdapterPush(endpoint)
    stop = False

    def _halt(_signum=None, _frame=None) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _halt)
    signal.signal(signal.SIGTERM, _halt)

    camera: LatestFrameCamera | None = None
    try:
        if mock:
            runtime_kwargs: dict = {
                "scenario": args.scenario,
                "pointing_confidence_min": float(vision_cfg.get("pointing_confidence_min", 0.55)),
                "publish_hz": float(vision_cfg.get("publish_hz", 12)),
                "freeze": False,
                "freeze_after_ms": args.freeze_after_ms,
            }
            if catalog:
                runtime_kwargs["objects"] = catalog
            runtime = VisionMockRuntime(**runtime_kwargs)
        else:
            camera = LatestFrameCamera(
                camera_index=int(devices_cfg.get("camera_index", 0)),
                width=int(devices_cfg.get("width", 1280)),
                height=int(devices_cfg.get("height", 720)),
                fps=int(devices_cfg.get("fps", 30)),
            )
            try:
                camera.start()
            except Exception as exc:
                publisher.send_event(make_offline(f"failed to open camera: {exc}"))
                return 1
            runtime = VisionHardwareRuntime(
                camera,
                catalog=catalog or [dict(row) for row in DEFAULT_CATALOG],
                pointing_confidence_min=float(vision_cfg.get("pointing_confidence_min", 0.55)),
                publish_hz=float(vision_cfg.get("publish_hz", 12)),
            )

        started = time.monotonic()
        last_heartbeat = 0.0
        period = 1.0 / max(float(vision_cfg.get("publish_hz", 12)), 1.0)
        while not stop:
            now = time.monotonic()
            elapsed_ms = (now - started) * 1000.0
            if mock and args.freeze and elapsed_ms >= args.freeze_after_ms:
                assert isinstance(runtime, VisionMockRuntime)
                if not runtime.frozen:
                    runtime.enable_freeze()
            for event in runtime.render_frame():
                publisher.send_event(event)
            if now - last_heartbeat >= 2.0:
                publisher.send_event(runtime.heartbeat(now - started, publisher.dropped_count))
                last_heartbeat = now
            if args.duration_seconds > 0 and (now - started) >= args.duration_seconds:
                break
            time.sleep(period)
        publisher.send_event(runtime.shutdown())
        return 0
    finally:
        if camera is not None:
            camera.stop()
        publisher.close()


def make_offline(detail: str):
    from vision_adapter.mock import make_event

    return make_event(
        event_type="device.status",
        sequence=0,
        payload={
            "status": "offline",
            "device_alias": "vision-camera",
            "detail": detail,
            "metadata": {"detector": "hsv_color"},
        },
    )


if __name__ == "__main__":
    raise SystemExit(main())
