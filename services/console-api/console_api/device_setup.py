"""Public device-setup checklist. Never returns secret values."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

CROWN_ENV_NAMES = ("NEUROSITY_EMAIL", "NEUROSITY_PASSWORD", "NEUROSITY_DEVICE_ID")
DEVICE_CONNECTION_DOC = "docs/multimodal-intent-compiler/03_DEVICE_CONNECTION.md"
LOCAL_SETUP_DOC = "docs/multimodal-intent-compiler/01_LOCAL_SETUP.md"


def _nonempty(value: Any) -> bool:
    return bool(str(value or "").strip())


def _crown_env_flags(root: Path) -> dict[str, bool]:
    file_vals = {}
    env_path = root / ".env.local"
    if env_path.exists():
        file_vals = dotenv_values(env_path)
    flags = {}
    for name in CROWN_ENV_NAMES:
        flags[name] = _nonempty(os.environ.get(name)) or _nonempty(file_vals.get(name))
    return flags


def public_setup(root: Path, config: dict[str, Any], *, mock: bool) -> dict[str, Any]:
    runtime_cfg = config.get("runtime", {})
    ports = runtime_cfg.get("ports", {})
    devices = config.get("devices", {})
    fusion = config.get("fusion", {})
    crown = devices.get("crown", {})
    ganglion = devices.get("ganglion", {})
    audio = devices.get("audio", {})
    vision = devices.get("vision", {})
    simulator = devices.get("simulator", {})

    crown_env = _crown_env_flags(root)
    env_vars_present = all(crown_env.values())
    serial_port = ganglion.get("serial_port")
    serial_port_set = _nonempty(serial_port)
    audio_device = audio.get("device_name")
    audio_device_set = _nonempty(audio_device)
    camera_index = vision.get("camera_index")
    machine_mode = str(runtime_cfg.get("machine_mode", "simulator_only"))

    checklist = [
        {
            "id": "crown",
            "name": "Neurosity Crown (EEG, shadow-only)",
            "configured": env_vars_present,
            "detail": (
                "Crown env vars are set in .env.local."
                if env_vars_present
                else "Edit .env.local with NEUROSITY_* names. Values stay on disk, not in this UI."
            ),
        },
        {
            "id": "ganglion",
            "name": "OpenBCI Ganglion (EMG)",
            "configured": serial_port_set or bool(ganglion.get("mock", True)),
            "detail": (
                "serial_port is set in configs/local.yaml."
                if serial_port_set
                else "Set devices.ganglion.serial_port in configs/local.yaml for hardware."
            ),
        },
        {
            "id": "audio",
            "name": "Microphone",
            "configured": audio_device_set or bool(audio.get("mock", True)),
            "detail": (
                "Audio device name is set."
                if audio_device_set
                else "Set devices.audio.device_name in configs/local.yaml, or use mock."
            ),
        },
        {
            "id": "vision",
            "name": "Camera",
            "configured": camera_index is not None,
            "detail": f"camera_index is {camera_index}.",
        },
        {
            "id": "simulator",
            "name": "Robot simulator",
            "configured": bool(simulator.get("enabled", True)),
            "detail": f"Machine mode: {machine_mode}. No physical robot is armed.",
        },
    ]

    return {
        "mock": mock,
        "machine_mode": machine_mode,
        "eeg_shadow_only": bool(fusion.get("eeg_shadow_only", True)),
        "ports": {
            "adapter_push": ports.get("adapter_push", "tcp://127.0.0.1:5555"),
            "normalized_pub": ports.get("normalized_pub", "tcp://127.0.0.1:5556"),
            "command_push": ports.get("command_push", "tcp://127.0.0.1:5557"),
            "control_rep": ports.get("control_rep", "tcp://127.0.0.1:5558"),
            "console_api": ports.get("console_api", 8000),
            "developer_console": ports.get("developer_console", 3000),
        },
        "crown": {
            "enabled": bool(crown.get("enabled", True)),
            "mock": bool(crown.get("mock", True)),
            "env_vars_present": env_vars_present,
            "shadow_only": True,
        },
        "ganglion": {
            "enabled": bool(ganglion.get("enabled", True)),
            "mock": bool(ganglion.get("mock", True)),
            "serial_port_set": serial_port_set,
        },
        "audio": {
            "enabled": bool(audio.get("enabled", True)),
            "mock": bool(audio.get("mock", True)),
            "device_name_set": audio_device_set,
            "sample_rate_hz": audio.get("sample_rate_hz", 16000),
        },
        "vision": {
            "enabled": bool(vision.get("enabled", True)),
            "mock": bool(vision.get("mock", True)),
            "camera_index": camera_index,
            "width": vision.get("width", 1280),
            "height": vision.get("height", 720),
            "fps": vision.get("fps", 30),
            "object_ids": [
                "object_blue_1",
                "object_red_1",
                "object_green_1",
                "object_yellow_1",
            ],
        },
        "simulator": {
            "enabled": bool(simulator.get("enabled", True)),
            "mode": machine_mode,
        },
        "checklist": checklist,
        "links": [
            {
                "title": "Device connection handbook",
                "path": DEVICE_CONNECTION_DOC,
                "url": "/api/docs/device-connection",
            },
            {
                "title": "Local Mac setup",
                "path": LOCAL_SETUP_DOC,
                "url": "/api/docs/local-setup",
            },
        ],
        "operator_notes": [
            "Do not paste credentials into this browser.",
            "Edit ignored .env.local and configs/local.yaml.",
            "EEG is shadow-only and never drives action.",
            "Simulator mode cannot emit physical robot commands.",
        ],
    }


DOC_FILES = {
    "device-connection": DEVICE_CONNECTION_DOC,
    "local-setup": LOCAL_SETUP_DOC,
}
