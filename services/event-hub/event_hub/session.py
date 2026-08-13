from __future__ import annotations

import hashlib
import json
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from intent_contracts.control import (
    ControlRequest,
    ControlResponse,
    SessionStartRequest,
    TrialStartRequest,
)
from intent_contracts.enums import SCHEMA_VERSION, SessionState


def new_session_id() -> str:
    return f"session_{uuid.uuid4().hex}"


def new_trial_id() -> str:
    return f"trial_{uuid.uuid4().hex}"


def snapshot_git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=1,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def config_hash(config: dict[str, Any] | None) -> str:
    payload = json.dumps(config or {}, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


_STARTABLE = {
    SessionState.NO_SESSION,
    SessionState.FINALIZED,
    SessionState.FAILED,
    SessionState.READY,
    SessionState.PREFLIGHT,
}


@dataclass
class SessionController:
    """Owns local session/trial lifecycle. Restart never resumes a prior session."""

    config: dict[str, Any] = field(default_factory=dict)
    state: SessionState = SessionState.NO_SESSION
    session_id: str | None = None
    trial_id: str | None = None
    session_wall_time_ns: int | None = None
    session_monotonic_time_ns: int | None = None
    config_digest: str | None = None
    commit: str | None = None
    model_versions: dict[str, str] = field(default_factory=dict)
    last_trial_instruction: str | None = None

    @property
    def recording(self) -> bool:
        return self.state == SessionState.RECORDING

    def start(self, request: SessionStartRequest) -> tuple[bool, str | None]:
        if self.state == SessionState.RECORDING:
            return False, "session already recording"
        if self.state not in _STARTABLE:
            return False, f"cannot start session from {self.state}"
        self.state = SessionState.PREFLIGHT
        if not request.consent:
            self.state = SessionState.FAILED
            return False, "consent required"
        self.state = SessionState.READY
        self.session_id = new_session_id()
        self.trial_id = None
        self.session_wall_time_ns = time.time_ns()
        self.session_monotonic_time_ns = time.monotonic_ns()
        self.config_digest = config_hash(self.config)
        self.commit = snapshot_git_commit()
        self.model_versions = dict(self.config.get("model_versions") or {})
        self.last_trial_instruction = None
        self.state = SessionState.RECORDING
        return True, None

    def stop(self, session_id: str | None = None) -> tuple[bool, str | None]:
        if self.state != SessionState.RECORDING:
            return False, f"no active session to stop (state={self.state})"
        if session_id and self.session_id and session_id != self.session_id:
            return False, "session_id mismatch"
        self.state = SessionState.STOPPING
        self.trial_id = None
        self.state = SessionState.FINALIZED
        return True, None

    def fail(self, reason: str) -> bool:
        if self.state != SessionState.RECORDING:
            return False
        self.state = SessionState.FAILED
        self.trial_id = None
        self.last_trial_instruction = reason
        return True

    def start_trial(self, request: TrialStartRequest) -> tuple[bool, str | None]:
        if self.state != SessionState.RECORDING or not self.session_id:
            return False, "trial.start requires an active recording session"
        if self.trial_id is not None:
            return False, "a trial is already active"
        self.trial_id = new_trial_id()
        self.last_trial_instruction = request.instruction
        return True, None

    def complete_trial(self, trial_id: str | None = None) -> tuple[bool, str | None]:
        if self.state != SessionState.RECORDING or not self.trial_id:
            return False, "no active trial to complete"
        if trial_id and trial_id != self.trial_id:
            return False, "trial_id mismatch"
        return True, None

    def abort_trial(self, trial_id: str | None = None) -> tuple[bool, str | None]:
        if self.state != SessionState.RECORDING or not self.trial_id:
            return False, "no active trial to abort"
        if trial_id and trial_id != self.trial_id:
            return False, "trial_id mismatch"
        return True, None

    def clear_trial(self) -> None:
        self.trial_id = None
        self.last_trial_instruction = None

    def control_error(
        self,
        request: ControlRequest,
        error: str,
    ) -> ControlResponse:
        return ControlResponse(
            ok=False,
            request_id=request.request_id,
            method=request.method,
            session_id=self.session_id,
            trial_id=self.trial_id,
            state=self.state,
            error=error,
        )

    def control_ok(
        self,
        request: ControlRequest,
        extra: dict[str, Any] | None = None,
    ) -> ControlResponse:
        payload = extra or {}
        return ControlResponse(
            ok=True,
            request_id=request.request_id,
            method=request.method,
            session_id=self.session_id,
            trial_id=self.trial_id,
            state=self.state,
            payload=payload,
        )

    def lifecycle_payload(self, *, reason: str | None = None) -> dict[str, Any]:
        return {
            "state": str(self.state),
            "config_hash": self.config_digest,
            "contract_version": SCHEMA_VERSION,
            "commit": self.commit,
            "model_versions": self.model_versions,
            "reason": reason,
        }
