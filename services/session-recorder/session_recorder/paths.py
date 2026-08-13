"""Session directory layout."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

SESSION_SUBDIRS = ("events", "biosignals", "media", "labels", "configs", "models")


@dataclass(frozen=True)
class SessionPaths:
    root: Path

    @property
    def events(self) -> Path:
        return self.root / "events"

    @property
    def biosignals(self) -> Path:
        return self.root / "biosignals"

    @property
    def media(self) -> Path:
        return self.root / "media"

    @property
    def labels(self) -> Path:
        return self.root / "labels"

    @property
    def configs(self) -> Path:
        return self.root / "configs"

    @property
    def models(self) -> Path:
        return self.root / "models"

    @property
    def manifest(self) -> Path:
        return self.root / "manifest.json"

    @property
    def checksums(self) -> Path:
        return self.root / "checksums.json"

    @property
    def normalized(self) -> Path:
        return self.events / "normalized.parquet"

    @property
    def decisions(self) -> Path:
        return self.events / "decisions.parquet"

    @property
    def safety(self) -> Path:
        return self.events / "safety.parquet"

    @property
    def outcomes(self) -> Path:
        return self.events / "outcomes.parquet"

    @property
    def trials(self) -> Path:
        return self.labels / "trials.parquet"

    @property
    def biosignal_chunks(self) -> Path:
        return self.biosignals / "chunks.parquet"

    @property
    def inflight(self) -> Path:
        return self.root / ".inflight"

    def create(self) -> None:
        for directory in (
            self.events,
            self.biosignals,
            self.media,
            self.labels,
            self.configs,
            self.models,
            self.inflight,
        ):
            directory.mkdir(parents=True, exist_ok=True)


def resolve_session_dir(
    session_id: str,
    *,
    sessions_dir: Path,
    fixtures_dir: Path | None = None,
) -> Path:
    """Resolve a session id or filesystem path to a session directory."""
    candidate = Path(session_id)
    if candidate.is_dir() and (candidate / "manifest.json").exists():
        return candidate.resolve()

    search_roots = [sessions_dir]
    if fixtures_dir is not None:
        search_roots.extend([fixtures_dir / "sessions", fixtures_dir])
    for root in search_roots:
        path = root / session_id
        if path.is_dir():
            return path.resolve()
    raise FileNotFoundError(f"session directory not found: {session_id}")
