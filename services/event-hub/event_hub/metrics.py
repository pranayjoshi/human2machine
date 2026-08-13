from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class HubMetrics:
    """In-process counters. Also logged periodically as structured fields."""

    invalid: int = 0
    duplicate: int = 0
    sequence_gaps: int = 0
    sequence_regressions: int = 0
    drops: int = 0
    clock_jumps: int = 0
    published: int = 0
    oversized: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "invalid": self.invalid,
            "duplicate": self.duplicate,
            "sequence_gaps": self.sequence_gaps,
            "sequence_regressions": self.sequence_regressions,
            "drops": self.drops,
            "clock_jumps": self.clock_jumps,
            "published": self.published,
            "oversized": self.oversized,
        }

    @property
    def error_count(self) -> int:
        return self.invalid + self.oversized + self.drops


@dataclass
class SequenceAnomaly:
    source: str
    previous: int
    sequence: int
    kind: str  # "gap" | "regression"
    event_id: str
    extra: dict[str, Any] = field(default_factory=dict)
