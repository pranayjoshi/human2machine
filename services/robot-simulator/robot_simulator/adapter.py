"""Hardware-agnostic machine interface and deterministic task-state simulator."""

from __future__ import annotations

import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from intent_contracts.commands import ActionCommand
from intent_contracts.enums import Action, DeviceHealth, MachineState, OutcomeKind
from intent_contracts.events import ActionOutcomePayload, MachineStatePayload, VisionObject

HANDOFF_XY = (0.50, 0.15)
HOME_XY = (0.50, 0.85)
DEFAULT_LAYOUT = (
    (0.20, 0.55),
    (0.40, 0.55),
    (0.60, 0.55),
    (0.80, 0.55),
)

ALLOWED_TRANSITIONS: dict[MachineState, frozenset[MachineState]] = {
    MachineState.DISCONNECTED: frozenset({MachineState.IDLE, MachineState.ESTOPPED}),
    MachineState.IDLE: frozenset(
        {
            MachineState.READY,
            MachineState.DISCONNECTED,
            MachineState.FAULT,
            MachineState.ESTOPPED,
        }
    ),
    MachineState.READY: frozenset(
        {
            MachineState.EXECUTING,
            MachineState.FAULT,
            MachineState.ESTOPPED,
            MachineState.IDLE,
            MachineState.DISCONNECTED,
        }
    ),
    MachineState.EXECUTING: frozenset(
        {
            MachineState.COMPLETED,
            MachineState.HOLDING,
            MachineState.CANCELLED,
            MachineState.FAULT,
            MachineState.ESTOPPED,
        }
    ),
    MachineState.HOLDING: frozenset(
        {
            MachineState.EXECUTING,
            MachineState.CANCELLED,
            MachineState.FAULT,
            MachineState.ESTOPPED,
        }
    ),
    MachineState.COMPLETED: frozenset(
        {MachineState.READY, MachineState.ESTOPPED, MachineState.FAULT}
    ),
    MachineState.CANCELLED: frozenset(
        {MachineState.READY, MachineState.ESTOPPED, MachineState.FAULT}
    ),
    MachineState.FAULT: frozenset(
        {
            MachineState.IDLE,
            MachineState.READY,
            MachineState.ESTOPPED,
            MachineState.DISCONNECTED,
        }
    ),
    MachineState.ESTOPPED: frozenset(
        {MachineState.IDLE, MachineState.READY, MachineState.DISCONNECTED}
    ),
}


class ExecutionStage(StrEnum):
    APPROACH = "approach"
    GRASP = "grasp"
    HANDOFF = "handoff"
    SELECT = "select"


class Clock(ABC):
    @abstractmethod
    def time_ns(self) -> int: ...

    @abstractmethod
    def monotonic_ns(self) -> int: ...


class WallClock(Clock):
    def time_ns(self) -> int:
        return time.time_ns()

    def monotonic_ns(self) -> int:
        return time.monotonic_ns()


class SimulatedClock(Clock):
    """Deterministic clock for tests; wall and monotonic stay aligned."""

    def __init__(self, start_ns: int = 1_000_000_000_000) -> None:
        self._t = start_ns

    def time_ns(self) -> int:
        return self._t

    def monotonic_ns(self) -> int:
        return self._t

    def advance_ms(self, milliseconds: float) -> None:
        self._t += int(milliseconds * 1_000_000)


@dataclass(frozen=True)
class ObjectSpec:
    object_id: str
    class_name: str
    table_position_xy: tuple[float, float]


DEFAULT_OBJECTS = (
    ObjectSpec("object_blue_1", "blue_block", DEFAULT_LAYOUT[0]),
    ObjectSpec("object_red_1", "red_block", DEFAULT_LAYOUT[1]),
    ObjectSpec("object_green_1", "green_block", DEFAULT_LAYOUT[2]),
    ObjectSpec("object_yellow_1", "yellow_block", DEFAULT_LAYOUT[3]),
)


@dataclass
class FaultInjection:
    slow_action_multiplier: float = 1.0
    unreachable_object_ids: frozenset[str] = field(default_factory=frozenset)
    missing_object_ids: frozenset[str] = field(default_factory=frozenset)
    grasp_failure_probability: float | None = None
    command_timeout_ms: float | None = None
    adapter_disconnect: bool = False
    force_grasp_failure: bool | None = None


@dataclass
class SimulatorSettings:
    approach_ms: float = 400.0
    grasp_ms: float = 250.0
    handoff_ms: float = 400.0
    seed: int = 7
    grasp_failure_probability: float = 0.0
    objects: tuple[ObjectSpec, ...] = DEFAULT_OBJECTS
    faults: FaultInjection = field(default_factory=FaultInjection)
    heartbeat_seconds: float = 2.0
    command_endpoint: str = "tcp://127.0.0.1:5557"
    event_endpoint: str = "tcp://127.0.0.1:5555"
    source: str = "robot-simulator"

    @classmethod
    def from_stacked_config(
        cls,
        config: dict[str, Any],
        *,
        faults: FaultInjection | None = None,
    ) -> SimulatorSettings:
        runtime = config.get("runtime") or {}
        ports = runtime.get("ports") or {}
        sim = config.get("simulator") or {}
        vision_objects = (config.get("vision") or {}).get("objects") or []
        objects: list[ObjectSpec] = []
        for index, item in enumerate(vision_objects):
            layout = DEFAULT_LAYOUT[index] if index < len(DEFAULT_LAYOUT) else (0.50, 0.50)
            objects.append(
                ObjectSpec(
                    object_id=str(item["object_id"]),
                    class_name=str(item.get("class_name", item["object_id"])),
                    table_position_xy=layout,
                )
            )
        return cls(
            approach_ms=float(sim.get("approach_ms", 400)),
            grasp_ms=float(sim.get("grasp_ms", 250)),
            handoff_ms=float(sim.get("handoff_ms", 400)),
            seed=int(sim.get("seed", 7)),
            grasp_failure_probability=float(sim.get("grasp_failure_probability", 0.0)),
            objects=tuple(objects) or DEFAULT_OBJECTS,
            faults=faults or FaultInjection(),
            heartbeat_seconds=float(runtime.get("heartbeat_seconds", 2)),
            command_endpoint=str(ports.get("command_push", "tcp://127.0.0.1:5557")),
            event_endpoint=str(ports.get("adapter_push", "tcp://127.0.0.1:5555")),
        )

    def scaled(self, milliseconds: float) -> float:
        return milliseconds * max(self.faults.slow_action_multiplier, 0.0)

    def grasp_probability(self) -> float:
        if self.faults.grasp_failure_probability is not None:
            return self.faults.grasp_failure_probability
        return self.grasp_failure_probability


@dataclass
class _Object:
    object_id: str
    class_name: str
    table_position_xy: list[float]
    home_xy: tuple[float, float]


@dataclass
class _ActiveCommand:
    command: ActionCommand
    started_mono_ns: int
    stage: ExecutionStage
    stage_elapsed_ms: float = 0.0
    grasped: bool = False
    approach_from: tuple[float, float] = HOME_XY
    handoff_from: tuple[float, float] = HOME_XY


class MachineAdapter(ABC):
    """Common machine interface. A future SO-ARM adapter must implement this."""

    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def disconnect(self) -> None: ...

    @abstractmethod
    def get_state(self) -> MachineStatePayload: ...

    @abstractmethod
    def execute(self, command: ActionCommand) -> None: ...

    @abstractmethod
    def hold(self, reason: str) -> None: ...

    @abstractmethod
    def cancel(self, command_id: str) -> None: ...

    @abstractmethod
    def emergency_stop(self, reason: str) -> None: ...

    @abstractmethod
    def reset(self) -> None: ...


class SimulatorMachineAdapter(MachineAdapter):
    """Deterministic tabletop task-state simulator (not a physics engine)."""

    def __init__(
        self,
        settings: SimulatorSettings | None = None,
        *,
        clock: Clock | None = None,
    ) -> None:
        self.settings = settings or SimulatorSettings()
        self._clock = clock or WallClock()
        self._state = MachineState.DISCONNECTED
        self._previous: MachineState | None = None
        self._objects: dict[str, _Object] = {}
        self._robot_xy = list(HOME_XY)
        self._held_object_id: str | None = None
        self._target_object_id: str | None = None
        self._progress = 0.0
        self._fault_reason: str | None = None
        self._last_outcome: str | None = None
        self._stage: ExecutionStage | None = None
        self._active: _ActiveCommand | None = None
        self._seen_command_ids: set[str] = set()
        self._seen_idempotency_keys: set[str] = set()
        self._rng = random.Random(self.settings.seed)
        self._last_tick_ns = self._clock.monotonic_ns()
        self.emitted_states: list[MachineStatePayload] = []
        self.emitted_outcomes: list[ActionOutcomePayload] = []
        self._init_world()

    def _init_world(self) -> None:
        self._objects = {}
        missing = self.settings.faults.missing_object_ids
        for spec in self.settings.objects:
            if spec.object_id in missing:
                continue
            self._objects[spec.object_id] = _Object(
                object_id=spec.object_id,
                class_name=spec.class_name,
                table_position_xy=list(spec.table_position_xy),
                home_xy=spec.table_position_xy,
            )
        self._robot_xy = list(HOME_XY)
        self._held_object_id = None
        self._target_object_id = None
        self._progress = 0.0
        self._stage = None

    @property
    def state(self) -> MachineState:
        return self._state

    @property
    def active_command_id(self) -> str | None:
        return self._active.command.command_id if self._active else None

    def connect(self) -> None:
        if self.settings.faults.adapter_disconnect:
            return
        if self._state is MachineState.DISCONNECTED:
            self._transition(MachineState.IDLE)
        if self._state is MachineState.IDLE:
            self._transition(MachineState.READY)

    def disconnect(self) -> None:
        if self._active is not None:
            self._finish_active(OutcomeKind.FAULT, "ADAPTER_DISCONNECT")
        if self._state is not MachineState.DISCONNECTED:
            self._state = MachineState.DISCONNECTED
            self._previous = MachineState.DISCONNECTED
            self._active = None
            self._stage = None
            self._progress = 0.0
            self._fault_reason = "ADAPTER_DISCONNECT"
            self._emit_state()

    def get_state(self) -> MachineStatePayload:
        return self._snapshot()

    def execute(self, command: ActionCommand) -> None:
        now = self._clock.time_ns()
        if command.expires_at_ns <= now:
            self._reject(command, "EXPIRED")
            return
        if (
            command.command_id in self._seen_command_ids
            or command.idempotency_key in self._seen_idempotency_keys
        ):
            self._reject(command, "DUPLICATE")
            return

        action = _as_action(command.action)
        if action is Action.STOP:
            self._remember(command)
            self.emergency_stop("STOP")
            return
        if action is Action.CANCEL:
            if self._is_blocked():
                self._reject(command, "BLOCKED")
                return
            self._remember(command)
            target = self.active_command_id or command.command_id
            self.cancel(target)
            return
        if action is Action.CONFIRM and self._state is MachineState.HOLDING:
            self._remember(command)
            self.resume()
            return

        if self._is_blocked():
            self._reject(command, "BLOCKED")
            return
        if self._state is not MachineState.READY:
            self._reject(command, "NOT_READY")
            return

        self._remember(command)
        if action in {Action.REQUEST_HANDOFF, Action.SELECT_OBJECT, Action.CONFIRM}:
            self._start_motion(command, action)
            return
        self._fault(f"UNSUPPORTED_ACTION:{command.action}")

    def hold(self, reason: str) -> None:
        if self._state is MachineState.HOLDING:
            return
        if self._state is not MachineState.EXECUTING:
            self._fault(f"INVALID_TRANSITION:{self._state}->HOLDING")
            return
        self._fault_reason = reason
        self._transition(MachineState.HOLDING)

    def resume(self) -> None:
        if self._state is not MachineState.HOLDING or self._active is None:
            return
        self._fault_reason = None
        self._transition(MachineState.EXECUTING)

    def cancel(self, command_id: str) -> None:
        if self._state not in {MachineState.EXECUTING, MachineState.HOLDING}:
            return
        if self._active is None:
            return
        if command_id and self._active.command.command_id != command_id:
            return
        self._drop_held()
        self._finish_active(OutcomeKind.CANCELLED, None)
        self._transition(MachineState.CANCELLED)
        self._transition(MachineState.READY)

    def emergency_stop(self, reason: str) -> None:
        if self._state is MachineState.ESTOPPED:
            return
        self._drop_held()
        if self._active is not None:
            self._finish_active(OutcomeKind.ESTOPPED, reason)
        self._fault_reason = reason
        self._progress = 0.0
        self._stage = None
        self._transition(MachineState.ESTOPPED)

    def reset(self) -> None:
        if self._state not in {MachineState.ESTOPPED, MachineState.FAULT}:
            return
        self._active = None
        self._fault_reason = None
        self._stage = None
        self._progress = 0.0
        self._held_object_id = None
        self._target_object_id = None
        self._init_world()
        self._rng = random.Random(self.settings.seed)
        self._transition(MachineState.IDLE)
        self._transition(MachineState.READY)

    def tick(self, now_monotonic_ns: int | None = None) -> None:
        now = now_monotonic_ns if now_monotonic_ns is not None else self._clock.monotonic_ns()
        dt_ms = (now - self._last_tick_ns) / 1_000_000
        self._last_tick_ns = now
        if dt_ms < 0:
            return
        self._advance(dt_ms)

    def advance_ms(self, milliseconds: float) -> None:
        if isinstance(self._clock, SimulatedClock):
            self._clock.advance_ms(milliseconds)
        self.tick()

    def force_transition(self, target: MachineState) -> None:
        """Test helper: attempt a raw transition (invalid ones become FAULT)."""
        self._transition(target)

    def _start_motion(self, command: ActionCommand, action: Action) -> None:
        target_id = command.target_object_id
        if action is Action.REQUEST_HANDOFF:
            if not target_id or target_id not in self._objects:
                self._fault("TARGET_MISSING", command)
                return
            self._target_object_id = target_id
            self._active = _ActiveCommand(
                command=command,
                started_mono_ns=self._clock.monotonic_ns(),
                stage=ExecutionStage.APPROACH,
                approach_from=(self._robot_xy[0], self._robot_xy[1]),
            )
            self._stage = ExecutionStage.APPROACH
            self._progress = 0.0
            self._transition(MachineState.EXECUTING)
            return

        self._target_object_id = target_id
        self._active = _ActiveCommand(
            command=command,
            started_mono_ns=self._clock.monotonic_ns(),
            stage=ExecutionStage.SELECT,
        )
        self._stage = ExecutionStage.SELECT
        self._progress = 1.0
        self._transition(MachineState.EXECUTING)
        self._complete_success()

    def _advance(self, dt_ms: float) -> None:
        if self._state is not MachineState.EXECUTING or self._active is None:
            return
        timeout = self.settings.faults.command_timeout_ms
        if timeout is not None:
            elapsed = (self._clock.monotonic_ns() - self._active.started_mono_ns) / 1_000_000
            if elapsed > timeout:
                self._abort_fault("COMMAND_TIMEOUT")
                return

        remaining = dt_ms
        for _ in range(8):
            if remaining < 0 or self._state is not MachineState.EXECUTING or self._active is None:
                break
            duration = self._stage_duration(self._active.stage)
            if duration <= 0:
                self._complete_stage()
                continue
            left = duration - self._active.stage_elapsed_ms
            step = min(remaining, left)
            self._active.stage_elapsed_ms += step
            remaining -= step
            self._update_motion()
            if self._active.stage_elapsed_ms + 1e-9 >= duration:
                self._complete_stage()
            if remaining <= 0:
                break

    def _stage_duration(self, stage: ExecutionStage) -> float:
        settings = self.settings
        if stage is ExecutionStage.APPROACH:
            return settings.scaled(settings.approach_ms)
        if stage is ExecutionStage.GRASP:
            return settings.scaled(settings.grasp_ms)
        if stage is ExecutionStage.HANDOFF:
            return settings.scaled(settings.handoff_ms)
        return 0.0

    def _complete_stage(self) -> None:
        assert self._active is not None
        stage = self._active.stage
        if stage is ExecutionStage.APPROACH:
            target = self._objects[self._active.command.target_object_id or ""]
            self._robot_xy = list(target.table_position_xy)
            if self._active.command.target_object_id in self.settings.faults.unreachable_object_ids:
                self._abort_fault("UNREACHABLE_OBJECT")
                return
            self._active.stage = ExecutionStage.GRASP
            self._active.stage_elapsed_ms = 0.0
            self._stage = ExecutionStage.GRASP
            self._emit_state()
            return
        if stage is ExecutionStage.GRASP:
            if self._grasp_fails():
                self._abort_fault("GRASP_FAILURE")
                return
            self._held_object_id = self._active.command.target_object_id
            self._active.grasped = True
            self._active.handoff_from = (self._robot_xy[0], self._robot_xy[1])
            self._active.stage = ExecutionStage.HANDOFF
            self._active.stage_elapsed_ms = 0.0
            self._stage = ExecutionStage.HANDOFF
            self._emit_state()
            return
        if stage is ExecutionStage.HANDOFF:
            self._place_at_handoff()
            self._complete_success()

    def _grasp_fails(self) -> bool:
        if self.settings.faults.force_grasp_failure is True:
            return True
        if self.settings.faults.force_grasp_failure is False:
            return False
        return self._rng.random() < self.settings.grasp_probability()

    def _update_motion(self) -> None:
        active = self._active
        if active is None:
            return
        duration = self._stage_duration(active.stage)
        frac = 1.0 if duration <= 0 else min(1.0, active.stage_elapsed_ms / duration)
        target = self._objects.get(active.command.target_object_id or "")
        if active.stage is ExecutionStage.APPROACH and target is not None:
            self._robot_xy = _lerp(active.approach_from, tuple(target.table_position_xy), frac)
        elif active.stage is ExecutionStage.HANDOFF:
            self._robot_xy = _lerp(active.handoff_from, HANDOFF_XY, frac)
            if target is not None and self._held_object_id == target.object_id:
                target.table_position_xy = list(self._robot_xy)
        self._progress = self._overall_progress()

    def _overall_progress(self) -> float:
        if self._active is None:
            return self._progress
        stages = (
            (ExecutionStage.APPROACH, self._stage_duration(ExecutionStage.APPROACH)),
            (ExecutionStage.GRASP, self._stage_duration(ExecutionStage.GRASP)),
            (ExecutionStage.HANDOFF, self._stage_duration(ExecutionStage.HANDOFF)),
        )
        total = sum(duration for _, duration in stages)
        if total <= 0:
            return 1.0
        elapsed = 0.0
        for stage, duration in stages:
            if self._active.stage is stage:
                elapsed += min(duration, self._active.stage_elapsed_ms)
                break
            elapsed += duration
        return min(1.0, elapsed / total)

    def _place_at_handoff(self) -> None:
        target_id = self._active.command.target_object_id if self._active else None
        if target_id and target_id in self._objects:
            self._objects[target_id].table_position_xy = list(HANDOFF_XY)
        self._robot_xy = list(HANDOFF_XY)
        self._held_object_id = None
        self._progress = 1.0

    def _complete_success(self) -> None:
        self._finish_active(OutcomeKind.COMPLETED, None)
        self._transition(MachineState.COMPLETED)
        self._stage = None
        self._progress = 0.0
        self._target_object_id = None
        self._transition(MachineState.READY)

    def _abort_fault(self, reason: str) -> None:
        command = self._active.command if self._active else None
        self._drop_held()
        self._finish_active(OutcomeKind.FAULT, reason)
        self._fault(reason, command, already_finished=True)

    def _drop_held(self) -> None:
        self._held_object_id = None

    def _finish_active(self, outcome: OutcomeKind, reason: str | None) -> None:
        active = self._active
        if active is None:
            return
        duration_ms = max(0.0, (self._clock.monotonic_ns() - active.started_mono_ns) / 1_000_000)
        self._last_outcome = str(outcome)
        if reason:
            self._fault_reason = reason
        self.emitted_outcomes.append(
            ActionOutcomePayload(
                command_id=active.command.command_id,
                decision_id=active.command.decision_id,
                outcome=outcome,
                duration_ms=duration_ms,
            )
        )
        self._active = None

    def _reject(self, command: ActionCommand, reason: str) -> None:
        self._last_outcome = str(OutcomeKind.REJECTED)
        self._fault_reason = reason
        self.emitted_outcomes.append(
            ActionOutcomePayload(
                command_id=command.command_id,
                decision_id=command.decision_id,
                outcome=OutcomeKind.REJECTED,
                duration_ms=0.0,
            )
        )
        self._emit_state()

    def _remember(self, command: ActionCommand) -> None:
        self._seen_command_ids.add(command.command_id)
        self._seen_idempotency_keys.add(command.idempotency_key)

    def _is_blocked(self) -> bool:
        return self._state in {
            MachineState.FAULT,
            MachineState.ESTOPPED,
            MachineState.DISCONNECTED,
        }

    def _fault(
        self,
        reason: str,
        command: ActionCommand | None = None,
        *,
        already_finished: bool = False,
    ) -> None:
        if command is not None and self._active is not None and not already_finished:
            self._finish_active(OutcomeKind.FAULT, reason)
        elif command is not None and self._active is None and not already_finished:
            self._last_outcome = str(OutcomeKind.FAULT)
            self.emitted_outcomes.append(
                ActionOutcomePayload(
                    command_id=command.command_id,
                    decision_id=command.decision_id,
                    outcome=OutcomeKind.FAULT,
                    duration_ms=0.0,
                )
            )
        self._fault_reason = reason
        self._stage = None
        if self._state is not MachineState.FAULT:
            self._transition(MachineState.FAULT)

    def _transition(self, target: MachineState) -> None:
        if target is self._state:
            return
        allowed = ALLOWED_TRANSITIONS[self._state]
        if target not in allowed:
            if self._state is not MachineState.FAULT:
                if self._active is not None:
                    self._finish_active(
                        OutcomeKind.FAULT, f"INVALID_TRANSITION:{self._state}->{target}"
                    )
                self._fault_reason = f"INVALID_TRANSITION:{self._state}->{target}"
                self._previous = self._state
                self._state = MachineState.FAULT
                self._stage = None
                self._emit_state()
            return
        self._previous = self._state
        self._state = target
        if target is MachineState.READY:
            self._active = None
            self._stage = None
        self._emit_state()

    def _health(self) -> str:
        if self._state is MachineState.DISCONNECTED:
            return DeviceHealth.OFFLINE
        if self._state in {MachineState.FAULT, MachineState.ESTOPPED}:
            return DeviceHealth.DEGRADED
        return DeviceHealth.HEALTHY

    def _snapshot(self) -> MachineStatePayload:
        objects = [
            VisionObject(
                object_id=item.object_id,
                class_name=item.class_name,
                confidence=1.0,
                bbox_xyxy=_bbox(item.table_position_xy),
                table_position_xy=list(item.table_position_xy),
            )
            for item in self._objects.values()
        ]
        active = None
        if self._active is not None:
            cmd = self._active.command
            active = {
                "command_id": cmd.command_id,
                "action": str(cmd.action),
                "target_object_id": cmd.target_object_id,
                "idempotency_key": cmd.idempotency_key,
            }
        return MachineStatePayload.model_validate(
            {
                "state": self._state,
                "previous_state": self._previous,
                "active_command_id": self.active_command_id,
                "held_object_id": self._held_object_id,
                "target_object_id": self._target_object_id,
                "progress": round(min(1.0, max(0.0, self._progress)), 6),
                "objects": [obj.model_dump(mode="json") for obj in objects],
                "fault_reason": self._fault_reason,
                "last_outcome": self._last_outcome,
                "health": self._health(),
                "stage": str(self._stage) if self._stage else None,
                "active_command": active,
                "robot_xy": list(self._robot_xy),
            }
        )

    def _emit_state(self) -> None:
        self.emitted_states.append(self._snapshot())


def _as_action(value: Action | str) -> Action | str:
    try:
        return Action(value)
    except ValueError:
        return value


def _lerp(start: tuple[float, float], end: tuple[float, float], t: float) -> list[float]:
    t = min(1.0, max(0.0, t))
    return [start[0] + (end[0] - start[0]) * t, start[1] + (end[1] - start[1]) * t]


def _bbox(xy: list[float]) -> list[float]:
    px = xy[0] * 640.0
    py = xy[1] * 480.0
    return [px - 40.0, py - 40.0, px + 40.0, py + 40.0]
