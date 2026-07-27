import base64
import hashlib
import io
import json
import os
import ssl
import stat
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import unittest
import urllib.error
import zipfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database import get_db
from app.routers import updates
from app.services import runtime_activity
from app.services.update_service import CHUNK_SIZE, InvalidUpdate, UpdateService
from app.services.update_service import get_update_service
from app.services.update_signing import public_update_descriptor, sign_platform_manifest


PRIVATE_KEY = bytes(range(32))
KEY_ID = "test-key"
GRANT = "g" * 43


def zip_bundle(files=None) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, body in (files or {"Backchannel/Backchannel.exe": b"app"}).items():
            archive.writestr(name, body)
    return output.getvalue()


def descriptor(archive: bytes, version="v0.4.0", published_at="2026-07-26T18:00:00Z"):
    manifest = {
        "version": version,
        "commit": "a" * 40,
        "published_at": published_at,
        "release_notes": "Security and reliability fixes.",
        "asset": {
            "id": "windows-x64",
            "platform": "Windows x64",
            "filename": "Backchannel-windows-x64.zip",
            "size": len(archive),
            "sha256": hashlib.sha256(archive).hexdigest(),
            "key": f"releases/{version}/Backchannel-windows-x64.zip",
            "content_type": "application/zip",
        },
    }
    return public_update_descriptor(sign_platform_manifest(manifest, KEY_ID, PRIVATE_KEY))


class UpdateFixture:
    def __init__(self, descriptor_value, archive):
        self.descriptor = descriptor_value
        self.archive = archive
        self.descriptor_requests = 0
        self.asset_requests = []
        self.descriptor_delay = 0
        self.asset_status = 200
        self.ignore_range = False
        self.wrong_range = False
        self.slow_asset = False
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                if self.path.startswith("/latest/"):
                    fixture.descriptor_requests += 1
                    if fixture.descriptor_delay:
                        time.sleep(fixture.descriptor_delay)
                    body = (
                        fixture.descriptor
                        if isinstance(fixture.descriptor, bytes)
                        else json.dumps(fixture.descriptor).encode()
                    )
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    try:
                        self.wfile.write(body)
                    except OSError:
                        pass
                    return

                fixture.asset_requests.append(dict(self.headers))
                if fixture.asset_status != 200:
                    self.send_response(fixture.asset_status)
                    self.end_headers()
                    return
                start = 0
                range_value = self.headers.get("Range")
                if range_value and not fixture.ignore_range:
                    start = int(range_value.removeprefix("bytes=").removesuffix("-"))
                    body = fixture.archive[start:]
                    self.send_response(206)
                    range_start = start + 1 if fixture.wrong_range else start
                    self.send_header(
                        "Content-Range",
                        f"bytes {range_start}-{len(fixture.archive) - 1}/{len(fixture.archive)}",
                    )
                else:
                    body = fixture.archive
                    self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    if fixture.slow_asset:
                        for offset in range(0, len(body), 65_536):
                            self.wfile.write(body[offset : offset + 65_536])
                            self.wfile.flush()
                            time.sleep(0.002)
                    else:
                        self.wfile.write(body)
                except OSError:
                    pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    @property
    def origin(self):
        return f"http://127.0.0.1:{self.server.server_port}"


class UpdateServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data_root = self.root / "data"
        self.install_root = self.root / "Backchannel"
        self.install_root.mkdir()
        (self.install_root / "Backchannel.exe").write_bytes(b"old")
        public = Ed25519PrivateKey.from_private_bytes(PRIVATE_KEY).public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
        self.keys_path = self.root / "keys.json"
        self.keys_path.write_text(json.dumps({
            "active": KEY_ID,
            "keys": {
                KEY_ID: base64.urlsafe_b64encode(public).rstrip(b"=").decode(),
            },
        }))

    def tearDown(self):
        self.temp.cleanup()

    def service(self, fixture=None, **overrides):
        descriptor_url = (
            f"{fixture.origin}/latest/{{platform_id}}" if fixture else "http://127.0.0.1:1/latest/{platform_id}"
        )
        asset_url = (
            f"{fixture.origin}/assets/{{version}}/{{platform_id}}" if fixture else "http://127.0.0.1:1/assets/{version}/{platform_id}"
        )
        options = {
            "enabled": True,
            "data_root": self.data_root,
            "install_root": self.install_root,
            "keys_path": self.keys_path,
            "current_version": "0.3.8",
            "platform_id": "windows-x64",
            "descriptor_url": descriptor_url,
            "asset_url": asset_url,
        }
        options.update(overrides)
        return UpdateService(**options)

    def test_source_deployment_is_disabled(self):
        service = UpdateService(enabled=False)
        self.assertEqual(service.status(), {"enabled": False, "state": "idle"})
        self.assertEqual(service.check(force=True), {"enabled": False, "state": "idle"})

    def test_check_verifies_caches_and_persists_without_blocking_status(self):
        archive = zip_bundle()
        with UpdateFixture(descriptor(archive), archive) as fixture:
            fixture.descriptor_delay = 0.1
            service = self.service(fixture)
            results = []
            threads = [
                threading.Thread(target=lambda: results.append(service.check(force=True)))
                for _ in range(2)
            ]
            for thread in threads:
                thread.start()
            time.sleep(0.02)
            self.assertEqual(service.status()["state"], "idle")
            for thread in threads:
                thread.join()

            self.assertEqual(fixture.descriptor_requests, 1)
            self.assertEqual(results[0]["state"], "available")
            self.assertEqual(results[0]["available_version"], "v0.4.0")
            self.assertEqual(results[0]["available_notes"], "Security and reliability fixes.")
            self.assertEqual(service.check()["state"], "available")
            self.assertEqual(fixture.descriptor_requests, 1)
            self.assertFalse((service.state_path.with_suffix(".tmp")).exists())
            restarted = self.service(fixture)
            self.assertEqual(restarted.status()["available_version"], "v0.4.0")

    def test_check_rejects_tampering_oversize_timeout_and_replay(self):
        archive = zip_bundle()
        first = descriptor(archive, "v0.5.0", "2026-07-26T19:00:00Z")
        with UpdateFixture(first, archive) as fixture:
            service = self.service(fixture, timeout=0.05)
            self.assertEqual(service.check(force=True)["state"], "available")
            fixture.descriptor = descriptor(archive, "v0.4.0", "2026-07-26T18:00:00Z")
            self.assertEqual(service.check(force=True)["state"], "error")
            self.assertEqual(service.status()["highest_seen_version"], "v0.5.0")

            tampered = descriptor(archive, "v0.6.0", "2026-07-26T20:00:00Z")
            tampered["release_notes"] = "tampered"
            fixture.descriptor = tampered
            self.assertEqual(service.check(force=True)["state"], "error")

            fixture.descriptor = b"{" + (b"x" * 70_000)
            self.assertEqual(service.check(force=True)["state"], "error")

            fixture.descriptor = first
            fixture.descriptor_delay = 0.2
            self.assertEqual(service.check(force=True)["state"], "error")
            self.assertNotIn("test-key", json.dumps(service.status()))

    def test_check_uses_certifi_tls_context(self):
        archive = zip_bundle()
        body = json.dumps(descriptor(archive)).encode()

        class Response(io.BytesIO):
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_):
                self.close()

        captured = {}

        def open_request(_request, **kwargs):
            captured.update(kwargs)
            return Response(body)

        service = self.service()
        with patch("app.services.update_service.urllib.request.urlopen", open_request):
            self.assertEqual(service.check(force=True)["state"], "available")
        self.assertIsInstance(captured["context"], ssl.SSLContext)
        self.assertEqual(captured["timeout"], 5)

    def test_download_resumes_streams_verifies_and_stages(self):
        archive = zip_bundle()
        with UpdateFixture(descriptor(archive), archive) as fixture:
            service = self.service(fixture)
            service.check(force=True)
            partial = service.partial_path
            partial.parent.mkdir(parents=True, exist_ok=True)
            partial.write_bytes(archive[:7])
            service.start_download(GRANT)
            service.wait_for_download()

            self.assertEqual(service.status()["state"], "ready")
            self.assertEqual(fixture.asset_requests[0]["Range"], "bytes=7-")
            self.assertEqual(fixture.asset_requests[0]["Authorization"], f"Bearer {GRANT}")
            self.assertTrue((service.staged_root / "Backchannel.exe").is_file())
            persisted = service.state_path.read_text()
            self.assertNotIn(GRANT, persisted)

    def test_range_ignored_restarts_and_expired_grant_preserves_partial(self):
        archive = zip_bundle()
        with UpdateFixture(descriptor(archive), archive) as fixture:
            fixture.ignore_range = True
            service = self.service(fixture)
            service.check(force=True)
            service.partial_path.parent.mkdir(parents=True, exist_ok=True)
            service.partial_path.write_bytes(b"old")
            service.start_download(GRANT)
            service.wait_for_download()
            self.assertEqual(service.status()["state"], "ready")
            self.assertEqual(service.partial_path.read_bytes(), archive)

        with UpdateFixture(descriptor(archive), archive) as fixture:
            fixture.asset_status = 404
            service = self.service(fixture, data_root=self.data_root / "expired")
            service.check(force=True)
            service.partial_path.parent.mkdir(parents=True, exist_ok=True)
            service.partial_path.write_bytes(b"old")
            service.start_download(GRANT)
            service.wait_for_download()
            self.assertEqual(service.status()["state"], "needs_authorization")
            self.assertEqual(service.partial_path.read_bytes(), b"old")

    def test_hash_size_and_archive_validation_fail_closed(self):
        archive = zip_bundle()
        with UpdateFixture(descriptor(archive), archive + b"extra") as fixture:
            service = self.service(fixture)
            service.check(force=True)
            service.start_download(GRANT)
            service.wait_for_download()
            self.assertEqual(service.status()["state"], "error")
            self.assertFalse(service.partial_path.exists())

        unsafe = zip_bundle({"../outside": b"bad"})
        with UpdateFixture(descriptor(unsafe), unsafe) as fixture:
            service = self.service(fixture)
            service.check(force=True)
            service.start_download(GRANT)
            service.wait_for_download()
            self.assertEqual(service.status()["state"], "error")
            self.assertFalse((self.root / "outside").exists())

    def test_archive_paths_devices_links_roots_and_expansion_are_bounded(self):
        service = self.service()

        def write_zip(name, body=b"x", mode=stat.S_IFREG | 0o600):
            path = self.root / f"{hash(name)}.zip"
            with zipfile.ZipFile(path, "w") as archive:
                info = zipfile.ZipInfo(name)
                info.external_attr = mode << 16
                archive.writestr(info, body)
            return path

        for path in [
            write_zip("/Backchannel/file"),
            write_zip("Backchannel/../outside"),
            write_zip("Other/file"),
            write_zip("Backchannel/device", mode=stat.S_IFCHR | 0o600),
            write_zip(
                "Backchannel/link",
                body=b"Backchannel.exe",
                mode=stat.S_IFLNK | 0o777,
            ),
        ]:
            with self.assertRaises(InvalidUpdate):
                service._zip_size(path)

        mac = self.service(platform_id="macos-arm64")
        safe_link = write_zip(
            "Backchannel.app/current",
            body=b"Contents/MacOS/Backchannel",
            mode=stat.S_IFLNK | 0o777,
        )
        self.assertEqual(mac._zip_size(safe_link), 0)
        with self.assertRaises(InvalidUpdate):
            mac._zip_size(write_zip(
                "Backchannel.app/current",
                body=b"../../outside",
                mode=stat.S_IFLNK | 0o777,
            ))

        expanded = write_zip("Backchannel/payload", body=b"xx")
        with patch("app.services.update_service.MAX_EXPANDED_BYTES", 1):
            with self.assertRaises(InvalidUpdate):
                service._zip_size(expanded)
        self.assertLessEqual(CHUNK_SIZE, 1024 * 1024)

    def test_linux_tar_accepts_only_in_bundle_relative_links(self):
        service = self.service(platform_id="linux-x64")

        def write_tar(target):
            path = self.root / f"{abs(hash(target))}.tar.gz"
            with tarfile.open(path, "w:gz") as archive:
                regular = tarfile.TarInfo("Backchannel/Backchannel")
                regular.size = 3
                archive.addfile(regular, io.BytesIO(b"app"))
                link = tarfile.TarInfo("Backchannel/current")
                link.type = tarfile.SYMTYPE
                link.linkname = target
                archive.addfile(link)
            return path

        self.assertEqual(service._tar_size(write_tar("Backchannel")), 3)
        with self.assertRaises(InvalidUpdate):
            service._tar_size(write_tar("../../outside"))

    @unittest.skipUnless(sys.platform == "darwin", "requires native macOS ditto")
    def test_macos_ditto_round_trip_preserves_mode_and_symlink(self):
        app = self.root / "fixture" / "Backchannel.app"
        executable = app / "Contents" / "MacOS" / "Backchannel"
        executable.parent.mkdir(parents=True)
        executable.write_text("#!/bin/sh\nexit 0\n")
        executable.chmod(0o755)
        link = app / "Contents" / "MacOS" / "current"
        link.symlink_to("Backchannel")
        archive = self.root / "Backchannel-macos-arm64.zip"
        subprocess.run(
            ["/usr/bin/ditto", "-c", "-k", "--keepParent", str(app), str(archive)],
            check=True,
        )
        install = self.root / "installed" / "Backchannel.app"
        (install / "Contents" / "MacOS").mkdir(parents=True)
        service = self.service(
            platform_id="macos-arm64",
            install_root=install,
            data_root=self.root / "mac-data",
        )
        service._state.update({
            "available_version": "v0.4.0",
            "filename": "Backchannel-macos-arm64.zip",
        })
        service._stage_archive(archive, {"asset": {"size": archive.stat().st_size}})
        staged = service.staged_root / "Contents" / "MacOS"
        self.assertTrue((staged / "Backchannel").stat().st_mode & stat.S_IXUSR)
        self.assertTrue((staged / "current").is_symlink())

    def test_cancel_keeps_a_bounded_partial_for_later_resume(self):
        archive = zip_bundle({"Backchannel/payload.bin": os.urandom(2_000_000)})
        with UpdateFixture(descriptor(archive), archive) as fixture:
            fixture.slow_asset = True
            service = self.service(fixture)
            service.check(force=True)
            service.start_download(GRANT)
            deadline = time.monotonic() + 2
            while service.status()["downloaded"] == 0 and time.monotonic() < deadline:
                time.sleep(0.01)
            service.cancel_download()
            service.wait_for_download()
            self.assertEqual(service.status()["state"], "available")
            self.assertLess(service.partial_path.stat().st_size, len(archive))

    def test_free_space_preflight_includes_archive_stage_backup_and_margin(self):
        archive = zip_bundle({"Backchannel/payload.bin": b"x" * 4096})
        with UpdateFixture(descriptor(archive), archive) as fixture:
            service = self.service(fixture)
            service.check(force=True)
            with patch(
                "app.services.update_service.shutil.disk_usage",
                return_value=(10_000, 9_999, 1),
            ):
                service.start_download(GRANT)
                service.wait_for_download()
            self.assertEqual(service.status()["state"], "error")
            self.assertFalse(service.staged_root.exists())

    def test_apply_writes_one_bounded_plan_and_stale_marker_returns_to_ready(self):
        archive = zip_bundle()
        helper = self.root / "BackchannelUpdater.exe"
        helper.write_bytes(b"helper")
        with UpdateFixture(descriptor(archive), archive) as fixture:
            service = self.service(fixture, helper_path=helper)
            service.check(force=True)
            service.start_download(GRANT)
            service.wait_for_download()
            result = service.request_apply()
            self.assertEqual(result["state"], "applying")
            plan_path = service.update_root / "apply.json"
            plan = json.loads(plan_path.read_text())
            self.assertEqual(set(plan), {
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
            })
            self.assertEqual(plan["launcher"], "Backchannel.exe")
            self.assertEqual(Path(plan["staged_dir"]), service.staged_root)
            self.assertNotIn(GRANT, plan_path.read_text())
            self.assertFalse(plan_path.with_suffix(".tmp").exists())

            old = time.time() - 61
            os.utime(plan_path, (old, old))
            self.assertEqual(service.status()["state"], "ready")
            self.assertFalse(plan_path.exists())

    def test_headless_apply_never_writes_a_restart_marker(self):
        service = self.service(apply_disabled=True)
        service._state["state"] = "ready"
        with self.assertRaisesRegex(RuntimeError, "headless"):
            service.request_apply()
        self.assertFalse((service.update_root / "apply.json").exists())

    def test_desktop_main_rejects_rebinding_hosts_without_exposing_the_token(self):
        code = """
from fastapi.testclient import TestClient
from app.main import app
client = TestClient(app)
assert client.get('/api/health', headers={'host': 'attacker.example'}).status_code == 400
response = client.get('/api/health', headers={
    'host': 'localhost',
    'origin': 'https://attacker.example',
})
assert response.status_code == 200
assert response.json() == {'status': 'ok'}
assert 'instance-secret' not in response.text
assert 'x-backchannel-instance' not in response.headers.get(
    'access-control-expose-headers', ''
).lower()
"""
        environment = {
            **os.environ,
            "PYTHONPATH": str(Path.cwd() / "backend"),
            "BACKCHANNEL_DESKTOP": "1",
            "BACKCHANNEL_INSTANCE_TOKEN": "instance-secret",
        }
        result = subprocess.run(
            [sys.executable, "-c", code],
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


class UpdateRouterTests(unittest.TestCase):
    class Service:
        def __init__(self):
            self.applies = 0
            self.apply_error = None

        def status(self):
            return {"enabled": True, "state": "ready"}

        def check(self, force=False):
            return {"enabled": True, "state": "available", "force": force}

        def start_download(self, grant):
            return {"enabled": True, "state": "downloading", "grant_seen": bool(grant)}

        def cancel_download(self):
            return {"enabled": True, "state": "available"}

        def request_apply(self):
            self.applies += 1
            if self.apply_error:
                raise RuntimeError(self.apply_error)
            return {"enabled": True, "state": "applying"}

    class Database:
        def __init__(self, active=0):
            self.active = active

        async def scalar(self, _query):
            return self.active

    def setUp(self):
        runtime_activity.release_shutdown()
        self.service = self.Service()
        self.database = self.Database()
        app = FastAPI()
        app.include_router(updates.router)
        app.dependency_overrides[get_update_service] = lambda: self.service

        async def database_override():
            yield self.database

        app.dependency_overrides[get_db] = database_override
        self.client = TestClient(app)
        self.environment = patch.dict(
            os.environ, {"BACKCHANNEL_INSTANCE_TOKEN": "instance-secret"}
        )
        self.environment.start()

    def tearDown(self):
        runtime_activity.release_shutdown()
        self.environment.stop()

    def mutation(self, method, path, **kwargs):
        headers = {"X-Backchannel-Instance": "instance-secret"}
        return self.client.request(method, path, headers=headers, **kwargs)

    def test_read_is_open_but_every_mutation_requires_the_instance_token(self):
        self.assertEqual(self.client.get("/api/updates").status_code, 200)
        for method, path in [
            ("POST", "/api/updates/check"),
            ("POST", "/api/updates/grant"),
            ("DELETE", "/api/updates/download"),
            ("POST", "/api/updates/apply"),
        ]:
            self.assertEqual(self.client.request(method, path).status_code, 403)
            self.assertEqual(
                self.client.request(
                    method, path, headers={"X-Backchannel-Instance": "wrong"}
                ).status_code,
                403,
            )

        self.assertEqual(
            self.mutation("POST", "/api/updates/check").json()["force"], True
        )
        self.assertEqual(
            self.mutation("POST", "/api/updates/grant", json={"grant": GRANT}).json()[
                "state"
            ],
            "downloading",
        )
        self.assertEqual(
            self.mutation("DELETE", "/api/updates/download").json()["state"],
            "available",
        )

    def test_ready_status_reports_the_active_runtime_blocker(self):
        with runtime_activity.track("audio import"):
            status = self.client.get("/api/updates").json()
        self.assertEqual(status["blocked_reason"], "audio import")
        self.assertEqual(
            self.client.get("/api/updates").json()["blocked_reason"],
            "",
        )

    def test_apply_reserves_shutdown_and_releases_every_failed_precheck(self):
        self.database.active = 1
        response = self.mutation("POST", "/api/updates/apply")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.service.applies, 0)
        with runtime_activity.track("new work"):
            self.assertEqual(runtime_activity.busy_reason(), "new work")

        self.database.active = 0
        self.service.apply_error = "stage is unavailable"
        response = self.mutation("POST", "/api/updates/apply")
        self.assertEqual(response.status_code, 409)
        with runtime_activity.track("retry work"):
            self.assertEqual(runtime_activity.busy_reason(), "retry work")

        self.service.apply_error = None
        response = self.mutation("POST", "/api/updates/apply")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.service.applies, 2)
        with self.assertRaises(runtime_activity.ShutdownReserved):
            with runtime_activity.track("late work"):
                pass


if __name__ == "__main__":
    unittest.main()
