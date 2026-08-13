"""Command consumer, state publisher, and heartbeat loop."""

from __future__ import annotations

from typing import Any

import structlog
from intent_contracts.commands import ActionCommand
from intent_contracts.enums import (
    PRODUCER_VERSION,
    SCHEMA_VERSION,
    DeviceHealth,
    EventType,
    MachineState,
)
from intent_contracts.envelope import EventEnvelope, new_event_id, now_monotonic_ns
from intent_contracts.events import ActionOutcomePayload, MachineStatePayload
from intent_runtime.heartbeat import heartbeat_event
from intent_runtime.zmq_bus import AdapterPush, CommandPull
from pydantic import ValidationError

from robot_simulator.adapter import SimulatorMachineAdapter, SimulatorSettings

_INTENT_TYPES = {
    EventType.INTENT_DECISION,
    EventType.INTENT_CANDIDATE_SET,
    EventType.INTENT_CONFLICT,
    EventType.INTENT_TIMEOUT,
    "intent.decision",
    "intent.candidate_set",
    "intent.conflict",
    "intent.timeout",
}

_RESET = {"machine.reset", "reset", "RESET"}
_ESTOP = {"machine.estop", "estop", "EMERGENCY_STOP", "STOP", "machine.stop"}
_HOLD = {"machine.hold", "hold", "HOLD"}
_CANCEL = {"machine.cancel", "cancel", "CANCEL"}
_RESUME = {"machine.resume", "resume", "RESUME"}


class SimulatorService:
    def __init__(
        self,
        adapter: SimulatorMachineAdapter,
        settings: SimulatorSettings,
        *,
        push: AdapterPush | None = None,
        pull: CommandPull | None = None,
    ) -> None:
        self.adapter = adapter
        self.settings = settings
        self._push = push
        self._pull = pull
        self._owns_sockets = False
        self._running = False
        self._sequence = 0
        self._state_cursor = 0
        self._outcome_cursor = 0
        self._error_count = 0
        self._started_mono_ns = now_monotonic_ns()
        self._last_command_mono_ns: int | None = None
        self._last_heartbeat_mono_ns = 0
        self._last_progress_pub_ns = 0
        self._log = structlog.get_logger("robot-simulator")

    def handle_message(self, message: object) -> None:
        if not isinstance(message, dict):
            self._error_count += 1
            return
        event_type = message.get("event_type")
        if event_type in _INTENT_TYPES:
            self._log.info("ignored_raw_intent", event_type=event_type)
            return

        method = str(message.get("method") or message.get("control") or "")
        payload = message.get("payload") if isinstance(message.get("payload"), dict) else {}
        if event_type == "machine.reset" or method in _RESET:
            self.adapter.reset()
            return
        if event_type == "machine.estop" or method in _ESTOP:
            self.adapter.emergency_stop(_reason(message, payload, default="ESTOP"))
            return
        if method in _HOLD:
            self.adapter.hold(_reason(message, payload, default="HOLD"))
            return
        if method in _CANCEL:
            command_id = str(
                message.get("command_id")
                or payload.get("command_id")
                or self.adapter.active_command_id
                or ""
            )
            self.adapter.cancel(command_id)
            return
        if method in _RESUME:
            self.adapter.resume()
            return

        try:
            command = ActionCommand.model_validate(message)
        except ValidationError:
            self._error_count += 1
            self._log.warning("invalid_command_schema")
            return
        self.adapter.execute(command)

    def drain(self) -> list[EventEnvelope]:
        published: list[EventEnvelope] = []
        while self._state_cursor < len(self.adapter.emitted_states):
            payload = self.adapter.emitted_states[self._state_cursor]
            self._state_cursor += 1
            published.append(self._send(EventType.MACHINE_STATE, payload, modality="machine"))
        while self._outcome_cursor < len(self.adapter.emitted_outcomes):
            payload = self.adapter.emitted_outcomes[self._outcome_cursor]
            self._outcome_cursor += 1
            published.append(self._send(EventType.ACTION_OUTCOME, payload, modality="machine"))
        return published

    def run(self) -> None:
        self._owns_sockets = self._push is None or self._pull is None
        if self._push is None:
            self._push = AdapterPush(self.settings.event_endpoint)
        if self._pull is None:
            self._pull = CommandPull(self.settings.command_endpoint)
        self._running = True
        self._started_mono_ns = now_monotonic_ns()
        self._last_heartbeat_mono_ns = 0
        try:
            if not self.settings.faults.adapter_disconnect:
                self.adapter.connect()
            self.drain()
            self._publish_heartbeat()
            while self._running:
                raw = self._pull.recv_command(timeout_ms=20)
                if raw is not None:
                    self._last_command_mono_ns = now_monotonic_ns()
                    self.handle_message(raw)
                self.adapter.tick()
                self.drain()
                self._maybe_publish_progress()
                self._maybe_heartbeat()
        finally:
            self._running = False
            try:
                self.adapter.disconnect()
                self.drain()
            except Exception:
                self._log.exception("disconnect_failed")
            if self._owns_sockets:
                if self._pull is not None:
                    self._pull.close()
                if self._push is not None:
                    self._push.close()

    def stop(self) -> None:
        self._running = False

    def _maybe_publish_progress(self) -> None:
        if self.adapter.state is not MachineState.EXECUTING:
            return
        now = now_monotonic_ns()
        if now - self._last_progress_pub_ns < 100_000_000:
            return
        self._last_progress_pub_ns = now
        self._send(EventType.MACHINE_STATE, self.adapter.get_state(), modality="machine")

    def _maybe_heartbeat(self) -> None:
        now = now_monotonic_ns()
        interval_ns = int(self.settings.heartbeat_seconds * 1_000_000_000)
        if now - self._last_heartbeat_mono_ns < interval_ns:
            return
        self._publish_heartbeat()

    def _publish_heartbeat(self) -> None:
        now = now_monotonic_ns()
        self._last_heartbeat_mono_ns = now
        uptime = (now - self._started_mono_ns) / 1_000_000_000
        last_age = None
        if self._last_command_mono_ns is not None:
            last_age = (now - self._last_command_mono_ns) / 1_000_000
        status = self.adapter.get_state().model_dump().get("health", DeviceHealth.HEALTHY)
        event = heartbeat_event(
            self.settings.source,
            uptime_seconds=uptime,
            last_data_age_ms=last_age,
            error_count=self._error_count,
            sequence=self._next_sequence(),
            status=status,
        )
        if self._push is not None:
            self._push.send_event(event)

    def _send(
        self,
        event_type: EventType,
        payload: MachineStatePayload | ActionOutcomePayload,
        *,
        modality: str,
    ) -> EventEnvelope:
        body = payload.model_dump(mode="json")
        event = EventEnvelope(
            schema_version=SCHEMA_VERSION,
            event_id=new_event_id(),
            event_type=event_type,
            source=self.settings.source,
            modality=modality,
            session_id=None,
            trial_id=None,
            sequence=self._next_sequence(),
            source_time_ns=None,
            received_monotonic_ns=now_monotonic_ns(),
            quality=1.0,
            producer_version=PRODUCER_VERSION,
            payload=body,
        )
        if self._push is not None:
            self._push.send_event(event)
        return event

    def _next_sequence(self) -> int:
        sequence = self._sequence
        self._sequence += 1
        return sequence


def _reason(message: dict[str, Any], payload: dict[str, Any], *, default: str) -> str:
    return str(message.get("reason") or payload.get("reason") or default)


def wait_forever(service: SimulatorService) -> None:
    """Block until SIGINT/SIGTERM; used by main."""
    import signal

    def _stop(*_args: object) -> None:
        service.stop()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    service.run()
