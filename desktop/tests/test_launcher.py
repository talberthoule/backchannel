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
