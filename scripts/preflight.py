#!/usr/bin/env python3
"""Fail if required localhost ports are occupied."""

from __future__ import annotations

import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path("packages/runtime-python/src")))
from intent_runtime.config import load_stacked_config

PORTS = {
    5555: "adapter PUSH",
    5556: "normalized PUB",
    5557: "command PULL",
    5558: "control REP",
    8000: "console API",
    3000: "developer console",
}


def port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def main() -> int:
    load_stacked_config(Path("configs"))
    occupied = [f"{port} ({label})" for port, label in PORTS.items() if port_open(port)]
    if occupied:
        print("preflight failed: occupied ports: " + ", ".join(occupied), file=sys.stderr)
        return 1
    print("preflight ok: required ports are free")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
