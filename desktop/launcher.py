"""Backchannel desktop launcher: embedded Postgres + uvicorn + tray icon."""

import ctypes
import json
import logging
import os
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from datetime import datetime, timezone
from pathlib import Path


def _guarantee_standard_streams() -> None:
    """Give the windowed build real stdout/stderr objects.

    A PyInstaller bundle built with console=False has no console, so Python
    sets sys.stdout and sys.stderr to None. Any library that writes to them
    then raises AttributeError on None.write, and not every library unwinds
    cleanly when it does: tqdm's clear() and refresh() take its process-global
    write lock, touch the stream, and release only on the next line, so the
    exception escapes with that lock held forever and the next progress bar
    anywhere in the process deadlocks. That is what froze session creation in
    v0.6.1 (ALP-373), because a PII Shield model download sat in front of it.

    Discarding the writes is right for a GUI app: real diagnostics go to
    backchannel.log through logging, which has its own file handler.

    Deliberately a copy of app.services.std_streams.ensure rather than an
    import of it: this has to run before the first backend import, and a
    launcher's safety net cannot depend on the thing it is protecting. The
    backend calls its own copy too, so every entry point is covered.
    """
    for name in ("stdout", "stderr"):
        if getattr(sys, name, None) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8", errors="replace"))
        # __stdout__/__stderr__ stay None otherwise, and libraries fall back to them.
        if getattr(sys, f"__{name}__", None) is None:
            setattr(sys, f"__{name}__", getattr(sys, name))


_guarantee_standard_streams()

# Dev checkout: make `app` (backend) importable. In the PyInstaller bundle
# the backend package is baked in and this directory does not exist.
_REPO_BACKEND = Path(__file__).resolve().parent.parent / "backend"
if _REPO_BACKEND.exists():
    sys.path.insert(0, str(_REPO_BACKEND))

from bcdesktop.paths import app_data_dir, free_port, resource
from bcdesktop.pg import EmbeddedPostgres
from updater import validate_plan

LOCK_NAME = "launcher.json"
STOP_NAME = "stop"
LOOPBACK_HOST = "127.0.0.1"
BROWSER_HOST = "localhost"
DEFAULT_APP_PORT = 8474
WINDOWS_BROWSERS = ("msedge.exe", "chrome.exe")
MACOS_BROWSERS = ("Microsoft Edge", "Google Chrome")
LINUX_BROWSERS = ("microsoft-edge", "google-chrome", "chromium")
INSTANCE_HEADER = "X-Backchannel-Instance"
UPDATER_NAMES = {
    "win32": "BackchannelUpdater.exe",
    "darwin": "Contents/MacOS/BackchannelUpdater",
    "linux": "BackchannelUpdater",
}


def app_url(port: int) -> str:
    return f"http://{BROWSER_HOST}:{port}"


def health_url(port: int) -> str:
    return f"http://{LOOPBACK_HOST}:{port}/api/health"


def install_root() -> Path:
    executable = Path(sys.executable).resolve()
    return executable.parents[2] if sys.platform == "darwin" else executable.parent


def updater_path(root: Path) -> Path:
    platform_key = "linux" if sys.platform.startswith("linux") else sys.platform
    return root / UPDATER_NAMES[platform_key]


def bind_app_socket() -> socket.socket:
    listener = socket.socket()
    try:
        listener.bind((LOOPBACK_HOST, DEFAULT_APP_PORT))
    except OSError:
        listener.close()
        listener = socket.socket()
        listener.bind((LOOPBACK_HOST, 0))
    return listener


def _windows_browser_path() -> str | None:
    try:
        query = ctypes.windll.shlwapi.AssocQueryStringW
        size = ctypes.c_uint()
        if query(0, 2, "http", None, None, ctypes.byref(size)) != 1:
            return None
        value = ctypes.create_unicode_buffer(size.value)
        if query(0, 2, "http", None, value, ctypes.byref(size)) != 0:
            return None
        path = Path(value.value)
        if path.name.casefold() in WINDOWS_BROWSERS and path.is_file():
            return str(path)
    except (AttributeError, OSError, ValueError):
        pass
    return None


def browser_opener(url: str) -> None:
    """Use Chromium app mode; unsupported defaults use normal system open."""
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


def instance_is_healthy(port: int, token: str) -> bool:
    try:
        req = urllib.request.urlopen(health_url(port), timeout=2)
        with req as resp:
            return (
                resp.status == 200
                and resp.headers.get(INSTANCE_HEADER) == token
            )
    except Exception:
        return False


def existing_instance_port(data_dir: Path) -> int | None:
    """Port of a healthy already-running instance, else None."""
    lock = data_dir / LOCK_NAME
    if not lock.exists():
        return None
    try:
        instance = json.loads(lock.read_text())
        port = instance["port"]
        if instance_is_healthy(port, instance["token"]):
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


def wait_healthy(
    port: int, timeout: float = 90.0, token: str | None = None
) -> bool:
    if token is None:
        return False
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if instance_is_healthy(port, token):
            return True
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


def _write_update_state(state_path: Path, value: dict) -> None:
    temporary = state_path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, separators=(",", ":"))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, state_path)


def _reset_stale_apply(data_dir: Path, marker: Path) -> None:
    marker.unlink(missing_ok=True)
    state_path = data_dir / "updates" / "state.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if isinstance(state, dict) and state.get("state") == "applying":
            state["state"] = "ready"
            state["error"] = ""
            _write_update_state(state_path, state)
    except Exception:
        pass


def _claim_update_marker(data_dir: Path) -> bool:
    marker = data_dir / "updates" / "apply.json"
    if not marker.is_file() or marker.is_symlink():
        return False
    try:
        value = json.loads(marker.read_text(encoding="utf-8"))
        requested = datetime.strptime(
            value["requested_at"], "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - requested).total_seconds()
        if age < 0 or age >= 60:
            raise ValueError
        validate_plan(value, marker)
        return True
    except Exception:
        _reset_stale_apply(data_dir, marker)
        return False


def _watch_for_update(icon, data_dir: Path, requested: threading.Event, stopped: threading.Event) -> None:
    while not stopped.is_set():
        if _claim_update_marker(data_dir):
            requested.set()
            icon.stop()
            return
        stopped.wait(1)


def _update_status(port: int) -> dict:
    try:
        with urllib.request.urlopen(
            f"http://{LOOPBACK_HOST}:{port}/api/updates", timeout=2
        ) as response:
            body = response.read(65_537)
        if response.status != 200 or len(body) > 65_536:
            return {}
        value = json.loads(body.decode("utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _update_menu_label(port: int) -> str:
    status = _update_status(port)
    if status.get("state") not in {
        "available",
        "authorizing",
        "downloading",
        "needs_authorization",
        "ready",
    }:
        return "Check for updates"
    version = status.get("available_version")
    notes = status.get("available_notes")
    if not isinstance(version, str) or not isinstance(notes, str):
        return "Check for updates"
    title = next((line.strip().lstrip("#").strip() for line in notes.splitlines() if line.strip()), "")
    return f"Update {version}: {title[:60]}" if title else f"Update {version}"


def _check_for_updates(port: int, token: str) -> None:
    try:
        request = urllib.request.Request(
            f"http://{LOOPBACK_HOST}:{port}/api/updates/check",
            data=b"",
            method="POST",
            headers={INSTANCE_HEADER: token},
        )
        with urllib.request.urlopen(request, timeout=5):
            pass
    except Exception:
        pass
    browser_opener(f"{app_url(port)}/?view=about")


def _launch_update_helper(data_dir: Path, helper_source: Path) -> Path:
    marker = (data_dir / "updates" / "apply.json").resolve(strict=True)
    value = json.loads(marker.read_text(encoding="utf-8"))
    plan = validate_plan(value, marker)
    source = helper_source.resolve(strict=True)
    if helper_source.is_symlink() or not source.is_file():
        raise RuntimeError("Update helper is unavailable.")
    destination = data_dir / "updates" / "bin" / plan.version / source.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp")
    shutil.copy2(source, temporary)
    os.replace(temporary, destination)
    subprocess.Popen(
        [str(destination), str(marker)],
        cwd=str(destination.parent),
    )
    return destination


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


def _run_tray(port: int, data_dir: Path, instance_token: str | None = None) -> bool:
    import pystray

    image = _tray_image()
    requested = threading.Event()
    stopped = threading.Event()

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
            pystray.MenuItem(
                (
                    lambda _item: _update_menu_label(port)
                    if instance_token
                    else "Check for updates"
                ),
                lambda _icon, _item: _check_for_updates(port, instance_token or ""),
            ),
            pystray.MenuItem("Quit", lambda _icon, _item: icon.stop()),
        ),
    )
    watcher = threading.Thread(
        target=_watch_for_update,
        args=(icon, data_dir, requested, stopped),
        daemon=True,
    )
    watcher.start()
    try:
        icon.run()
    finally:
        stopped.set()
        watcher.join(timeout=2)
    return requested.is_set()


def _configure_update_environment(instance_token: str, headless: bool) -> None:
    root = install_root()
    packaged = bool(getattr(sys, "frozen", False))
    os.environ["BACKCHANNEL_DESKTOP"] = "1" if packaged else "0"
    os.environ["BACKCHANNEL_INSTANCE_TOKEN"] = instance_token
    os.environ["BACKCHANNEL_INSTALL_DIR"] = str(root)
    os.environ["BACKCHANNEL_UPDATE_KEYS"] = str(resource("release_signing_keys.json"))
    os.environ["BACKCHANNEL_UPDATE_HELPER"] = str(updater_path(root))
    os.environ["BACKCHANNEL_UPDATE_APPLY_DISABLED"] = (
        "1" if headless or not packaged else "0"
    )
    os.environ["BACKCHANNEL_BOUND_HOST"] = LOOPBACK_HOST


def _launch_requested_update(requested: bool, data_dir: Path, log) -> int:
    if not requested:
        return 0
    try:
        _launch_update_helper(
            data_dir, Path(os.environ["BACKCHANNEL_UPDATE_HELPER"])
        )
        return 0
    except Exception:
        log.exception("failed to start update helper")
        _error_dialog(
            f"Backchannel could not start the update. See log: {data_dir / 'backchannel.log'}"
        )
        return 1


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

    listener = bind_app_socket()
    app_port = listener.getsockname()[1]
    instance_token = secrets.token_urlsafe()
    os.environ["DATABASE_URL"] = pg.database_url(pg_port)
    os.environ["DATA_DIR"] = str(data_dir / "data")
    if sys.platform == "win32":
        # Wrap the credentials master key with DPAPI so a copied AppData
        # folder cannot decrypt the stored provider keys (see
        # app.services.secrets). Only the same Windows user on this machine
        # can unwrap it; the file is upgraded in place on first read.
        os.environ.setdefault("CREDENTIALS_MASTER_KEY_PROTECTION", "dpapi")
    os.environ["FRONTEND_DIST"] = str(resource("frontend"))
    _configure_update_environment(instance_token, headless)
    ffmpeg = resource("ffmpeg") / (
        "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    )
    if ffmpeg.is_file():
        os.environ["BACKCHANNEL_FFMPEG"] = str(ffmpeg)

    # Import after env is set: app.config reads the environment at import.
    import uvicorn

    server = uvicorn.Server(
        uvicorn.Config(
            "app.main:app",
            host=LOOPBACK_HOST,
            port=app_port,
            log_config=None,
            headers=[(INSTANCE_HEADER, instance_token)],
            ws_ping_timeout=90.0,
            ws_max_queue=2048,
            ws_max_size=65_536,
        )
    )
    thread = threading.Thread(
        target=server.run, kwargs={"sockets": [listener]}, daemon=True
    )
    log.info("starting app on port %s", app_port)
    thread.start()

    lock = data_dir / LOCK_NAME
    update_requested = False
    try:
        lock.write_text(
            json.dumps(
                {"port": app_port, "pid": os.getpid(), "token": instance_token}
            )
        )
        if not wait_healthy(app_port, token=instance_token):
            log.error("app failed to become healthy; see postgres.log too")
            if not headless:
                _error_dialog(
                    f"Backchannel failed to start. See log: {data_dir / 'backchannel.log'}"
                )
            return 1
        if headless:
            _wait_for_stop_file(data_dir)
        else:
            browser_opener(app_url(app_port))
            update_requested = _run_tray(app_port, data_dir, instance_token)
    finally:
        log.info("shutting down")
        server.should_exit = True
        thread.join(timeout=15)
        listener.close()
        pg.stop()
        lock.unlink(missing_ok=True)
    return _launch_requested_update(update_requested, data_dir, log)


if __name__ == "__main__":
    sys.exit(run(headless=os.environ.get("BACKCHANNEL_HEADLESS") == "1"))
