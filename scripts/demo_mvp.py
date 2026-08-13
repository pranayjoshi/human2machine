#!/usr/bin/env python3
"""Live mock-stack smoke for Milestone 0.

Default is --attach (use `just run-mocks` in another terminal). --spawn launches
the same process list as scripts/run_stack.py.
"""

# ruff: noqa: E402
from __future__ import annotations

import argparse
import json
import socket
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = Path(__file__).resolve().parent
for extra in (
    ROOT / "packages/contracts-python/src",
    ROOT / "packages/runtime-python/src",
    SCRIPTS,
):
    text = str(extra)
    if text not in sys.path:
        sys.path.insert(0, text)

import zmq
from intent_contracts.control import ControlRequest, ControlResponse
from intent_contracts.enums import ControlMethod
from intent_contracts.envelope import new_event_id, now_monotonic_ns
from intent_runtime.zmq_bus import AdapterPush, NormalizedSubscriber
from run_stack import shutdown, spawn, stack_commands

FIXTURES = ROOT / "data/fixtures/events"
CONTROL_ENDPOINT = "tcp://127.0.0.1:5558"
PUSH_ENDPOINT = "tcp://127.0.0.1:5555"
SUB_ENDPOINT = "tcp://127.0.0.1:5556"
READY_TIMEOUT_S = 20.0
RESULT_TIMEOUT_S = 10.0
INSTRUCTION = "Give me that object"
SCENARIOS = ("success", "conflict", "cancel")
APPROVE_GRACE_S = 1.8


def _load_fixture(name: str) -> dict[str, Any]:
    data = json.loads((FIXTURES / name).read_text())
    data.pop("normalized_time_ns", None)
    return data


def _stamp(
    event: dict[str, Any],
    *,
    now_ns: int,
    sequence: int,
    session_id: str | None,
    trial_id: str | None,
    event_id: str | None = None,
) -> dict[str, Any]:
    stamped = dict(event)
    stamped.pop("normalized_time_ns", None)
    stamped["event_id"] = event_id or new_event_id()
    stamped["session_id"] = session_id
    stamped["trial_id"] = trial_id
    stamped["sequence"] = sequence
    stamped["source_time_ns"] = now_ns
    stamped["received_monotonic_ns"] = now_ns
    return stamped


def build_scenario_events(
    scenario: str,
    *,
    session_id: str | None = None,
    trial_id: str | None = None,
    now_ns: int | None = None,
) -> list[dict[str, Any]]:
    """Unnormalized adapter envelopes for a demo trial. Omits normalized_time_ns."""
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario: {scenario}")
    clock = now_ns if now_ns is not None else now_monotonic_ns()
    vision = _load_fixture("vision_objects.json")
    audio = _load_fixture("audio_intent.json")
    emg = _load_fixture("emg_confirm.json")
    machine = {
        "schema_version": vision["schema_version"],
        "event_id": new_event_id(),
        "event_type": "machine.state",
        "source": "robot-simulator",
        "modality": "machine",
        "session_id": session_id,
        "trial_id": trial_id,
        "sequence": 0,
        "source_time_ns": clock,
        "received_monotonic_ns": clock,
        "quality": 1.0,
        "producer_version": vision["producer_version"],
        "payload": {
            "state": "READY",
            "previous_state": None,
            "active_command_id": None,
            "held_object_id": None,
            "target_object_id": None,
            "progress": 0.0,
            "objects": list(vision["payload"]["objects"]),
            "fault_reason": None,
        },
    }

    if scenario == "success":
        audio["payload"]["transcript"] = "give me that one"
        audio["payload"]["action"] = "REQUEST_HANDOFF"
        audio["payload"]["target_reference"] = "DEICTIC"
        audio["payload"]["target_object_id"] = None
        vision["payload"]["pointing_candidates"] = [
            {"object_id": "object_blue_1", "confidence": 0.82}
        ]
        emg["payload"]["label"] = "confirm"
        emg["payload"]["confidence"] = 0.91
        emg["payload"]["candidate_scores"] = {"rest": 0.04, "confirm": 0.91, "cancel": 0.05}
    elif scenario == "conflict":
        audio["payload"]["transcript"] = "give me the blue block"
        audio["payload"]["action"] = "REQUEST_HANDOFF"
        audio["payload"]["target_reference"] = "NAMED"
        audio["payload"]["target_object_id"] = "object_blue_1"
        vision["payload"]["pointing_candidates"] = [
            {"object_id": "object_red_1", "confidence": 0.88}
        ]
        emg["payload"]["label"] = "confirm"
        emg["payload"]["confidence"] = 0.91
        emg["payload"]["candidate_scores"] = {"rest": 0.04, "confirm": 0.91, "cancel": 0.05}
    else:
        audio["payload"]["transcript"] = "cancel"
        audio["payload"]["action"] = "CANCEL"
        audio["payload"]["target_reference"] = "NONE"
        audio["payload"]["target_object_id"] = None
        audio["payload"]["confidence"] = 0.99
        audio["quality"] = 0.99
        vision["payload"]["pointing_candidates"] = []
        emg["payload"]["label"] = "cancel"
        emg["payload"]["confidence"] = 0.99
        emg["payload"]["candidate_scores"] = {"rest": 0.04, "confirm": 0.05, "cancel": 0.99}

    audio["payload"]["utterance_start_ns"] = max(0, clock - 35_000_000)
    audio["payload"]["utterance_end_ns"] = clock + 10_000_000
    emg["payload"]["window_start_ns"] = max(0, clock + 25_000_000)
    emg["payload"]["window_end_ns"] = clock + 30_000_000

    events = [
        _stamp(machine, now_ns=clock, sequence=1, session_id=session_id, trial_id=trial_id),
        _stamp(
            vision,
            now_ns=clock + 10_000_000,
            sequence=2,
            session_id=session_id,
            trial_id=trial_id,
        ),
        _stamp(
            audio,
            now_ns=clock + 20_000_000,
            sequence=3,
            session_id=session_id,
            trial_id=trial_id,
        ),
        _stamp(
            emg,
            now_ns=clock + 30_000_000,
            sequence=4,
            session_id=session_id,
            trial_id=trial_id,
        ),
    ]
    if scenario == "cancel":
        events = [events[0], events[2]]
    return events


def demo_passed(verdict: str | None, outcome: str | None, scenario: str) -> bool:
    verdict_u = (verdict or "").upper()
    outcome_u = (outcome or "").upper()
    if verdict_u == "ASK_CONFIRMATION":
        return True
    if verdict_u == "APPROVE" and outcome_u == "COMPLETED":
        return True
    if scenario == "cancel" and verdict_u == "APPROVE":
        return True
    if scenario == "cancel" and outcome_u == "CANCELLED":
        return True
    return False


def _port_from_endpoint(endpoint: str) -> int:
    hostport = endpoint.rsplit("/", 1)[-1]
    return int(hostport.rsplit(":", 1)[-1])


def control_plane_bound(endpoint: str = CONTROL_ENDPOINT, timeout_s: float = 0.2) -> bool:
    port = _port_from_endpoint(endpoint)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout_s)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def wait_for_control_plane(endpoint: str, timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if control_plane_bound(endpoint) and _control_roundtrip(endpoint):
            return True
        time.sleep(0.15)
    return False


def _control_roundtrip(endpoint: str, timeout_ms: int = 400) -> bool:
    ctx = zmq.Context.instance()
    sock = ctx.socket(zmq.REQ)
    sock.setsockopt(zmq.LINGER, 0)
    sock.setsockopt(zmq.RCVTIMEO, timeout_ms)
    sock.setsockopt(zmq.SNDTIMEO, timeout_ms)
    sock.connect(endpoint)
    try:
        probe = ControlRequest(method="demo.ping", request_id=new_event_id())
        sock.send_json(probe.model_dump(mode="json"))
        raw = sock.recv_json()
        return isinstance(raw, dict)
    except zmq.ZMQError:
        return False
    finally:
        sock.close(linger=0)


class ControlClient:
    def __init__(self, endpoint: str = CONTROL_ENDPOINT, timeout_ms: int = 2000) -> None:
        self.endpoint = endpoint
        ctx = zmq.Context.instance()
        self._sock = ctx.socket(zmq.REQ)
        self._sock.setsockopt(zmq.LINGER, 0)
        self._sock.setsockopt(zmq.RCVTIMEO, timeout_ms)
        self._sock.setsockopt(zmq.SNDTIMEO, timeout_ms)
        self._sock.connect(endpoint)

    def request(
        self,
        method: ControlMethod | str,
        *,
        session_id: str | None = None,
        trial_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> ControlResponse:
        req = ControlRequest(
            method=method,
            request_id=new_event_id(),
            session_id=session_id,
            trial_id=trial_id,
            payload=payload or {},
        )
        self._sock.send_json(req.model_dump(mode="json"))
        raw = self._sock.recv_json()
        if not isinstance(raw, dict):
            raise RuntimeError("control response was not an object")
        return ControlResponse.model_validate(raw)

    def close(self) -> None:
        self._sock.close(linger=0)


def _prefer_safety(current: dict[str, Any] | None, incoming: dict[str, Any]) -> dict[str, Any]:
    if current is None:
        return incoming
    rank = {"APPROVE": 3, "ASK_CONFIRMATION": 2, "HOLD": 1, "REJECT": 0, "EMERGENCY_STOP": 0}
    cur = rank.get(str((current.get("payload") or {}).get("verdict") or "").upper(), -1)
    nxt = rank.get(str((incoming.get("payload") or {}).get("verdict") or "").upper(), -1)
    return incoming if nxt >= cur else current


def collect_loop(
    subscriber: NormalizedSubscriber,
    *,
    timeout_s: float,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None]:
    deadline = time.monotonic() + timeout_s
    intent: dict[str, Any] | None = None
    safety: dict[str, Any] | None = None
    outcome: dict[str, Any] | None = None
    approve_at: float | None = None
    while time.monotonic() < deadline:
        remaining_ms = max(1, int((deadline - time.monotonic()) * 1000))
        event = subscriber.recv_event(timeout_ms=min(200, remaining_ms))
        if event is not None:
            etype = str(event.get("event_type") or "")
            if etype == "intent.decision":
                intent = event
            elif etype == "safety.decision":
                safety = _prefer_safety(safety, event)
            elif etype == "action.outcome":
                outcome = event
        verdict = str(((safety or {}).get("payload") or {}).get("verdict") or "").upper()
        if verdict == "APPROVE" and approve_at is None:
            approve_at = time.monotonic()
        if _loop_done(safety, outcome, approve_at):
            break
    return intent, safety, outcome


def _loop_done(
    safety: dict[str, Any] | None,
    outcome: dict[str, Any] | None,
    approve_at: float | None,
    *,
    grace_s: float = APPROVE_GRACE_S,
) -> bool:
    if safety is None:
        return False
    verdict = str((safety.get("payload") or {}).get("verdict") or "").upper()
    if verdict == "ASK_CONFIRMATION":
        return True
    if verdict == "APPROVE":
        if outcome is not None:
            return True
        return approve_at is not None and (time.monotonic() - approve_at) >= grace_s
    return False


def print_report(
    *,
    scenario: str,
    session_id: str | None,
    trial_id: str | None,
    intent: dict[str, Any] | None,
    safety: dict[str, Any] | None,
    outcome: dict[str, Any] | None,
    passed: bool,
) -> None:
    intent_payload = (intent or {}).get("payload") or {}
    safety_payload = (safety or {}).get("payload") or {}
    outcome_payload = (outcome or {}).get("payload") or {}
    action = intent_payload.get("action")
    target = intent_payload.get("target_object_id")
    decision = " ".join(part for part in (action, target) if part) or None
    verdict = safety_payload.get("verdict")
    command_id = safety_payload.get("command_id") or outcome_payload.get("command_id")
    result_outcome = outcome_payload.get("outcome")
    print("=== Milestone 0 demo ===")
    print(f"scenario:    {scenario}")
    print(f"session_id:  {session_id}")
    print(f"trial_id:    {trial_id}")
    print(f"decision:    {decision}")
    print(f"decision_id: {intent_payload.get('decision_id') or safety_payload.get('decision_id')}")
    print(f"verdict:     {verdict}")
    print(f"command_id:  {command_id}")
    print(f"outcome:     {result_outcome}")
    print(f"result:      {'PASS' if passed else 'FAIL'}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prove the live mock stack completes Milestone 0")
    parser.add_argument(
        "--attach",
        action="store_true",
        help="Use an already-running stack (default). Implies no spawn.",
    )
    parser.add_argument(
        "--spawn",
        action="store_true",
        help="Launch the mock stack using scripts/run_stack.py helpers",
    )
    parser.add_argument("--scenario", choices=SCENARIOS, default="success")
    parser.add_argument("--control", default=CONTROL_ENDPOINT)
    parser.add_argument("--push", default=PUSH_ENDPOINT)
    parser.add_argument("--sub", default=SUB_ENDPOINT)
    parser.add_argument("--ready-timeout", type=float, default=READY_TIMEOUT_S)
    parser.add_argument("--result-timeout", type=float, default=RESULT_TIMEOUT_S)
    return parser.parse_args(argv)


def run_demo(args: argparse.Namespace) -> int:
    attach = args.attach or not args.spawn
    children: list[Any] = []
    control: ControlClient | None = None
    push: AdapterPush | None = None
    sub: NormalizedSubscriber | None = None
    session_id: str | None = None

    try:
        if not attach:
            print("spawning mock stack...")
            children.extend(spawn(command) for command in stack_commands(sys.executable, mock=True))

        print(f"waiting for control plane {args.control} (timeout {args.ready_timeout:.0f}s)")
        if not wait_for_control_plane(args.control, args.ready_timeout):
            print(
                "control plane did not respond; start the stack with `just run-mocks`",
                file=sys.stderr,
            )
            return 1

        sub = NormalizedSubscriber(
            args.sub,
            topics=[b"intent.decision", b"safety.decision", b"action.outcome"],
        )
        time.sleep(0.25)
        push = AdapterPush(args.push)
        control = ControlClient(args.control)

        started = control.request(
            ControlMethod.SESSION_START,
            payload={"user_id": "demo", "consent": True},
        )
        if not started.ok or not started.session_id:
            print(f"session.start failed: {started.error}", file=sys.stderr)
            return 1
        session_id = started.session_id

        trial = control.request(
            ControlMethod.TRIAL_START,
            session_id=session_id,
            payload={"instruction": INSTRUCTION},
        )
        if not trial.ok:
            print(f"trial.start failed: {trial.error}", file=sys.stderr)
            return 1
        trial_id = trial.trial_id

        events = build_scenario_events(
            args.scenario,
            session_id=session_id,
            trial_id=trial_id,
        )
        for event in events:
            push.send_event(event)

        intent, safety, outcome = collect_loop(sub, timeout_s=args.result_timeout)
        verdict = str(((safety or {}).get("payload") or {}).get("verdict") or "") or None
        result_outcome = str(((outcome or {}).get("payload") or {}).get("outcome") or "") or None
        passed = demo_passed(verdict, result_outcome, args.scenario)
        print_report(
            scenario=args.scenario,
            session_id=session_id,
            trial_id=trial_id,
            intent=intent,
            safety=safety,
            outcome=outcome,
            passed=passed,
        )

        try:
            control.request(ControlMethod.SESSION_STOP, session_id=session_id)
        except Exception as exc:
            print(f"session.stop failed: {exc}", file=sys.stderr)
            return 1
        session_id = None
        return 0 if passed else 1
    except KeyboardInterrupt:
        print("demo interrupted", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"demo crashed: {exc}", file=sys.stderr)
        return 1
    finally:
        if control is not None and session_id is not None:
            try:
                control.request(ControlMethod.SESSION_STOP, session_id=session_id)
            except Exception:
                pass
            session_id = None
        if push is not None:
            push.close()
        if sub is not None:
            sub.close()
        if control is not None:
            control.close()
        if children:
            shutdown(children)


def main(argv: list[str] | None = None) -> int:
    return run_demo(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
