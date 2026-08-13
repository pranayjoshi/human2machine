from __future__ import annotations

import json
from typing import Any

import zmq
import zmq.asyncio

from intent_contracts.envelope import EventEnvelope


class AdapterPush:
    """Adapters PUSH unnormalized events to the hub on port 5555."""

    def __init__(self, endpoint: str = "tcp://127.0.0.1:5555") -> None:
        self.endpoint = endpoint
        self._ctx = zmq.Context.instance()
        self._sock = self._ctx.socket(zmq.PUSH)
        self._sock.setsockopt(zmq.LINGER, 0)
        self._sock.setsockopt(zmq.SNDHWM, 1000)
        self._sock.connect(endpoint)

    def send_event(self, event: EventEnvelope | dict[str, Any]) -> None:
        payload = event.to_unnormalized_dict() if isinstance(event, EventEnvelope) else event
        payload.pop("normalized_time_ns", None)
        self._sock.send_json(payload)

    def close(self) -> None:
        self._sock.close(linger=0)


class NormalizedSubscriber:
    def __init__(
        self,
        endpoint: str = "tcp://127.0.0.1:5556",
        topics: list[bytes] | None = None,
    ) -> None:
        self.endpoint = endpoint
        self._ctx = zmq.Context.instance()
        self._sock = self._ctx.socket(zmq.SUB)
        self._sock.setsockopt(zmq.LINGER, 0)
        self._sock.setsockopt(zmq.RCVHWM, 10000)
        if topics:
            for topic in topics:
                self._sock.setsockopt(zmq.SUBSCRIBE, topic)
        else:
            self._sock.setsockopt(zmq.SUBSCRIBE, b"")
        self._sock.connect(endpoint)

    def recv_event(self, timeout_ms: int | None = None) -> dict[str, Any] | None:
        if timeout_ms is not None:
            if not self._sock.poll(timeout_ms):
                return None
        raw = self._sock.recv()
        if b" " in raw[:80]:
            _, body = raw.split(b" ", 1)
        else:
            body = raw
        return json.loads(body)

    def close(self) -> None:
        self._sock.close(linger=0)


class CommandPush:
    def __init__(self, endpoint: str = "tcp://127.0.0.1:5557") -> None:
        self.endpoint = endpoint
        self._ctx = zmq.Context.instance()
        self._sock = self._ctx.socket(zmq.PUSH)
        self._sock.setsockopt(zmq.LINGER, 0)
        self._sock.connect(endpoint)

    def send_command(self, command: dict[str, Any]) -> None:
        self._sock.send_json(command)

    def close(self) -> None:
        self._sock.close(linger=0)


class CommandPull:
    def __init__(self, endpoint: str = "tcp://127.0.0.1:5557") -> None:
        self.endpoint = endpoint
        self._ctx = zmq.Context.instance()
        self._sock = self._ctx.socket(zmq.PULL)
        self._sock.setsockopt(zmq.LINGER, 0)
        self._sock.bind(endpoint)

    def recv_command(self, timeout_ms: int | None = None) -> dict[str, Any] | None:
        if timeout_ms is not None:
            if not self._sock.poll(timeout_ms):
                return None
        return self._sock.recv_json()

    def close(self) -> None:
        self._sock.close(linger=0)
