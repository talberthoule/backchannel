import hashlib
import hmac
import json
import math
import os
import posixpath
import re
import shutil
import ssl
import stat
import subprocess
import sys
import tarfile
import threading
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath

import certifi

from app.release_notes import APP_VERSION
from app.services.secrets import data_dir
from app.services.update_signing import (
    TRUSTED_ASSETS,
    parse_release_signing_keys,
    verify_update_descriptor,
)


CHUNK_SIZE = 1024 * 1024
MAX_DESCRIPTOR_BYTES = 64 * 1024
MAX_EXPANDED_BYTES = 20 * 1024 * 1024 * 1024
CACHE_AGE = timedelta(hours=24)
GRANT_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")
ROOT_NAMES = {
    "windows-x64": "Backchannel",
    "linux-x64": "Backchannel",
    "macos-arm64": "Backchannel.app",
}
LAUNCHERS = {
    "windows-x64": "Backchannel.exe",
    "linux-x64": "Backchannel",
    "macos-arm64": "Contents/MacOS/Backchannel",
}
STATE_FIELDS = {
    "enabled",
    "state",
    "current_version",
    "available_version",
    "available_notes",
    "published_at",
    "highest_seen_version",
    "highest_seen_published_at",
    "platform_id",
    "filename",
    "size",
    "downloaded",
    "checked_at",
    "error",
    "blocked_reason",
}


class InvalidUpdate(ValueError):
    pass


class NeedsAuthorization(RuntimeError):
    pass


def _version(value: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", value)
    if not match:
        raise InvalidUpdate("invalid version")
    return tuple(map(int, match.groups()))


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _platform_id() -> str | None:
    machine = __import__("platform").machine().lower()
    if sys.platform == "win32" and machine in {"amd64", "x86_64"}:
        return "windows-x64"
    if sys.platform == "darwin" and machine in {"arm64", "aarch64"}:
        return "macos-arm64"
    if sys.platform.startswith("linux") and machine in {"amd64", "x86_64"}:
        return "linux-x64"
    return None


class UpdateService:
    def __init__(
        self,
        *,
        enabled: bool | None = None,
        data_root: Path | str | None = None,
        install_root: Path | str | None = None,
        keys_path: Path | str | None = None,
        current_version: str = APP_VERSION,
        platform_id: str | None = None,
        descriptor_url: str = "https://downloads.backchannel.page/api/update/latest/{platform_id}",
        asset_url: str = "https://downloads.backchannel.page/api/update/assets/{version}/{platform_id}",
        timeout: float = 5,
        apply_disabled: bool | None = None,
        helper_path: Path | str | None = None,
    ):
        self.enabled = (
            os.environ.get("BACKCHANNEL_DESKTOP") == "1" if enabled is None else enabled
        )
        self._lock = threading.Lock()
        self._check_done = threading.Event()
        self._check_done.set()
        self._checking = False
        self._download_thread: threading.Thread | None = None
        self._cancel = threading.Event()
        if not self.enabled:
            return

        normalized_version = current_version.removeprefix("v")
        self.current_version = f"v{normalized_version}"
        _version(self.current_version)
        self.platform_id = platform_id or _platform_id()
        if self.platform_id not in ROOT_NAMES:
            raise ValueError("unsupported update platform")
        runtime_data = Path(data_root) if data_root else data_dir().parent
        self.data_root = runtime_data.resolve()
        self.update_root = self.data_root / "updates"
        self.state_path = self.update_root / "state.json"
        raw_install = install_root or os.environ.get("BACKCHANNEL_INSTALL_DIR")
        raw_keys = keys_path or os.environ.get("BACKCHANNEL_UPDATE_KEYS")
        if not raw_install or not raw_keys:
            raise ValueError("desktop update paths are not configured")
        self.install_root = Path(raw_install).resolve()
        self.keys_path = Path(raw_keys).resolve()
        self.descriptor_url = descriptor_url
        self.asset_url = asset_url
        self.timeout = timeout
        self.apply_disabled = (
            os.environ.get("BACKCHANNEL_UPDATE_APPLY_DISABLED") == "1"
            if apply_disabled is None
            else apply_disabled
        )
        raw_helper = helper_path or os.environ.get("BACKCHANNEL_UPDATE_HELPER")
        self.helper_path = Path(raw_helper).resolve() if raw_helper else None
        _, self.public_keys = parse_release_signing_keys(
            json.loads(self.keys_path.read_text(encoding="utf-8"))
        )
        self._state = self._load_state()

    def _default_state(self) -> dict:
        return {
            "enabled": True,
            "state": "idle",
            "current_version": self.current_version,
            "available_version": "",
            "available_notes": "",
            "published_at": "",
            "highest_seen_version": "",
            "highest_seen_published_at": "",
            "platform_id": self.platform_id,
            "filename": "",
            "size": 0,
            "downloaded": 0,
            "checked_at": "",
            "error": "",
            "blocked_reason": "",
        }

    def _load_state(self) -> dict:
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
            if not isinstance(value, dict) or set(value) != STATE_FIELDS:
                raise ValueError
            if (
                value["current_version"] != self.current_version
                or value["platform_id"] != self.platform_id
                or type(value["size"]) is not int
                or type(value["downloaded"]) is not int
            ):
                raise ValueError
            return value
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return self._default_state()

    def _save_locked(self) -> None:
        self.update_root.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(self._state, stream, sort_keys=True, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.state_path)

    def _copy_status_locked(self) -> dict:
        return dict(self._state)

    def status(self) -> dict:
        if not self.enabled:
            return {"enabled": False, "state": "idle"}
        with self._lock:
            self._clear_stale_apply_locked()
            return self._copy_status_locked()

    def _clear_stale_apply_locked(self) -> None:
        marker = self.update_root / "apply.json"
        if self._state["state"] != "applying":
            return
        if not marker.exists():
            self._state["state"] = "ready"
            self._state["error"] = ""
            self._save_locked()
            return
        try:
            stale = _utc_now().timestamp() - marker.stat().st_mtime >= 60
        except OSError:
            stale = False
        if stale:
            marker.unlink(missing_ok=True)
            self._state["state"] = "ready"
            self._state["error"] = ""
            self._save_locked()

    def _cached_locked(self) -> bool:
        if self._state["state"] == "error" or not self._state["checked_at"]:
            return False
        try:
            checked = _timestamp(self._state["checked_at"])
        except (ValueError, TypeError):
            return False
        return _utc_now() - checked < CACHE_AGE

    def _fetch_descriptor(self) -> dict:
        request = urllib.request.Request(
            self.descriptor_url.format(platform_id=self.platform_id),
            headers={"Accept": "application/json"},
        )
        context = ssl.create_default_context(cafile=certifi.where())
        with urllib.request.urlopen(
            request, timeout=self.timeout, context=context
        ) as response:
            if getattr(response, "status", 200) != 200:
                raise InvalidUpdate("descriptor request failed")
            body = response.read(MAX_DESCRIPTOR_BYTES + 1)
        if len(body) > MAX_DESCRIPTOR_BYTES:
            raise InvalidUpdate("descriptor is too large")
        try:
            raw = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise InvalidUpdate("descriptor is invalid") from error
        try:
            value = verify_update_descriptor(
                raw, self.platform_id, "0.0.0", self.public_keys
            )
        except ValueError as error:
            raise InvalidUpdate("descriptor verification failed") from error
        with self._lock:
            high_version = self._state["highest_seen_version"]
            high_time = self._state["highest_seen_published_at"]
        if high_version and _version(value["version"]) < _version(high_version):
            raise InvalidUpdate("descriptor replay")
        if high_time and _timestamp(value["published_at"]) < _timestamp(high_time):
            raise InvalidUpdate("descriptor replay")
        return value

    def _claim_check(self, force: bool):
        with self._lock:
            if not force and self._cached_locked():
                return self._copy_status_locked(), None
            if self._checking:
                return None, self._check_done
            self._checking = True
            self._check_done.clear()
            return None, None

    def _store_descriptor_locked(self, descriptor: dict) -> None:
        current_high = self._state["highest_seen_version"]
        current_time = self._state["highest_seen_published_at"]
        if not current_high or _version(descriptor["version"]) > _version(current_high):
            self._state["highest_seen_version"] = descriptor["version"]
        if not current_time or _timestamp(descriptor["published_at"]) > _timestamp(current_time):
            self._state["highest_seen_published_at"] = descriptor["published_at"]
        if _version(descriptor["version"]) <= _version(self.current_version):
            next_state = "idle"
            available = ("", "", "", "", 0)
        else:
            same_ready = (
                self._state["state"] == "ready"
                and self._state["available_version"] == descriptor["version"]
            )
            next_state = "ready" if same_ready else "available"
            asset = descriptor["asset"]
            available = (
                descriptor["version"],
                descriptor["release_notes"],
                descriptor["published_at"],
                asset["filename"],
                asset["size"],
            )
        (
            self._state["available_version"],
            self._state["available_notes"],
            self._state["published_at"],
            self._state["filename"],
            self._state["size"],
        ) = available
        self._state["state"] = next_state
        self._state["downloaded"] = (
            self._state["size"] if next_state == "ready" else 0
        )
        self._state["checked_at"] = _utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")
        self._state["error"] = ""
        self._state["blocked_reason"] = ""
        self._save_locked()

    def check(self, force: bool = False) -> dict:
        if not self.enabled:
            return {"enabled": False, "state": "idle"}
        cached, done = self._claim_check(force)
        if cached is not None:
            return cached
        if done is not None:
            done.wait(self.timeout + 1)
            return self.status()

        try:
            descriptor = self._fetch_descriptor()
            with self._lock:
                self._store_descriptor_locked(descriptor)
        except Exception:
            with self._lock:
                self._state["state"] = "error"
                self._state["error"] = "Update information could not be verified."
                self._state["blocked_reason"] = ""
                self._save_locked()
        finally:
            with self._lock:
                self._checking = False
                self._check_done.set()
        return self.status()

    @property
    def partial_path(self) -> Path:
        version = self._state["available_version"]
        filename = self._state["filename"]
        if not version or not filename:
            raise RuntimeError("no update is available")
        return self.update_root / version / f"{filename}.partial"

    @property
    def stage_dir(self) -> Path:
        version = self._state["available_version"]
        if not version:
            raise RuntimeError("no update is available")
        return self.install_root.parent / f".backchannel-stage-{version}"

    @property
    def staged_root(self) -> Path:
        return self.stage_dir / ROOT_NAMES[self.platform_id]

    def start_download(self, grant: str) -> dict:
        if not self.enabled:
            return {"enabled": False, "state": "idle"}
        if not GRANT_RE.fullmatch(grant or ""):
            raise ValueError("invalid update grant")
        with self._lock:
            if self._download_thread and self._download_thread.is_alive():
                return self._copy_status_locked()
            if self._state["state"] not in {"available", "needs_authorization"}:
                raise RuntimeError("update is not ready to download")
            self._cancel.clear()
            self._state["state"] = "downloading"
            self._state["error"] = ""
            self._state["blocked_reason"] = ""
            self._save_locked()
            self._download_thread = threading.Thread(
                target=self._download, args=(grant,), daemon=True
            )
            self._download_thread.start()
            return self._copy_status_locked()

    def wait_for_download(self, timeout: float = 30) -> None:
        thread = self._download_thread
        if thread:
            thread.join(timeout)

    def cancel_download(self) -> dict:
        if not self.enabled:
            return {"enabled": False, "state": "idle"}
        self._cancel.set()
        return self.status()

    def _asset_request(self, grant: str, start: int | None):
        headers = {
            "Accept": "application/octet-stream",
            "Authorization": f"Bearer {grant}",
        }
        if start is not None:
            headers["Range"] = f"bytes={start}-"
        request = urllib.request.Request(
            self.asset_url.format(
                version=self._state["available_version"],
                platform_id=self.platform_id,
            ),
            headers=headers,
        )
        try:
            return urllib.request.urlopen(
                request,
                timeout=self.timeout,
                context=ssl.create_default_context(cafile=certifi.where()),
            )
        except urllib.error.HTTPError as error:
            if error.code in {401, 403, 404}:
                raise NeedsAuthorization from error
            raise

    def _progress(self, downloaded: int) -> None:
        with self._lock:
            self._state["downloaded"] = downloaded
            self._save_locked()

    def _available_descriptor(self) -> dict:
        descriptor = self._fetch_descriptor()
        expected = (
            self._state["available_version"],
            self._state["published_at"],
            self._state["filename"],
            self._state["size"],
        )
        actual = (
            descriptor["version"],
            descriptor["published_at"],
            descriptor["asset"]["filename"],
            descriptor["asset"]["size"],
        )
        if actual != expected:
            raise InvalidUpdate("available update changed")
        return descriptor

    def _resume_digest(self, partial: Path, size: int):
        partial.parent.mkdir(parents=True, exist_ok=True)
        start = partial.stat().st_size if partial.exists() else 0
        if start > size:
            partial.unlink()
            start = 0
        digest = hashlib.sha256()
        if start:
            with partial.open("rb") as existing:
                while chunk := existing.read(CHUNK_SIZE):
                    digest.update(chunk)
        self._progress(start)
        return start, digest

    def _open_download(self, grant: str, start: int, size: int):
        response = self._asset_request(grant, start if start else None)
        status = getattr(response, "status", None)
        if start and status == 206:
            wanted = f"bytes {start}-{size - 1}/{size}"
            if response.headers.get("Content-Range") == wanted:
                return response, start, None
            response.close()
            response = self._asset_request(grant, None)
            if getattr(response, "status", None) != 200:
                response.close()
                raise InvalidUpdate("invalid download response")
            return response, 0, hashlib.sha256()
        if start and status == 200:
            return response, 0, hashlib.sha256()
        if status != 200:
            response.close()
            raise InvalidUpdate("invalid download response")
        return response, start, None

    def _stream_download(
        self, response, partial: Path, start: int, size: int, digest
    ) -> int | None:
        mode = "ab" if start else "wb"
        downloaded = start
        with response, partial.open(mode) as output:
            while chunk := response.read(CHUNK_SIZE):
                if self._cancel.is_set():
                    with self._lock:
                        self._state["state"] = "available"
                        self._state["downloaded"] = downloaded
                        self._save_locked()
                    return None
                downloaded += len(chunk)
                if downloaded > size:
                    raise InvalidUpdate("download exceeded declared size")
                output.write(chunk)
                digest.update(chunk)
                self._progress(downloaded)
            output.flush()
            os.fsync(output.fileno())
        return downloaded

    def _verify_download(
        self, partial: Path, descriptor: dict, digest, downloaded: int
    ) -> None:
        asset = descriptor["asset"]
        if downloaded != asset["size"]:
            raise InvalidUpdate("download was shorter than declared size")
        if not hmac.compare_digest(digest.hexdigest(), asset["sha256"]):
            raise InvalidUpdate("download hash mismatch")
        verify_update_descriptor(
            descriptor, self.platform_id, self.current_version, self.public_keys
        )
        self._stage_archive(partial, descriptor)
        with self._lock:
            self._state["state"] = "ready"
            self._state["downloaded"] = downloaded
            self._state["error"] = ""
            self._save_locked()

    def _download(self, grant: str) -> None:
        partial = self.partial_path
        try:
            descriptor = self._available_descriptor()
            start, digest = self._resume_digest(
                partial, descriptor["asset"]["size"]
            )
            response, start, replacement = self._open_download(
                grant, start, descriptor["asset"]["size"]
            )
            digest = replacement or digest
            downloaded = self._stream_download(
                response, partial, start, descriptor["asset"]["size"], digest
            )
            if downloaded is None:
                return
            self._verify_download(partial, descriptor, digest, downloaded)
        except NeedsAuthorization:
            with self._lock:
                self._state["state"] = "needs_authorization"
                self._state["error"] = ""
                self._state["downloaded"] = partial.stat().st_size if partial.exists() else 0
                self._save_locked()
        except InvalidUpdate:
            partial.unlink(missing_ok=True)
            self._remove_stage()
            self._download_error("The update failed verification.")
        except Exception:
            self._download_error("The update download could not be completed.")

    def _download_error(self, message: str) -> None:
        with self._lock:
            self._state["state"] = "error"
            self._state["error"] = message
            self._state["downloaded"] = (
                self.partial_path.stat().st_size if self.partial_path.exists() else 0
            )
            self._save_locked()

    def _remove_stage(self) -> None:
        stage = self.stage_dir
        if stage.exists():
            shutil.rmtree(stage)

    def _safe_path(self, name: str) -> PurePosixPath:
        if not name or "\\" in name or "\x00" in name or name.startswith("/"):
            raise InvalidUpdate("unsafe archive path")
        path = PurePosixPath(name.rstrip("/"))
        if (
            not path.parts
            or path.parts[0] != ROOT_NAMES[self.platform_id]
            or any(part in {"", ".", ".."} for part in path.parts)
            or (self.platform_id == "windows-x64" and any(":" in part for part in path.parts))
        ):
            raise InvalidUpdate("unsafe archive path")
        return path

    def _safe_link(self, member: PurePosixPath, target: str, *, hard: bool = False) -> None:
        if not target or "\\" in target or "\x00" in target:
            raise InvalidUpdate("unsafe archive link")
        link = PurePosixPath(target)
        if link.is_absolute():
            raise InvalidUpdate("unsafe archive link")
        base = PurePosixPath() if hard else member.parent
        normalized = PurePosixPath(posixpath.normpath(str(base / link)))
        if not normalized.parts or normalized.parts[0] != ROOT_NAMES[self.platform_id]:
            raise InvalidUpdate("unsafe archive link")
        if ".." in normalized.parts:
            raise InvalidUpdate("unsafe archive link")

    def _zip_size(self, archive_path: Path) -> int:
        expanded = 0
        with zipfile.ZipFile(archive_path) as archive:
            for info in archive.infolist():
                member = self._safe_path(info.filename)
                mode = (info.external_attr >> 16) & 0xFFFF
                kind = stat.S_IFMT(mode)
                if stat.S_ISLNK(mode):
                    if self.platform_id != "macos-arm64" or info.file_size > 4096:
                        raise InvalidUpdate("unsupported archive link")
                    try:
                        target = archive.read(info).decode("utf-8")
                    except UnicodeDecodeError as error:
                        raise InvalidUpdate("invalid archive link") from error
                    self._safe_link(member, target)
                elif kind not in {0, stat.S_IFREG, stat.S_IFDIR}:
                    raise InvalidUpdate("unsupported archive entry")
                elif not info.is_dir():
                    expanded += info.file_size
                if expanded > MAX_EXPANDED_BYTES:
                    raise InvalidUpdate("archive expands beyond limit")
        return expanded

    def _tar_size(self, archive_path: Path) -> int:
        expanded = 0
        with tarfile.open(archive_path, "r:gz") as archive:
            for info in archive.getmembers():
                member = self._safe_path(info.name)
                if info.issym():
                    self._safe_link(member, info.linkname)
                elif info.islnk():
                    self._safe_link(member, info.linkname, hard=True)
                elif info.isfile():
                    expanded += info.size
                elif not info.isdir():
                    raise InvalidUpdate("unsupported archive entry")
                if expanded > MAX_EXPANDED_BYTES:
                    raise InvalidUpdate("archive expands beyond limit")
        return expanded

    @staticmethod
    def _tree_size(root: Path) -> int:
        total = 0
        for path in root.rglob("*"):
            if path.is_file() and not path.is_symlink():
                total += path.stat().st_size
        return total

    def _stage_archive(self, archive_path: Path, descriptor: dict) -> None:
        if self.platform_id == "linux-x64":
            expanded = self._tar_size(archive_path)
        else:
            expanded = self._zip_size(archive_path)
        installed = self._tree_size(self.install_root)
        required = math.ceil(
            (descriptor["asset"]["size"] + expanded + installed) * 1.1
        )
        if shutil.disk_usage(self.install_root.parent)[2] < required:
            raise InvalidUpdate("insufficient update space")

        self._remove_stage()
        self.stage_dir.mkdir(parents=True)
        try:
            if self.platform_id == "linux-x64":
                with tarfile.open(archive_path, "r:gz") as archive:
                    archive.extractall(self.stage_dir, filter="data")
            elif self.platform_id == "macos-arm64":
                subprocess.run(
                    ["/usr/bin/ditto", "-x", "-k", str(archive_path), str(self.stage_dir)],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
                with zipfile.ZipFile(archive_path) as archive:
                    archive.extractall(self.stage_dir)
            children = list(self.stage_dir.iterdir())
            if children != [self.staged_root] or not self.staged_root.is_dir():
                raise InvalidUpdate("archive root mismatch")
        except InvalidUpdate:
            self._remove_stage()
            raise
        except (zipfile.BadZipFile, tarfile.TarError, subprocess.CalledProcessError, UnicodeError) as error:
            self._remove_stage()
            raise InvalidUpdate("archive extraction failed") from error
        except Exception:
            self._remove_stage()
            raise

    def _apply_bundle_paths_locked(self):
        if self._state["state"] != "ready":
            raise RuntimeError("The update is not ready to install.")
        if (
            not self.install_root.is_dir()
            or self.install_root.is_symlink()
            or not self.staged_root.is_dir()
            or self.staged_root.is_symlink()
            or not self.helper_path
            or not self.helper_path.is_file()
        ):
            raise RuntimeError("The staged update is unavailable.")
        parent = self.install_root.parent.resolve(strict=True)
        install = self.install_root.resolve(strict=True)
        staged = self.staged_root.resolve(strict=True)
        if install.parent != parent or staged.parent != self.stage_dir.resolve(strict=True):
            raise RuntimeError("The staged update path is invalid.")
        if os.stat(parent).st_dev != os.stat(staged).st_dev or not os.access(parent, os.W_OK):
            raise RuntimeError("The install location cannot be updated safely.")
        return parent, install, staged

    def _apply_plan_locked(self) -> dict:
        parent, install, staged = self._apply_bundle_paths_locked()
        version = self._state["available_version"]
        backup = parent / f"{self.install_root.name}.backup-{version}"
        failed = parent / f"{self.install_root.name}.failed-{version}"
        if backup.exists() or failed.exists() or backup.is_symlink() or failed.is_symlink():
            raise RuntimeError("A previous update needs recovery.")
        launcher = LAUNCHERS[self.platform_id]
        if not (install / Path(launcher)).is_file():
            raise RuntimeError("The current launcher is unavailable.")
        return {
            "schema": 1,
            "version": version,
            "requested_at": _utc_now().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "old_pid": os.getpid(),
            "app_data_dir": str(self.data_root),
            "install_dir": str(install),
            "staged_dir": str(staged),
            "backup_dir": str(backup),
            "failed_dir": str(failed),
            "launcher": launcher,
            "lock_path": str(self.data_root / "launcher.json"),
            "state_path": str(self.state_path.resolve(strict=True)),
        }

    def _write_apply_plan_locked(self, plan: dict) -> None:
        self._state["state"] = "applying"
        self._state["error"] = ""
        self._save_locked()
        marker = self.update_root / "apply.json"
        temporary = marker.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(plan, stream, sort_keys=True, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, marker)

    def request_apply(self) -> dict:
        if not self.enabled:
            return {"enabled": False, "state": "idle"}
        if self.apply_disabled:
            raise RuntimeError("Update installation is unavailable in headless mode.")
        with self._lock:
            self._write_apply_plan_locked(self._apply_plan_locked())
            return self._copy_status_locked()


_service: UpdateService | None = None


def get_update_service() -> UpdateService:
    global _service
    if _service is None:
        _service = UpdateService()
    return _service
