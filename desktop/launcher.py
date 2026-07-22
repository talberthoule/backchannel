"""Backchannel desktop launcher: embedded Postgres + uvicorn + tray icon."""

import json
import logging
import os
import shutil
import socket
import subprocess
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
LOOPBACK_HOST = "127.0.0.1"
BROWSER_HOST = "localhost"
DEFAULT_APP_PORT = 8474
WINDOWS_BROWSERS = ("msedge.exe", "chrome.exe")
MACOS_BROWSERS = ("Microsoft Edge", "Google Chrome")
LINUX_BROWSERS = ("microsoft-edge", "google-chrome", "chromium")


def app_url(port: int) -> str:
    return f"http://{BROWSER_HOST}:{port}"


def health_url(port: int) -> str:
    return f"http://{LOOPBACK_HOST}:{port}/api/health"


def select_app_port() -> int:
    try:
        with socket.socket() as candidate:
            candidate.bind((LOOPBACK_HOST, DEFAULT_APP_PORT))
    except OSError:
        return free_port()
    return DEFAULT_APP_PORT


def _windows_browser_path() -> str | None:
    try:
        import winreg
    except ImportError:
        winreg = None

    if winreg is not None:
        for executable in WINDOWS_BROWSERS:
            key_name = (
                "Software\\Microsoft\\Windows\\CurrentVersion\\App Paths\\"
                + executable
            )
            for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                try:
                    key = winreg.OpenKey(hive, key_name)
                    try:
                        value = winreg.QueryValue(key, None)
                    finally:
                        winreg.CloseKey(key)
                except OSError:
                    continue
                path = Path(str(value).strip('"'))
                if path.is_file():
                    return str(path)

    installs = (
        ("PROGRAMFILES(X86)", "Microsoft", "Edge", "Application", "msedge.exe"),
        ("PROGRAMFILES", "Microsoft", "Edge", "Application", "msedge.exe"),
        ("LOCALAPPDATA", "Microsoft", "Edge", "Application", "msedge.exe"),
        ("PROGRAMFILES", "Google", "Chrome", "Application", "chrome.exe"),
        ("PROGRAMFILES(X86)", "Google", "Chrome", "Application", "chrome.exe"),
        ("LOCALAPPDATA", "Google", "Chrome", "Application", "chrome.exe"),
    )
    for environment, *parts in installs:
        root = os.environ.get(environment)
        if root:
            path = Path(root).joinpath(*parts)
            if path.is_file():
                return str(path)
    return None


def browser_opener(url: str) -> None:
    if sys.platform == "darwin":
        for application in MACOS_BROWSERS:
            try:
                result = subprocess.run(
                    ["open", "-na", application, "--args", f"--app={url}"],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except OSError:
                break
            if result.returncode == 0:
                return
    else:
        browser = None
        if sys.platform == "win32":
            browser = _windows_browser_path()
        elif sys.platform.startswith("linux"):
            browser = next(
                (path for name in LINUX_BROWSERS if (path := shutil.which(name))),
                None,
            )
        if browser:
            try:
                subprocess.Popen([browser, f"--app={url}"])
                return
            except OSError:
                pass
    webbrowser.open(url)


def existing_instance_port(data_dir: Path) -> int | None:
    """Port of a healthy already-running instance, else None."""
    lock = data_dir / LOCK_NAME
    if not lock.exists():
        return None
    try:
        port = json.loads(lock.read_text())["port"]
        req = urllib.request.urlopen(health_url(port), timeout=2)
        with req as resp:
            if resp.status == 200:
                return port
    except Exception:
        pass
    return None


def wait_for_other_instance(
    data_dir: Path, timeout: float = 60.0, interval: float = 2.0
) -> int | None:
    """Poll for another instance to publish a healthy port, else None."""
    deadline = time.monotonic() + timeout
    while True:
        port = existing_instance_port(data_dir)
        if port is not None:
            return port
        if time.monotonic() >= deadline:
            return None
        time.sleep(interval)


def wait_healthy(port: int, timeout: float = 90.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            req = urllib.request.urlopen(health_url(port), timeout=2)
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


def _open_data_folder(data_dir: Path) -> None:
    try:
        if sys.platform == "win32":
            os.startfile(data_dir)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            import subprocess

            subprocess.run(["open", str(data_dir)], check=False)
        else:
            import subprocess

            subprocess.run(["xdg-open", str(data_dir)], check=False)
    except Exception:
        logging.getLogger("launcher").exception("failed to open data folder")


def _tray_image():
    from PIL import Image, ImageDraw

    icon_png = resource("assets") / "icon.png"
    try:
        with Image.open(icon_png) as brand:
            return brand.convert("RGBA")
    except Exception:
        logging.getLogger("launcher").exception(
            "brand icon unavailable at %s; using fallback", icon_png
        )
    image = Image.new("RGB", (64, 64), (30, 41, 59))
    draw = ImageDraw.Draw(image)
    draw.ellipse((16, 16, 48, 48), fill=(56, 189, 248))
    return image


def _run_tray(port: int, data_dir: Path) -> None:
    import pystray

    image = _tray_image()

    icon = pystray.Icon(
        "backchannel",
        image,
        f"Backchannel - {BROWSER_HOST}:{port}",
        menu=pystray.Menu(
            pystray.MenuItem(
                "Open Backchannel",
                lambda _icon, _item: browser_opener(app_url(port)),
            ),
            pystray.MenuItem(
                "Open data folder",
                lambda _icon, _item: _open_data_folder(data_dir),
            ),
            pystray.MenuItem("Quit", lambda _icon, _item: icon.stop()),
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
            browser_opener(app_url(port))
        return 0

    pg = EmbeddedPostgres(resource("pgsql"), data_dir)
    pg_port = free_port()
    foreign_postmaster = False
    try:
        pg.recover_stale()
        # recover_stale() already unlinked a genuinely stale pidfile, so a
        # pidfile that still exists here belongs to a LIVE postmaster
        # owned by another instance that is starting or already running.
        foreign_postmaster = (pg.pgdata / "postmaster.pid").exists()
        pg.ensure_initdb()
        log.info("starting postgres on port %s", pg_port)
        pg.start(pg_port)
    except Exception:
        log.exception("postgres failed to start")
        if foreign_postmaster:
            log.warning(
                "postmaster.pid belongs to another instance; not stopping it"
            )
            other_port = wait_for_other_instance(data_dir)
            if other_port is not None:
                log.info("other instance is healthy on port %s", other_port)
                if not headless:
                    browser_opener(app_url(other_port))
                return 0
            log.error("no other instance became healthy within timeout")
            if not headless:
                _error_dialog(
                    "Backchannel appears to be starting in another window. "
                    f"If it never opens, see log: {data_dir / 'backchannel.log'}"
                )
            return 1
        try:
            pg.stop()
        except Exception:
            log.exception("cleanup stop failed")
        if not headless:
            _error_dialog(f"PostgreSQL failed to start. See log: {pg.log}")
        return 1

    app_port = select_app_port()
    os.environ["DATABASE_URL"] = pg.database_url(pg_port)
    os.environ["DATA_DIR"] = str(data_dir / "data")
    os.environ["FRONTEND_DIST"] = str(resource("frontend"))

    # Import after env is set: app.config reads the environment at import.
    import uvicorn

    server = uvicorn.Server(
        uvicorn.Config(
            "app.main:app", host=LOOPBACK_HOST, port=app_port, log_config=None
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    log.info("starting app on port %s", app_port)
    thread.start()

    lock = data_dir / LOCK_NAME
    try:
        if not wait_healthy(app_port):
            log.error("app failed to become healthy; see postgres.log too")
            if not headless:
                _error_dialog(
                    f"Backchannel failed to start. See log: {data_dir / 'backchannel.log'}"
                )
            return 1
        lock.write_text(json.dumps({"port": app_port, "pid": os.getpid()}))
        if headless:
            _wait_for_stop_file(data_dir)
        else:
            browser_opener(app_url(app_port))
            _run_tray(app_port, data_dir)
    finally:
        log.info("shutting down")
        server.should_exit = True
        thread.join(timeout=15)
        pg.stop()
        lock.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(run(headless=os.environ.get("BACKCHANNEL_HEADLESS") == "1"))
