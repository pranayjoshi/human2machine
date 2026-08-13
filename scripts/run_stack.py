#!/usr/bin/env python3
"""Launch the local mock or hardware stack."""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def spawn(command: list[str], extra_env: dict[str, str] | None = None) -> subprocess.Popen:
    env = os.environ.copy()
    pythonpath = [
        str(ROOT / "packages/contracts-python/src"),
        str(ROOT / "packages/runtime-python/src"),
        str(ROOT / "services/event-hub"),
        str(ROOT / "services/fusion-runtime"),
        str(ROOT / "services/safety-gateway"),
        str(ROOT / "services/robot-simulator"),
        str(ROOT / "services/session-recorder"),
        str(ROOT / "services/console-api"),
        str(ROOT / "services/ganglion-adapter"),
        str(ROOT / "services/audio-adapter"),
        str(ROOT / "services/vision-adapter"),
    ]
    env["PYTHONPATH"] = os.pathsep.join(pythonpath)
    if extra_env:
        env.update(extra_env)
    return subprocess.Popen(command, cwd=ROOT, env=env)


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--mock", action="store_true")
    mode.add_argument("--hardware", action="store_true")
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args()

    if args.hardware and not args.confirm:
        print("refusing hardware start without --confirm", file=sys.stderr)
        return 2

    mock_flag = ["--mock"] if args.mock else []
    if args.hardware:
        print("hardware mode will access Crown, Ganglion, microphone, and camera")

    children: list[subprocess.Popen] = []

    def shutdown(*_args: object) -> None:
        for child in children:
            if child.poll() is None:
                child.send_signal(signal.SIGINT)
        time.sleep(0.5)
        for child in children:
            if child.poll() is None:
                child.kill()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    python = sys.executable
    children.extend(
        [
            spawn([python, "-m", "event_hub.main", *mock_flag]),
            spawn([python, "-m", "fusion_runtime.main", *mock_flag]),
            spawn([python, "-m", "safety_gateway.main", *mock_flag]),
            spawn([python, "-m", "robot_simulator.main", *mock_flag]),
            spawn([python, "-m", "session_recorder.main", *mock_flag]),
            spawn([python, "-m", "console_api.main", *mock_flag]),
            spawn([python, "-m", "ganglion_adapter.main", *mock_flag]),
            spawn([python, "-m", "audio_adapter.main", *mock_flag]),
            spawn([python, "-m", "vision_adapter.main", *mock_flag]),
            spawn(["pnpm", "--filter", "@intent/crown-adapter", "start", "--", *mock_flag]),
            spawn(["pnpm", "--filter", "@intent/developer-console", "dev"]),
        ]
    )
    print("stack launched; Ctrl+C to stop")
    try:
        while True:
            for child in children:
                code = child.poll()
                if code not in (None, 0):
                    print(f"child exited with {code}: {child.args}", file=sys.stderr)
                    shutdown()
                    return code
            time.sleep(0.5)
    except KeyboardInterrupt:
        shutdown()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
