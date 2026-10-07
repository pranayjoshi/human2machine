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

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env.local", override=False)


def stack_commands(python: str, *, mock: bool) -> list[list[str]]:
    """Process list shared with scripts/demo_mvp.py --spawn.

    Hardware mode opens Crown, Ganglion, mic, and camera. Fusion, safety, and
    the robot simulator stay on ``--mock``: the physical arm is out of scope.
    """
    adapter_flag = ["--mock"] if mock else ["--hardware"]
    mock_only = ["--mock"]
    optional_mock = mock_only if mock else []
    return [
        [python, "-m", "event_hub.main", *optional_mock],
        [python, "-m", "fusion_runtime.main", *mock_only],
        [python, "-m", "safety_gateway.main", *mock_only],
        [python, "-m", "robot_simulator.main", *mock_only],
        [python, "-m", "session_recorder.main", *optional_mock],
        [python, "-m", "console_api.main", *optional_mock],
        [
            python,
            "-m",
            "ganglion_adapter.main",
            *adapter_flag,
            *(["--startup-attempts", "3"] if not mock else []),
            *(["--idle"] if mock else []),
        ],
        [python, "-m", "audio_adapter.main", *adapter_flag, *(["--idle"] if mock else [])],
        [python, "-m", "vision_adapter.main", *adapter_flag],
        [python, "-m", "crown_adapter.main", *adapter_flag],
        ["pnpm", "--filter", "@intent/developer-console", "dev"],
    ]


def is_optional_stack_child(command: list[str] | tuple[str, ...], *, mock: bool) -> bool:
    """Shadow-only biosignals must not tear down the hardware stack."""
    if mock:
        return False
    blob = " ".join(str(part) for part in command)
    return "crown_adapter.main" in blob or "ganglion_adapter.main" in blob


def _process_name(command: list[str]) -> str:
    if "-m" in command:
        index = command.index("-m")
        if index + 1 < len(command):
            return command[index + 1].removesuffix(".main").replace("_", "-")
    if "@intent/developer-console" in command:
        return "developer-console"
    return Path(command[0]).stem


def spawn(
    command: list[str],
    extra_env: dict[str, str] | None = None,
    *,
    log_dir: Path | None = None,
) -> subprocess.Popen:
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
        str(ROOT / "services/crown-adapter"),
        str(ROOT / "services/audio-adapter"),
        str(ROOT / "services/vision-adapter"),
    ]
    env["PYTHONPATH"] = os.pathsep.join(pythonpath)
    env.setdefault("H2M_LOG_FORMAT", "json")
    if extra_env:
        env.update(extra_env)
    target_dir = log_dir or ROOT / "data" / "runtime" / "logs"
    target_dir.mkdir(parents=True, exist_ok=True)
    log_path = target_dir / f"{_process_name(command)}.log"
    output = log_path.open("w", encoding="utf-8")
    try:
        return subprocess.Popen(
            command,
            cwd=ROOT,
            env=env,
            stdout=output,
            stderr=subprocess.STDOUT,
        )
    finally:
        output.close()


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

    log_dir = ROOT / "data" / "runtime" / "logs"
    children.extend(
        spawn(command, log_dir=log_dir)
        for command in stack_commands(sys.executable, mock=args.mock)
    )
    print(f"stack ready · logs: {log_dir} · Ctrl+C to stop")
    ignored: set[int] = set()
    try:
        while True:
            for child in children:
                if id(child) in ignored:
                    continue
                code = child.poll()
                if code not in (None, 0):
                    args_list = list(child.args) if isinstance(child.args, (list, tuple)) else []
                    if is_optional_stack_child(args_list, mock=args.mock):
                        print(
                            f"optional child exited with {code}: {child.args} "
                            "(shadow-only biosignal adapter; the rest of the stack continues)",
                            file=sys.stderr,
                        )
                        ignored.add(id(child))
                        continue
                    print(f"child exited with {code}: {child.args}", file=sys.stderr)
                    shutdown(children)
                    return code
            time.sleep(0.5)
    except KeyboardInterrupt:
        shutdown(children)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
