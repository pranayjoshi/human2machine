from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from intent_contracts.enums import PRODUCER_VERSION, SCHEMA_VERSION
from intent_contracts.envelope import EventEnvelope, new_event_id, now_monotonic_ns
from intent_runtime.heartbeat import heartbeat_event as runtime_heartbeat

from audio_adapter.parser import parse_utterance

SOURCE = "audio-adapter"
MODEL_ID = "grammar_v1"


def find_repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in [here, *here.parents]:
        if (parent / "configs" / "local.yaml").exists():
            return parent
    return Path.cwd()


def load_scripted_utterances(path: Path | None = None) -> list[dict[str, Any]]:
    fixture = path or find_repo_root() / "data" / "fixtures" / "audio" / "scripted_utterances.json"
    return json.loads(fixture.read_text())


def make_event(
    *,
    event_type: str,
    sequence: int,
    payload: dict[str, Any],
    modality: str | None = "audio",
    source_time_ns: int | None = None,
    quality: float = 1.0,
) -> EventEnvelope:
    return EventEnvelope(
        schema_version=SCHEMA_VERSION,
        event_id=new_event_id(),
        event_type=event_type,
        source=SOURCE,
        modality=modality,
        session_id=None,
        trial_id=None,
        sequence=sequence,
        source_time_ns=source_time_ns,
        received_monotonic_ns=now_monotonic_ns(),
        quality=quality,
        producer_version=PRODUCER_VERSION,
        payload=payload,
    )


class AudioMockRuntime:
    def __init__(
        self, utterances: list[dict[str, Any]] | None = None, model_id: str = MODEL_ID
    ) -> None:
        self.utterances = utterances if utterances is not None else load_scripted_utterances()
        self.model_id = model_id
        self.sequence = 0
        self._emitted = 0
        self._started = False

    def collect(self) -> list[EventEnvelope]:
        events = [self._device_status("healthy", "mock microphone")]
        for row in self.utterances:
            events.extend(self._events_for_row(row))
        return events

    def events_due(self, elapsed_ms: int) -> list[EventEnvelope]:
        events: list[EventEnvelope] = []
        if not self._started:
            events.append(self._device_status("healthy", "mock microphone"))
            self._started = True
        while (
            self._emitted < len(self.utterances)
            and int(self.utterances[self._emitted]["at_ms"]) <= elapsed_ms
        ):
            events.extend(self._events_for_row(self.utterances[self._emitted]))
            self._emitted += 1
        return events

    def heartbeat(self, uptime_seconds: float, dropped: int) -> EventEnvelope:
        event = runtime_heartbeat(
            SOURCE,
            uptime_seconds=uptime_seconds,
            last_data_age_ms=None,
            error_count=dropped,
            sequence=self._next_seq(),
            status="degraded" if dropped else "healthy",
        )
        return event

    def shutdown(self) -> EventEnvelope:
        return self._device_status("offline", "adapter stopping")

    def _events_for_row(self, row: dict[str, Any]) -> list[EventEnvelope]:
        transcript = str(row["transcript"])
        at_ms = int(row["at_ms"])
        source_time_ns = at_ms * 1_000_000
        asr_conf = row.get("confidence")
        parsed = parse_utterance(transcript, asr_confidence=asr_conf)
        is_final = bool(row.get("is_final", True))
        noise = bool(row.get("noise", False))
        quality = 0.45 if noise else 0.95
        events: list[EventEnvelope] = []
        if is_final:
            partial_text = transcript.split(" ")[0]
            partial = parse_utterance(partial_text, asr_confidence=0.4)
            events.append(
                self._intent_event(
                    transcript=partial_text,
                    parsed=partial,
                    is_final=False,
                    start_ns=source_time_ns,
                    end_ns=source_time_ns + 80_000_000,
                    quality=quality * 0.7,
                )
            )
        events.append(
            self._intent_event(
                transcript=transcript,
                parsed=parsed,
                is_final=is_final,
                start_ns=source_time_ns,
                end_ns=source_time_ns + 350_000_000,
                quality=quality,
            )
        )
        events.append(
            make_event(
                event_type="data.quality",
                sequence=self._next_seq(),
                source_time_ns=source_time_ns,
                quality=quality,
                payload={
                    "score": quality,
                    "components": {"asr": quality, "grammar": parsed.grammar_match},
                    "flags": ["noise"] if noise else [],
                },
            )
        )
        return events

    def _intent_event(
        self, transcript, parsed, is_final, start_ns, end_ns, quality
    ) -> EventEnvelope:
        return make_event(
            event_type="audio.intent_candidate",
            sequence=self._next_seq(),
            source_time_ns=end_ns,
            quality=quality,
            payload={
                "transcript": transcript,
                "is_final": is_final,
                "action": parsed.action,
                "target_reference": parsed.target_reference,
                "target_object_id": parsed.target_object_id,
                "confidence": parsed.confidence if is_final else min(parsed.confidence, 0.4),
                "utterance_start_ns": start_ns,
                "utterance_end_ns": end_ns,
                "model_id": self.model_id,
            },
        )

    def _device_status(self, status: str, detail: str) -> EventEnvelope:
        return make_event(
            event_type="device.status",
            sequence=self._next_seq(),
            modality="audio",
            payload={
                "status": status,
                "device_alias": "audio-mock",
                "detail": detail,
                "metadata": {"capture": "fixture"},
            },
        )

    def _next_seq(self) -> int:
        value = self.sequence
        self.sequence += 1
        return value
