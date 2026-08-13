from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

LOGGER = logging.getLogger("intent_runtime")


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open() as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"expected mapping in {path}")
    return data


def load_stacked_config(config_dir: Path | None = None) -> dict[str, Any]:
    root = config_dir or Path("configs")
    merged: dict[str, Any] = {}
    for name in ("local.yaml", "modalities.yaml", "safety.yaml"):
        path = root / name
        if path.exists():
            _deep_update(merged, load_yaml(path))
    return merged


def _deep_update(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    for key, value in incoming.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_update(base[key], value)
        else:
            base[key] = value
    return base
