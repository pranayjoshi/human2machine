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


def stack_commands(python: str, *, mock: bool) -> list[list[str]]:
    """Process list shared with scripts/demo_mvp.py --spawn."""
    mock_flag = ["--mock"] if mock else []
    return [
        [python, "-m", "event_hub.main", *mock_flag],
        [python, "-m", "fusion_runtime.main", *mock_flag],
        [python, "-m", "safety_gateway.main", *mock_flag],
        [python, "-m", "robot_simulator.main", *mock_flag],
        [python, "-m", "session_recorder.main", *mock_flag],
        [python, "-m", "console_api.main", *mock_flag],
        [python, "-m", "ganglion_adapter.main", *mock_flag],
        [python, "-m", "audio_adapter.main", *mock_flag],
        [python, "-m", "vision_adapter.main", *mock_flag],
        ["pnpm", "--filter", "@intent/crown-adapter", "start", "--", *mock_flag],
        ["pnpm", "--filter", "@intent/developer-console", "dev"],
    ]


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


def shutdown(children: list[subprocess.Popen], *, linger_s: float = 0.5) -> None:
    for child in children:
        if child.poll() is None:
            child.send_signal(signal.SIGINT)
    time.sleep(linger_s)
    for child in children:
        if child.poll() is None:
            child.kill()


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

    if args.hardware:
        print("hardware mode will access Crown, Ganglion, microphone, and camera")

    children: list[subprocess.Popen] = []

    def _stop(*_args: object) -> None:
        shutdown(children)

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    children.extend(spawn(command) for command in stack_commands(sys.executable, mock=args.mock))
    print("stack launched; Ctrl+C to stop")
    try:
        while True:
            for child in children:
                code = child.poll()
                if code not in (None, 0):
                    print(f"child exited with {code}: {child.args}", file=sys.stderr)
                    shutdown(children)
                    return code
            time.sleep(0.5)
    except KeyboardInterrupt:
        shutdown(children)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
