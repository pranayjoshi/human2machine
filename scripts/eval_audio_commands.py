#!/usr/bin/env python3
"""Evaluate grammar parsing on committed audio fixtures. No ASR, no microphone."""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for extra in (
    ROOT / "packages/contracts-python/src",
    ROOT / "services/audio-adapter",
):
    path = str(extra)
    if path not in sys.path:
        sys.path.insert(0, path)

from audio_adapter.parser import parse_utterance  # noqa: E402

DEFAULT_FIXTURE = ROOT / "data" / "fixtures" / "audio" / "milestone2_commands.json"
ACCURACY_GATE = 0.95
SAFETY_RECALL_GATE = 1.0
LATENCY_P95_GATE_S = 1.5
SAFETY_ACTIONS = frozenset({"STOP", "CANCEL"})


@dataclass
class EvalResult:
    n: int
    action_accuracy: float
    stop_cancel_recall: float
    unknown_rate: float
    latency_p95_s: float
    category_counts: dict[str, int]
    category_correct: dict[str, int]
    safety_n: int
    safety_hits: int
    unknown_n: int
    unknown_hits: int
    failures: list[str] = field(default_factory=list)

    def passed(self) -> bool:
        return (
            self.n >= 100
            and self.action_accuracy >= ACCURACY_GATE
            and self.stop_cancel_recall >= SAFETY_RECALL_GATE
        )


def load_fixture(path: Path) -> list[dict]:
    rows = json.loads(path.read_text())
    if not isinstance(rows, list):
        raise ValueError(f"fixture must be a JSON list: {path}")
    return [row for row in rows if row.get("is_final", True)]


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    index = min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))
    return ordered[index]


def evaluate(path: Path | None = None) -> EvalResult:
    fixture = path or DEFAULT_FIXTURE
    rows = load_fixture(fixture)
    correct = 0
    predicted_unknown = 0
    safety_n = 0
    safety_hits = 0
    unknown_n = 0
    unknown_hits = 0
    category_counts: Counter[str] = Counter()
    category_correct: Counter[str] = Counter()
    latencies: list[float] = []
    failures: list[str] = []

    for row in rows:
        transcript = str(row["transcript"])
        expected = str(row["action"])
        category = str(row.get("category") or expected.lower())
        category_counts[category] += 1
        started = time.perf_counter()
        parsed = parse_utterance(transcript)
        latencies.append(time.perf_counter() - started)
        if parsed.action == "UNKNOWN":
            predicted_unknown += 1
        if expected in SAFETY_ACTIONS:
            safety_n += 1
            if parsed.action == expected:
                safety_hits += 1
        if expected == "UNKNOWN":
            unknown_n += 1
            if parsed.action == "UNKNOWN":
                unknown_hits += 1
        action_ok = parsed.action == expected
        target_ok = True
        if "target_reference" in row:
            target_ok = parsed.target_reference == row["target_reference"]
        if "target_object_id" in row:
            target_ok = target_ok and parsed.target_object_id == row["target_object_id"]
        if action_ok:
            correct += 1
            category_correct[category] += 1
        else:
            failures.append(f"{transcript!r}: expected {expected} got {parsed.action}")
        if action_ok and not target_ok:
            failures.append(
                f"{transcript!r}: action ok, target expected "
                f"{row.get('target_reference')}/{row.get('target_object_id')} "
                f"got {parsed.target_reference}/{parsed.target_object_id}"
            )

    n = len(rows)
    return EvalResult(
        n=n,
        action_accuracy=(correct / n) if n else 0.0,
        stop_cancel_recall=(safety_hits / safety_n) if safety_n else 0.0,
        unknown_rate=(predicted_unknown / n) if n else 0.0,
        latency_p95_s=_percentile(latencies, 0.95),
        category_counts=dict(category_counts),
        category_correct=dict(category_correct),
        safety_n=safety_n,
        safety_hits=safety_hits,
        unknown_n=unknown_n,
        unknown_hits=unknown_hits,
        failures=failures,
    )


def format_report(result: EvalResult) -> str:
    lines = [
        f"samples: {result.n}",
        f"action_accuracy: {result.action_accuracy:.4f}",
        f"stop_cancel_recall: {result.stop_cancel_recall:.4f} "
        f"({result.safety_hits}/{result.safety_n})",
        f"unknown_rate: {result.unknown_rate:.4f}",
        f"unsupported_unknown: {result.unknown_hits}/{result.unknown_n}",
        f"latency_p95_s: {result.latency_p95_s:.6f}",
        "categories:",
    ]
    for name in sorted(result.category_counts):
        total = result.category_counts[name]
        hits = result.category_correct.get(name, 0)
        lines.append(f"  {name}: {hits}/{total}")
    if result.failures:
        lines.append("mismatches:")
        lines.extend(f"  {item}" for item in result.failures[:20])
        if len(result.failures) > 20:
            lines.append(f"  ... {len(result.failures) - 20} more")
    gate = "PASS" if result.passed() and result.latency_p95_s < LATENCY_P95_GATE_S else "FAIL"
    lines.append(
        f"gates: accuracy>={ACCURACY_GATE} stop_cancel_recall>={SAFETY_RECALL_GATE} "
        f"p95<{LATENCY_P95_GATE_S}s -> {gate}"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "fixture",
        nargs="?",
        type=Path,
        default=DEFAULT_FIXTURE,
        help="JSON fixture of scripted utterances",
    )
    args = parser.parse_args(argv)
    result = evaluate(args.fixture)
    print(format_report(result))
    if not result.passed():
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
