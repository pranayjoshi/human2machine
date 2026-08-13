from __future__ import annotations

import time

import pytest
from event_hub.queues import NEVER_DROP_TYPES, PublishQueue
from intent_contracts.enums import EventType
from intent_contracts.envelope import EventEnvelope

from tests.unit.event_hub.helpers import BIOSIGNAL_PAYLOAD, INTENT_PAYLOAD


def _envelope(*, event_type: str, source: str, sequence: int, event_id: str) -> EventEnvelope:
    return EventEnvelope(
        event_id=event_id,
        event_type=event_type,
        source=source,
        sequence=sequence,
        received_monotonic_ns=time.monotonic_ns(),
        normalized_time_ns=sequence,
        payload=INTENT_PAYLOAD if event_type == EventType.INTENT_DECISION else BIOSIGNAL_PAYLOAD,
    )


@pytest.mark.asyncio
async def test_drops_old_biosignal_keeps_intent_decision() -> None:
    queue = PublishQueue(max_per_producer=2)
    source = "fusion-runtime"
    bio_0 = _envelope(event_type="biosignal.chunk", source=source, sequence=0, event_id="q00000001")
    bio_1 = _envelope(event_type="biosignal.chunk", source=source, sequence=1, event_id="q00000002")
    assert queue.put(bio_0) == 0
    assert queue.put(bio_1) == 0
    dropped = queue.put(
        _envelope(
            event_type="intent.decision",
            source=source,
            sequence=2,
            event_id="q00000003",
        )
    )
    assert dropped == 1
    first = await queue.get()
    second = await queue.get()
    types = {str(first.event_type), str(second.event_type)}
    assert EventType.INTENT_DECISION.value in types
    assert EventType.INTENT_DECISION.value in NEVER_DROP_TYPES
    assert queue.drops == 1


@pytest.mark.asyncio
async def test_full_queue_drops_incoming_preview_not_protected() -> None:
    queue = PublishQueue(max_per_producer=1)
    source = "ganglion-emg"
    queue.put(
        _envelope(
            event_type="intent.decision",
            source=source,
            sequence=0,
            event_id="p00000001",
        )
    )
    dropped = queue.put(
        _envelope(event_type="biosignal.chunk", source=source, sequence=1, event_id="p00000002")
    )
    assert dropped == 1
    kept = await queue.get()
    assert str(kept.event_type) == EventType.INTENT_DECISION.value
