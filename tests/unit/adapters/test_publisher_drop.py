from __future__ import annotations

import zmq
from ganglion_adapter.events import make_event
from ganglion_adapter.publisher import BoundedAdapterPush


class _FullSocket:
    def send_json(self, _payload, flags=0):
        raise zmq.Again()

    def close(self, linger=0):
        return


def test_publisher_drops_when_hub_is_unavailable() -> None:
    push = BoundedAdapterPush.__new__(BoundedAdapterPush)
    push.endpoint = "tcp://127.0.0.1:5555"
    push.dropped_count = 0
    push._sock = _FullSocket()
    event = make_event(
        event_type="device.status",
        sequence=0,
        payload={"status": "healthy", "device_alias": "x"},
    )
    assert push.send_event(event) is False
    assert push.dropped_count == 1
    push.close()
