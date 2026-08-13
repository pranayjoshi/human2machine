"""Delete a recorded session directory (raw + derived artifacts)."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from intent_runtime.config import load_stacked_config


def delete_session(session_id: str, sessions_dir: Path) -> Path:
    sessions_dir = sessions_dir.resolve()
    target = (sessions_dir / session_id).resolve()
    if not target.is_relative_to(sessions_dir):
        raise ValueError(f"refusing to delete path outside sessions dir: {target}")
    if not target.exists():
        raise FileNotFoundError(f"session not found: {target}")
    if not target.is_dir():
        raise NotADirectoryError(f"not a session directory: {target}")
    shutil.rmtree(target)
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Delete a local session directory")
    parser.add_argument("--session", required=True)
    parser.add_argument("--sessions-dir", default=None)
    args = parser.parse_args(argv)
    config = load_stacked_config()
    storage = config.get("storage") or {}
    sessions_dir = Path(args.sessions_dir or storage.get("sessions_dir") or "data/sessions")
    deleted = delete_session(args.session, sessions_dir)
    print(f"deleted {deleted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
