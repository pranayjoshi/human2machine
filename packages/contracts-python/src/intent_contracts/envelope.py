from __future__ import annotations

import time
import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from intent_contracts.enums import PRODUCER_VERSION, SCHEMA_VERSION, EventType


def new_event_id() -> str:
    return uuid.uuid4().hex


def now_wall_ns() -> int:
    return time.time_ns()


def now_monotonic_ns() -> int:
    return time.monotonic_ns()


class EventEnvelope(BaseModel):
    """Canonical event wrapper. Adapters omit normalized_time_ns; the hub adds it."""

    model_config = ConfigDict(extra="allow")

    schema_version: str = SCHEMA_VERSION
    event_id: str = Field(min_length=8)
    event_type: EventType | str
    source: str = Field(min_length=1)
    modality: str | None = None
    session_id: str | None = None
    trial_id: str | None = None
    sequence: int = Field(ge=0)
    source_time_ns: int | None = None
    received_monotonic_ns: int = Field(ge=0)
    normalized_time_ns: int | None = None
    quality: float = Field(ge=0.0, le=1.0, default=1.0)
    producer_version: str = PRODUCER_VERSION
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("schema_version")
    @classmethod
    def reject_unknown_major(cls, value: str) -> str:
        major = value.split(".", 1)[0]
        if major != SCHEMA_VERSION.split(".", 1)[0]:
            raise ValueError(f"unsupported schema major version: {value}")
        return value

    @field_validator("source_time_ns", "received_monotonic_ns", "normalized_time_ns", "sequence")
    @classmethod
    def timestamps_are_ints(cls, value: int | None) -> int | None:
        if value is None:
            return value
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("timestamps and sequence must be integers")
        return value

    @model_validator(mode="after")
    def finite_quality(self) -> EventEnvelope:
        if not (0.0 <= self.quality <= 1.0):
            raise ValueError("quality must be in [0, 1]")
        return self

    def to_unnormalized_dict(self) -> dict[str, Any]:
        data = self.model_dump(mode="json")
        data.pop("normalized_time_ns", None)
        return data
