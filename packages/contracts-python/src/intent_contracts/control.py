from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from intent_contracts.enums import ControlMethod, SessionState


class SessionStartRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    user_id: str = "primary"
    record_audio: bool = False
    record_video: bool = False
    consent: bool = True


class TrialStartRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    instruction: str
    ground_truth_action: str | None = None
    ground_truth_target: str | None = None
    ambiguous: bool = False


class ControlRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    method: ControlMethod | str
    request_id: str
    session_id: str | None = None
    trial_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class ControlResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    ok: bool
    request_id: str
    method: ControlMethod | str
    session_id: str | None = None
    trial_id: str | None = None
    state: SessionState | str
    error: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class PreflightResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    ready: bool
    checks: list[dict[str, Any]]
