import http.server
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch

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
    def _browser_opener(self):
        opener = getattr(launcher, "browser_opener", None)
        self.assertIsNotNone(opener, "browser_opener is missing")
        return opener

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

    def test_app_port_prefers_stable_default(self):
        choose_port = getattr(launcher, "select_app_port", None)
        self.assertIsNotNone(choose_port, "select_app_port is missing")
        self.assertEqual(getattr(launcher, "DEFAULT_APP_PORT", None), 8474)
        with (
            patch("launcher.socket.socket") as socket_factory,
            patch.object(launcher, "free_port") as free_port,
        ):
            self.assertEqual(choose_port(), 8474)

        socket_factory.return_value.__enter__.return_value.bind.assert_called_once_with(
            ("127.0.0.1", 8474)
        )
        free_port.assert_not_called()

    def test_app_port_falls_back_when_default_is_occupied(self):
        choose_port = getattr(launcher, "select_app_port", None)
        self.assertIsNotNone(choose_port, "select_app_port is missing")
        with (
            patch("launcher.socket.socket") as socket_factory,
            patch.object(launcher, "free_port", return_value=54321) as free_port,
        ):
            socket_factory.return_value.__enter__.return_value.bind.side_effect = (
                OSError("occupied")
            )
            self.assertEqual(choose_port(), 54321)

        free_port.assert_called_once_with()

    def test_windows_browser_opener_prefers_edge_app_paths_registry(self):
        opener = self._browser_opener()
        registry = Mock()
        registry.HKEY_CURRENT_USER = object()
        registry.HKEY_LOCAL_MACHINE = object()
        registry.QueryValue.return_value = r"C:\Program Files\Edge\msedge.exe"
        with (
            patch.object(launcher.sys, "platform", "win32"),
            patch.dict(launcher.sys.modules, {"winreg": registry}),
            patch.object(Path, "is_file", return_value=True),
            patch("launcher.subprocess.Popen") as popen,
        ):
            opener("http://localhost:8474")

        self.assertIn("App Paths\\msedge.exe", registry.OpenKey.call_args.args[1])
        popen.assert_called_once_with(
            [r"C:\Program Files\Edge\msedge.exe", "--app=http://localhost:8474"]
        )

    def test_windows_browser_opener_uses_standard_install_directory(self):
        opener = self._browser_opener()
        registry = Mock()
        registry.HKEY_CURRENT_USER = object()
        registry.HKEY_LOCAL_MACHINE = object()
        registry.OpenKey.side_effect = OSError("missing")
        with (
            patch.object(launcher.sys, "platform", "win32"),
            patch.dict(launcher.sys.modules, {"winreg": registry}),
            patch.dict(
                launcher.os.environ,
                {"PROGRAMFILES(X86)": r"C:\Program Files (x86)"},
                clear=True,
            ),
            patch.object(Path, "is_file", return_value=True),
            patch("launcher.subprocess.Popen") as popen,
        ):
            opener("http://localhost:8474")

        popen.assert_called_once_with(
            [
                str(
                    Path(r"C:\Program Files (x86)")
                    / "Microsoft"
                    / "Edge"
                    / "Application"
                    / "msedge.exe"
                ),
                "--app=http://localhost:8474",
            ]
        )

    def test_macos_browser_opener_tries_edge_then_chrome_app_mode(self):
        opener = self._browser_opener()
        failed = Mock(returncode=1)
        launched = Mock(returncode=0)
        with (
            patch.object(launcher.sys, "platform", "darwin"),
            patch("launcher.subprocess.run", side_effect=[failed, launched]) as run,
            patch("launcher.webbrowser.open") as fallback,
        ):
            opener("http://localhost:8474")

        self.assertEqual(
            run.call_args_list,
            [
                call(
                    [
                        "open", "-na", "Microsoft Edge", "--args",
                        "--app=http://localhost:8474",
                    ],
                    check=False,
                    stdout=launcher.subprocess.DEVNULL,
                    stderr=launcher.subprocess.DEVNULL,
                ),
                call(
                    [
                        "open", "-na", "Google Chrome", "--args",
                        "--app=http://localhost:8474",
                    ],
                    check=False,
                    stdout=launcher.subprocess.DEVNULL,
                    stderr=launcher.subprocess.DEVNULL,
                ),
            ],
        )
        fallback.assert_not_called()

    def test_linux_browser_opener_uses_first_chromium_on_path(self):
        opener = self._browser_opener()
        locations = {"google-chrome": "/usr/bin/google-chrome"}
        with (
            patch.object(launcher.sys, "platform", "linux"),
            patch("launcher.shutil.which", side_effect=locations.get) as which,
            patch("launcher.subprocess.Popen") as popen,
        ):
            opener("http://localhost:8474")

        self.assertEqual(
            which.call_args_list,
            [call("microsoft-edge"), call("google-chrome")],
        )
        popen.assert_called_once_with(
            ["/usr/bin/google-chrome", "--app=http://localhost:8474"]
        )

    def test_browser_opener_falls_back_when_chromium_is_unavailable(self):
        opener = self._browser_opener()
        with (
            patch.object(launcher.sys, "platform", "linux"),
            patch("launcher.shutil.which", return_value=None),
            patch("launcher.webbrowser.open") as fallback,
        ):
            opener("http://localhost:8474")

        fallback.assert_called_once_with("http://localhost:8474")

    def test_existing_instance_opens_with_browser_opener(self):
        self._browser_opener()
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(launcher, "app_data_dir", return_value=Path(tmp)),
            patch.object(launcher, "existing_instance_port", return_value=8474),
            patch.object(launcher.logging, "basicConfig"),
            patch.object(launcher, "browser_opener") as opener,
        ):
            self.assertEqual(launcher.run(), 0)

        opener.assert_called_once_with("http://localhost:8474")

    def test_tray_open_action_uses_browser_opener(self):
        self._browser_opener()
        pystray = Mock()
        pystray.Menu.side_effect = lambda *items: items
        pystray.MenuItem.side_effect = lambda label, action: (label, action)
        icon = pystray.Icon.return_value
        with (
            patch.dict(launcher.sys.modules, {"pystray": pystray}),
            patch.object(launcher, "_tray_image"),
            patch.object(launcher, "browser_opener") as opener,
        ):
            launcher._run_tray(8474, Path("data"))
            menu = pystray.Icon.call_args.kwargs["menu"]
            menu[0][1](None, None)

        opener.assert_called_once_with("http://localhost:8474")
        icon.run.assert_called_once_with()

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
        data_dir = Path("/tmp/data")
        with (
            patch.object(launcher.sys, "platform", "linux"),
            patch("subprocess.run") as run,
        ):
            launcher._open_data_folder(data_dir)

        run.assert_called_once_with(["xdg-open", str(data_dir)], check=False)


if __name__ == "__main__":
    unittest.main()
