"""Standalone stdlib updater for atomically swapping desktop bundles."""

import ctypes
import hmac
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable


INSTANCE_HEADER = "X-Backchannel-Instance"
VERSION = re.compile(r"^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
PLAN_FIELDS = {
    "schema",
    "version",
    "requested_at",
    "old_pid",
    "app_data_dir",
    "install_dir",
    "staged_dir",
    "backup_dir",
    "failed_dir",
    "launcher",
    "lock_path",
    "state_path",
}


class PlanError(ValueError):
    pass


@dataclass(frozen=True)
class ApplyPlan:
    version: str
    requested_at: str
    old_pid: int
    app_data_dir: Path
    install_dir: Path
    staged_dir: Path
    backup_dir: Path
    failed_dir: Path
    launcher: str
    lock_path: Path
    state_path: Path
    plan_path: Path


def expected_launcher() -> str:
    if sys.platform == "win32":
        return "Backchannel.exe"
    if sys.platform == "darwin":
        return "Contents/MacOS/Backchannel"
    if sys.platform.startswith("linux"):
        return "Backchannel"
    raise PlanError("unsupported updater platform")


def expected_root() -> str:
    return "Backchannel.app" if sys.platform == "darwin" else "Backchannel"


def _existing_path(value: object) -> Path:
    if not isinstance(value, str):
        raise PlanError("invalid path")
    path = Path(value)
    if not path.is_absolute() or path.is_symlink():
        raise PlanError("invalid path")
    try:
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise PlanError("missing path") from error
    if resolved != path:
        raise PlanError("symlinked path")
    return path


def _absent_path(value: object, parent: Path) -> Path:
    if not isinstance(value, str):
        raise PlanError("invalid path")
    path = Path(value)
    if (
        not path.is_absolute()
        or path.parent != parent
        or path.exists()
        or path.is_symlink()
        or path.parent.resolve(strict=True) != path.parent
    ):
        raise PlanError("invalid absent path")
    return path


def _validate_identity(value: object) -> dict:
    if not isinstance(value, dict) or set(value) != PLAN_FIELDS:
        raise PlanError("invalid plan shape")
    if value["schema"] != 1 or type(value["old_pid"]) is not int or value["old_pid"] <= 0:
        raise PlanError("invalid plan identity")
    if not isinstance(value["version"], str) or not VERSION.fullmatch(value["version"]):
        raise PlanError("invalid plan version")
    if (
        not isinstance(value["requested_at"], str)
        or not TIMESTAMP.fullmatch(value["requested_at"])
    ):
        raise PlanError("invalid plan timestamp")
    try:
        datetime.strptime(value["requested_at"], "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as error:
        raise PlanError("invalid plan timestamp") from error
    return value


def _bundle_roots(value: dict, plan_path: Path):
    plan_path = _existing_path(str(plan_path))
    app_data = _existing_path(value["app_data_dir"])
    updates = _existing_path(str(app_data / "updates"))
    if plan_path != updates / "apply.json":
        raise PlanError("invalid plan location")
    install = _existing_path(value["install_dir"])
    staged = _existing_path(value["staged_dir"])
    if (
        not install.is_dir()
        or not staged.is_dir()
        or install.name != expected_root()
        or staged.name != expected_root()
    ):
        raise PlanError("invalid bundle roots")
    expected_stage_parent = install.parent / f".backchannel-stage-{value['version']}"
    if staged.parent != expected_stage_parent or staged.parent.resolve(strict=True) != staged.parent:
        raise PlanError("invalid staging root")
    return plan_path, app_data, updates, install, staged


def _recovery_paths(value: dict, install: Path):
    backup = _absent_path(
        value["backup_dir"], install.parent
    )
    failed = _absent_path(
        value["failed_dir"], install.parent
    )
    if backup.name != f"{install.name}.backup-{value['version']}":
        raise PlanError("invalid backup path")
    if failed.name != f"{install.name}.failed-{value['version']}":
        raise PlanError("invalid failed path")
    return backup, failed


def _validate_launcher(value: dict, install: Path, staged: Path) -> str:
    launcher = value["launcher"]
    if launcher != expected_launcher():
        raise PlanError("invalid launcher")
    for root in (install, staged):
        executable = root / Path(launcher)
        if not executable.is_file() or executable.is_symlink():
            raise PlanError("launcher is unavailable")
    return launcher


def _runtime_paths(
    value: dict,
    app_data: Path,
    updates: Path,
    install: Path,
    staged: Path,
):
    lock_path = Path(value["lock_path"]) if isinstance(value["lock_path"], str) else Path()
    state_path = _existing_path(value["state_path"])
    if (
        not lock_path.is_absolute()
        or lock_path != app_data / "launcher.json"
        or state_path != updates / "state.json"
        or lock_path.parent.resolve(strict=True) != app_data
    ):
        raise PlanError("invalid runtime paths")
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise PlanError("invalid update state") from error
    if (
        not isinstance(state, dict)
        or state.get("state") != "applying"
        or state.get("available_version") != value["version"]
    ):
        raise PlanError("update is not applying")
    if os.stat(install.parent).st_dev != os.stat(staged).st_dev:
        raise PlanError("cross-filesystem update")
    return lock_path, state_path


def validate_plan(value: object, plan_path: Path) -> ApplyPlan:
    value = _validate_identity(value)
    plan_path, app_data, updates, install, staged = _bundle_roots(
        value, plan_path
    )
    backup, failed = _recovery_paths(value, install)
    launcher = _validate_launcher(value, install, staged)
    lock_path, state_path = _runtime_paths(
        value, app_data, updates, install, staged
    )

    return ApplyPlan(
        version=value["version"],
        requested_at=value["requested_at"],
        old_pid=value["old_pid"],
        app_data_dir=app_data,
        install_dir=install,
        staged_dir=staged,
        backup_dir=backup,
        failed_dir=failed,
        launcher=launcher,
        lock_path=lock_path,
        state_path=state_path,
        plan_path=plan_path,
    )


def _read_plan(path: Path) -> ApplyPlan:
    if not path.is_absolute():
        raise PlanError("plan path must be absolute")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise PlanError("plan could not be read") from error
    return validate_plan(value, path)


def _pid_running(pid: int) -> bool:
    if sys.platform == "win32":
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def instance_is_healthy(app_data: Path) -> bool:
    try:
        lock = json.loads((app_data / "launcher.json").read_text(encoding="utf-8"))
        if not isinstance(lock, dict) or set(lock) != {"port", "pid", "token"}:
            return False
        port = lock["port"]
        token = lock["token"]
        if (
            type(port) is not int
            or port < 1
            or port > 65535
            or not isinstance(token, str)
            or not token
        ):
            return False
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/health", timeout=2
        ) as response:
            body = response.read(1025)
            return (
                response.status == 200
                and len(body) <= 1024
                and hmac.compare_digest(response.headers.get(INSTANCE_HEADER, ""), token)
                and json.loads(body.decode("utf-8")) == {"status": "ok"}
            )
    except Exception:
        return False


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, separators=(",", ":"))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _record(plan: ApplyPlan, status: str, message: str) -> None:
    _write_json(
        plan.app_data_dir / "updates" / "rollback.json",
        {"version": plan.version, "status": status, "message": message},
    )
    try:
        state = json.loads(plan.state_path.read_text(encoding="utf-8"))
        if isinstance(state, dict):
            state["state"] = "error"
            state["error"] = message
            _write_json(plan.state_path, state)
    except Exception:
        pass


def _wait_for_shutdown(
    plan: ApplyPlan,
    pid_running: Callable[[int], bool],
    monotonic: Callable[[], float],
    sleep: Callable[[float], None],
) -> bool:
    deadline = monotonic() + 60
    while pid_running(plan.old_pid) or plan.lock_path.exists():
        if monotonic() >= deadline:
            return False
        sleep(0.25)
    return True


def _wait_for_health(
    plan: ApplyPlan,
    process,
    health: Callable[[Path], bool],
    monotonic: Callable[[], float],
    sleep: Callable[[float], None],
) -> bool:
    deadline = monotonic() + 300
    while True:
        if process.poll() is not None:
            return False
        if health(plan.app_data_dir):
            return True
        if monotonic() >= deadline:
            return False
        sleep(1)


def _stop_process(process) -> None:
    if process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=10)
    except Exception:
        try:
            process.kill()
        except Exception:
            pass


def _launch(process_factory, root: Path, launcher: str):
    return process_factory([str(root / Path(launcher))], cwd=str(root))


def _rollback(plan: ApplyPlan, process, process_factory) -> int:
    _stop_process(process)
    try:
        if plan.install_dir.exists():
            if plan.failed_dir.exists():
                raise OSError("failed bundle path already exists")
            os.replace(plan.install_dir, plan.failed_dir)
        os.replace(plan.backup_dir, plan.install_dir)
        _launch(process_factory, plan.install_dir, plan.launcher)
        _record(
            plan,
            "rolled_back",
            "The update did not start. The previous version is running.",
        )
        plan.plan_path.unlink(missing_ok=True)
        return 1
    except Exception:
        _record(
            plan,
            "manual_recovery_required",
            "Automatic rollback failed. Recovery files were preserved.",
        )
        return 2


def apply_update(
    plan_path: Path,
    *,
    process_factory=subprocess.Popen,
    health: Callable[[Path], bool] = instance_is_healthy,
    pid_running: Callable[[int], bool] = _pid_running,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    plan = _read_plan(Path(plan_path))
    if not _wait_for_shutdown(plan, pid_running, monotonic, sleep):
        _record(
            plan,
            "not_applied",
            "The previous version did not finish shutting down.",
        )
        plan.plan_path.unlink(missing_ok=True)
        return 1

    try:
        os.replace(plan.install_dir, plan.backup_dir)
    except OSError:
        _record(
            plan,
            "not_applied",
            "The current installation could not be prepared for update.",
        )
        plan.plan_path.unlink(missing_ok=True)
        return 1
    try:
        os.replace(plan.staged_dir, plan.install_dir)
        process = _launch(process_factory, plan.install_dir, plan.launcher)
    except Exception:
        process = None
    if process is None:
        class FailedProcess:
            @staticmethod
            def poll():
                return 1

        process = FailedProcess()
    if not _wait_for_health(plan, process, health, monotonic, sleep):
        return _rollback(plan, process, process_factory)

    shutil.rmtree(plan.backup_dir)
    plan.plan_path.unlink(missing_ok=True)
    plan.state_path.unlink(missing_ok=True)
    (plan.app_data_dir / "updates" / "rollback.json").unlink(missing_ok=True)
    shutil.rmtree(plan.app_data_dir / "updates" / plan.version, ignore_errors=True)
    try:
        plan.staged_dir.parent.rmdir()
    except OSError:
        pass
    return 0


def main() -> int:
    if len(sys.argv) != 2:
        return 2
    try:
        return apply_update(Path(sys.argv[1]))
    except Exception:
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
