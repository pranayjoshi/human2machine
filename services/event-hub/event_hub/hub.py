from __future__ import annotations

import json
import time
from collections import OrderedDict, deque
from collections.abc import Callable
from typing import Any

import structlog
from intent_contracts.control import (
    ControlRequest,
    ControlResponse,
    SessionStartRequest,
    TrialStartRequest,
)
from intent_contracts.enums import (
    PRODUCER_VERSION,
    SCHEMA_VERSION,
    ControlMethod,
    EventType,
    SessionState,
)
from intent_contracts.envelope import EventEnvelope, new_event_id, now_monotonic_ns
from intent_contracts.validation import parse_unnormalized_event
from intent_runtime.heartbeat import heartbeat_event
from pydantic import ValidationError

from event_hub.metrics import HubMetrics, SequenceAnomaly
from event_hub.session import SessionController

RECORDABLE_ADAPTER_TYPES = frozenset(
    {
        EventType.BIOSIGNAL_CHUNK.value,
        EventType.MOTION_CHUNK.value,
        EventType.MODALITY_FEATURE.value,
        EventType.VISION_OBJECTS.value,
        EventType.VISION_HANDS.value,
        EventType.VISION_HEAD_DIRECTION.value,
        EventType.AUDIO_INTENT_CANDIDATE.value,
    }
)

PublishHook = Callable[[EventEnvelope], None]


def encode_pub_message(event: EventEnvelope) -> bytes:
    """PUB frame: `event_type + b' ' + json_bytes` for optional SUB prefix filters."""
    body = event.model_dump_json().encode()
    return str(event.event_type).encode() + b" " + body


class EventHub:
    """Validate, dedupe, time-normalize, and attach session IDs. No intent inference."""

    def __init__(
        self,
        *,
        config: dict[str, Any] | None = None,
        max_event_bytes: int = 262144,
        retain_published: bool = False,
        on_publish: PublishHook | None = None,
        dedupe_maxlen: int = 65536,
        source: str = "event-hub",
    ) -> None:
        self.config = config or {}
        self.max_event_bytes = max_event_bytes
        self.retain_published = retain_published
        self._on_publish = on_publish
        self.source = source
        self.metrics = HubMetrics()
        self.session = SessionController(config=self.config)
        self.published: list[EventEnvelope] = []
        self.sequence_anomalies: deque[SequenceAnomaly] = deque(maxlen=256)
        self._seen_ids: OrderedDict[str, None] = OrderedDict()
        self._dedupe_maxlen = dedupe_maxlen
        self._last_sequence: dict[str, int] = {}
        self._last_normalized: dict[str, int] = {}
        self._hub_sequence = 0
        self._hub_start_monotonic_ns = time.monotonic_ns()
        self._started_at_monotonic = time.monotonic()
        self._last_adapter_monotonic_ns: int | None = None
        self._log = structlog.get_logger("event-hub")

    def ingest_raw(self, raw: bytes) -> EventEnvelope | None:
        if len(raw) > self.max_event_bytes:
            self.metrics.invalid += 1
            self.metrics.oversized += 1
            self._log.warning(
                "event_too_large",
                size=len(raw),
                max_event_bytes=self.max_event_bytes,
            )
            return None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            self.metrics.invalid += 1
            self._log.warning("invalid_json", error=str(exc))
            return None
        if not isinstance(data, dict):
            self.metrics.invalid += 1
            self._log.warning("invalid_event", error="payload is not an object")
            return None
        return self.ingest(data)

    def ingest(self, data: dict[str, Any]) -> EventEnvelope | None:
        payload = dict(data)
        if payload.get("received_monotonic_ns") is None:
            payload["received_monotonic_ns"] = time.monotonic_ns()
        try:
            envelope = parse_unnormalized_event(payload)
        except (ValidationError, ValueError, TypeError) as exc:
            self.metrics.invalid += 1
            self._log.warning(
                "invalid_event",
                error=str(exc),
                event_type=payload.get("event_type"),
                source=payload.get("source"),
            )
            return None
        except Exception as exc:  # noqa: BLE001 — never crash the ingest loop
            self.metrics.invalid += 1
            self._log.warning("invalid_event", error=str(exc), error_type=type(exc).__name__)
            return None
        return self._accept(envelope, from_adapter=True)

    def inject_fixture_record(self, data: dict[str, Any]) -> EventEnvelope | None:
        """Historical JSONL may include hub fields; strip them before adapter validation."""
        payload = dict(data)
        payload.pop("normalized_time_ns", None)
        return self.ingest(payload)

    def inject_fixture_file(self, path: str) -> list[EventEnvelope]:
        published: list[EventEnvelope] = []
        with open(path) as handle:
            for line_no, line in enumerate(handle, start=1):
                text = line.strip()
                if not text or text.startswith("#"):
                    continue
                try:
                    record = json.loads(text)
                except json.JSONDecodeError as exc:
                    self.metrics.invalid += 1
                    self._log.warning("fixture_invalid_json", line=line_no, error=str(exc))
                    continue
                if not isinstance(record, dict):
                    self.metrics.invalid += 1
                    continue
                event = self.inject_fixture_record(record)
                if event is not None:
                    published.append(event)
        self._log.info("fixture_injected", path=path, published=len(published))
        return published

    def handle_control(self, request: ControlRequest) -> ControlResponse:
        method = str(request.method)
        try:
            if method == ControlMethod.SESSION_START:
                return self._session_start(request)
            if method == ControlMethod.SESSION_STOP:
                return self._session_stop(request)
            if method == ControlMethod.TRIAL_START:
                return self._trial_start(request)
            if method == ControlMethod.TRIAL_COMPLETE:
                return self._trial_complete(request)
            if method == ControlMethod.TRIAL_ABORT:
                return self._trial_abort(request)
        except Exception as exc:  # noqa: BLE001
            self._log.exception("control_failed", method=method)
            return self.session.control_error(request, str(exc))
        return self.session.control_error(request, f"unknown control method: {method}")

    def handle_control_raw(self, raw: bytes) -> bytes:
        request_id = ""
        method: str = ""
        try:
            if len(raw) > self.max_event_bytes:
                raise ValueError("control request too large")
            data = json.loads(raw)
            if isinstance(data, dict):
                request_id = str(data.get("request_id") or "")
                method = str(data.get("method") or "")
            request = ControlRequest.model_validate(data)
        except Exception as exc:  # noqa: BLE001
            response = ControlResponse(
                ok=False,
                request_id=request_id,
                method=method,
                session_id=self.session.session_id,
                trial_id=self.session.trial_id,
                state=self.session.state,
                error=str(exc),
            )
            return response.model_dump_json().encode()
        return self.handle_control(request).model_dump_json().encode()

    def emit_heartbeat(self) -> EventEnvelope | None:
        last_age_ms = None
        if self._last_adapter_monotonic_ns is not None:
            last_age_ms = (time.monotonic_ns() - self._last_adapter_monotonic_ns) / 1_000_000
        event = heartbeat_event(
            self.source,
            uptime_seconds=time.monotonic() - self._started_at_monotonic,
            last_data_age_ms=last_age_ms,
            error_count=self.metrics.error_count,
            sequence=self._next_hub_sequence(),
            session_id=self.session.session_id if self.session.recording else None,
        )
        return self._accept(event, from_adapter=False)

    def fail_active_session(self, reason: str = "hub_shutdown") -> EventEnvelope | None:
        """End an in-flight session. Restart never pretends the timeline continues."""
        if not self.session.fail(reason):
            return None
        event = self._hub_lifecycle_event(EventType.SESSION_FAILED, reason=reason)
        self._reset_session_clock()
        self._log.warning("session_failed", session_id=event.session_id, reason=reason)
        return self._emit_internal(event)

    def _session_start(self, request: ControlRequest) -> ControlResponse:
        start_req = SessionStartRequest.model_validate(request.payload)
        ok, error = self.session.start(start_req)
        if not ok:
            return self.session.control_error(request, error or "session.start failed")
        self._last_normalized.clear()
        event = self._hub_lifecycle_event(EventType.SESSION_STARTED)
        self._emit_internal(event)
        self._log.info(
            "session_started",
            session_id=self.session.session_id,
            config_hash=self.session.config_digest,
        )
        return self.session.control_ok(
            request,
            {
                "session_wall_time_ns": self.session.session_wall_time_ns,
                "session_monotonic_time_ns": self.session.session_monotonic_time_ns,
                "config_hash": self.session.config_digest,
                "commit": self.session.commit,
            },
        )

    def _session_stop(self, request: ControlRequest) -> ControlResponse:
        session_id = self.session.session_id
        ok, error = self.session.stop(request.session_id)
        if not ok:
            return self.session.control_error(request, error or "session.stop failed")
        event = self._hub_lifecycle_event(
            EventType.SESSION_STOPPED,
            session_id=session_id,
            reason="session.stop",
        )
        self._emit_internal(event)
        self._reset_session_clock()
        self._log.info("session_stopped", session_id=session_id)
        return self.session.control_ok(request)

    def _trial_start(self, request: ControlRequest) -> ControlResponse:
        trial_req = TrialStartRequest.model_validate(request.payload)
        ok, error = self.session.start_trial(trial_req)
        if not ok:
            return self.session.control_error(request, error or "trial.start failed")
        payload = trial_req.model_dump(mode="json")
        event = self._hub_lifecycle_event(EventType.TRIAL_STARTED, trial_payload=payload)
        self._emit_internal(event)
        self._log.info(
            "trial_started",
            session_id=self.session.session_id,
            trial_id=self.session.trial_id,
        )
        return self.session.control_ok(request)

    def _trial_complete(self, request: ControlRequest) -> ControlResponse:
        trial_id = self.session.trial_id
        ok, error = self.session.complete_trial(request.trial_id)
        if not ok:
            return self.session.control_error(request, error or "trial.complete failed")
        extra = dict(request.payload)
        extra.setdefault("instruction", self.session.last_trial_instruction)
        event = self._hub_lifecycle_event(
            EventType.TRIAL_COMPLETED,
            trial_id=trial_id,
            trial_payload=extra,
        )
        self.session.clear_trial()
        self._emit_internal(event)
        return self.session.control_ok(request)

    def _trial_abort(self, request: ControlRequest) -> ControlResponse:
        trial_id = self.session.trial_id
        ok, error = self.session.abort_trial(request.trial_id)
        if not ok:
            return self.session.control_error(request, error or "trial.abort failed")
        extra = dict(request.payload)
        extra.setdefault("instruction", self.session.last_trial_instruction)
        extra.setdefault("failure_reason", extra.get("reason") or "aborted")
        event = self._hub_lifecycle_event(
            EventType.TRIAL_ABORTED,
            trial_id=trial_id,
            trial_payload=extra,
        )
        self.session.clear_trial()
        self._emit_internal(event)
        return self.session.control_ok(request)

    def _accept(self, envelope: EventEnvelope, *, from_adapter: bool) -> EventEnvelope | None:
        if from_adapter:
            self._last_adapter_monotonic_ns = envelope.received_monotonic_ns
        if self._is_duplicate(envelope.event_id):
            self.metrics.duplicate += 1
            self._log.info(
                "duplicate_event",
                event_id=envelope.event_id,
                source=envelope.source,
                event_type=str(envelope.event_type),
            )
            return None
        self._note_sequence(envelope)
        normalized = self._normalize(envelope)
        return self._dispatch(normalized)

    def _emit_internal(self, envelope: EventEnvelope) -> EventEnvelope:
        self._is_duplicate(envelope.event_id)
        self._note_sequence(envelope)
        if envelope.normalized_time_ns is not None:
            last = self._last_normalized.get(envelope.source)
            value = envelope.normalized_time_ns
            if last is not None and value < last:
                envelope = envelope.model_copy(update={"normalized_time_ns": last})
                value = last
            self._last_normalized[envelope.source] = value
        return self._dispatch(envelope)

    def _dispatch(self, envelope: EventEnvelope) -> EventEnvelope:
        self.metrics.published += 1
        if self.retain_published:
            self.published.append(envelope)
        if self._on_publish is not None:
            self._on_publish(envelope)
        return envelope

    def _normalize(self, envelope: EventEnvelope) -> EventEnvelope:
        received = envelope.received_monotonic_ns
        if self.session.recording and self.session.session_monotonic_time_ns is not None:
            computed = received - self.session.session_monotonic_time_ns
        else:
            computed = received - self._hub_start_monotonic_ns
        last = self._last_normalized.get(envelope.source)
        if last is not None and computed < last:
            self.metrics.clock_jumps += 1
            self._log.warning(
                "normalized_time_regression",
                source=envelope.source,
                previous=last,
                computed=computed,
                event_id=envelope.event_id,
            )
            computed = last
        self._last_normalized[envelope.source] = computed
        updates: dict[str, Any] = {"normalized_time_ns": computed}
        if self.session.recording:
            event_type = str(envelope.event_type)
            if event_type in RECORDABLE_ADAPTER_TYPES:
                updates["session_id"] = self.session.session_id
                updates["trial_id"] = self.session.trial_id
            else:
                if envelope.session_id is None:
                    updates["session_id"] = self.session.session_id
                if envelope.trial_id is None:
                    updates["trial_id"] = self.session.trial_id
        return envelope.model_copy(update=updates)

    def _note_sequence(self, envelope: EventEnvelope) -> None:
        previous = self._last_sequence.get(envelope.source)
        self._last_sequence[envelope.source] = envelope.sequence
        if previous is None:
            return
        if envelope.sequence == previous + 1:
            return
        if envelope.sequence > previous + 1:
            kind = "gap"
            self.metrics.sequence_gaps += 1
        else:
            kind = "regression"
            self.metrics.sequence_regressions += 1
        anomaly = SequenceAnomaly(
            source=envelope.source,
            previous=previous,
            sequence=envelope.sequence,
            kind=kind,
            event_id=envelope.event_id,
        )
        self.sequence_anomalies.append(anomaly)
        self._log.warning(
            "sequence_anomaly",
            source=envelope.source,
            previous=previous,
            sequence=envelope.sequence,
            kind=kind,
            event_id=envelope.event_id,
            sequence_gaps=self.metrics.sequence_gaps,
            sequence_regressions=self.metrics.sequence_regressions,
        )

    def _is_duplicate(self, event_id: str) -> bool:
        if event_id in self._seen_ids:
            return True
        self._seen_ids[event_id] = None
        if len(self._seen_ids) > self._dedupe_maxlen:
            self._seen_ids.popitem(last=False)
        return False

    def _next_hub_sequence(self) -> int:
        seq = self._hub_sequence
        self._hub_sequence += 1
        return seq

    def _reset_session_clock(self) -> None:
        self._last_normalized.clear()

    def _hub_lifecycle_event(
        self,
        event_type: EventType,
        *,
        session_id: str | None = None,
        trial_id: str | None = None,
        reason: str | None = None,
        trial_payload: dict[str, Any] | None = None,
    ) -> EventEnvelope:
        received = now_monotonic_ns()
        sid = session_id if session_id is not None else self.session.session_id
        tid = trial_id if trial_id is not None else self.session.trial_id
        session_types = {
            EventType.SESSION_STARTED,
            EventType.SESSION_STOPPED,
            EventType.SESSION_FAILED,
        }
        if event_type in session_types:
            payload = self.session.lifecycle_payload(reason=reason)
            if event_type == EventType.SESSION_STARTED:
                payload["state"] = str(SessionState.RECORDING)
            elif event_type == EventType.SESSION_STOPPED:
                payload["state"] = str(SessionState.FINALIZED)
            else:
                payload["state"] = str(SessionState.FAILED)
        else:
            payload = trial_payload or {}
        session_anchor = self.session.session_monotonic_time_ns
        if session_anchor is not None and event_type == EventType.SESSION_STARTED:
            normalized = 0
        elif session_anchor is not None:
            normalized = max(0, received - session_anchor)
        else:
            normalized = received - self._hub_start_monotonic_ns
        return EventEnvelope(
            schema_version=SCHEMA_VERSION,
            event_id=new_event_id(),
            event_type=event_type,
            source=self.source,
            modality=None,
            session_id=sid,
            trial_id=tid,
            sequence=self._next_hub_sequence(),
            source_time_ns=None,
            received_monotonic_ns=received,
            normalized_time_ns=normalized,
            quality=1.0,
            producer_version=PRODUCER_VERSION,
            payload=payload,
        )
