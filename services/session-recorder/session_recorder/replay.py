"""Replay recorded sessions onto the event bus.

Normalized historical events are re-issued with a new replay ``session_id``.
Original identifiers are preserved as ``original_event_id`` / ``original_session_id``
in payload metadata.

Publishing uses PUSH to port 5555 (adapter ingest). The event hub is the sole
binder of the normalized PUB socket on 5556; replay therefore injects events so
the hub can re-publish them. Adapter ingest omits top-level ``normalized_time_ns``;
the original value is kept as ``original_normalized_time_ns`` in the payload.
Eval mode skips sleeps and yields in ``normalized_time_ns`` order.
"""

from __future__ import annotations

import argparse
import time
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from intent_contracts.envelope import new_event_id
from intent_runtime.config import load_stacked_config

from session_recorder.constants import ADAPTER_PUSH
from session_recorder.parquet_io import load_biosignal_chunks, load_events_parquet, reattach_samples
from session_recorder.paths import SessionPaths, resolve_session_dir

REPLAY_MODES = ("realtime", "accelerated", "step", "eval")


def load_session_events(session_dir: Path) -> list[dict[str, Any]]:
    paths = SessionPaths(session_dir)
    events = load_events_parquet(paths.normalized)
    chunks = load_biosignal_chunks(paths.biosignal_chunks)
    restored: list[dict[str, Any]] = []
    for event in events:
        event_id = str(event.get("event_id") or "")
        restored.append(reattach_samples(event, chunks.get(event_id)))
    restored.sort(
        key=lambda item: (
            item.get("normalized_time_ns") is None,
            item.get("normalized_time_ns") or 0,
        )
    )
    return restored


def prepare_replay_event(
    event: dict[str, Any],
    *,
    replay_session_id: str,
) -> dict[str, Any]:
    payload = dict(event.get("payload") or {})
    payload.setdefault("original_event_id", event.get("event_id"))
    payload.setdefault("original_session_id", event.get("session_id"))
    if event.get("normalized_time_ns") is not None:
        payload.setdefault("original_normalized_time_ns", event.get("normalized_time_ns"))
    replayed = dict(event)
    replayed["event_id"] = new_event_id()
    replayed["session_id"] = replay_session_id
    replayed["payload"] = payload
    return replayed


def to_adapter_event(event: dict[str, Any]) -> dict[str, Any]:
    data = dict(event)
    data.pop("normalized_time_ns", None)
    return data


def should_exclude(event: dict[str, Any], exclude_modalities: set[str]) -> bool:
    if not exclude_modalities:
        return False
    modality = event.get("modality")
    return isinstance(modality, str) and modality.lower() in exclude_modalities


def iter_replay_events(
    session_dir: Path,
    *,
    mode: str = "eval",
    factor: float = 10.0,
    exclude_modalities: list[str] | None = None,
    replay_session_id: str | None = None,
    step_wait: Callable[[], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> Iterator[dict[str, Any]]:
    if mode not in REPLAY_MODES:
        raise ValueError(f"unsupported replay mode: {mode}")
    excluded = {item.strip().lower() for item in (exclude_modalities or []) if item.strip()}
    replay_session_id = replay_session_id or f"replay_{uuid.uuid4().hex[:12]}"
    events = [
        event for event in load_session_events(session_dir) if not should_exclude(event, excluded)
    ]
    previous_ns: int | None = None
    for event in events:
        current_ns = event.get("normalized_time_ns")
        if mode == "step":
            if step_wait is None:
                input("Press Enter for next event...")
            else:
                step_wait()
        elif (
            mode in {"realtime", "accelerated"}
            and current_ns is not None
            and previous_ns is not None
        ):
            delta_s = max(0.0, (int(current_ns) - int(previous_ns)) / 1_000_000_000)
            if mode == "accelerated":
                delta_s /= max(factor, 1e-9)
            if delta_s > 0:
                sleep(delta_s)
        if current_ns is not None:
            previous_ns = int(current_ns)
        yield prepare_replay_event(event, replay_session_id=replay_session_id)


def publish_replay(events: Iterator[dict[str, Any]], endpoint: str = ADAPTER_PUSH) -> int:
    from intent_runtime.zmq_bus import AdapterPush

    push = AdapterPush(endpoint)
    count = 0
    try:
        for event in events:
            push.send_event(to_adapter_event(event))
            count += 1
    finally:
        push.close()
    return count


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Replay a recorded session")
    parser.add_argument("--session", required=True, help="Session id or path")
    parser.add_argument("--mode", choices=REPLAY_MODES, default="eval")
    parser.add_argument("--factor", type=float, default=10.0, help="Accelerated-mode speedup")
    parser.add_argument(
        "--exclude-modalities",
        default="",
        help="Comma-separated modalities to drop (e.g. audio,eeg)",
    )
    parser.add_argument(
        "--endpoint",
        default=ADAPTER_PUSH,
        help="PUSH endpoint (hub ingest on 5555)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Iterate events without publishing")
    parser.add_argument("--sessions-dir", default=None)
    parser.add_argument("--fixtures-dir", default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    config = load_stacked_config()
    storage = config.get("storage") or {}
    sessions_dir = Path(args.sessions_dir or storage.get("sessions_dir") or "data/sessions")
    fixtures_dir = Path(args.fixtures_dir or storage.get("fixtures_dir") or "data/fixtures")
    session_dir = resolve_session_dir(
        args.session,
        sessions_dir=sessions_dir,
        fixtures_dir=fixtures_dir,
    )
    exclude = [part for part in str(args.exclude_modalities).split(",") if part.strip()]
    stream = iter_replay_events(
        session_dir,
        mode=args.mode,
        factor=args.factor,
        exclude_modalities=exclude,
    )
    if args.dry_run:
        count = sum(1 for _ in stream)
        print(f"dry-run replayed {count} events from {session_dir}")
        return 0
    count = publish_replay(stream, endpoint=args.endpoint)
    print(f"published {count} replay events from {session_dir} to {args.endpoint}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
