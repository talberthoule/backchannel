import http.server
import json
import socket
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, call, patch

import launcher


class _HealthHandler(http.server.BaseHTTPRequestHandler):
    instance_token = None

    def do_GET(self):
        if self.path == "/api/health":
            self.send_response(200)
            if self.instance_token is not None:
                self.send_header(launcher.INSTANCE_HEADER, self.instance_token)
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

    def _serve_health(self, instance_token=None):
        handler = type(
            "HealthHandler",
            (_HealthHandler,),
            {"instance_token": instance_token},
        )
        server = http.server.HTTPServer(("127.0.0.1", 0), handler)
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

    def test_app_socket_prefers_stable_default(self):
        with socket.socket() as available:
            available.bind((launcher.LOOPBACK_HOST, 0))
            preferred_port = available.getsockname()[1]
        with patch.object(launcher, "DEFAULT_APP_PORT", preferred_port):
            listener = launcher.bind_app_socket()
        self.addCleanup(listener.close)

        self.assertEqual(listener.getsockname()[1], preferred_port)

    def test_app_socket_falls_back_and_stays_reserved(self):
        bind_app_socket = getattr(launcher, "bind_app_socket", None)
        self.assertIsNotNone(bind_app_socket, "bind_app_socket is missing")
        with socket.socket() as occupied:
            occupied.bind((launcher.LOOPBACK_HOST, 0))
            occupied_port = occupied.getsockname()[1]
            with patch.object(launcher, "DEFAULT_APP_PORT", occupied_port):
                listener = bind_app_socket()
        self.addCleanup(listener.close)

        fallback_port = listener.getsockname()[1]
        self.assertNotEqual(fallback_port, occupied_port)
        with socket.socket() as contender:
            with self.assertRaises(OSError):
                contender.bind((launcher.LOOPBACK_HOST, fallback_port))

    def test_windows_browser_path_uses_http_association(self):
        chrome = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

        def resolve(_flags, assoc_string, association, _extra, output, size):
            self.assertEqual(assoc_string, 2)  # ASSOCSTR_EXECUTABLE
            self.assertEqual(association, "http")
            size._obj.value = len(chrome) + 1
            if output is None:
                return 1  # S_FALSE: caller now has the required buffer size
            output.value = chrome
            return 0

        query = Mock(side_effect=resolve)
        windll = Mock()
        windll.shlwapi.AssocQueryStringW = query
        browser_path = Mock(name="browser_path")
        browser_path.name = "chrome.exe"
        browser_path.is_file.return_value = True
        browser_path.__str__ = Mock(return_value=chrome)
        with (
            patch.object(launcher.ctypes, "windll", windll, create=True),
            patch.object(launcher, "Path", return_value=browser_path) as path,
        ):
            self.assertEqual(launcher._windows_browser_path(), chrome)

        self.assertEqual(query.call_count, 2)
        path.assert_called_once_with(chrome)

    def test_windows_browser_opener_uses_default_chrome_in_app_mode(self):
        opener = self._browser_opener()
        chrome = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
        with (
            patch.object(launcher.sys, "platform", "win32"),
            patch.object(
                launcher, "_windows_browser_path", return_value=chrome
            ) as default_browser,
            patch("launcher.subprocess.Popen") as popen,
        ):
            opener("http://localhost:8474")

        default_browser.assert_called_once_with()
        popen.assert_called_once_with(
            [chrome, "--app=http://localhost:8474"]
        )

    def test_windows_browser_opener_falls_back_for_unsupported_default(self):
        opener = self._browser_opener()
        with (
            patch.object(launcher.sys, "platform", "win32"),
            patch.object(launcher, "_windows_browser_path", return_value=None),
            patch("launcher.subprocess.Popen") as popen,
            patch("launcher.webbrowser.open") as fallback,
        ):
            opener("http://localhost:8474")

        popen.assert_not_called()
        fallback.assert_called_once_with("http://localhost:8474")

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

    def test_run_starts_on_reserved_socket(self):
        listener = Mock()
        listener.getsockname.return_value = (launcher.LOOPBACK_HOST, 54321)
        postgres = Mock()
        uvicorn = Mock()
        server = uvicorn.Server.return_value
        secrets = Mock()
        secrets.token_urlsafe.return_value = "ours"
        observed_health = {}

        def confirm_health(port, timeout=90.0, token=None):
            lock = Path(tmp) / launcher.LOCK_NAME
            observed_health.update(
                port=port,
                token=token,
                lock=json.loads(lock.read_text()) if lock.exists() else None,
            )
            return True

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(launcher, "app_data_dir", return_value=Path(tmp)),
            patch.object(launcher, "existing_instance_port", return_value=None),
            patch.object(launcher, "EmbeddedPostgres", return_value=postgres),
            patch.object(postgres, "pgdata", Path(tmp) / "pgdata"),
            patch.object(postgres, "database_url", return_value="postgresql://db"),
            patch.object(launcher, "resource", return_value=Path(tmp)),
            patch.object(launcher.sys, "frozen", True, create=True),
            patch.object(launcher, "free_port", return_value=15432),
            patch.object(launcher, "bind_app_socket", return_value=listener),
            patch.object(launcher, "secrets", secrets, create=True),
            patch.dict(launcher.sys.modules, {"uvicorn": uvicorn}),
            patch.object(launcher.threading, "Thread") as thread_factory,
            patch.object(launcher, "wait_healthy", side_effect=confirm_health),
            patch.object(launcher, "browser_opener") as opener,
            patch.object(launcher, "_run_tray", return_value=False),
            patch.object(launcher.logging, "basicConfig"),
        ):
            self.assertEqual(launcher.run(), 0)

        opener.assert_called_once_with("http://localhost:54321")
        thread_factory.assert_called_once_with(
            target=server.run,
            kwargs={"sockets": [listener]},
            daemon=True,
        )
        self.assertEqual(
            observed_health,
            {
                "port": 54321,
                "token": "ours",
                "lock": {
                    "port": 54321,
                    "pid": launcher.os.getpid(),
                    "token": "ours",
                },
            },
        )
        uvicorn.Config.assert_called_once_with(
            "app.main:app",
            host=launcher.LOOPBACK_HOST,
            port=54321,
            log_config=None,
            headers=[(launcher.INSTANCE_HEADER, "ours")],
            ws_ping_timeout=90.0,
            ws_max_queue=2048,
            ws_max_size=65_536,
        )
        self.assertEqual(launcher.os.environ["BACKCHANNEL_DESKTOP"], "1")
        self.assertEqual(launcher.os.environ["BACKCHANNEL_INSTANCE_TOKEN"], "ours")
        self.assertEqual(
            launcher.os.environ["BACKCHANNEL_INSTALL_DIR"],
            str(launcher.install_root()),
        )
        self.assertEqual(
            launcher.os.environ["BACKCHANNEL_UPDATE_KEYS"],
            str(Path(tmp)),
        )
        self.assertEqual(
            launcher.os.environ["BACKCHANNEL_UPDATE_HELPER"],
            str(launcher.updater_path(launcher.install_root())),
        )
        self.assertEqual(
            launcher.os.environ["BACKCHANNEL_UPDATE_APPLY_DISABLED"],
            "0",
        )

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

    def test_update_watcher_notices_only_a_fresh_valid_apply_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            updates = data_dir / "updates"
            updates.mkdir()
            state = updates / "state.json"
            state.write_text(json.dumps({"state": "applying"}))
            marker = updates / "apply.json"
            marker.write_text(json.dumps({
                "requested_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }))
            with patch.object(launcher, "validate_plan") as validate:
                self.assertTrue(launcher._claim_update_marker(data_dir))
            validate.assert_called_once()

            marker.unlink()
            (updates / "other.json").write_text("{}")
            self.assertFalse(launcher._claim_update_marker(data_dir))

            marker.write_text(json.dumps({
                "requested_at": (
                    datetime.now(timezone.utc) - timedelta(seconds=61)
                ).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }))
            self.assertFalse(launcher._claim_update_marker(data_dir))
            self.assertFalse(marker.exists())
            self.assertEqual(json.loads(state.read_text())["state"], "ready")

    def test_update_watcher_stops_the_tray_for_an_exact_marker(self):
        icon = Mock()
        requested = threading.Event()
        stopped = threading.Event()
        with patch.object(launcher, "_claim_update_marker", return_value=True):
            launcher._watch_for_update(icon, Path("data"), requested, stopped)
        self.assertTrue(requested.is_set())
        icon.stop.assert_called_once_with()

    def test_tray_check_posts_instance_token_then_opens_about(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        with (
            patch("launcher.urllib.request.urlopen", return_value=response) as urlopen,
            patch.object(launcher, "browser_opener") as opener,
        ):
            launcher._check_for_updates(8474, "instance-secret")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.method, "POST")
        self.assertEqual(
            {key.lower(): value for key, value in request.header_items()}.get(
                launcher.INSTANCE_HEADER.lower()
            ),
            "instance-secret",
        )
        opener.assert_called_once_with("http://localhost:8474/?view=about")

    def test_available_tray_label_includes_version_and_signed_note_title(self):
        with patch.object(launcher, "_update_status", return_value={
            "state": "available",
            "available_version": "v0.4.0",
            "available_notes": "# Safer updates\nMore detail.",
        }):
            self.assertEqual(
                launcher._update_menu_label(8474),
                "Update v0.4.0: Safer updates",
            )

    def test_helper_is_copied_outside_install_and_started_with_only_the_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            marker = data_dir / "updates" / "apply.json"
            marker.parent.mkdir()
            marker.write_text(json.dumps({"version": "v0.4.0"}))
            helper = data_dir / "installed" / "BackchannelUpdater.exe"
            helper.parent.mkdir()
            helper.write_bytes(b"helper")
            with (
                patch.object(
                    launcher,
                    "validate_plan",
                    return_value=Mock(version="v0.4.0"),
                ),
                patch("launcher.subprocess.Popen") as popen,
            ):
                copied = launcher._launch_update_helper(data_dir, helper)
            self.assertEqual(
                copied,
                data_dir / "updates" / "bin" / "v0.4.0" / helper.name,
            )
            self.assertEqual(copied.read_bytes(), b"helper")
            popen.assert_called_once_with([str(copied), str(marker)])

    def test_stale_lock_file_means_no_instance(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "launcher.json").write_text(
                json.dumps({"port": 1, "pid": 99999})
            )
            self.assertIsNone(launcher.existing_instance_port(Path(tmp)))

    def test_live_lock_file_returns_port(self):
        token = "ours"
        port = self._serve_health(token)
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "launcher.json").write_text(
                json.dumps({"port": port, "pid": 1, "token": token})
            )
            self.assertEqual(launcher.existing_instance_port(Path(tmp)), port)

    def test_live_lock_file_rejects_foreign_health_response(self):
        port = self._serve_health()
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "launcher.json").write_text(
                json.dumps({"port": port, "pid": 1, "token": "ours"})
            )
            self.assertIsNone(launcher.existing_instance_port(Path(tmp)))

    def test_wait_healthy_true_for_live_server(self):
        token = "ours"
        port = self._serve_health(token)
        self.assertTrue(launcher.wait_healthy(port, timeout=5, token=token))

    def test_wait_healthy_rejects_unidentified_200(self):
        port = self._serve_health()
        self.assertFalse(launcher.wait_healthy(port, timeout=0.2))

    def test_wait_healthy_false_when_nothing_listens(self):
        from bcdesktop.paths import free_port

        self.assertFalse(
            launcher.wait_healthy(free_port(), timeout=1, token="ours")
        )

    def test_wait_for_other_instance_returns_port_once_lock_appears(self):
        token = "ours"
        port = self._serve_health(token)
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "launcher.json").write_text(
                json.dumps({"port": port, "pid": 1, "token": token})
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
