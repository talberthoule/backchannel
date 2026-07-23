"""Platform paths, port picking, and bundle resource resolution."""

import os
import socket
import sys
from pathlib import Path

APP_NAME = "Backchannel"

# Repo-checkout locations for each bundled resource (dev mode). In a
# PyInstaller bundle every resource sits directly under sys._MEIPASS.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEV_RESOURCES = {
    "frontend": _REPO_ROOT / "frontend" / "dist",
    "models": _REPO_ROOT / "backend" / "models",
    "pgsql": _REPO_ROOT / "desktop" / "pgsql",
    "assets": _REPO_ROOT / "desktop" / "assets",
    "ffmpeg": _REPO_ROOT / "desktop" / "ffmpeg",
}


def app_data_dir() -> Path:
    override = os.environ.get("BACKCHANNEL_DATA_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32":
        return Path(os.environ["LOCALAPPDATA"]) / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    return Path.home() / ".local" / "share" / APP_NAME.lower()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def resource(name: str) -> Path:
    if name not in _DEV_RESOURCES:
        raise KeyError(f"unknown resource: {name}")
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass) / name
    return _DEV_RESOURCES[name]
