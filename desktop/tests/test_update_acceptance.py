import base64
import gc
import json
import random
import subprocess
import sys
import tempfile
import time
import tracemalloc
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[2]
for source in (ROOT, ROOT / "backend", ROOT / "desktop"):
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))

from app.services.update_service import CHUNK_SIZE, UpdateService
from backend.tests.test_update_service import (
    GRANT,
    KEY_ID,
    PRIVATE_KEY,
    UpdateFixture,
    descriptor,
    zip_bundle,
)
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from updater import INSTANCE_HEADER, apply_update
from desktop.scripts.smoke_update_archive import GracefulProcess


class NativeSmokeHarnessTests(unittest.TestCase):
    def test_graceful_stop_retries_past_the_launcher_startup_race(self):
        class Process:
            returncode = None

            def __init__(self):
                self.waits = 0

            def poll(self):
                return self.returncode

            def wait(self, timeout=None):
                self.waits += 1
                if self.waits == 1:
                    raise subprocess.TimeoutExpired("Backchannel", timeout)
                self.returncode = 0
                return 0

            def terminate(self):
                self.returncode = -15

        process = Process()
        stop = Mock()
        GracefulProcess(process, stop).terminate()
        self.assertEqual(process.returncode, 0)
        self.assertEqual(stop.touch.call_count, 2)


class HealthFixture:
    def __init__(self):
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                body = b'{"status":"ok"}'
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.send_header(INSTANCE_HEADER, fixture.token)
                self.end_headers()
                self.wfile.write(body)

        self.token = "new-health-token"
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()


@unittest.skipUnless(sys.platform == "win32", "Windows native acceptance")
class DesktopUpdateAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data = self.root / "app-data"
        self.install = self.root / "Backchannel"
        self.install.mkdir()
        (self.install / "Backchannel.exe").write_bytes(b"known-good")
        self.helper = self.root / "BackchannelUpdater.exe"
        self.helper.write_bytes(b"helper")

        public = Ed25519PrivateKey.from_private_bytes(PRIVATE_KEY).public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
        self.keys = self.root / "keys.json"
        self.keys.write_text(json.dumps({
            "active": KEY_ID,
            "keys": {
                KEY_ID: base64.urlsafe_b64encode(public).rstrip(b"=").decode(),
            },
        }))

    def tearDown(self):
        self.temp.cleanup()

    def service(self, fixture):
        return UpdateService(
            enabled=True,
            data_root=self.data,
            install_root=self.install,
            keys_path=self.keys,
            current_version="0.3.8",
            platform_id="windows-x64",
            descriptor_url=f"{fixture.origin}/latest/{{platform_id}}",
            asset_url=f"{fixture.origin}/assets/{{version}}/{{platform_id}}",
            helper_path=self.helper,
        )

    def wait_for_partial(self, service):
        deadline = time.monotonic() + 10
        while service.status()["downloaded"] < CHUNK_SIZE:
            if time.monotonic() >= deadline:
                self.fail("download did not produce a resumable partial")
            time.sleep(0.005)
        service.cancel_download()
        service.wait_for_download()
        self.assertEqual(service.status()["state"], "available")
        return service.partial_path.stat().st_size

    def test_signed_update_resumes_swaps_and_rolls_back_with_bounded_memory(self):
        payload = random.Random(150).randbytes(3 * CHUNK_SIZE)
        archive = zip_bundle({
            "Backchannel/Backchannel.exe": b"new-launcher",
            "Backchannel/payload.bin": payload,
        })
        self.assertGreater(len(archive), 3 * CHUNK_SIZE)

        with UpdateFixture(descriptor(archive), archive) as fixture:
            service = self.service(fixture)
            started = time.perf_counter()
            checked = service.check(force=True)
            check_seconds = time.perf_counter() - started
            self.assertEqual(checked["available_version"], "v0.4.0")

            fixture.slow_asset = True
            service.start_download(GRANT)
            partial_size = self.wait_for_partial(service)
            self.assertGreater(partial_size, 0)
            self.assertLess(partial_size, len(archive))

            fixture.slow_asset = False
            gc.collect()
            tracemalloc.start()
            baseline = tracemalloc.get_traced_memory()[0]
            service.start_download(GRANT)
            service.wait_for_download()
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            peak_increment = peak - baseline

            self.assertEqual(service.status()["state"], "ready")
            self.assertEqual(
                fixture.asset_requests[-1].get("Range"),
                f"bytes={partial_size}-",
            )
            self.assertEqual(
                fixture.asset_requests[-1].get("Authorization"),
                f"Bearer {GRANT}",
            )
            self.assertLessEqual(peak_increment, 8 * 1024 * 1024)

            service.request_apply()
            plan_path = self.data / "updates" / "apply.json"
            process = Mock()
            process.poll.return_value = None
            with HealthFixture() as health:
                def launch(_args, cwd=None):
                    self.assertEqual(Path(cwd), self.install)
                    (self.data / "launcher.json").write_text(json.dumps({
                        "port": health.server.server_port,
                        "pid": 123,
                        "token": health.token,
                    }))
                    return process

                result = apply_update(
                    plan_path,
                    process_factory=launch,
                    pid_running=lambda _pid: False,
                    sleep=lambda _seconds: None,
                )
            self.assertEqual(result, 0)
            self.assertEqual((self.install / "Backchannel.exe").read_bytes(), b"new-launcher")

            # Repeat the same verified download, then reject the new health and
            # prove the known-good install is relaunched.
            (self.data / "launcher.json").unlink(missing_ok=True)
            service = self.service(fixture)
            service.check(force=True)
            service.start_download(GRANT)
            service.wait_for_download()
            self.assertEqual(service.status()["state"], "ready")
            (self.install / "Backchannel.exe").write_bytes(b"known-good")
            service.request_apply()

            failed = Mock()
            failed.poll.return_value = None
            restored = Mock()
            restored.poll.return_value = None
            launches = Mock(side_effect=[failed, restored])
            clock = Mock(side_effect=[0, 0, 301])
            result = apply_update(
                self.data / "updates" / "apply.json",
                process_factory=launches,
                health=lambda _data: False,
                pid_running=lambda _pid: False,
                monotonic=clock,
                sleep=lambda _seconds: None,
            )
            self.assertEqual(result, 1)
            self.assertEqual((self.install / "Backchannel.exe").read_bytes(), b"known-good")
            self.assertEqual(
                (self.root / "Backchannel.failed-v0.4.0" / "Backchannel.exe").read_bytes(),
                b"new-launcher",
            )
            self.assertEqual(launches.call_count, 2)

        main_source = (ROOT / "backend" / "app" / "routers" / "updates.py").read_text()
        self.assertIn(
            "asyncio.create_task(asyncio.to_thread(get_update_service().check))",
            main_source,
        )
        self.assertLess(check_seconds, 5)
        print(
            "ALP-150 acceptance:",
            f"archive={len(archive)}",
            f"check={check_seconds:.3f}s",
            f"peak_increment={peak_increment}",
        )


if __name__ == "__main__":
    unittest.main()
