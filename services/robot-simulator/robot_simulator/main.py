"""Headless robot simulator entrypoint: python -m robot_simulator.main --mock"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from intent_runtime.config import load_stacked_config
from intent_runtime.logging import configure_logging

from robot_simulator.adapter import (
    FaultInjection,
    SimulatorMachineAdapter,
    SimulatorSettings,
    WallClock,
)
from robot_simulator.service import SimulatorService, wait_forever

_FAULT_CHOICES = ("slow", "unreachable", "missing", "grasp", "timeout", "disconnect")


def _repo_configs() -> Path:
    here = Path(__file__).resolve()
    return here.parents[3] / "configs"


def _parse_faults(names: list[str]) -> FaultInjection:
    flags = set(names)
    return FaultInjection(
        slow_action_multiplier=3.0 if "slow" in flags else 1.0,
        unreachable_object_ids=(
            frozenset({"object_blue_1"}) if "unreachable" in flags else frozenset()
        ),
        missing_object_ids=frozenset({"object_blue_1"}) if "missing" in flags else frozenset(),
        grasp_failure_probability=1.0 if "grasp" in flags else None,
        command_timeout_ms=80.0 if "timeout" in flags else None,
        adapter_disconnect="disconnect" in flags,
        force_grasp_failure=True if "grasp" in flags else None,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="robot_simulator")
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Run the headless task-state simulator (required; physical robots are out of scope)",
    )
    parser.add_argument("--config-dir", type=Path, default=None)
    parser.add_argument(
        "--fault",
        action="append",
        default=[],
        choices=_FAULT_CHOICES,
        help="Inject a simulator fault (repeatable). Also available via FaultInjection in tests.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.mock:
        print(
            "robot simulator requires --mock; physical adapters are out of scope",
            file=sys.stderr,
        )
        return 2

    configure_logging("robot-simulator")
    config_dir = args.config_dir
    if config_dir is None:
        cwd = Path("configs")
        config_dir = cwd if cwd.exists() else _repo_configs()
    config = load_stacked_config(config_dir)
    settings = SimulatorSettings.from_stacked_config(config, faults=_parse_faults(args.fault))
    adapter = SimulatorMachineAdapter(settings, clock=WallClock())
    service = SimulatorService(adapter, settings)
    wait_forever(service)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
