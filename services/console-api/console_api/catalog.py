"""Known services and preflight check metadata."""

from __future__ import annotations

from typing import Any

SERVICE_CATALOG: list[dict[str, Any]] = [
    {
        "id": "crown-adapter",
        "name": "Crown EEG",
        "required": False,
        "aliases": ("crown-adapter", "crown", "neurosity-crown", "neurosity"),
        "recovery": "Power the Crown, join the same Wi-Fi, and confirm NEUROSITY_* env vars.",
    },
    {
        "id": "ganglion-adapter",
        "name": "Ganglion EMG",
        "required": True,
        "aliases": ("ganglion-adapter", "ganglion", "ganglion-emg", "openbci-ganglion"),
        "recovery": (
            "Connect the USB dongle, confirm the serial port in configs/local.yaml, "
            "and check all four channels."
        ),
    },
    {
        "id": "audio-adapter",
        "name": "Microphone",
        "required": True,
        "aliases": ("audio-adapter", "audio", "microphone"),
        "recovery": "Grant microphone permission and select a device in configs/local.yaml.",
    },
    {
        "id": "vision-adapter",
        "name": "Camera",
        "required": True,
        "aliases": ("vision-adapter", "vision", "camera"),
        "recovery": (
            "Grant camera permission, confirm the camera index, and re-run table calibration."
        ),
    },
    {
        "id": "event-hub",
        "name": "Event hub",
        "required": True,
        "aliases": ("event-hub", "hub"),
        "recovery": (
            "Restart the event hub (`python -m event_hub.main`) "
            "and confirm ports 5555/5556/5558 are free."
        ),
    },
    {
        "id": "fusion-runtime",
        "name": "Fusion runtime",
        "required": True,
        "aliases": ("fusion-runtime", "fusion"),
        "recovery": "Restart fusion-runtime and confirm it is subscribed to the normalized stream.",
    },
    {
        "id": "safety-gateway",
        "name": "Safety gateway",
        "required": True,
        "aliases": ("safety-gateway", "safety"),
        "recovery": "Restart the safety gateway and verify configs/safety.yaml loaded.",
    },
    {
        "id": "robot-simulator",
        "name": "Simulator",
        "required": True,
        "aliases": ("robot-simulator", "simulator"),
        "recovery": (
            "Restart the robot simulator. Physical robot transport stays disarmed "
            "in simulator_only mode."
        ),
    },
    {
        "id": "session-recorder",
        "name": "Recorder",
        "required": True,
        "aliases": ("session-recorder", "recorder"),
        "recovery": (
            "Restart the session recorder and confirm data/sessions is writable "
            "with free disk space."
        ),
    },
]


def resolve_service_id(source: str) -> str | None:
    lowered = source.strip().lower()
    for item in SERVICE_CATALOG:
        if lowered == item["id"] or lowered in item["aliases"]:
            return item["id"]
    return None
