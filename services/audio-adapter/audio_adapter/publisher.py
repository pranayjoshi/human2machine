from __future__ import annotations

from typing import Any

import zmq
from intent_contracts.envelope import EventEnvelope

from audio_adapter.capture import strip_raw_audio_payload


def _outgoing_event(event: EventEnvelope | dict[str, Any]) -> dict[str, Any]:
    payload = event.to_unnormalized_dict() if isinstance(event, EventEnvelope) else dict(event)
    payload.pop("normalized_time_ns", None)
    inner = payload.get("payload")
    if isinstance(inner, dict):
        payload["payload"] = strip_raw_audio_payload(inner)
    return payload


class BoundedAdapterPush:
    def __init__(self, endpoint: str = "tcp://127.0.0.1:5555", high_water_mark: int = 256) -> None:
        self.endpoint = endpoint
        self.dropped_count = 0
        self._ctx = zmq.Context.instance()
        self._sock = self._ctx.socket(zmq.PUSH)
        self._sock.setsockopt(zmq.LINGER, 0)
        self._sock.setsockopt(zmq.SNDHWM, high_water_mark)
        self._sock.connect(endpoint)

    def send_event(self, event: EventEnvelope | dict[str, Any]) -> bool:
        payload = _outgoing_event(event)
        try:
            self._sock.send_json(payload, flags=zmq.DONTWAIT)
            return True
        except zmq.Again:
            self.dropped_count += 1
            return False
        except zmq.ZMQError:
            self.dropped_count += 1
            return False

    def close(self) -> None:
        self._sock.close(linger=0)


class ListSink:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.dropped_count = 0

    def send_event(self, event: EventEnvelope | dict[str, Any]) -> bool:
        self.events.append(_outgoing_event(event))
        return True

    def close(self) -> None:
        return
