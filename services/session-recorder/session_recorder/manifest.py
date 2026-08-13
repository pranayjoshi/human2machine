"""Session manifest construction and config/git snapshots."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Any

from intent_contracts.enums import PRODUCER_VERSION, SCHEMA_VERSION

from session_recorder.checksums import atomic_write_json
from session_recorder.constants import FINALIZATION_PARTIAL
from session_recorder.paths import SessionPaths

SAFE_DEVICE_KEYS = ("enabled", "mock")


def git_commit_info(repo: Path | None = None) -> tuple[str | None, bool]:
    cwd = repo or Path.cwd()
    if not (cwd / ".git").exists():
        return None, False
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=cwd,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        dirty = bool(
            subprocess.check_output(
                ["git", "status", "--porcelain"],
                cwd=cwd,
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
        )
        return commit or None, dirty
    except (OSError, subprocess.CalledProcessError):
        return None, False


def hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot_configs(session_paths: SessionPaths, config_dir: Path | None) -> dict[str, str]:
    hashes: dict[str, str] = {}
    if config_dir is None or not config_dir.is_dir():
        return hashes
    for name in ("local.yaml", "modalities.yaml", "safety.yaml"):
        source = config_dir / name
        if not source.is_file():
            continue
        target = session_paths.configs / name
        target.write_bytes(source.read_bytes())
        hashes[name] = hash_file(target)
    return hashes


def sanitized_device_aliases(config: dict[str, Any] | None) -> dict[str, Any]:
    devices = (config or {}).get("devices") or {}
    aliases: dict[str, Any] = {}
    if not isinstance(devices, dict):
        return aliases
    for name, spec in devices.items():
        if isinstance(spec, dict):
            aliases[name] = {key: spec.get(key) for key in SAFE_DEVICE_KEYS if key in spec}
        else:
            aliases[name] = {"present": True}
    return aliases


def empty_manifest(
    *,
    session_id: str,
    user_id: str = "primary",
    start_wall_time_ns: int,
    consent: bool = True,
    record_audio: bool = False,
    record_video: bool = False,
    commit: str | None = None,
    dirty_tree: bool = False,
    contract_version: str = SCHEMA_VERSION,
    config_hashes: dict[str, str] | None = None,
    device_aliases: dict[str, Any] | None = None,
    model_ids: dict[str, str] | None = None,
    producer_version: str = PRODUCER_VERSION,
) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "user_id": user_id,
        "start_wall_time_ns": start_wall_time_ns,
        "end_wall_time_ns": None,
        "duration_ns": None,
        "consent": consent,
        "record_audio": record_audio,
        "record_video": record_video,
        "commit": commit,
        "dirty_tree": dirty_tree,
        "contract_version": contract_version,
        "config_hashes": config_hashes or {},
        "device_aliases": device_aliases or {},
        "model_ids": model_ids or {},
        "stream_completeness": {
            "events": False,
            "biosignals": False,
            "audio": bool(record_audio),
            "video": bool(record_video),
        },
        "packet_loss_summary": {
            "total_packet_loss_count": 0,
            "dropped_low_priority_events": 0,
        },
        "finalization_status": FINALIZATION_PARTIAL,
        "encryption": "none",
        "retention": "local",
        "event_counts": {},
        "time_range": {
            "min_normalized_ns": None,
            "max_normalized_ns": None,
        },
        "producer_version": producer_version,
    }


def write_manifest(session_paths: SessionPaths, manifest: dict[str, Any]) -> None:
    atomic_write_json(session_paths.manifest, manifest)
