"""Safety gateway transport. Policy evaluation stays in ``policy.py``."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

import structlog
from intent_contracts.envelope import new_event_id, now_monotonic_ns
from intent_runtime.config import load_stacked_config
from intent_runtime.heartbeat import heartbeat_event
from intent_runtime.logging import configure_logging
from intent_runtime.zmq_bus import AdapterPush, CommandPush, NormalizedSubscriber

from safety_gateway.policy import (
    SOURCE,
    SafetyState,
    apply_event,
    make_safety_event,
    safety_config_from_mapping,
)

SUB_TOPICS = [
    b"intent.decision",
    b"machine.state",
    b"vision.objects",
    b"modality.feature",
    b"session.started",
    b"session.stopped",
    b"session.failed",
    b"trial.started",
    b"trial.completed",
    b"trial.aborted",
    b"action.outcome",
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Deterministic safety gateway")
    parser.add_argument(
        "--mock",
        action="store_true",
        required=True,
        help="Required. Keep the gateway in simulator-only mock mode; never arm hardware.",
    )
    parser.add_argument(
        "--config-dir",
        type=Path,
        default=Path("configs"),
        help="Directory containing local.yaml, modalities.yaml, and safety.yaml",
    )
    return parser.parse_args(argv)


def _ports(config: dict[str, Any]) -> dict[str, str]:
    runtime = config.get("runtime") or {}
    ports = runtime.get("ports") or {}
    return {
        "hub_push": str(ports.get("adapter_push", "tcp://127.0.0.1:5555")),
        "normalized_sub": str(ports.get("normalized_pub", "tcp://127.0.0.1:5556")),
        "command_push": str(ports.get("command_push", "tcp://127.0.0.1:5557")),
    }


def _initial_state(config: dict[str, Any]) -> SafetyState:
    runtime = config.get("runtime") or {}
    devices = config.get("devices") or {}
    physical = bool(
        runtime.get("machine_mode") == "physical_robot"
        or devices.get("so_arm")
        or devices.get("physical_robot")
        or devices.get("arm")
    )
    # --mock is required: ActionCommand destination is always the simulator.
    return SafetyState(
        physical_adapter_configured=physical,
        physical_armed=False,
        command_destination="simulator",
    )


def _publish_result(
    result,
    *,
    config,
    state: SafetyState,
    hub: AdapterPush,
    commands: CommandPush,
    sequence: int,
    log,
) -> int:
    event = make_safety_event(
        result,
        config,
        state,
        sequence=sequence,
        received_monotonic_ns=now_monotonic_ns(),
        event_id=new_event_id(),
    )
    hub.send_event(event)
    log.info(
        "safety.decision",
        decision_id=result.decision_id,
        verdict=str(result.verdict),
        reason_codes=list(result.reason_codes),
        command_id=result.command.command_id if result.command else None,
        confirmation_id=result.confirmation_id,
    )
    if result.command is not None:
        commands.send_command(result.command.model_dump(mode="json"))
    return sequence + 1


def run(args: argparse.Namespace) -> None:
    configure_logging(SOURCE)
    log = structlog.get_logger(SOURCE)
    stacked = load_stacked_config(args.config_dir)
    config = safety_config_from_mapping(stacked)
    ports = _ports(stacked)
    runtime = stacked.get("runtime") or {}
    heartbeat_s = float(runtime.get("heartbeat_seconds", 2))

    # Mock mode is mandatory: physical robot commands stay impossible.
    if not args.mock:
        raise SystemExit("--mock is required")
    if config.mode != "physical_robot":
        log.info("simulator_only_mode", policy_version=config.policy_version, mode=config.mode)

    state = _initial_state(stacked)
    hub = AdapterPush(ports["hub_push"])
    commands = CommandPush(ports["command_push"])
    sub = NormalizedSubscriber(ports["normalized_sub"], topics=SUB_TOPICS)
    started = time.monotonic()
    last_beat = 0.0
    sequence = 0
    beat_sequence = 0
    error_count = 0
    last_data_age_ms = None

    log.info("safety_gateway_started", mock=True, subscribe=ports["normalized_sub"])
    try:
        while True:
            now = time.monotonic()
            if now - last_beat >= heartbeat_s:
                hub.send_event(
                    heartbeat_event(
                        SOURCE,
                        uptime_seconds=now - started,
                        last_data_age_ms=last_data_age_ms,
                        error_count=error_count,
                        sequence=beat_sequence,
                        session_id=state.session_id,
                    )
                )
                beat_sequence += 1
                last_beat = now

            raw = sub.recv_event(timeout_ms=100)
            if raw is None:
                # Poll confirmation timeout even without inbound events.
                now_ns = now_monotonic_ns()
                state, results = apply_event(state, {"event_type": "poll"}, config, now_ns=now_ns)
                for result in results:
                    sequence = _publish_result(
                        result,
                        config=config,
                        state=state,
                        hub=hub,
                        commands=commands,
                        sequence=sequence,
                        log=log,
                    )
                continue

            last_data_age_ms = 0.0
            now_ns = int(raw.get("normalized_time_ns") or now_monotonic_ns())
            try:
                state, results = apply_event(state, raw, config, now_ns=now_ns)
            except Exception:
                error_count += 1
                log.exception("policy_apply_failed")
                continue
            for result in results:
                sequence = _publish_result(
                    result,
                    config=config,
                    state=state,
                    hub=hub,
                    commands=commands,
                    sequence=sequence,
                    log=log,
                )
    except KeyboardInterrupt:
        log.info("safety_gateway_stopping")
    finally:
        sub.close()
        hub.close()
        commands.close()


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    run(args)


if __name__ == "__main__":
    main(sys.argv[1:])
