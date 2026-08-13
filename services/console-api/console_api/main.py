"""Entry: python -m console_api.main --mock"""

from __future__ import annotations

import argparse

import uvicorn
from intent_runtime.config import load_stacked_config
from intent_runtime.logging import configure_logging

from console_api.app import create_app
from console_api.runtime import find_repo_root


def main() -> None:
    parser = argparse.ArgumentParser(description="Developer console FastAPI gateway")
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Run without hardware; tolerate a missing event hub",
    )
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args()

    configure_logging("console-api")
    config = load_stacked_config(find_repo_root() / "configs")
    port = args.port or int(config.get("runtime", {}).get("ports", {}).get("console_api", 8000))
    app = create_app(mock=args.mock)
    uvicorn.run(app, host=args.host, port=port, log_level="info")


if __name__ == "__main__":
    main()
