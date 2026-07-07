# Native Windows/Mac Executable Packaging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship Backchannel as a double-clickable executable for Windows and macOS (tray launcher + embedded PostgreSQL + browser UI), built unsigned by GitHub Actions, while leaving the Docker path untouched.

**Architecture:** A new `desktop/` directory holds a PyInstaller-packaged launcher that starts a bundled zonky.io PostgreSQL, runs uvicorn in-process serving the existing FastAPI app plus the built frontend, opens the default browser, and sits in the system tray. The only backend changes are a portable UUID column type and an optional static-files mount.

**Tech Stack:** Python 3.12, PyInstaller (one-dir), pystray + Pillow (tray icon), zonky.io embedded-postgres-binaries 16.x, GitHub Actions (windows-latest, macos-latest).

**Spec:** `docs/superpowers/specs/2026-07-07-native-packaging-design.md`

## Global Constraints

- Python 3.12 (matches `backend/Dockerfile`).
- New code is ASCII-only (per CLAUDE.md).
- Do NOT modify `docker-compose.yml`, `backend/Dockerfile`, `frontend/Dockerfile`, or `frontend/nginx.conf` — the Docker path stays byte-identical.
- Backend tests run from `backend/` with `python -m unittest discover -s tests`. Two orchestrator graceful-drain tests fail on the base branch (pre-existing) — ignore exactly those two; any OTHER failure is yours.
- Desktop tests run from `desktop/` with `python -m unittest discover -s tests`.
- The launcher binds only to `127.0.0.1`, never `0.0.0.0`.
- Embedded Postgres superuser is named `backchannel`; the app connects to the default `postgres` database (no createdb step).
- Commit after every task with the message given in the task.

---

### Task 1: Portable Uuid column type

Swap the PostgreSQL-dialect UUID type for SQLAlchemy 2.0's portable `Uuid`.
On PostgreSQL it still renders as native `UUID`, so this is behavior-neutral
for Docker while removing the only dialect-specific type in the models.

**Files:**
- Modify: `backend/app/models.py` (line 5 import, all `UUID(as_uuid=True)` columns)

**Interfaces:**
- Produces: `models.py` no longer imports from `sqlalchemy.dialects.postgresql`. Column Python type is still `uuid.UUID` — no caller changes anywhere.

- [ ] **Step 1: Replace the import**

In `backend/app/models.py` replace line 5:

```python
from sqlalchemy.dialects.postgresql import UUID
```

with:

```python
from sqlalchemy import Uuid
```

- [ ] **Step 2: Replace every column type usage**

Replace ALL occurrences of `UUID(as_uuid=True)` in `backend/app/models.py` with `Uuid()`. There are ~30 occurrences; use a global replace. Example result:

```python
id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
```

Verify zero occurrences remain: `grep -c "UUID(as_uuid" backend/app/models.py` must print `0`, and `grep -c "dialects.postgresql" backend/app/models.py` must print `0`.

- [ ] **Step 3: Run the backend test suite**

Run from `backend/`: `python -m unittest discover -s tests`
Expected: same results as base branch — only the two pre-existing orchestrator graceful-drain failures.

- [ ] **Step 4: Commit**

```bash
git add backend/app/models.py
git commit -m "refactor: use portable SQLAlchemy Uuid type in models"
```

---

### Task 2: Optional frontend static mount

Let the backend serve the built frontend when `FRONTEND_DIST` is set (native
mode). Docker never sets it, so nginx keeps that job there.

**Files:**
- Modify: `backend/app/config.py` (Settings class)
- Modify: `backend/app/main.py` (bottom of file)
- Test: `backend/tests/test_static_mount.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `settings.FRONTEND_DIST: str` (default `""`), and `mount_frontend(application: FastAPI, dist_dir: str) -> None` in `app.main`. Task 5's launcher sets the `FRONTEND_DIST` env var.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_static_mount.py`:

```python
import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI


class MountFrontendTests(unittest.TestCase):
    def test_noop_when_dist_unset(self):
        from app.main import mount_frontend

        app = FastAPI()
        before = len(app.routes)
        mount_frontend(app, "")
        self.assertEqual(len(app.routes), before)

    def test_mounts_static_files_when_dist_set(self):
        from app.main import mount_frontend

        app = FastAPI()
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "index.html").write_text("<html></html>")
            mount_frontend(app, tmp)
            self.assertTrue(
                any(getattr(r, "name", "") == "frontend" for r in app.routes)
            )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run from `backend/`: `python -m unittest tests.test_static_mount -v`
Expected: FAIL with `ImportError: cannot import name 'mount_frontend'`

- [ ] **Step 3: Implement**

In `backend/app/config.py`, add one field to `Settings` (below `DATABASE_URL` on line 7):

```python
    FRONTEND_DIST: str = ""  # path to built frontend; empty = nginx serves it (Docker)
```

In `backend/app/main.py`, add `from app.config import settings` to the imports, then append at the very bottom of the file (after the `/api/health` route — the mount must be registered LAST so API and WS routes win):

```python
def mount_frontend(application: FastAPI, dist_dir: str) -> None:
    """Serve the built frontend from the backend (native desktop mode)."""
    if not dist_dir:
        return
    from fastapi.staticfiles import StaticFiles

    application.mount("/", StaticFiles(directory=dist_dir, html=True), name="frontend")


mount_frontend(app, settings.FRONTEND_DIST)
```

- [ ] **Step 4: Run test to verify it passes**

Run from `backend/`: `python -m unittest tests.test_static_mount -v`
Expected: 2 tests PASS.

Also run the full suite: `python -m unittest discover -s tests` — no new failures.

- [ ] **Step 5: Commit**

```bash
git add backend/app/config.py backend/app/main.py backend/tests/test_static_mount.py
git commit -m "feat: optionally serve built frontend from FastAPI via FRONTEND_DIST"
```

---

### Task 3: Desktop package - paths, ports, resources

Foundation helpers for the launcher: platform app-data dir (with env
override for tests/CI), free-port picker, and bundle-vs-repo resource
resolution.

**Files:**
- Create: `desktop/bcdesktop/__init__.py` (empty file)
- Create: `desktop/bcdesktop/paths.py`
- Create: `desktop/tests/__init__.py` (empty file)
- Test: `desktop/tests/test_paths.py`

**Interfaces:**
- Produces (used by Tasks 4, 5):
  - `app_data_dir() -> Path` — honors `BACKCHANNEL_DATA_DIR` env override
  - `free_port() -> int`
  - `resource(name: str) -> Path` — `name` in `{"frontend", "models", "pgsql"}`; resolves inside the PyInstaller bundle (`sys._MEIPASS`) or the repo checkout in dev

- [ ] **Step 1: Write the failing tests**

Create empty `desktop/bcdesktop/__init__.py` and `desktop/tests/__init__.py`, then create `desktop/tests/test_paths.py`:

```python
import os
import socket
import unittest
from pathlib import Path
from unittest import mock

from bcdesktop.paths import app_data_dir, free_port, resource


class PathsTests(unittest.TestCase):
    def test_app_data_dir_env_override_wins(self):
        with mock.patch.dict(os.environ, {"BACKCHANNEL_DATA_DIR": "/somewhere/else"}):
            self.assertEqual(app_data_dir(), Path("/somewhere/else"))

    def test_app_data_dir_is_platform_specific(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("BACKCHANNEL_DATA_DIR", None)
            self.assertIn("Backchannel", str(app_data_dir()))

    def test_free_port_is_bindable(self):
        port = free_port()
        with socket.socket() as s:
            s.bind(("127.0.0.1", port))

    def test_resource_dev_fallback_points_into_repo(self):
        # No _MEIPASS in tests, so these resolve against the repo checkout.
        self.assertTrue(str(resource("frontend")).endswith("dist"))
        self.assertTrue(str(resource("models")).endswith("models"))
        self.assertTrue(str(resource("pgsql")).endswith("pgsql"))

    def test_resource_rejects_unknown_name(self):
        with self.assertRaises(KeyError):
            resource("nonsense")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run from `desktop/`: `python -m unittest discover -s tests -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bcdesktop.paths'`

- [ ] **Step 3: Implement**

Create `desktop/bcdesktop/paths.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run from `desktop/`: `python -m unittest discover -s tests -v`
Expected: 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add desktop/bcdesktop/__init__.py desktop/bcdesktop/paths.py desktop/tests/__init__.py desktop/tests/test_paths.py
git commit -m "feat: desktop paths/ports/resource helpers"
```

---

### Task 4: Embedded Postgres manager

Wraps the bundled zonky binaries: first-run `initdb` with a generated
password, `pg_ctl` start/stop, stale-pid recovery after a crash, and the
`DATABASE_URL` the app needs.

**Files:**
- Create: `desktop/bcdesktop/pg.py`
- Test: `desktop/tests/test_pg.py`

**Interfaces:**
- Consumes: nothing from other tasks (takes plain `Path`s).
- Produces (used by Task 5):
  - `EmbeddedPostgres(pg_dir: Path, data_dir: Path)`
  - `.recover_stale() -> None`, `.ensure_initdb() -> None`, `.start(port: int) -> None`, `.stop() -> None`
  - `.database_url(port: int) -> str` — `postgresql+asyncpg://backchannel:<pw>@127.0.0.1:<port>/postgres`

- [ ] **Step 1: Write the failing tests**

Create `desktop/tests/test_pg.py`:

```python
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bcdesktop.pg import EmbeddedPostgres


class EmbeddedPostgresTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data_dir = Path(tmp.name)
        self.pg = EmbeddedPostgres(Path("/fake/pgsql"), self.data_dir)

    def test_password_is_generated_once_and_stable(self):
        first = self.pg.password()
        self.assertEqual(first, self.pg.password())
        self.assertGreaterEqual(len(first), 32)

    def test_initdb_runs_with_password_auth(self):
        with mock.patch("bcdesktop.pg.subprocess.run") as run:
            run.return_value = mock.Mock(returncode=0)
            self.pg.ensure_initdb()
        cmd = run.call_args.args[0]
        self.assertIn("initdb", str(cmd[0]))
        self.assertIn("-A", cmd)
        self.assertIn("scram-sha-256", cmd)
        self.assertIn("backchannel", cmd)

    def test_initdb_skipped_when_cluster_exists(self):
        (self.data_dir / "pgdata").mkdir(parents=True)
        (self.data_dir / "pgdata" / "PG_VERSION").write_text("16")
        with mock.patch("bcdesktop.pg.subprocess.run") as run:
            self.pg.ensure_initdb()
        run.assert_not_called()

    def test_start_binds_localhost_only_on_given_port(self):
        with mock.patch("bcdesktop.pg.subprocess.run") as run:
            run.return_value = mock.Mock(returncode=0)
            self.pg.start(54321)
        cmd = run.call_args.args[0]
        self.assertIn("pg_ctl", str(cmd[0]))
        opts = cmd[cmd.index("-o") + 1]
        self.assertIn("-p 54321", opts)
        self.assertIn("listen_addresses=127.0.0.1", opts)

    def test_stop_is_noop_without_pidfile(self):
        with mock.patch("bcdesktop.pg.subprocess.run") as run:
            self.pg.stop()
        run.assert_not_called()

    def test_recover_stale_removes_pidfile_when_not_running(self):
        pgdata = self.data_dir / "pgdata"
        pgdata.mkdir(parents=True)
        pidfile = pgdata / "postmaster.pid"
        pidfile.write_text("99999")
        with mock.patch("bcdesktop.pg.subprocess.run") as run:
            run.return_value = mock.Mock(returncode=3)  # pg_ctl status: not running
            self.pg.recover_stale()
        self.assertFalse(pidfile.exists())

    def test_recover_stale_keeps_pidfile_when_running(self):
        pgdata = self.data_dir / "pgdata"
        pgdata.mkdir(parents=True)
        pidfile = pgdata / "postmaster.pid"
        pidfile.write_text("1234")
        with mock.patch("bcdesktop.pg.subprocess.run") as run:
            run.return_value = mock.Mock(returncode=0)  # pg_ctl status: running
            self.pg.recover_stale()
        self.assertTrue(pidfile.exists())

    def test_database_url_shape(self):
        url = self.pg.database_url(54321)
        self.assertTrue(url.startswith("postgresql+asyncpg://backchannel:"))
        self.assertIn("@127.0.0.1:54321/postgres", url)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run from `desktop/`: `python -m unittest tests.test_pg -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bcdesktop.pg'`

- [ ] **Step 3: Implement**

Create `desktop/bcdesktop/pg.py`:

```python
"""Lifecycle management for the bundled zonky.io PostgreSQL binaries."""

import secrets
import subprocess
from pathlib import Path


class EmbeddedPostgres:
    def __init__(self, pg_dir: Path, data_dir: Path):
        self.bin = Path(pg_dir) / "bin"
        self.pgdata = Path(data_dir) / "pgdata"
        self.pwfile = Path(data_dir) / "pgpassword"
        self.log = Path(data_dir) / "postgres.log"

    def password(self) -> str:
        if not self.pwfile.exists():
            self.pwfile.parent.mkdir(parents=True, exist_ok=True)
            self.pwfile.write_text(secrets.token_hex(16))
        return self.pwfile.read_text().strip()

    def _run(self, cmd: list) -> None:
        subprocess.run(cmd, check=True, capture_output=True, text=True)

    def ensure_initdb(self) -> None:
        if (self.pgdata / "PG_VERSION").exists():
            return
        self.password()
        self._run([
            str(self.bin / "initdb"),
            "-D", str(self.pgdata),
            "-U", "backchannel",
            "-A", "scram-sha-256",
            "--pwfile", str(self.pwfile),
            "-E", "UTF8",
        ])

    def recover_stale(self) -> None:
        # A postmaster.pid left by a crash blocks the next start. pg_ctl
        # status exits non-zero when no server is actually running.
        pidfile = self.pgdata / "postmaster.pid"
        if not pidfile.exists():
            return
        status = subprocess.run(
            [str(self.bin / "pg_ctl"), "-D", str(self.pgdata), "status"],
            capture_output=True,
        )
        if status.returncode != 0:
            pidfile.unlink()

    def start(self, port: int) -> None:
        self._run([
            str(self.bin / "pg_ctl"),
            "-D", str(self.pgdata),
            "-o", f"-p {port} -c listen_addresses=127.0.0.1",
            "-l", str(self.log),
            "-w",
            "start",
        ])

    def stop(self) -> None:
        if not (self.pgdata / "postmaster.pid").exists():
            return
        self._run([
            str(self.bin / "pg_ctl"),
            "-D", str(self.pgdata),
            "-m", "fast",
            "-w",
            "stop",
        ])

    def database_url(self, port: int) -> str:
        # token_hex passwords are URL-safe by construction.
        return (
            f"postgresql+asyncpg://backchannel:{self.password()}"
            f"@127.0.0.1:{port}/postgres"
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run from `desktop/`: `python -m unittest tests.test_pg -v`
Expected: 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add desktop/bcdesktop/pg.py desktop/tests/test_pg.py
git commit -m "feat: embedded Postgres lifecycle manager"
```

---

### Task 5: Launcher

The executable entry point: single-instance detection, Postgres up, uvicorn
in-process, browser open, tray icon, clean shutdown. Headless mode (env
`BACKCHANNEL_HEADLESS=1`) skips browser+tray and waits for a `stop` file —
that is what CI's smoke test drives.

**Files:**
- Create: `desktop/launcher.py`
- Create: `desktop/requirements.txt`
- Test: `desktop/tests/test_launcher.py`

**Interfaces:**
- Consumes: `app_data_dir`, `free_port`, `resource` (Task 3); `EmbeddedPostgres` (Task 4); `app.main:app` + `FRONTEND_DIST` env (Task 2).
- Produces: `run(headless: bool) -> int`, `existing_instance_port(data_dir: Path) -> int | None`, `wait_healthy(port: int, timeout: float) -> bool`. Writes `<data_dir>/launcher.json` (`{"port": int, "pid": int}`) once healthy — Task 8's smoke test reads it.

- [ ] **Step 1: Create desktop/requirements.txt**

```
pystray>=0.19.5
pillow>=10.0.0
pyinstaller>=6.10.0
```

- [ ] **Step 2: Write the failing tests**

Create `desktop/tests/test_launcher.py` (tests the pure/network helpers; full orchestration is covered by the CI smoke test in Task 8):

```python
import http.server
import json
import tempfile
import threading
import unittest
from pathlib import Path

import launcher


class _HealthHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/health":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"status": "ok"}')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):
        pass


class LauncherHelperTests(unittest.TestCase):
    def _serve_health(self):
        server = http.server.HTTPServer(("127.0.0.1", 0), _HealthHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        return server.server_address[1]

    def test_no_lock_file_means_no_instance(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(launcher.existing_instance_port(Path(tmp)))

    def test_stale_lock_file_means_no_instance(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "launcher.json").write_text(
                json.dumps({"port": 1, "pid": 99999})
            )
            self.assertIsNone(launcher.existing_instance_port(Path(tmp)))

    def test_live_lock_file_returns_port(self):
        port = self._serve_health()
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "launcher.json").write_text(
                json.dumps({"port": port, "pid": 1})
            )
            self.assertEqual(launcher.existing_instance_port(Path(tmp)), port)

    def test_wait_healthy_true_for_live_server(self):
        port = self._serve_health()
        self.assertTrue(launcher.wait_healthy(port, timeout=5))

    def test_wait_healthy_false_when_nothing_listens(self):
        from bcdesktop.paths import free_port

        self.assertFalse(launcher.wait_healthy(free_port(), timeout=1))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run tests to verify they fail**

Run from `desktop/`: `python -m unittest tests.test_launcher -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'launcher'`

- [ ] **Step 4: Implement**

Create `desktop/launcher.py`:

```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run from `desktop/`: `python -m unittest discover -s tests -v`
Expected: all desktop tests PASS (paths + pg + launcher).

- [ ] **Step 6: Commit**

```bash
git add desktop/launcher.py desktop/requirements.txt desktop/tests/test_launcher.py
git commit -m "feat: desktop launcher with tray, headless mode, single-instance lock"
```

---

### Task 6: Postgres binaries download script

Fetches the zonky.io standalone Postgres for the current platform into
`desktop/pgsql/`. The zonky maven artifact is a jar (zip) containing one
`.txz` tarball with `bin/`, `lib/`, `share/`.

**Files:**
- Create: `desktop/scripts/__init__.py` (empty file)
- Create: `desktop/scripts/download_pg.py`
- Modify: `.gitignore` (add `desktop/pgsql/`)
- Test: `desktop/tests/test_download_pg.py`

**Interfaces:**
- Produces: `desktop/pgsql/bin/{initdb,pg_ctl,postgres}` on disk (consumed by Task 4 at runtime, Task 7 at build time). Pure helpers `artifact_platform() -> str` and `jar_url(plat: str) -> str` for tests.

- [ ] **Step 1: Write the failing tests**

Create `desktop/tests/test_download_pg.py`:

```python
import unittest
from unittest import mock

from scripts.download_pg import artifact_platform, jar_url


class DownloadPgTests(unittest.TestCase):
    def test_platform_names_match_zonky_artifacts(self):
        with mock.patch("scripts.download_pg.sys.platform", "win32"):
            self.assertEqual(artifact_platform(), "windows-amd64")
        with mock.patch("scripts.download_pg.sys.platform", "darwin"):
            with mock.patch("scripts.download_pg.platform.machine", return_value="arm64"):
                self.assertEqual(artifact_platform(), "darwin-arm64v8")
            with mock.patch("scripts.download_pg.platform.machine", return_value="x86_64"):
                self.assertEqual(artifact_platform(), "darwin-amd64")

    def test_jar_url_points_at_maven_central(self):
        url = jar_url("windows-amd64")
        self.assertTrue(url.startswith("https://repo1.maven.org/maven2/io/zonky/test/postgres/"))
        self.assertTrue(url.endswith(".jar"))
        self.assertIn("embedded-postgres-binaries-windows-amd64", url)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run from `desktop/`: `python -m unittest tests.test_download_pg -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.download_pg'`

- [ ] **Step 3: Implement**

Create empty `desktop/scripts/__init__.py`, then `desktop/scripts/download_pg.py`:

```python
"""Download zonky.io embedded Postgres binaries for the current platform."""

import io
import platform
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

PG_VERSION = "16.4.0"
DEST = Path(__file__).resolve().parent.parent / "pgsql"


def artifact_platform() -> str:
    if sys.platform == "win32":
        return "windows-amd64"
    if sys.platform == "darwin":
        if platform.machine() == "arm64":
            return "darwin-arm64v8"
        return "darwin-amd64"
    return "linux-amd64"


def jar_url(plat: str) -> str:
    name = f"embedded-postgres-binaries-{plat}"
    return (
        "https://repo1.maven.org/maven2/io/zonky/test/postgres/"
        f"{name}/{PG_VERSION}/{name}-{PG_VERSION}.jar"
    )


def main() -> None:
    if (DEST / "bin").exists():
        print(f"pgsql already present at {DEST}")
        return
    DEST.mkdir(parents=True, exist_ok=True)
    url = jar_url(artifact_platform())
    print(f"downloading {url}")
    with urllib.request.urlopen(url) as resp:
        jar = io.BytesIO(resp.read())
    with zipfile.ZipFile(jar) as zf:
        txz_name = next(n for n in zf.namelist() if n.endswith(".txz"))
        txz = io.BytesIO(zf.read(txz_name))
    with tarfile.open(fileobj=txz, mode="r:xz") as tf:
        tf.extractall(DEST, filter="tar")  # "tar" keeps the +x bits binaries need
    print(f"extracted postgres to {DEST}")


if __name__ == "__main__":
    main()
```

Add to `.gitignore` (create the entry, keep existing content):

```
desktop/pgsql/
```

- [ ] **Step 4: Run tests, then run the script for real**

Run from `desktop/`: `python -m unittest tests.test_download_pg -v` — expected: 2 tests PASS.

Then run: `python scripts/download_pg.py`
Expected output ends with `extracted postgres to ...desktop\pgsql` and `desktop/pgsql/bin/pg_ctl.exe` exists (Windows).

- [ ] **Step 5: Dev-mode end-to-end sanity check (manual, this machine)**

From `desktop/` with backend deps installed, run: `set BACKCHANNEL_HEADLESS=1 && python launcher.py` in one shell; in another, `curl http://127.0.0.1:<port from %LOCALAPPDATA%\Backchannel\launcher.json>/api/health` returns `{"status":"ok"}`. Create `%LOCALAPPDATA%\Backchannel\stop` to shut it down cleanly. (Requires `cd frontend && npm run build` once so `frontend/dist` exists.)

- [ ] **Step 6: Commit**

```bash
git add desktop/scripts/__init__.py desktop/scripts/download_pg.py desktop/tests/test_download_pg.py .gitignore
git commit -m "feat: zonky Postgres download script"
```

---

### Task 7: PyInstaller spec

One-dir bundle: launcher entry point, backend `app` package baked in,
frontend dist + ONNX models + pgsql binaries as data, macOS `.app` wrapper.

**Files:**
- Create: `desktop/backchannel.spec`

**Interfaces:**
- Consumes: `desktop/launcher.py` (Task 5), `frontend/dist`, `backend/models`, `desktop/pgsql` on disk.
- Produces: `dist/Backchannel/` folder with `Backchannel(.exe)` binary; on macOS additionally `dist/Backchannel.app`. Task 8 smoke-tests it, Task 9 zips it.

- [ ] **Step 1: Write the spec**

Create `desktop/backchannel.spec`:

```python
# PyInstaller spec for the Backchannel desktop bundle (one-dir).
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

repo = Path(SPECPATH).parent

hidden = collect_submodules("app") + [
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
]
if sys.platform == "win32":
    hidden.append("pystray._win32")
elif sys.platform == "darwin":
    hidden.append("pystray._darwin")

a = Analysis(
    [str(repo / "desktop" / "launcher.py")],
    pathex=[str(repo / "backend"), str(repo / "desktop")],
    datas=[
        (str(repo / "frontend" / "dist"), "frontend"),
        (str(repo / "backend" / "models"), "models"),
        (str(repo / "desktop" / "pgsql"), "pgsql"),
    ],
    hiddenimports=hidden,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name="Backchannel",
    console=False,
)

coll = COLLECT(exe, a.binaries, a.datas, name="Backchannel")

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Backchannel.app",
        bundle_identifier="io.github.backchannel",
        # Menu-bar (tray) app: no Dock icon.
        info_plist={"LSUIElement": True},
    )
```

- [ ] **Step 2: Build locally to verify the spec parses and bundles**

Prereqs on this machine: `pip install -r desktop/requirements.txt`, `frontend/dist` built, models downloaded (`cd backend && python scripts/download_models.py`), pgsql downloaded (Task 6).

Run from repo root: `pyinstaller desktop/backchannel.spec --distpath dist --workpath build --noconfirm`
Expected: exits 0; `dist/Backchannel/Backchannel.exe` exists; `dist/Backchannel/_internal/frontend/index.html`, `_internal/models/silero_vad.onnx`, and `_internal/pgsql/bin/` all exist.

- [ ] **Step 3: Commit**

```bash
git add desktop/backchannel.spec
git commit -m "feat: PyInstaller spec for desktop bundle"
```

---

### Task 8: Bundle smoke test script

Runs the built bundle headless in an isolated temp data dir, asserts the
health endpoint answers, and asserts clean shutdown. Run locally and by CI.

**Files:**
- Create: `desktop/scripts/smoke_test.py`

**Interfaces:**
- Consumes: `dist/Backchannel/Backchannel(.exe)` (Task 7); launcher's `BACKCHANNEL_HEADLESS`/`BACKCHANNEL_DATA_DIR` env contract and `launcher.json`/`stop` files (Task 5).
- Produces: exit code 0 on success (CI gate).

- [ ] **Step 1: Write the script**

Create `desktop/scripts/smoke_test.py`:

```python
"""Smoke test the built desktop bundle: start headless, hit health, stop."""

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path


def bundle_exe() -> Path:
    exe = Path("dist") / "Backchannel" / "Backchannel"
    if sys.platform == "win32":
        exe = exe.with_suffix(".exe")
    if not exe.exists():
        raise SystemExit(f"bundle not found: {exe}")
    return exe


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        env = dict(
            os.environ, BACKCHANNEL_HEADLESS="1", BACKCHANNEL_DATA_DIR=tmp
        )
        proc = subprocess.Popen([str(bundle_exe())], env=env)
        lock = Path(tmp) / "launcher.json"
        try:
            deadline = time.monotonic() + 300  # first run does initdb
            port = None
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    print("FAIL: launcher exited early", file=sys.stderr)
                    return 1
                if lock.exists():
                    port = json.loads(lock.read_text())["port"]
                    break
                time.sleep(1)
            if port is None:
                print("FAIL: timed out waiting for launcher.json", file=sys.stderr)
                return 1
            url = f"http://127.0.0.1:{port}/api/health"
            with urllib.request.urlopen(url, timeout=5) as resp:
                body = resp.read().decode()
            if resp.status != 200 or "ok" not in body:
                print(f"FAIL: bad health response: {body}", file=sys.stderr)
                return 1
            print(f"OK: healthy on port {port}")
        finally:
            (Path(tmp) / "stop").touch()
            try:
                proc.wait(timeout=90)
            except subprocess.TimeoutExpired:
                proc.kill()
                print("FAIL: launcher did not shut down cleanly", file=sys.stderr)
                return 1
        if proc.returncode != 0:
            print(f"FAIL: exit code {proc.returncode}", file=sys.stderr)
            return 1
        print("OK: clean shutdown")
        return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run it against the local build**

Run from repo root: `python desktop/scripts/smoke_test.py`
Expected output:

```
OK: healthy on port <n>
OK: clean shutdown
```

If it fails, debug with the launcher log inside the temp dir before it is cleaned up (add a `input()` breakpoint temporarily) or run the bundle by hand with `BACKCHANNEL_HEADLESS=1 BACKCHANNEL_DATA_DIR=<some dir>`.

- [ ] **Step 3: Commit**

```bash
git add desktop/scripts/smoke_test.py
git commit -m "test: headless smoke test for the desktop bundle"
```

---

### Task 9: GitHub Actions release workflow

Build both platforms on version tags, smoke test, zip, attach to the
GitHub Release.

**Files:**
- Create: `.github/workflows/desktop-release.yml`

**Interfaces:**
- Consumes: everything from Tasks 5-8.
- Produces: `Backchannel-windows-x64.zip` and `Backchannel-macos-arm64.zip` on the GitHub Release for tag `v*`.

- [ ] **Step 1: Write the workflow**

Create `.github/workflows/desktop-release.yml`:

```yaml
name: Desktop release

on:
  push:
    tags: ["v*"]
  workflow_dispatch:

permissions:
  contents: write

jobs:
  build:
    strategy:
      fail-fast: false
      matrix:
        include:
          - os: windows-latest
            asset: Backchannel-windows-x64.zip
          - os: macos-latest
            asset: Backchannel-macos-arm64.zip
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-node@v4
        with:
          node-version: 20

      - name: Build frontend
        working-directory: frontend
        run: |
          npm ci
          npm run build

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install Python dependencies
        run: pip install -r backend/requirements.txt -r desktop/requirements.txt

      - name: Download ONNX models
        working-directory: backend
        run: python scripts/download_models.py

      - name: Download embedded Postgres
        run: python desktop/scripts/download_pg.py

      - name: Build bundle
        run: pyinstaller desktop/backchannel.spec --distpath dist --workpath build --noconfirm

      - name: Smoke test bundle
        run: python desktop/scripts/smoke_test.py

      - name: Zip (Windows)
        if: runner.os == 'Windows'
        run: Compress-Archive -Path dist/Backchannel -DestinationPath ${{ matrix.asset }}

      - name: Zip (macOS)
        if: runner.os == 'macOS'
        run: ditto -c -k --keepParent dist/Backchannel.app ${{ matrix.asset }}

      - name: Upload artifact
        uses: actions/upload-artifact@v4
        with:
          name: ${{ matrix.asset }}
          path: ${{ matrix.asset }}

      - name: Attach to release
        if: startsWith(github.ref, 'refs/tags/')
        uses: softprops/action-gh-release@v2
        with:
          files: ${{ matrix.asset }}
```

- [ ] **Step 2: Validate the workflow YAML**

Run: `python -c "import yaml, pathlib; yaml.safe_load(pathlib.Path('.github/workflows/desktop-release.yml').read_text()); print('yaml ok')"`
Expected: `yaml ok` (install pyyaml if missing: `pip install pyyaml`).

- [ ] **Step 3: Commit, then trigger a real run**

```bash
git add .github/workflows/desktop-release.yml
git commit -m "ci: desktop release builds for Windows and macOS"
```

After the branch is pushed, trigger via `gh workflow run desktop-release.yml` (workflow_dispatch) and confirm both matrix jobs go green with `gh run watch`. Fix forward if a platform-specific packaging issue surfaces (most likely candidates: a missing PyInstaller hidden import, or macOS tar permissions).

---

### Task 10: Documentation

README install section framing the two options; CLAUDE.md note about the
desktop path.

**Files:**
- Modify: `README.md` (installation/getting-started section)
- Modify: `CLAUDE.md` (Build & Run section)

**Interfaces:**
- Consumes: asset names from Task 9.

- [ ] **Step 1: Add the README section**

In `README.md`, add a "Run it" section ahead of the existing Docker instructions (adapt placement to the current README structure; keep existing Docker text as-is under the second option):

```markdown
## Run it

### Option 1: Desktop app (easiest)

Download the latest release for your platform from the
[Releases page](../../releases):

- `Backchannel-windows-x64.zip` - unzip, run `Backchannel.exe`.
  Windows SmartScreen will warn on first run because the build is
  unsigned: click "More info" then "Run anyway".
- `Backchannel-macos-arm64.zip` (Apple Silicon) - unzip, right-click
  `Backchannel.app` and choose "Open" the first time (unsigned build).

The app lives in your system tray / menu bar and opens Backchannel in your
default browser. Data is stored per-user (`%LOCALAPPDATA%\Backchannel` on
Windows, `~/Library/Application Support/Backchannel` on macOS).

Notes:
- MP3/M4A audio import needs `ffmpeg` on your PATH (WAV/FLAC/OGG work
  out of the box).
- The optional Sortformer diarizer is Docker-only; the desktop app uses
  the built-in lightweight diarizer.

### Option 2: Docker (isolated)

Keeps everything in containers, includes the optional Sortformer diarizer,
and doesn't touch your environment - at the cost of installing Docker and a
couple of extra setup steps.
```

- [ ] **Step 2: Update CLAUDE.md**

In `CLAUDE.md` under "Build & Run", add after the Docker Compose subsection:

```markdown
### Desktop bundle (Windows/macOS)

`desktop/` contains a PyInstaller launcher that runs the backend with an
embedded zonky.io PostgreSQL and serves the built frontend via
`FRONTEND_DIST`. Desktop tests: run `python -m unittest discover -s tests`
from `desktop/`. Local build: `pyinstaller desktop/backchannel.spec`;
release builds run in `.github/workflows/desktop-release.yml` on `v*` tags
(unsigned; Sortformer and ffmpeg are not bundled).
```

- [ ] **Step 3: Commit**

```bash
git add README.md CLAUDE.md
git commit -m "docs: desktop app install instructions"
```

Note: `README.md` has unrelated uncommitted changes in the working tree — stage only your hunks (`git add -p README.md`) or coordinate with the user before committing.
