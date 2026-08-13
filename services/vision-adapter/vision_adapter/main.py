from __future__ import annotations

import argparse
import signal
import time
from pathlib import Path

from intent_runtime.config import load_stacked_config

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


def main(argv: list[str] | None = None, sink: BoundedAdapterPush | ListSink | None = None) -> None:
    args = build_parser().parse_args(argv)
    mock = not args.hardware
    config = load_stacked_config(find_repo_root() / "configs")
    endpoint = args.endpoint or config.get("runtime", {}).get("ports", {}).get(
        "adapter_push", "tcp://127.0.0.1:5555"
    )
    vision_cfg = config.get("vision", {})
    if args.list_devices:
        print("mock-camera" if mock else "hardware camera listing is stubbed")
        return
    if not mock:
        print("hardware camera path is stubbed; use --mock")
        return

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
                }
            )

    publisher = sink or BoundedAdapterPush(endpoint)
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
    stop = False

    def _halt(_signum=None, _frame=None) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _halt)
    signal.signal(signal.SIGTERM, _halt)

    started = time.monotonic()
    last_heartbeat = 0.0
    period = 1.0 / max(runtime.publish_hz, 1.0)
    try:
        while not stop:
            now = time.monotonic()
            elapsed_ms = (now - started) * 1000.0
            if args.freeze and elapsed_ms >= args.freeze_after_ms and not runtime.frozen:
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
    finally:
        publisher.close()


if __name__ == "__main__":
    main()
