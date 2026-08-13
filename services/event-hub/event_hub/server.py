from __future__ import annotations

import asyncio
import signal
from collections.abc import Callable
from pathlib import Path
from typing import Any

import structlog
import zmq
import zmq.asyncio
from intent_contracts.control import ControlResponse

from event_hub.hub import EventHub, encode_pub_message
from event_hub.queues import PublishQueue

DEFAULT_PULL = "tcp://127.0.0.1:5555"
DEFAULT_PUB = "tcp://127.0.0.1:5556"
DEFAULT_REP = "tcp://127.0.0.1:5558"


class EventHubServer:
    """Localhost ZeroMQ event hub: PULL 5555, PUB 5556, REP 5558. Never binds 5557."""

    def __init__(
        self,
        hub: EventHub,
        *,
        pull_endpoint: str = DEFAULT_PULL,
        pub_endpoint: str = DEFAULT_PUB,
        rep_endpoint: str = DEFAULT_REP,
        heartbeat_seconds: float = 2.0,
        queue_depth: int = 512,
        fixture_path: Path | None = None,
    ) -> None:
        self.hub = hub
        self.pull_endpoint = pull_endpoint
        self.pub_endpoint = pub_endpoint
        self.rep_endpoint = rep_endpoint
        self.heartbeat_seconds = heartbeat_seconds
        self.fixture_path = fixture_path
        self.queue = PublishQueue(max_per_producer=queue_depth)
        self._log = structlog.get_logger("event-hub")
        self._ctx: zmq.asyncio.Context | None = None
        self._pull: zmq.asyncio.Socket | None = None
        self._pub: zmq.asyncio.Socket | None = None
        self._rep: zmq.asyncio.Socket | None = None
        self._stop = asyncio.Event()
        hub._on_publish = self._enqueue

    def _enqueue(self, event: Any) -> None:
        dropped = self.queue.put(event)
        if dropped:
            self.hub.metrics.drops += dropped
            self._log.warning(
                "queue_drop",
                source=getattr(event, "source", None),
                event_type=str(getattr(event, "event_type", "")),
                dropped=dropped,
                drops=self.hub.metrics.drops,
                queue_depth=self.queue.qsize(),
            )

    def request_stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        self._ctx = zmq.asyncio.Context.instance()
        pull = self._ctx.socket(zmq.PULL)
        pull.setsockopt(zmq.LINGER, 0)
        pull.setsockopt(zmq.RCVHWM, 2000)
        pull.bind(self.pull_endpoint)
        self._pull = pull

        pub = self._ctx.socket(zmq.PUB)
        pub.setsockopt(zmq.LINGER, 0)
        pub.setsockopt(zmq.SNDHWM, 10000)
        pub.bind(self.pub_endpoint)
        self._pub = pub

        rep = self._ctx.socket(zmq.REP)
        rep.setsockopt(zmq.LINGER, 0)
        rep.bind(self.rep_endpoint)
        self._rep = rep

        self._log.info(
            "event_hub_bound",
            pull=self.pull_endpoint,
            pub=self.pub_endpoint,
            rep=self.rep_endpoint,
            max_event_bytes=self.hub.max_event_bytes,
        )

        tasks = [
            asyncio.create_task(self._ingest_loop(), name="event-hub-ingest"),
            asyncio.create_task(self._publish_loop(), name="event-hub-publish"),
            asyncio.create_task(self._control_loop(), name="event-hub-control"),
            asyncio.create_task(self._heartbeat_loop(), name="event-hub-heartbeat"),
        ]
        if self.fixture_path is not None:
            tasks.append(asyncio.create_task(self._inject_fixture(), name="event-hub-fixture"))
        try:
            await self._stop.wait()
        finally:
            self.hub.fail_active_session("hub_shutdown")
            self._log.info("hub_metrics", **self.hub.metrics.as_dict())
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self._close_sockets()

    async def _inject_fixture(self) -> None:
        await asyncio.sleep(0.15)
        assert self.fixture_path is not None
        self.hub.inject_fixture_file(str(self.fixture_path))

    async def _ingest_loop(self) -> None:
        assert self._pull is not None
        while not self._stop.is_set():
            try:
                raw = await self._pull.recv()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                self._log.warning("pull_recv_failed", error=str(exc))
                continue
            try:
                self.hub.ingest_raw(raw)
            except Exception as exc:  # noqa: BLE001
                self.hub.metrics.invalid += 1
                self._log.warning("ingest_failed", error=str(exc))

    async def _publish_loop(self) -> None:
        assert self._pub is not None
        while not self._stop.is_set():
            try:
                event = await self.queue.get()
                await self._pub.send(encode_pub_message(event))
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                self._log.warning("publish_failed", error=str(exc))

    async def _control_loop(self) -> None:
        assert self._rep is not None
        while not self._stop.is_set():
            try:
                raw = await self._rep.recv()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                self._log.warning("control_recv_failed", error=str(exc))
                continue
            try:
                response = self.hub.handle_control_raw(raw)
            except Exception as exc:  # noqa: BLE001
                self._log.exception("control_handler_failed")
                response = (
                    ControlResponse(
                        ok=False,
                        request_id="",
                        method="",
                        session_id=self.hub.session.session_id,
                        trial_id=self.hub.session.trial_id,
                        state=self.hub.session.state,
                        error=str(exc),
                    )
                    .model_dump_json()
                    .encode()
                )
            try:
                await self._rep.send(response)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                self._log.warning("control_send_failed", error=str(exc))

    async def _heartbeat_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.hub.emit_heartbeat()
                self._log.info(
                    "hub_metrics",
                    **self.hub.metrics.as_dict(),
                    session_state=str(self.hub.session.state),
                )
                await asyncio.wait_for(self._stop.wait(), timeout=self.heartbeat_seconds)
            except TimeoutError:
                continue
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                self._log.warning("heartbeat_failed", error=str(exc))
                await asyncio.sleep(self.heartbeat_seconds)

    def _close_sockets(self) -> None:
        for sock in (self._pull, self._pub, self._rep):
            if sock is not None:
                sock.close(linger=0)
        self._pull = None
        self._pub = None
        self._rep = None


def install_signal_handlers(stop: Callable[[], None]) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop)
        except (NotImplementedError, RuntimeError):
            signal.signal(sig, lambda _signum, _frame: stop())
