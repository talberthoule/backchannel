"""Exercise one native release archive through staging, swap, and rollback."""

import argparse
import base64
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import zipfile
from contextlib import contextmanager
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[2]
for source in (ROOT, ROOT / "backend", ROOT / "desktop"):
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))

from app.services.update_service import LAUNCHERS, ROOT_NAMES, UpdateService
from app.services.update_signing import (
    TRUSTED_ASSETS,
    parse_release_signing_keys,
    public_update_descriptor,
    sign_platform_manifest,
    verify_update_descriptor,
)
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from updater import apply_update, instance_is_healthy
from desktop.scripts.smoke_test import dump_logs, stop_process


VERSION = "v999.0.0"
PRIVATE_KEY = bytes(range(32))
KEY_ID = "native-smoke"


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


def signed_descriptor(archive: Path, platform_id: str) -> tuple[dict, dict]:
    platform, filename, content_type = TRUSTED_ASSETS[platform_id]
    if archive.name != filename or archive.is_symlink():
        raise RuntimeError(f"expected archive filename {filename}")
    manifest = {
        "version": VERSION,
        "commit": "a" * 40,
        "published_at": "2099-01-01T00:00:00Z",
        "release_notes": "Native packaged update smoke.",
        "asset": {
            "id": platform_id,
            "platform": platform,
            "filename": filename,
            "size": archive.stat().st_size,
            "sha256": digest(archive),
            "key": f"releases/{VERSION}/{filename}",
            "content_type": content_type,
        },
    }
    signed = sign_platform_manifest(manifest, KEY_ID, PRIVATE_KEY)
    public = Ed25519PrivateKey.from_private_bytes(PRIVATE_KEY).public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    keys = {
        "active": KEY_ID,
        "keys": {
            KEY_ID: base64.urlsafe_b64encode(public).rstrip(b"=").decode(),
        },
    }
    return public_update_descriptor(signed), keys


def archive_links(archive: Path, platform_id: str) -> list[tuple[str, str, bool]]:
    links = []
    if platform_id == "linux-x64":
        with tarfile.open(archive, "r:gz") as source:
            for member in source.getmembers():
                if member.issym() or member.islnk():
                    links.append((member.name, member.linkname, member.islnk()))
    elif platform_id == "macos-arm64":
        with zipfile.ZipFile(archive) as source:
            for member in source.infolist():
                mode = (member.external_attr >> 16) & 0xFFFF
                if stat.S_ISLNK(mode):
                    links.append((
                        member.filename,
                        source.read(member).decode("utf-8"),
                        False,
                    ))
    return links


def assert_links(stage: Path, links: list[tuple[str, str, bool]]) -> None:
    for name, target, hard in links:
        path = stage / PurePosixPath(name)
        if hard:
            if not path.exists() or not os.path.samefile(path, stage / PurePosixPath(target)):
                raise RuntimeError(f"hard link was not preserved: {name}")
        elif not path.is_symlink() or os.readlink(path) != target:
            raise RuntimeError(f"symbolic link was not preserved: {name}")


class GracefulProcess:
    def __init__(self, process: subprocess.Popen, stop: Path):
        self.process = process
        self.stop = stop

    def poll(self):
        return self.process.poll()

    def wait(self, timeout=None):
        return self.process.wait(timeout=timeout)

    def terminate(self):
        if not stop_process(self.process, self.stop, timeout=90):
            self.process.terminate()

    def kill(self):
        self.process.kill()


def wait_for_health(
    app_data: Path, process: GracefulProcess, timeout: float = 300
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            dump_logs(app_data)
            raise RuntimeError(f"launcher exited {process.process.returncode}")
        if instance_is_healthy(app_data):
            return
        time.sleep(1)
    dump_logs(app_data)
    raise RuntimeError("launcher did not become healthy")


def stop(process: GracefulProcess) -> None:
    process.terminate()
    process.wait(timeout=10)
    if process.process.returncode != 0:
        raise RuntimeError(f"launcher exited {process.process.returncode}")


@contextmanager
def temporary_directory():
    # Resolve so plan paths survive the updater's symlink refusal on macOS,
    # where the runner TMPDIR sits under the /var -> /private/var symlink.
    root = Path(tempfile.mkdtemp(prefix="backchannel-update-smoke-")).resolve(strict=True)
    try:
        yield root
    finally:
        deadline = time.monotonic() + 30
        while root.exists():
            try:
                shutil.rmtree(root)
            except OSError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.5)


def ready(service: UpdateService, descriptor: dict) -> None:
    service._state.update({
        "state": "ready",
        "available_version": VERSION,
        "available_notes": descriptor["release_notes"],
        "published_at": descriptor["published_at"],
        "highest_seen_version": VERSION,
        "highest_seen_published_at": descriptor["published_at"],
        "filename": descriptor["asset"]["filename"],
        "size": descriptor["asset"]["size"],
        "downloaded": descriptor["asset"]["size"],
        "checked_at": "2099-01-01T00:00:00Z",
        "error": "",
        "blocked_reason": "",
    })
    with service._lock:
        service._save_locked()


def launcher_factory(app_data: Path, processes: list[GracefulProcess]):
    stop_path = app_data / "stop"

    def launch(args, cwd):
        stop_path.unlink(missing_ok=True)
        process = GracefulProcess(
            subprocess.Popen(args, cwd=cwd, env=os.environ.copy()),
            stop_path,
        )
        processes.append(process)
        return process

    return launch


def apply_success(
    service: UpdateService,
    app_data: Path,
    marker: Path,
    processes: list[GracefulProcess],
    launch,
) -> None:
    service.request_apply()
    result = apply_update(
        app_data / "updates" / "apply.json",
        process_factory=launch,
        pid_running=lambda _pid: False,
    )
    if result != 0 or marker.exists() or not processes:
        raise RuntimeError("native update swap failed")
    wait_for_health(app_data, processes[-1])
    stop(processes[-1])


def apply_forced_rollback(
    service: UpdateService,
    descriptor: dict,
    archive: Path,
    app_data: Path,
    install: Path,
    processes: list[GracefulProcess],
    launch,
) -> None:
    service._stage_archive(archive, descriptor)
    marker = install / "native-smoke-known-good"
    marker.write_text("known good", encoding="utf-8")
    ready(service, descriptor)
    service.request_apply()
    clock = [0.0]
    rejected_healthy = [False]

    def reject_health(data: Path) -> bool:
        if instance_is_healthy(data):
            rejected_healthy[0] = True
            clock[0] = 301.0
        return False

    result = apply_update(
        app_data / "updates" / "apply.json",
        process_factory=launch,
        health=reject_health,
        pid_running=lambda _pid: False,
        monotonic=lambda: clock[0],
    )
    if result != 1 or not rejected_healthy[0] or not marker.is_file():
        raise RuntimeError("native forced rollback failed")
    wait_for_health(app_data, processes[-1])
    stop(processes[-1])


def restore_environment(name: str, value: str | None) -> None:
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value


def kill_processes(processes: list[GracefulProcess]) -> None:
    for process in processes:
        if process.poll() is None:
            process.kill()


def run(archive: Path, platform_id: str) -> None:
    archive = archive.resolve(strict=True)
    descriptor, key_document = signed_descriptor(archive, platform_id)
    _, public_keys = parse_release_signing_keys(key_document)
    verify_update_descriptor(descriptor, platform_id, "1.0.0", public_keys)
    links = archive_links(archive, platform_id)

    with temporary_directory() as root:
        app_data = root / "app-data"
        install = root / ROOT_NAMES[platform_id]
        launcher = Path(LAUNCHERS[platform_id])
        install_launcher = install / launcher
        install_launcher.parent.mkdir(parents=True)
        install_launcher.write_bytes(b"placeholder")
        if platform_id != "windows-x64":
            install_launcher.chmod(0o755)
        helper = root / "BackchannelUpdater"
        helper.write_bytes(b"helper")
        keys_path = root / "keys.json"
        keys_path.write_text(json.dumps(key_document), encoding="utf-8")

        service = UpdateService(
            enabled=True,
            data_root=app_data,
            install_root=install,
            keys_path=keys_path,
            current_version="1.0.0",
            platform_id=platform_id,
            helper_path=helper,
        )
        service._state["available_version"] = VERSION
        service._stage_archive(archive, descriptor)
        staged = service.staged_root
        staged_launcher = staged / launcher
        if not staged_launcher.is_file() or staged_launcher.is_symlink():
            raise RuntimeError("staged launcher is missing")
        if platform_id != "windows-x64" and not os.access(staged_launcher, os.X_OK):
            raise RuntimeError("staged launcher is not executable")
        assert_links(service.stage_dir, links)

        shutil.rmtree(install)
        shutil.copytree(staged, install, symlinks=True)
        marker = install / "native-smoke-known-good"
        marker.write_text("known good", encoding="utf-8")
        ready(service, descriptor)

        original_headless = os.environ.get("BACKCHANNEL_HEADLESS")
        original_data = os.environ.get("BACKCHANNEL_DATA_DIR")
        os.environ["BACKCHANNEL_HEADLESS"] = "1"
        os.environ["BACKCHANNEL_DATA_DIR"] = str(app_data)
        processes = []
        launch = launcher_factory(app_data, processes)

        try:
            apply_success(service, app_data, marker, processes, launch)
            apply_forced_rollback(
                service, descriptor, archive, app_data, install, processes, launch
            )
        finally:
            restore_environment("BACKCHANNEL_HEADLESS", original_headless)
            restore_environment("BACKCHANNEL_DATA_DIR", original_data)
            kill_processes(processes)

    print(f"OK: native {platform_id} update and forced rollback")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--platform", required=True, choices=sorted(TRUSTED_ASSETS))
    args = parser.parse_args()
    try:
        run(args.archive, args.platform)
    except Exception as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
