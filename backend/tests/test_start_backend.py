import importlib.util
import subprocess
import sys
import types
import unittest
from pathlib import Path
from unittest import mock


_fake_installer = types.ModuleType("install_sortformer")
_fake_installer.ensure_sortformer_installed = mock.Mock()
_spec = importlib.util.spec_from_file_location(
    "start_backend_under_test",
    Path(__file__).resolve().parents[1] / "scripts" / "start_backend.py",
)
_start_backend = importlib.util.module_from_spec(_spec)
with mock.patch.dict(sys.modules, {"install_sortformer": _fake_installer}):
    _spec.loader.exec_module(_start_backend)


EXPECTED_COMMAND = [
    "uvicorn",
    "app.main:app",
    "--host",
    "0.0.0.0",
    "--port",
    "8000",
    "--ws-ping-timeout",
    "90",
    "--ws-max-queue",
    "2048",
    "--ws-max-size",
    "65536",
]


class BackendStartupTests(unittest.TestCase):
    def test_execs_uvicorn_without_reload(self):
        with (
            mock.patch.object(_start_backend, "ensure_sortformer_installed"),
            mock.patch.object(_start_backend.os, "execvp") as execvp,
            mock.patch.object(subprocess, "run", return_value=mock.Mock(returncode=0)),
            mock.patch.dict(_start_backend.os.environ, {"BACKEND_RELOAD": "false"}),
        ):
            _start_backend.main()

        execvp.assert_called_once_with(
            "uvicorn",
            EXPECTED_COMMAND,
        )

    def test_execs_uvicorn_with_reload_last(self):
        with (
            mock.patch.object(_start_backend, "ensure_sortformer_installed"),
            mock.patch.object(_start_backend.os, "execvp") as execvp,
            mock.patch.object(subprocess, "run", return_value=mock.Mock(returncode=0)),
            mock.patch.dict(_start_backend.os.environ, {"BACKEND_RELOAD": "true"}),
        ):
            _start_backend.main()

        execvp.assert_called_once_with(
            "uvicorn",
            EXPECTED_COMMAND + ["--reload"],
        )

    def test_native_gpu_start_uses_same_websocket_limits(self):
        script = (
            Path(__file__).resolve().parents[1]
            / "scripts"
            / "setup_windows_gpu.ps1"
        ).read_text(encoding="utf-8")

        self.assertIn("--ws-ping-timeout 90", script)
        self.assertIn("--ws-max-queue 2048", script)
        self.assertIn("--ws-max-size 65536", script)


if __name__ == "__main__":
    unittest.main()
