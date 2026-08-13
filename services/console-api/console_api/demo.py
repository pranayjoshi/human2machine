"""Scripted Milestone 0 demo trials: unnormalized adapter events for the hub."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Literal

from intent_contracts.enums import PRODUCER_VERSION, SCHEMA_VERSION
from intent_contracts.envelope import new_event_id, now_monotonic_ns, now_wall_ns
from intent_contracts.validation import parse_unnormalized_event

DemoScenario = Literal["success", "conflict", "cancel"]
SCENARIOS: tuple[str, ...] = ("success", "conflict", "cancel")


def demo_fixtures_dir(root: Path) -> Path:
    return root / "data" / "fixtures" / "demo"


def load_scenario_spec(root: Path, scenario: DemoScenario | str) -> dict[str, Any]:
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown demo scenario: {scenario}")
    path = demo_fixtures_dir(root) / f"{scenario}.json"
    spec = json.loads(path.read_text())
    if spec.get("scenario") != scenario:
        raise ValueError(f"fixture scenario mismatch in {path}")
    return spec


def materialize_demo_events(
    spec: dict[str, Any],
    *,
    session_id: str | None,
    trial_id: str | None,
    sequence_start: int = 1,
) -> list[tuple[int, dict[str, Any]]]:
    """Return (delay_ms, unnormalized event dict) pairs ready to PUSH."""
    wall = now_wall_ns()
    mono = now_monotonic_ns()
    prepared: list[tuple[int, dict[str, Any]]] = []
    for index, item in enumerate(spec.get("events") or []):
        delay_ms = int(item.get("delay_ms") or 0)
        offset_ns = delay_ms * 1_000_000
        payload = deepcopy(item.get("payload") or {})
        if "utterance_start_ns" in payload:
            payload["utterance_start_ns"] = wall + offset_ns - 35_000_000
            payload["utterance_end_ns"] = wall + offset_ns
        if payload.get("feature_name") == "emg_gesture":
            payload["window_start_ns"] = wall + offset_ns - 25_000_000
            payload["window_end_ns"] = wall + offset_ns
        event: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "event_id": new_event_id(),
            "event_type": item["event_type"],
            "source": item["source"],
            "modality": item.get("modality"),
            "session_id": session_id,
            "trial_id": trial_id,
            "sequence": sequence_start + index,
            "source_time_ns": wall + offset_ns,
            "received_monotonic_ns": mono + offset_ns,
            "quality": float(item.get("quality", 1.0)),
            "producer_version": PRODUCER_VERSION,
            "payload": payload,
        }
        parse_unnormalized_event(event)
        prepared.append((delay_ms, event))
    return prepared
