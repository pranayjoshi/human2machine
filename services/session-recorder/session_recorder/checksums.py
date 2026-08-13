"""Atomic file helpers and SHA-256 checksums for session artifacts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

SKIP_NAME_SUFFIXES = (".tmp",)
SKIP_DIR_NAMES = {".inflight"}
SKIP_FILE_NAMES = {"checksums.json"}


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    tmp.replace(path)


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    atomic_write_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def iter_checksum_files(session_dir: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(session_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.name in SKIP_FILE_NAMES or path.name.endswith(SKIP_NAME_SUFFIXES):
            continue
        if any(part in SKIP_DIR_NAMES for part in path.relative_to(session_dir).parts):
            continue
        files.append(path)
    return files


def write_checksums(session_dir: Path) -> dict[str, str]:
    checksums = {
        str(path.relative_to(session_dir)): sha256_file(path)
        for path in iter_checksum_files(session_dir)
    }
    atomic_write_json(session_dir / "checksums.json", checksums)
    return checksums


def verify_checksums(session_dir: Path) -> tuple[bool, list[str]]:
    checksums_path = session_dir / "checksums.json"
    if not checksums_path.is_file():
        return False, ["checksums.json is missing"]
    recorded = json.loads(checksums_path.read_text())
    problems: list[str] = []
    current = {
        str(path.relative_to(session_dir)): sha256_file(path)
        for path in iter_checksum_files(session_dir)
    }
    for rel, digest in recorded.items():
        if rel not in current:
            problems.append(f"missing file: {rel}")
        elif current[rel] != digest:
            problems.append(f"checksum mismatch: {rel}")
    for rel in current:
        if rel not in recorded:
            problems.append(f"unexpected file: {rel}")
    return not problems, problems
