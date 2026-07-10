"""Backchannel desktop launcher: embedded Postgres + uvicorn + tray icon."""

import json
import logging
import os
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

# Dev checkout: make `app` (backend) importable. In the PyInstaller bundle
# the backend package is baked in and this directory does not exist.
_REPO_BACKEND = Path(__file__).resolve().parent.parent / "backend"
if _REPO_BACKEND.exists():
    sys.path.insert(0, str(_REPO_BACKEND))

from bcdesktop.paths import app_data_dir, free_port, resource
from bcdesktop.pg import EmbeddedPostgres

LOCK_NAME = "launcher.json"
STOP_NAME = "stop"


def existing_instance_port(data_dir: Path) -> int | None:
    """Port of a healthy already-running instance, else None."""
    lock = data_dir / LOCK_NAME
    if not lock.exists():
        return None
    try:
        port = json.loads(lock.read_text())["port"]
        req = urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/health", timeout=2
        )
        with req as resp:
            if resp.status == 200:
                return port
    except Exception:
        pass
    return None


def wait_healthy(port: int, timeout: float = 90.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            req = urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/health", timeout=2
            )
            with req as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(0.5)
    return False


def _wait_for_stop_file(data_dir: Path) -> None:
    stop = data_dir / STOP_NAME
    stop.unlink(missing_ok=True)
    while not stop.exists():
        time.sleep(1)
    stop.unlink(missing_ok=True)


def _error_dialog(message: str) -> None:
    """Best-effort native error popup; falls back to stderr."""
    try:
        if sys.platform == "win32":
            import ctypes

            ctypes.windll.user32.MessageBoxW(0, message, "Backchannel", 0x10)
            return
        if sys.platform == "darwin":
            import subprocess

            subprocess.run(
                [
                    "osascript",
                    "-e",
                    f'display alert "Backchannel" message "{message}"',
                ],
                check=False,
            )
            return
    except Exception:
        pass
    print(message, file=sys.stderr)


def _run_tray(port: int) -> None:
    import pystray
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (64, 64), (30, 41, 59))
    draw = ImageDraw.Draw(image)
    draw.ellipse((16, 16, 48, 48), fill=(56, 189, 248))

    icon = pystray.Icon(
        "backchannel",
        image,
        "Backchannel",
        menu=pystray.Menu(
            pystray.MenuItem(
                "Open",
                lambda: webbrowser.open(f"http://127.0.0.1:{port}"),
            ),
            pystray.MenuItem("Quit", lambda: icon.stop()),
        ),
    )
    icon.run()


def run(headless: bool = False) -> int:
    data_dir = app_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=str(data_dir / "backchannel.log"),
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    log = logging.getLogger("launcher")

    port = existing_instance_port(data_dir)
    if port is not None:
        log.info("instance already running on port %s", port)
        if not headless:
            webbrowser.open(f"http://127.0.0.1:{port}")
        return 0

    pg = EmbeddedPostgres(resource("pgsql"), data_dir)
    pg_port = free_port()
    try:
        pg.recover_stale()
        pg.ensure_initdb()
        log.info("starting postgres on port %s", pg_port)
        pg.start(pg_port)
    except Exception:
        log.exception("postgres failed to start")
        if not headless:
            _error_dialog(f"PostgreSQL failed to start. See log: {pg.log}")
        return 1

    app_port = free_port()
    os.environ["DATABASE_URL"] = pg.database_url(pg_port)
    os.environ["DATA_DIR"] = str(data_dir / "data")
    os.environ["FRONTEND_DIST"] = str(resource("frontend"))

    # Import after env is set: app.config reads the environment at import.
    import uvicorn

    server = uvicorn.Server(
        uvicorn.Config(
            "app.main:app", host="127.0.0.1", port=app_port, log_config=None
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    log.info("starting app on port %s", app_port)
    thread.start()

    lock = data_dir / LOCK_NAME
    try:
        if not wait_healthy(app_port):
            log.error("app failed to become healthy; see postgres.log too")
            return 1
        lock.write_text(json.dumps({"port": app_port, "pid": os.getpid()}))
        if headless:
            _wait_for_stop_file(data_dir)
        else:
            webbrowser.open(f"http://127.0.0.1:{app_port}")
            _run_tray(app_port)
    finally:
        log.info("shutting down")
        server.should_exit = True
        thread.join(timeout=15)
        pg.stop()
        lock.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(run(headless=os.environ.get("BACKCHANNEL_HEADLESS") == "1"))
