"""On-disk session writer: incremental parquet flushes and atomic finalization."""

from __future__ import annotations

import shutil
from collections import Counter
from pathlib import Path
from typing import Any

from intent_contracts.enums import PRODUCER_VERSION, SCHEMA_VERSION, EventType
from intent_contracts.envelope import now_wall_ns

from session_recorder.checksums import write_checksums
from session_recorder.constants import (
    DECISION_EVENT_TYPE,
    FINALIZATION_FAILED,
    FINALIZATION_FINALIZED,
    FINALIZATION_PARTIAL,
    FLUSH_EVERY_EVENTS,
    OUTCOME_EVENT_TYPE,
    SAFETY_EVENT_TYPE,
    TRIAL_EVENT_TYPES,
)
from session_recorder.manifest import (
    empty_manifest,
    git_commit_info,
    sanitized_device_aliases,
    snapshot_configs,
    write_manifest,
)
from session_recorder.parquet_io import (
    BIOSIGNAL_SCHEMA,
    EVENT_SCHEMA,
    concat_parquet,
    event_to_row,
    load_events_parquet,
    strip_biosignal_samples,
)
from session_recorder.paths import SessionPaths


class SessionStore:
    """Creates the session directory, buffers events, and finalizes artifacts."""

    def __init__(
        self,
        sessions_dir: Path,
        *,
        config_dir: Path | None = None,
        config: dict[str, Any] | None = None,
        repo_dir: Path | None = None,
        flush_every: int = FLUSH_EVERY_EVENTS,
    ) -> None:
        self.sessions_dir = Path(sessions_dir)
        self.config_dir = Path(config_dir) if config_dir else None
        self.config = config or {}
        self.repo_dir = Path(repo_dir) if repo_dir else None
        self.flush_every = flush_every
        self.paths: SessionPaths | None = None
        self.manifest: dict[str, Any] | None = None
        self.session_id: str | None = None
        self.accepting = False
        self._event_rows: list[dict[str, Any]] = []
        self._decision_rows: list[dict[str, Any]] = []
        self._safety_rows: list[dict[str, Any]] = []
        self._outcome_rows: list[dict[str, Any]] = []
        self._trial_rows: list[dict[str, Any]] = []
        self._biosignal_rows: list[dict[str, Any]] = []
        self._event_parts: list[Path] = []
        self._decision_parts: list[Path] = []
        self._safety_parts: list[Path] = []
        self._outcome_parts: list[Path] = []
        self._trial_parts: list[Path] = []
        self._biosignal_parts: list[Path] = []
        self._part_n = 0
        self._counts: Counter[str] = Counter()
        self._packet_loss = 0
        self._dropped_low_priority = 0
        self._min_ns: int | None = None
        self._max_ns: int | None = None
        self._seen_ids: set[str] = set()
        self._finalized = False

    @property
    def active(self) -> bool:
        return self.accepting and self.paths is not None

    def open_from_started(self, event: dict[str, Any]) -> SessionPaths:
        session_id = event.get("session_id")
        if not session_id:
            raise ValueError("session.started requires session_id")
        payload = dict(event.get("payload") or {})
        storage = self.config.get("storage") or {}
        record_audio = bool(payload.get("record_audio", storage.get("record_audio", False)))
        record_video = bool(payload.get("record_video", storage.get("record_video", False)))
        commit, dirty = git_commit_info(self.repo_dir)
        if payload.get("commit"):
            commit = str(payload["commit"])
        model_ids = dict(payload.get("model_versions") or {})
        start_ns = int(payload.get("session_wall_time_ns") or now_wall_ns())
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        root = self.sessions_dir / str(session_id)
        root.mkdir(parents=True, exist_ok=True)
        paths = SessionPaths(root)
        # Persist PARTIAL before any heavier I/O so a crash is detectable.
        manifest = empty_manifest(
            session_id=str(session_id),
            user_id=str(payload.get("user_id") or "primary"),
            start_wall_time_ns=start_ns,
            consent=bool(payload.get("consent", True)),
            record_audio=record_audio,
            record_video=record_video,
            commit=commit,
            dirty_tree=dirty,
            contract_version=str(payload.get("contract_version") or SCHEMA_VERSION),
            device_aliases=sanitized_device_aliases(self.config),
            model_ids=model_ids,
            producer_version=str(event.get("producer_version") or PRODUCER_VERSION),
        )
        if payload.get("config_hash"):
            manifest["config_hashes"]["session.started"] = str(payload["config_hash"])
        write_manifest(paths, manifest)
        paths.create()
        manifest["config_hashes"].update(snapshot_configs(paths, self.config_dir))
        write_manifest(paths, manifest)
        self.paths = paths
        self.manifest = manifest
        self.session_id = str(session_id)
        self.accepting = True
        self._finalized = False
        self.ingest(event)
        return paths

    def ingest(self, event: dict[str, Any]) -> None:
        if self.paths is None or self._finalized:
            return
        event_id = event.get("event_id")
        if event_id:
            if event_id in self._seen_ids:
                return
            self._seen_ids.add(str(event_id))
        event_type = str(event.get("event_type") or "")
        payload, chunk = strip_biosignal_samples(event)
        row = event_to_row(event, payload)
        self._event_rows.append(row)
        self._counts[event_type] += 1
        normalized = event.get("normalized_time_ns")
        if normalized is not None:
            value = int(normalized)
            self._min_ns = value if self._min_ns is None else min(self._min_ns, value)
            self._max_ns = value if self._max_ns is None else max(self._max_ns, value)
        if chunk is not None:
            self._biosignal_rows.append(chunk)
            self._packet_loss += int(chunk.get("packet_loss_count") or 0)
        if event_type == DECISION_EVENT_TYPE:
            self._decision_rows.append(row)
        elif event_type == SAFETY_EVENT_TYPE:
            self._safety_rows.append(row)
        elif event_type == OUTCOME_EVENT_TYPE:
            self._outcome_rows.append(row)
        elif event_type in TRIAL_EVENT_TYPES:
            self._trial_rows.append(row)
        if len(self._event_rows) >= self.flush_every:
            self.flush()

    def record_drops(self, count: int) -> None:
        self._dropped_low_priority += count

    def flush(self) -> None:
        if self.paths is None:
            return
        inflight = self.paths.inflight
        inflight.mkdir(parents=True, exist_ok=True)
        n = self._part_n
        self._flush_bucket(
            "_event_rows",
            "_event_parts",
            EVENT_SCHEMA,
            inflight / f"normalized-{n:05d}.parquet",
        )
        self._flush_bucket(
            "_decision_rows",
            "_decision_parts",
            EVENT_SCHEMA,
            inflight / f"decisions-{n:05d}.parquet",
        )
        self._flush_bucket(
            "_safety_rows",
            "_safety_parts",
            EVENT_SCHEMA,
            inflight / f"safety-{n:05d}.parquet",
        )
        self._flush_bucket(
            "_outcome_rows",
            "_outcome_parts",
            EVENT_SCHEMA,
            inflight / f"outcomes-{n:05d}.parquet",
        )
        self._flush_bucket(
            "_trial_rows",
            "_trial_parts",
            EVENT_SCHEMA,
            inflight / f"trials-{n:05d}.parquet",
        )
        self._flush_bucket(
            "_biosignal_rows",
            "_biosignal_parts",
            BIOSIGNAL_SCHEMA,
            inflight / f"biosignals-{n:05d}.parquet",
        )
        self._part_n += 1
        if self.manifest is not None:
            self.manifest["event_counts"] = dict(self._counts)
            self.manifest["time_range"] = {
                "min_normalized_ns": self._min_ns,
                "max_normalized_ns": self._max_ns,
            }
            self.manifest["packet_loss_summary"] = {
                "total_packet_loss_count": self._packet_loss,
                "dropped_low_priority_events": self._dropped_low_priority,
            }
            self.manifest["finalization_status"] = FINALIZATION_PARTIAL
            write_manifest(self.paths, self.manifest)

    def _flush_bucket(self, rows_attr: str, parts_attr: str, schema, dest: Path) -> None:
        rows: list[dict[str, Any]] = getattr(self, rows_attr)
        if not rows:
            return
        concat_parquet([], rows, schema, dest)
        getattr(self, parts_attr).append(dest)
        setattr(self, rows_attr, [])

    def stop_accepting(self) -> None:
        self.accepting = False

    def finalize(self, *, failed: bool = False) -> dict[str, Any]:
        if self.paths is None or self.manifest is None:
            raise RuntimeError("no active session to finalize")
        self.accepting = False
        self.flush()
        concat_parquet(self._event_parts, self._event_rows, EVENT_SCHEMA, self.paths.normalized)
        concat_parquet(
            self._decision_parts, self._decision_rows, EVENT_SCHEMA, self.paths.decisions
        )
        concat_parquet(self._safety_parts, self._safety_rows, EVENT_SCHEMA, self.paths.safety)
        concat_parquet(self._outcome_parts, self._outcome_rows, EVENT_SCHEMA, self.paths.outcomes)
        concat_parquet(self._trial_parts, self._trial_rows, EVENT_SCHEMA, self.paths.trials)
        concat_parquet(
            self._biosignal_parts,
            self._biosignal_rows,
            BIOSIGNAL_SCHEMA,
            self.paths.biosignal_chunks,
        )
        issues = self._validate()
        end_ns = now_wall_ns()
        start_ns = int(self.manifest["start_wall_time_ns"])
        status = FINALIZATION_FAILED if failed or issues else FINALIZATION_FINALIZED
        self.manifest.update(
            {
                "end_wall_time_ns": end_ns,
                "duration_ns": max(0, end_ns - start_ns),
                "event_counts": dict(self._counts),
                "time_range": {
                    "min_normalized_ns": self._min_ns,
                    "max_normalized_ns": self._max_ns,
                },
                "packet_loss_summary": {
                    "total_packet_loss_count": self._packet_loss,
                    "dropped_low_priority_events": self._dropped_low_priority,
                },
                "stream_completeness": {
                    "events": not issues,
                    "biosignals": self.paths.biosignal_chunks.is_file(),
                    "audio": False,
                    "video": False,
                    "issues": issues,
                },
                "finalization_status": status,
            }
        )
        if self.paths.inflight.exists():
            shutil.rmtree(self.paths.inflight, ignore_errors=True)
        write_manifest(self.paths, self.manifest)
        write_checksums(self.paths.root)
        self._finalized = True
        return self.manifest

    def _validate(self) -> list[str]:
        issues: list[str] = []
        if self.paths is None:
            return ["missing session directory"]
        recorded = load_events_parquet(self.paths.normalized)
        if len(recorded) != sum(self._counts.values()):
            issues.append(
                f"normalized row count {len(recorded)} != ingested {sum(self._counts.values())}"
            )
        times = [
            row.get("normalized_time_ns")
            for row in recorded
            if row.get("normalized_time_ns") is not None
        ]
        if times:
            min_ns, max_ns = min(times), max(times)
            if self._min_ns != min_ns or self._max_ns != max_ns:
                issues.append("time range mismatch")
            if min_ns > max_ns:
                issues.append("invalid time range")
        for label, path, expected_type in (
            ("decisions", self.paths.decisions, DECISION_EVENT_TYPE),
            ("safety", self.paths.safety, SAFETY_EVENT_TYPE),
            ("outcomes", self.paths.outcomes, OUTCOME_EVENT_TYPE),
        ):
            rows = load_events_parquet(path)
            expected = self._counts.get(expected_type, 0)
            if len(rows) != expected:
                issues.append(f"{label} count {len(rows)} != {expected}")
            if any(row.get("event_type") != expected_type for row in rows):
                issues.append(f"{label} contains mixed event types")
        leftover_tmp = list(self.paths.root.rglob("*.tmp"))
        if leftover_tmp:
            issues.append(f"temp files remain: {[str(p) for p in leftover_tmp]}")
        return issues


def is_session_started(event: dict[str, Any]) -> bool:
    return str(event.get("event_type")) == EventType.SESSION_STARTED.value


def is_session_stopped(event: dict[str, Any]) -> bool:
    return str(event.get("event_type")) in {
        EventType.SESSION_STOPPED.value,
        EventType.SESSION_FAILED.value,
    }
