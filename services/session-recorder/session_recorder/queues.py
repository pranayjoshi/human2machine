"""Bounded queues that never drop safety/decision/outcome/session markers."""

from __future__ import annotations

import queue
from typing import Any

from session_recorder.constants import (
    BIOSIGNAL_QUEUE_BOUND,
    CRITICAL_EVENT_TYPES,
    DROPPABLE_EVENT_TYPES,
    NORMAL_QUEUE_BOUND,
)


def event_priority(event: dict[str, Any]) -> str:
    event_type = str(event.get("event_type", ""))
    if event_type in CRITICAL_EVENT_TYPES:
        return "critical"
    if event_type in DROPPABLE_EVENT_TYPES:
        return "droppable"
    return "normal"


class RecorderQueues:
    """Critical queue is unbounded; biosignal/motion drops under backpressure."""

    def __init__(
        self,
        *,
        biosignal_bound: int = BIOSIGNAL_QUEUE_BOUND,
        normal_bound: int = NORMAL_QUEUE_BOUND,
    ) -> None:
        self.critical: queue.Queue[dict[str, Any]] = queue.Queue()
        self.normal: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=normal_bound)
        self.droppable: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=biosignal_bound)
        self.dropped_low_priority = 0

    def submit(self, event: dict[str, Any]) -> bool:
        priority = event_priority(event)
        if priority == "critical":
            self.critical.put(event)
            return True
        if priority == "droppable":
            try:
                self.droppable.put_nowait(event)
                return True
            except queue.Full:
                self.dropped_low_priority += 1
                return False
        try:
            self.normal.put_nowait(event)
            return True
        except queue.Full:
            try:
                self.normal.get_nowait()
            except queue.Empty:
                pass
            try:
                self.normal.put_nowait(event)
                return True
            except queue.Full:
                self.dropped_low_priority += 1
                return False

    def drain(self, *, max_items: int = 256) -> list[dict[str, Any]]:
        batch: list[dict[str, Any]] = []
        while len(batch) < max_items:
            taken = self._take_one()
            if taken is None:
                break
            batch.append(taken)
        return batch

    def _take_one(self) -> dict[str, Any] | None:
        for bucket in (self.critical, self.normal, self.droppable):
            try:
                return bucket.get_nowait()
            except queue.Empty:
                continue
        return None

    def empty(self) -> bool:
        return self.critical.empty() and self.normal.empty() and self.droppable.empty()

    def qsize(self) -> int:
        return self.critical.qsize() + self.normal.qsize() + self.droppable.qsize()
