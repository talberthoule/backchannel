"""Backend startup wrapper."""

from __future__ import annotations

import os
import sys

from install_sortformer import ensure_sortformer_installed


def main() -> int:
    ensure_sortformer_installed(required=False)

    command = [
        "uvicorn",
        "app.main:app",
        "--host",
        "0.0.0.0",
        "--port",
        "8000",
        "--ws-ping-timeout",
        "90",
        "--ws-max-queue",
        "2048",
        "--ws-max-size",
        "65536",
    ]
    if os.getenv("BACKEND_RELOAD", "true").strip().lower() not in {"0", "false", "no", "off"}:
        command.append("--reload")

    os.execvp(command[0], command)
    return 0


if __name__ == "__main__":
    sys.exit(main())
