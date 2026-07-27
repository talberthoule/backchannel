import http.server
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import updater
from updater import (
    INSTANCE_HEADER,
    PlanError,
    apply_update,
    expected_launcher,
    expected_root,
    instance_is_healthy,
    validate_plan,
)


class UpdaterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.app_data = self.root / "app-data"
        self.updates = self.app_data / "updates"
        self.updates.mkdir(parents=True)
        self.install = self.root / expected_root()
        self.install.mkdir()
        self.launcher = expected_launcher()
        old_launcher = self.install / Path(self.launcher)
        old_launcher.parent.mkdir(parents=True, exist_ok=True)
        old_launcher.write_text("old")
        self.stage_parent = self.root / ".backchannel-stage-v0.4.0"
        self.stage = self.stage_parent / expected_root()
        self.stage.mkdir(parents=True)
        new_launcher = self.stage / Path(self.launcher)
        new_launcher.parent.mkdir(parents=True, exist_ok=True)
        new_launcher.write_text("new")
        self.state = self.updates / "state.json"
        self.state.write_text(json.dumps({
            "state": "applying",
            "available_version": "v0.4.0",
        }))
        self.plan_path = self.updates / "apply.json"
        self.plan = {
            "schema": 1,
            "version": "v0.4.0",
            "requested_at": "2026-07-26T18:00:00Z",
            "old_pid": 999_999,
            "app_data_dir": str(self.app_data),
            "install_dir": str(self.install),
            "staged_dir": str(self.stage),
            "backup_dir": str(self.root / f"{expected_root()}.backup-v0.4.0"),
            "failed_dir": str(self.root / f"{expected_root()}.failed-v0.4.0"),
            "launcher": self.launcher,
            "lock_path": str(self.app_data / "launcher.json"),
            "state_path": str(self.state),
        }
        self.write_plan()

    def tearDown(self):
        self.temp.cleanup()

    def write_plan(self):
        self.plan_path.write_text(json.dumps(self.plan))

    def test_plan_validation_accepts_only_exact_sibling_paths_and_applying_state(self):
        value = validate_plan(self.plan, self.plan_path)
        self.assertEqual(value.version, "v0.4.0")
        self.assertEqual(value.install_dir, self.install)
        self.assertEqual(value.staged_dir, self.stage)

        cases = [
            {**self.plan, "extra": True},
            {key: value for key, value in self.plan.items() if key != "version"},
            {**self.plan, "schema": 2},
            {**self.plan, "version": "v04.0.0"},
            {**self.plan, "install_dir": "relative"},
            {**self.plan, "backup_dir": str(self.root / "elsewhere" / "backup")},
            {**self.plan, "launcher": "../Backchannel.exe"},
        ]
        for invalid in cases:
            with self.subTest(invalid=invalid):
                with self.assertRaises(PlanError):
                    validate_plan(invalid, self.plan_path)

        Path(self.plan["backup_dir"]).mkdir()
        with self.assertRaises(PlanError):
            validate_plan(self.plan, self.plan_path)
        Path(self.plan["backup_dir"]).rmdir()
        Path(self.plan["failed_dir"]).mkdir()
        with self.assertRaises(PlanError):
            validate_plan(self.plan, self.plan_path)
        Path(self.plan["failed_dir"]).rmdir()

        self.state.write_text(json.dumps({
            "state": "ready",
            "available_version": "v0.4.0",
        }))
        with self.assertRaises(PlanError):
            validate_plan(self.plan, self.plan_path)

    def test_plan_validation_rejects_cross_filesystem_staging(self):
        real_stat = os.stat

        def different_device(path, *args, **kwargs):
            result = real_stat(path, *args, **kwargs)
            if Path(path) == self.stage:
                fields = list(result)
                fields[2] += 1
                return os.stat_result(fields)
            return result

        with patch("updater.os.stat", side_effect=different_device):
            with self.assertRaises(PlanError):
                validate_plan(self.plan, self.plan_path)

    def test_plan_validation_rejects_symlinked_existing_roots(self):
        target = self.root / "real-state.json"
        target.write_text(self.state.read_text())
        self.state.unlink()
        try:
            self.state.symlink_to(target)
        except OSError as error:
            self.skipTest(f"symlink privilege unavailable: {error}")
        with self.assertRaises(PlanError):
            validate_plan(self.plan, self.plan_path)

    def test_success_swaps_launches_verifies_and_only_then_removes_backup(self):
        process = Mock()
        process.poll.return_value = None
        process_factory = Mock(return_value=process)
        health = Mock(return_value=True)
        result = apply_update(
            self.plan_path,
            process_factory=process_factory,
            health=health,
            pid_running=lambda _pid: False,
            sleep=lambda _seconds: None,
        )
        self.assertEqual(result, 0)
        self.assertEqual((self.install / Path(self.launcher)).read_text(), "new")
        self.assertFalse(Path(self.plan["backup_dir"]).exists())
        self.assertFalse(self.plan_path.exists())
        process_factory.assert_called_once_with(
            [str(self.install / Path(self.launcher))],
            cwd=str(self.install),
        )
        health.assert_called_once_with(self.app_data)

    def test_main_leaves_the_install_tree_before_applying(self):
        previous = Path.cwd()
        try:
            os.chdir(self.install)
            with (
                patch.object(updater.sys, "argv", ["updater", str(self.plan_path)]),
                patch.object(updater, "apply_update", return_value=0) as apply,
            ):
                self.assertEqual(updater.main(), 0)
            self.assertEqual(Path.cwd(), self.plan_path.parent)
            apply.assert_called_once_with(self.plan_path)
        finally:
            os.chdir(previous)

    def test_exited_new_process_rolls_back_immediately_and_relaunches_old(self):
        failed_process = Mock()
        failed_process.poll.return_value = 7
        old_process = Mock()
        process_factory = Mock(side_effect=[failed_process, old_process])
        health = Mock(return_value=False)
        result = apply_update(
            self.plan_path,
            process_factory=process_factory,
            health=health,
            pid_running=lambda _pid: False,
            sleep=lambda _seconds: None,
        )
        self.assertEqual(result, 1)
        self.assertEqual((self.install / Path(self.launcher)).read_text(), "old")
        self.assertEqual(
            (Path(self.plan["failed_dir"]) / Path(self.launcher)).read_text(),
            "new",
        )
        health.assert_not_called()
        self.assertEqual(process_factory.call_count, 2)

    def test_wrong_health_until_timeout_rolls_back_a_running_child(self):
        new_process = Mock()
        new_process.poll.return_value = None
        old_process = Mock()
        process_factory = Mock(side_effect=[new_process, old_process])
        result = apply_update(
            self.plan_path,
            process_factory=process_factory,
            health=lambda _app_data: False,
            pid_running=lambda _pid: False,
            monotonic=Mock(side_effect=[0, 0, 301]),
            sleep=lambda _seconds: None,
        )
        self.assertEqual(result, 1)
        new_process.terminate.assert_called_once_with()
        self.assertEqual((self.install / Path(self.launcher)).read_text(), "old")

    def test_health_requires_the_new_lock_and_matching_response_token(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            token = "new-token"

            def log_message(self, *_):
                pass

            def do_GET(self):
                self.send_response(200)
                self.send_header(INSTANCE_HEADER, self.token)
                self.end_headers()
                self.wfile.write(b'{"status":"ok"}')

        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        lock = self.app_data / "launcher.json"
        self.assertFalse(instance_is_healthy(self.app_data))
        lock.write_text(json.dumps({
            "port": server.server_port,
            "pid": 123,
            "token": "wrong-token",
        }))
        self.assertFalse(instance_is_healthy(self.app_data))
        lock.write_text(json.dumps({
            "port": server.server_port,
            "pid": 123,
            "token": "new-token",
        }))
        self.assertTrue(instance_is_healthy(self.app_data))

    def test_old_process_or_lock_timeout_never_moves_the_good_install(self):
        (self.app_data / "launcher.json").write_text("{}")
        process_factory = Mock()
        result = apply_update(
            self.plan_path,
            process_factory=process_factory,
            health=lambda _app_data: False,
            pid_running=lambda _pid: True,
            monotonic=Mock(side_effect=[0, 61]),
            sleep=lambda _seconds: None,
        )
        self.assertEqual(result, 1)
        self.assertEqual((self.install / Path(self.launcher)).read_text(), "old")
        self.assertTrue(self.stage.exists())
        process_factory.assert_not_called()

    def test_rollback_failure_keeps_backup_and_failed_bundle_for_recovery(self):
        failed_process = Mock()
        failed_process.poll.return_value = 1
        real_replace = os.replace

        def replace(source, target):
            if Path(source) == Path(self.plan["backup_dir"]):
                raise OSError("restore failed")
            return real_replace(source, target)

        with patch("updater.os.replace", side_effect=replace):
            result = apply_update(
                self.plan_path,
                process_factory=Mock(return_value=failed_process),
                health=lambda _app_data: False,
                pid_running=lambda _pid: False,
                sleep=lambda _seconds: None,
            )
        self.assertEqual(result, 2)
        self.assertTrue(Path(self.plan["backup_dir"]).exists())
        self.assertTrue(Path(self.plan["failed_dir"]).exists())
        rollback = json.loads((self.updates / "rollback.json").read_text())
        self.assertEqual(rollback["status"], "manual_recovery_required")


if __name__ == "__main__":
    unittest.main()
