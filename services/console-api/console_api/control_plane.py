"""REQ/REP session-control client for the event hub."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

import zmq
from intent_contracts.control import ControlRequest, ControlResponse
from intent_contracts.enums import ControlMethod, SessionState
from intent_contracts.envelope import new_event_id

LOGGER = logging.getLogger("console_api.control")

ControlTransport = Callable[[ControlRequest], ControlResponse]


class ControlPlane:
    """Send ControlRequest messages; fall back to a local session store in mock mode."""

    def __init__(
        self,
        endpoint: str,
        *,
        mock: bool,
        transport: ControlTransport | None = None,
        timeout_ms: int = 1500,
    ) -> None:
        self.endpoint = endpoint
        self.mock = mock
        self.timeout_ms = timeout_ms
        self._transport = transport
        self._lock = threading.Lock()
        self.last_request: ControlRequest | None = None
        self._sessions: dict[str, dict[str, Any]] = {}
        self._sock: zmq.Socket | None = None
        if transport is None:
            self._connect()

    def _connect(self) -> None:
        try:
            ctx = zmq.Context.instance()
            sock = ctx.socket(zmq.REQ)
            sock.setsockopt(zmq.LINGER, 0)
            sock.setsockopt(zmq.RCVTIMEO, self.timeout_ms)
            sock.setsockopt(zmq.SNDTIMEO, self.timeout_ms)
            sock.connect(self.endpoint)
            self._sock = sock
        except Exception:
            LOGGER.warning("control plane socket unavailable", exc_info=True)
            self._sock = None

    def close(self) -> None:
        if self._sock is not None:
            self._sock.close(linger=0)
            self._sock = None

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
        self.last_request = req
        if self._transport is not None:
            return self._transport(req)
        try:
            return self._zmq_request(req)
        except Exception as exc:
            if self.mock:
                LOGGER.info("control plane falling back to mock: %s", exc)
                return self.local_handle(req)
            raise

    def _zmq_request(self, req: ControlRequest) -> ControlResponse:
        with self._lock:
            if self._sock is None:
                raise RuntimeError("control socket is not connected")
            self._sock.send_json(req.model_dump(mode="json"))
            raw = self._sock.recv_json()
        if not isinstance(raw, dict):
            raise RuntimeError("control response was not an object")
        return ControlResponse.model_validate(raw)

    def local_handle(self, req: ControlRequest) -> ControlResponse:
        method = str(req.method)
        payload = dict(req.payload)
        if method == ControlMethod.SESSION_START:
            session_id = req.session_id or f"session_{new_event_id()[:16]}"
            record = {
                "session_id": session_id,
                "state": SessionState.RECORDING,
                "user_id": payload.get("user_id", "primary"),
                "record_audio": bool(payload.get("record_audio", False)),
                "record_video": bool(payload.get("record_video", False)),
                "consent": bool(payload.get("consent", True)),
                "trials": [],
            }
            self._sessions[session_id] = record
            return ControlResponse(
                ok=True,
                request_id=req.request_id,
                method=method,
                session_id=session_id,
                state=SessionState.RECORDING,
                payload={"user_id": record["user_id"]},
            )
        if method == ControlMethod.SESSION_STOP:
            session_id = req.session_id
            if not session_id or session_id not in self._sessions:
                return ControlResponse(
                    ok=False,
                    request_id=req.request_id,
                    method=method,
                    session_id=session_id,
                    state=SessionState.NO_SESSION,
                    error="unknown session",
                )
            self._sessions[session_id]["state"] = SessionState.FINALIZED
            return ControlResponse(
                ok=True,
                request_id=req.request_id,
                method=method,
                session_id=session_id,
                state=SessionState.FINALIZED,
            )
        if method == ControlMethod.TRIAL_START:
            session_id = req.session_id
            if not session_id or session_id not in self._sessions:
                return ControlResponse(
                    ok=False,
                    request_id=req.request_id,
                    method=method,
                    session_id=session_id,
                    state=SessionState.NO_SESSION,
                    error="unknown session",
                )
            trial_id = req.trial_id or f"trial_{new_event_id()[:16]}"
            trial = {
                "trial_id": trial_id,
                "instruction": payload.get("instruction"),
                "ground_truth_action": payload.get("ground_truth_action"),
                "ground_truth_target": payload.get("ground_truth_target"),
                "ambiguous": bool(payload.get("ambiguous", False)),
                "state": "STARTED",
            }
            self._sessions[session_id]["trials"].append(trial)
            return ControlResponse(
                ok=True,
                request_id=req.request_id,
                method=method,
                session_id=session_id,
                trial_id=trial_id,
                state=SessionState.RECORDING,
                payload=trial,
            )
        if method in {ControlMethod.TRIAL_COMPLETE, ControlMethod.TRIAL_ABORT}:
            session_id = req.session_id
            state = (
                SessionState.RECORDING
                if session_id and session_id in self._sessions
                else SessionState.NO_SESSION
            )
            return ControlResponse(
                ok=bool(session_id and session_id in self._sessions),
                request_id=req.request_id,
                method=method,
                session_id=session_id,
                trial_id=req.trial_id,
                state=state,
                error=None if session_id in self._sessions else "unknown session",
            )
        return ControlResponse(
            ok=False,
            request_id=req.request_id,
            method=method,
            session_id=req.session_id,
            trial_id=req.trial_id,
            state=SessionState.FAILED,
            error=f"unsupported method {method}",
        )
