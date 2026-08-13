from __future__ import annotations

import asyncio
from collections import defaultdict, deque

from intent_contracts.enums import EventType
from intent_contracts.envelope import EventEnvelope

NEVER_DROP_TYPES = frozenset(
    {
        EventType.INTENT_DECISION.value,
        EventType.INTENT_CONFLICT.value,
        EventType.INTENT_TIMEOUT.value,
        EventType.SAFETY_DECISION.value,
        EventType.ACTION_OUTCOME.value,
        EventType.SESSION_STARTED.value,
        EventType.SESSION_STOPPED.value,
        EventType.SESSION_FAILED.value,
        EventType.TRIAL_STARTED.value,
        EventType.TRIAL_INSTRUCTION.value,
        EventType.TRIAL_LABEL.value,
        EventType.TRIAL_COMPLETED.value,
        EventType.TRIAL_ABORTED.value,
    }
)


def is_protected(event: EventEnvelope) -> bool:
    return str(event.event_type) in NEVER_DROP_TYPES


class PublishQueue:
    """Bounded per-producer queues. Drops old high-rate preview/biosignal first."""

    def __init__(self, max_per_producer: int = 512) -> None:
        self.max_per_producer = max_per_producer
        self._queues: dict[str, deque[EventEnvelope]] = defaultdict(deque)
        self._cycle: deque[str] = deque()
        self._wakeup = asyncio.Event()
        self.drops = 0

    def put(self, event: EventEnvelope) -> int:
        """Enqueue ``event``. Returns the number of events dropped to make room."""
        q = self._queues[event.source]
        was_empty = not q
        dropped = 0
        if len(q) >= self.max_per_producer:
            dropped = self._make_room(q, event)
            if dropped < 0:
                self.drops += 1
                return 1
        q.append(event)
        if was_empty:
            self._cycle.append(event.source)
        self._wakeup.set()
        self.drops += dropped
        return dropped

    def _make_room(self, q: deque[EventEnvelope], incoming: EventEnvelope) -> int:
        """Return drops performed, or -1 if incoming itself should be dropped."""
        if is_protected(incoming):
            if self._evict_droppable(q):
                return 1
            return 0
        if q and not is_protected(q[0]):
            q.popleft()
            return 1
        if self._evict_droppable(q):
            return 1
        return -1

    def _evict_droppable(self, q: deque[EventEnvelope]) -> bool:
        kept: deque[EventEnvelope] = deque()
        evicted = False
        for item in q:
            if not evicted and not is_protected(item):
                evicted = True
                continue
            kept.append(item)
        if evicted:
            q.clear()
            q.extend(kept)
        return evicted

    def _pop(self) -> EventEnvelope | None:
        for _ in range(len(self._cycle)):
            source = self._cycle.popleft()
            q = self._queues[source]
            if not q:
                continue
            item = q.popleft()
            if q:
                self._cycle.append(source)
            return item
        return None

    async def get(self) -> EventEnvelope:
        while True:
            item = self._pop()
            if item is not None:
                return item
            self._wakeup.clear()
            item = self._pop()
            if item is not None:
                return item
            await self._wakeup.wait()

    def qsize(self) -> int:
        return sum(len(q) for q in self._queues.values())

    def depth_by_source(self) -> dict[str, int]:
        return {source: len(q) for source, q in self._queues.items() if q}
