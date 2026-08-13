from __future__ import annotations

from pathlib import Path

import pytest
from intent_contracts.commands import ActionCommand
from intent_contracts.enums import MachineState, OutcomeKind
from intent_contracts.validation import parse_unnormalized_event
from intent_runtime.config import load_stacked_config
from robot_simulator.adapter import (
    ExecutionStage,
    FaultInjection,
    SimulatedClock,
    SimulatorMachineAdapter,
    SimulatorSettings,
)
from robot_simulator.service import SimulatorService


def make_adapter(
    settings: SimulatorSettings | None = None,
) -> tuple[SimulatorMachineAdapter, SimulatedClock]:
    clock = SimulatedClock()
    adapter = SimulatorMachineAdapter(settings or SimulatorSettings(), clock=clock)
    return adapter, clock


def make_command(clock: SimulatedClock, **overrides: object) -> ActionCommand:
    now = clock.time_ns()
    payload: dict[str, object] = {
        "schema_version": "1.0.0",
        "command_id": "cmd-1",
        "decision_id": "dec-1",
        "action": "REQUEST_HANDOFF",
        "target_object_id": "object_blue_1",
        "issued_at_ns": now,
        "expires_at_ns": now + 5_000_000_000,
        "safety_policy_version": "safety-policy-v1",
        "idempotency_key": "dec-1:REQUEST_HANDOFF:object_blue_1",
    }
    payload.update(overrides)
    return ActionCommand.model_validate(payload)


def changed_states(adapter: SimulatorMachineAdapter) -> list[str]:
    states: list[str] = []
    for event in adapter.emitted_states:
        value = str(event.state)
        if not states or states[-1] != value:
            states.append(value)
    return states


def _connected() -> tuple[SimulatorMachineAdapter, object]:
    adapter, clock = make_adapter()
    adapter.connect()
    return adapter, clock


def test_connect_reaches_ready() -> None:
    adapter, _ = make_adapter()
    adapter.connect()
    assert adapter.state is MachineState.READY
    assert changed_states(adapter) == ["IDLE", "READY"]


def test_only_unexpired_command_executes() -> None:
    adapter, clock = _connected()
    expired = make_command(clock, expires_at_ns=clock.time_ns())
    adapter.execute(expired)
    assert adapter.state is MachineState.READY
    assert adapter.emitted_outcomes[-1].outcome == OutcomeKind.REJECTED
    assert adapter.emitted_outcomes[-1].command_id == expired.command_id

    live = make_command(clock, command_id="cmd-live", idempotency_key="live-key")
    adapter.execute(live)
    adapter.advance_ms(1200)
    assert adapter.emitted_outcomes[-1].outcome == OutcomeKind.COMPLETED
    assert adapter.emitted_outcomes[-1].command_id == "cmd-live"
    assert adapter.state is MachineState.READY


def test_duplicate_command_id_and_idempotency_execute_once() -> None:
    adapter, clock = _connected()
    command = make_command(clock)
    adapter.execute(command)
    adapter.advance_ms(1200)
    assert [o.outcome for o in adapter.emitted_outcomes] == [OutcomeKind.COMPLETED]

    adapter.execute(command)
    assert [o.outcome for o in adapter.emitted_outcomes] == [
        OutcomeKind.COMPLETED,
        OutcomeKind.REJECTED,
    ]

    twin = make_command(clock, command_id="cmd-other")  # same idempotency_key
    adapter.execute(twin)
    assert adapter.emitted_outcomes[-1].outcome == OutcomeKind.REJECTED
    completed = [o for o in adapter.emitted_outcomes if o.outcome == OutcomeKind.COMPLETED]
    assert len(completed) == 1


@pytest.mark.parametrize(
    ("wait_ms", "stage"),
    [
        (50.0, ExecutionStage.APPROACH),
        (400.0, ExecutionStage.GRASP),
        (650.0, ExecutionStage.HANDOFF),
    ],
)
def test_cancel_interrupts_every_execution_stage(wait_ms: float, stage: ExecutionStage) -> None:
    adapter, clock = _connected()
    command = make_command(clock)
    adapter.execute(command)
    adapter.advance_ms(wait_ms)
    assert adapter.state is MachineState.EXECUTING
    assert adapter.get_state().stage == str(stage)
    adapter.cancel(command.command_id)
    assert adapter.state is MachineState.READY
    assert adapter.emitted_outcomes[-1].outcome == OutcomeKind.CANCELLED
    assert "CANCELLED" in changed_states(adapter)
    assert adapter.get_state().held_object_id is None


def test_estop_blocks_later_commands_until_reset() -> None:
    adapter, clock = _connected()
    first = make_command(clock)
    adapter.execute(first)
    adapter.advance_ms(50)
    adapter.emergency_stop("operator")
    assert adapter.state is MachineState.ESTOPPED
    assert adapter.emitted_outcomes[-1].outcome == OutcomeKind.ESTOPPED

    blocked = make_command(clock, command_id="cmd-2", idempotency_key="key-2")
    adapter.execute(blocked)
    assert adapter.state is MachineState.ESTOPPED
    assert adapter.emitted_outcomes[-1].outcome == OutcomeKind.REJECTED

    adapter.reset()
    assert adapter.state is MachineState.READY
    later = make_command(clock, command_id="cmd-3", idempotency_key="key-3")
    adapter.execute(later)
    adapter.advance_ms(1200)
    assert adapter.emitted_outcomes[-1].outcome == OutcomeKind.COMPLETED
    assert adapter.state is MachineState.READY


def test_every_transition_emits_machine_state() -> None:
    adapter, clock = _connected()
    before = len(adapter.emitted_states)
    command = make_command(clock)
    adapter.execute(command)
    after_start = adapter.emitted_states[-1]
    assert after_start.state == MachineState.EXECUTING
    assert after_start.previous_state == MachineState.READY
    adapter.advance_ms(1200)
    states = changed_states(adapter)
    assert states == ["IDLE", "READY", "EXECUTING", "COMPLETED", "READY"]
    assert len(adapter.emitted_states) >= before + 3
    for event in adapter.emitted_states:
        assert event.state != event.previous_state or event.previous_state is None


def test_same_seed_yields_identical_outcomes() -> None:
    def run(seed: int) -> tuple[list[str], list[tuple[str, tuple[float, float]]]]:
        settings = SimulatorSettings(
            seed=seed,
            grasp_failure_probability=0.5,
        )
        adapter, clock = make_adapter(settings=settings)
        adapter.connect()
        adapter.execute(make_command(clock))
        adapter.advance_ms(1200)
        outcomes = [str(o.outcome) for o in adapter.emitted_outcomes]
        positions = [
            (obj.object_id, tuple(obj.table_position_xy)) for obj in adapter.get_state().objects
        ]
        return outcomes, positions

    assert run(7) == run(7)
    assert run(11) == run(11)


def test_invalid_transition_emits_fault() -> None:
    adapter, _ = _connected()
    adapter.hold("not-executing")
    assert adapter.state is MachineState.FAULT
    assert adapter.get_state().fault_reason is not None
    assert adapter.get_state().fault_reason.startswith("INVALID_TRANSITION")
    assert changed_states(adapter)[-1] == "FAULT"

    adapter2, _ = _connected()
    adapter2.force_transition(MachineState.COMPLETED)
    assert adapter2.state is MachineState.FAULT


def test_hold_pauses_progress() -> None:
    adapter, clock = _connected()
    adapter.execute(make_command(clock))
    adapter.advance_ms(100)
    progress = adapter.get_state().progress
    adapter.hold("safety")
    assert adapter.state is MachineState.HOLDING
    adapter.advance_ms(400)
    assert adapter.get_state().progress == progress
    adapter.cancel(adapter.active_command_id or "cmd-1")
    assert adapter.state is MachineState.READY
    assert adapter.emitted_outcomes[-1].outcome == OutcomeKind.CANCELLED


def test_missing_target_faults() -> None:
    adapter, clock = _connected()
    adapter.execute(make_command(clock, target_object_id="nope", idempotency_key="missing"))
    assert adapter.state is MachineState.FAULT
    assert adapter.emitted_outcomes[-1].outcome == OutcomeKind.FAULT


def test_grasp_failure_fault_injection() -> None:
    settings = SimulatorSettings(faults=FaultInjection(force_grasp_failure=True))
    adapter, clock = make_adapter(settings=settings)
    adapter.connect()
    adapter.execute(make_command(clock))
    adapter.advance_ms(1200)
    assert adapter.state is MachineState.FAULT
    assert adapter.emitted_outcomes[-1].outcome == OutcomeKind.FAULT


def test_visual_state_includes_objects_and_health() -> None:
    adapter, clock = _connected()
    snapshot = adapter.get_state()
    ids = {obj.object_id for obj in snapshot.objects}
    assert ids == {
        "object_blue_1",
        "object_red_1",
        "object_green_1",
        "object_yellow_1",
    }
    dumped = snapshot.model_dump()
    assert dumped["health"] == "healthy"
    adapter.execute(make_command(clock))
    executing = adapter.get_state()
    assert executing.active_command_id == "cmd-1"
    assert executing.target_object_id == "object_blue_1"
    assert dumped["last_outcome"] is None


def test_config_loads_simulator_timings_and_objects() -> None:
    config = load_stacked_config(Path("configs"))
    settings = SimulatorSettings.from_stacked_config(config)
    assert settings.approach_ms == 400
    assert settings.grasp_ms == 250
    assert settings.handoff_ms == 400
    assert settings.seed == 7
    assert settings.grasp_failure_probability == 0.0
    assert [obj.object_id for obj in settings.objects] == [
        "object_blue_1",
        "object_red_1",
        "object_green_1",
        "object_yellow_1",
    ]


def test_service_ignores_intent_decision_and_publishes_valid_events() -> None:
    adapter, clock = _connected()
    service = SimulatorService(adapter, SimulatorSettings())
    service.handle_message(
        {
            "event_type": "intent.decision",
            "payload": {"decision_id": "nope", "action": "REQUEST_HANDOFF"},
        }
    )
    assert adapter.state is MachineState.READY
    assert adapter.emitted_outcomes == []

    service.handle_message(make_command(clock).model_dump(mode="json"))
    adapter.advance_ms(1200)
    envelopes = service.drain()
    types = [str(event.event_type) for event in envelopes]
    assert "machine.state" in types
    assert "action.outcome" in types
    for event in envelopes:
        parse_unnormalized_event(event.to_unnormalized_dict())


def test_main_requires_mock() -> None:
    from robot_simulator.main import main

    assert main([]) == 2
