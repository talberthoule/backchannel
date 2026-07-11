import http.server
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

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
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server.server_address[1]

    def test_no_lock_file_means_no_instance(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(launcher.existing_instance_port(Path(tmp)))

    def test_browser_url_uses_friendly_localhost_name(self):
        self.assertEqual(
            "http://localhost:54321",
            launcher.app_url(54321),
        )

    def test_health_url_stays_on_numeric_loopback(self):
        self.assertEqual(
            "http://127.0.0.1:54321/api/health",
            launcher.health_url(54321),
        )

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

    def test_wait_for_other_instance_returns_port_once_lock_appears(self):
        port = self._serve_health()
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "launcher.json").write_text(
                json.dumps({"port": port, "pid": 1})
            )
            found = launcher.wait_for_other_instance(
                Path(tmp), timeout=1, interval=0.05
            )
        self.assertEqual(found, port)

    def test_wait_for_other_instance_times_out_when_nothing_appears(self):
        with tempfile.TemporaryDirectory() as tmp:
            found = launcher.wait_for_other_instance(
                Path(tmp), timeout=0.2, interval=0.05
            )
        self.assertIsNone(found)

    def test_linux_opens_data_folder_with_xdg_open(self):
        with (
            patch.object(launcher.sys, "platform", "linux"),
            patch("subprocess.run") as run,
        ):
            launcher._open_data_folder(Path("/tmp/data"))

        run.assert_called_once_with(["xdg-open", "/tmp/data"], check=False)


if __name__ == "__main__":
    unittest.main()
