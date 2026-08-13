"""Unit tests for session storage, finalization, replay, and deletion."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from multiprocessing import get_context
from pathlib import Path

import pyarrow.parquet as pq
import pytest
from intent_contracts.validation import parse_event
from session_recorder.checksums import verify_checksums
from session_recorder.constants import FINALIZATION_FINALIZED, FINALIZATION_PARTIAL
from session_recorder.delete import delete_session
from session_recorder.paths import SessionPaths
from session_recorder.queues import RecorderQueues
from session_recorder.replay import (
    iter_replay_events,
    load_session_events,
)
from session_recorder.replay import (
    main as replay_main,
)
from session_recorder.store import SessionStore
from session_recorder.synthetic import (
    GOLDEN_EVENT_TYPES,
    SYNTHETIC_SESSION_ID,
    synthetic_success_events,
    write_synthetic_success_fixture,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_DIR = REPO_ROOT / "data" / "fixtures" / "sessions" / SYNTHETIC_SESSION_ID
GITIGNORE = REPO_ROOT / ".gitignore"


def _record_all(sessions_dir: Path, events: list[dict] | None = None) -> SessionPaths:
    events = events or synthetic_success_events()
    store = SessionStore(sessions_dir, repo_dir=Path("/tmp"))
    store.open_from_started(events[0])
    for event in events[1:-1]:
        store.ingest(event)
    store.ingest(events[-1])
    store.finalize()
    assert store.paths is not None
    return store.paths


def test_synthetic_events_match_contracts() -> None:
    for event in synthetic_success_events():
        parse_event(event)


def test_finalize_tiny_session_without_corrupt_files(tmp_path: Path) -> None:
    paths = _record_all(tmp_path)
    manifest = json.loads(paths.manifest.read_text())
    assert manifest["finalization_status"] == FINALIZATION_FINALIZED
    assert manifest["session_id"] == SYNTHETIC_SESSION_ID
    assert manifest["user_id"] == "user_synthetic"
    assert manifest["record_audio"] is False
    assert manifest["record_video"] is False
    assert manifest["retention"] == "local"
    assert manifest["encryption"] == "none"
    assert not list(paths.root.rglob("*.tmp"))
    assert not paths.inflight.exists()
    for parquet_path in (
        paths.normalized,
        paths.decisions,
        paths.safety,
        paths.outcomes,
        paths.trials,
    ):
        table = pq.read_table(parquet_path)
        assert table.schema is not None
    events = load_session_events(paths.root)
    assert [event["event_type"] for event in events] == GOLDEN_EVENT_TYPES
    biosignal = next(event for event in events if event["event_type"] == "biosignal.chunk")
    assert biosignal["payload"]["samples"] == [[0.0, 0.25, 0.5, 0.25], [0.0, -0.25, 0.0, 0.25]]
    normalized_payloads = pq.read_table(paths.normalized).column("payload_json").to_pylist()
    for raw in normalized_payloads:
        payload = json.loads(raw)
        assert "samples" not in payload or payload.get("samples") in (None, [])
    ok, problems = verify_checksums(paths.root)
    assert ok, problems


def test_forced_crash_leaves_partial(tmp_path: Path) -> None:
    events = synthetic_success_events()
    store = SessionStore(tmp_path, repo_dir=Path("/tmp"))
    store.open_from_started(events[0])
    store.ingest(events[1])
    store.flush()
    assert store.paths is not None
    manifest = json.loads(store.paths.manifest.read_text())
    assert manifest["finalization_status"] == FINALIZATION_PARTIAL
    assert not (store.paths.root / "checksums.json").exists()


def _kill_mid_write_worker(sessions_dir: str, ready_path: str) -> None:
    from pathlib import Path

    from session_recorder.store import SessionStore
    from session_recorder.synthetic import synthetic_success_events

    store = SessionStore(Path(sessions_dir), repo_dir=Path("/tmp"), flush_every=10**9)
    events = synthetic_success_events()
    store.open_from_started(events[0])
    Path(ready_path).write_text("ready")
    chunk = dict(events[2])
    payload = dict(chunk["payload"])
    payload["samples"] = [[float(i) for i in range(256)] for _ in range(8)]
    payload["sample_count"] = 256
    payload["channel_names"] = [f"ch{i}" for i in range(8)]
    for index in range(400):
        event = dict(chunk)
        event["event_id"] = f"crash{index:024d}"
        event["sequence"] = index + 10
        event["payload"] = payload
        store.ingest(event)
    store.flush()
    time.sleep(30)


def test_forced_kill_mid_write_detectable_partial(tmp_path: Path) -> None:
    ready = tmp_path / "ready"
    ctx = get_context("spawn")
    proc = ctx.Process(target=_kill_mid_write_worker, args=(str(tmp_path), str(ready)))
    proc.start()
    deadline = time.time() + 15
    while not ready.exists() and time.time() < deadline:
        time.sleep(0.02)
    assert ready.exists(), "child did not start the session"
    time.sleep(0.05)
    os.kill(proc.pid, signal.SIGKILL)
    proc.join(timeout=5)
    session_dir = tmp_path / SYNTHETIC_SESSION_ID
    manifest = json.loads((session_dir / "manifest.json").read_text())
    assert manifest["finalization_status"] == FINALIZATION_PARTIAL


def test_replay_golden_event_type_sequence(tmp_path: Path) -> None:
    paths = _record_all(tmp_path)
    replayed = list(iter_replay_events(paths.root, mode="eval"))
    assert [event["event_type"] for event in replayed] == GOLDEN_EVENT_TYPES
    original_ids = {event["event_id"] for event in load_session_events(paths.root)}
    for event in replayed:
        assert event["session_id"] != SYNTHETIC_SESSION_ID
        assert event["session_id"].startswith("replay_")
        assert event["payload"]["original_session_id"] == SYNTHETIC_SESSION_ID
        assert event["payload"]["original_event_id"] in original_ids
        assert event["event_id"] not in original_ids


def test_replay_committed_fixture_golden_sequence() -> None:
    assert FIXTURE_DIR.is_dir(), "synthetic_success fixture must be committed"
    replayed = list(iter_replay_events(FIXTURE_DIR, mode="eval"))
    assert [event["event_type"] for event in replayed] == GOLDEN_EVENT_TYPES


def test_modality_ablation_exclude(tmp_path: Path) -> None:
    paths = _record_all(tmp_path)
    replayed = list(
        iter_replay_events(paths.root, mode="eval", exclude_modalities=["audio", "eeg"])
    )
    types = [event["event_type"] for event in replayed]
    assert "audio.intent_candidate" not in types
    assert "intent.decision" in types
    assert "safety.decision" in types
    assert "session.started" in types
    assert "vision.objects" in types


def test_replay_eval_skips_sleep(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = _record_all(tmp_path)
    slept: list[float] = []
    list(iter_replay_events(paths.root, mode="eval", sleep=slept.append))
    assert slept == []
    list(iter_replay_events(paths.root, mode="realtime", sleep=slept.append))
    assert slept
    assert slept[0] == pytest.approx(0.01)


def test_delete_removes_session_dir(tmp_path: Path) -> None:
    paths = _record_all(tmp_path)
    deleted = delete_session(SYNTHETIC_SESSION_ID, tmp_path)
    assert deleted == paths.root
    assert not paths.root.exists()


def test_checksums_detect_tampering(tmp_path: Path) -> None:
    paths = _record_all(tmp_path)
    ok, problems = verify_checksums(paths.root)
    assert ok, problems
    data = paths.normalized.read_bytes()
    paths.normalized.write_bytes(data + b"\x00")
    ok, problems = verify_checksums(paths.root)
    assert not ok
    assert any("checksum mismatch" in item for item in problems)


def test_sessions_dir_gitignored_except_fixtures() -> None:
    text = GITIGNORE.read_text()
    assert "data/sessions/" in text
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", "data/sessions/example_session/manifest.json"],
        cwd=REPO_ROOT,
    )
    assert ignored.returncode == 0
    fixture = subprocess.run(
        ["git", "check-ignore", "-q", "data/fixtures/sessions/synthetic_success/manifest.json"],
        cwd=REPO_ROOT,
    )
    assert fixture.returncode == 1
    assert FIXTURE_DIR.joinpath("manifest.json").is_file()
    assert FIXTURE_DIR.joinpath("events/normalized.parquet").is_file()
    ok, problems = verify_checksums(FIXTURE_DIR)
    assert ok, problems


def test_critical_events_never_dropped() -> None:
    queues = RecorderQueues(biosignal_bound=1, normal_bound=1)
    safety = {"event_type": "safety.decision", "event_id": "s1", "payload": {}}
    decision = {"event_type": "intent.decision", "event_id": "d1", "payload": {}}
    outcome = {"event_type": "action.outcome", "event_id": "o1", "payload": {}}
    started = {"event_type": "session.started", "event_id": "st1", "payload": {}}
    chunk = {
        "event_type": "biosignal.chunk",
        "event_id": "b1",
        "payload": {"samples": [[0.0]]},
    }
    assert queues.submit(safety)
    assert queues.submit(decision)
    assert queues.submit(outcome)
    assert queues.submit(started)
    assert queues.submit(chunk)
    assert queues.submit({**chunk, "event_id": "b2"}) is False
    assert queues.dropped_low_priority == 1
    drained = queues.drain(max_items=20)
    types = [item["event_type"] for item in drained]
    assert types[:4] == ["safety.decision", "intent.decision", "action.outcome", "session.started"]


def test_replay_cli_dry_run_fixture() -> None:
    code = replay_main(
        [
            "--session",
            SYNTHETIC_SESSION_ID,
            "--mode",
            "eval",
            "--dry-run",
            "--fixtures-dir",
            str(REPO_ROOT / "data" / "fixtures"),
            "--sessions-dir",
            str(REPO_ROOT / "data" / "sessions"),
        ]
    )
    assert code == 0


def test_write_fixture_helper_roundtrip(tmp_path: Path) -> None:
    written = write_synthetic_success_fixture(tmp_path)
    manifest = json.loads((written / "manifest.json").read_text())
    assert manifest["finalization_status"] == FINALIZATION_FINALIZED
    ok, problems = verify_checksums(written)
    assert ok, problems
