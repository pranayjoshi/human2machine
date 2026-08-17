"""BLE advertisement scan for Ganglion listing. Does not open a BrainFlow session."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

GANGLION_NAME_PREFIXES = ("Ganglion", "Simblee")


def is_ganglion_advertisement(name: str | None) -> bool:
    text = (name or "").strip()
    if not text:
        return False
    lowered = text.lower()
    return any(lowered.startswith(prefix.lower()) for prefix in GANGLION_NAME_PREFIXES)


def scan_ble_devices(
    *,
    timeout_s: float = 8.0,
    discover: Callable[[float], list[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    """Return nearby BLE advertisements. ``discover`` is injected in tests."""
    if discover is not None:
        return list(discover(timeout_s))
    return _bleak_discover(timeout_s)


def _bleak_discover(timeout_s: float) -> list[dict[str, Any]]:
    try:
        from bleak import BleakScanner
    except ImportError as exc:
        raise RuntimeError("bleak is not installed; pip install bleak") from exc

    async def _run() -> list[dict[str, Any]]:
        found = await BleakScanner.discover(timeout=max(1.0, float(timeout_s)))
        rows: list[dict[str, Any]] = []
        for device in found:
            rows.append(
                {
                    "name": device.name,
                    "address": device.address,
                    "rssi": getattr(device, "rssi", None),
                }
            )
        rows.sort(
            key=lambda row: (
                not is_ganglion_advertisement(row.get("name")),
                str(row.get("name") or ""),
            )
        )
        return rows

    return asyncio.run(_run())
