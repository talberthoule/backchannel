"""Backend startup wrapper."""

from __future__ import annotations

import os
import subprocess
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
    ]
    if os.getenv("BACKEND_RELOAD", "true").strip().lower() not in {"0", "false", "no", "off"}:
        command.append("--reload")

    return subprocess.run(command).returncode


if __name__ == "__main__":
    sys.exit(main())
