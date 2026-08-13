"""Subscribe to the normalized bus and persist sessions without blocking ingest."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from session_recorder.constants import HEARTBEAT_SECONDS
from session_recorder.queues import RecorderQueues
from session_recorder.store import SessionStore, is_session_started, is_session_stopped


class SessionRecorder:
    """Non-blocking ingest: queues events, writer thread flushes to disk."""

    def __init__(
        self,
        sessions_dir: Path,
        *,
        config_dir: Path | None = None,
        config: dict[str, Any] | None = None,
        repo_dir: Path | None = None,
        writer_poll_s: float = 0.02,
    ) -> None:
        self.store = SessionStore(
            sessions_dir,
            config_dir=config_dir,
            config=config,
            repo_dir=repo_dir,
        )
        self.queues = RecorderQueues()
        self._writer_poll_s = writer_poll_s
        self._stop = threading.Event()
        self._writer: threading.Thread | None = None
        self._lock = threading.Lock()
        self.last_event_monotonic = time.monotonic()

    def start(self) -> None:
        if self._writer is not None:
            return
        self._stop.clear()
        self._writer = threading.Thread(
            target=self._writer_loop,
            name="session-writer",
            daemon=True,
        )
        self._writer.start()

    def stop(self, *, finalize_open: bool = False) -> None:
        self._stop.set()
        if self._writer is not None:
            self._writer.join(timeout=5.0)
            self._writer = None
        self._drain_all()
        if finalize_open and self.store.session_id and self.store.manifest:
            if self.store.manifest.get("finalization_status") == "PARTIAL":
                self.store.finalize()

    def handle_event(self, event: dict[str, Any]) -> None:
        """Queue events; parquet writes happen on the writer thread.

        Session start writes a PARTIAL manifest immediately. Session stop drains
        and finalizes. Biosignal/motion may be dropped; critical types are not.
        """
        self.last_event_monotonic = time.monotonic()
        if is_session_started(event):
            with self._lock:
                if self.store.active:
                    self._drain_all()
                    self.store.finalize()
                self.store.open_from_started(event)
            return
        if not self.store.session_id:
            return
        if event.get("session_id") not in (None, self.store.session_id):
            return
        self.queues.submit(event)
        if is_session_stopped(event):
            self._wait_for_drain(timeout_s=5.0)
            failed = str(event.get("event_type")) == "session.failed"
            with self._lock:
                self.store.record_drops(self.queues.dropped_low_priority)
                self.store.stop_accepting()
                self._drain_all()
                self.store.finalize(failed=failed)

    def handle_event_sync(self, event: dict[str, Any]) -> None:
        """Test helper: ingest on the calling thread without the writer loop."""
        self.last_event_monotonic = time.monotonic()
        if is_session_started(event):
            if self.store.active:
                self.store.finalize()
            self.store.open_from_started(event)
            return
        if not self.store.active:
            return
        if event.get("session_id") not in (None, self.store.session_id):
            return
        if is_session_stopped(event):
            self.store.ingest(event)
            failed = str(event.get("event_type")) == "session.failed"
            self.store.record_drops(self.queues.dropped_low_priority)
            self.store.finalize(failed=failed)
            return
        self.store.ingest(event)

    def data_age_ms(self) -> float:
        return (time.monotonic() - self.last_event_monotonic) * 1000.0

    def _writer_loop(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                batch = self.queues.drain()
                if batch and not self.store._finalized:
                    for event in batch:
                        self.store.ingest(event)
                    self.store.flush()
            if not batch:
                time.sleep(self._writer_poll_s)

    def _drain_all(self) -> None:
        while True:
            batch = self.queues.drain(max_items=1024)
            if not batch:
                break
            for event in batch:
                self.store.ingest(event)
        self.store.flush()

    def _wait_for_drain(self, timeout_s: float) -> None:
        deadline = time.monotonic() + timeout_s
        while not self.queues.empty() and time.monotonic() < deadline:
            time.sleep(0.01)
        self._drain_all()


def heartbeat_interval(config: dict[str, Any] | None) -> float:
    runtime = (config or {}).get("runtime") or {}
    return float(runtime.get("heartbeat_seconds") or HEARTBEAT_SECONDS)
