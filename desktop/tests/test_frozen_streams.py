"""The frozen bundle must survive libraries that write to stdout/stderr.

A windowed PyInstaller build (console=False) leaves sys.stdout and sys.stderr
as None. Libraries write to them anyway, and tqdm in particular takes its
process-global write lock, touches the stream, and releases only on the line
after -- so the AttributeError escapes with the lock still held and every later
progress bar in the process deadlocks. In v0.6.1 that froze session creation
behind a PII Shield model download (ALP-373).
"""

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = (ROOT / "desktop" / "backchannel.spec").read_text()
LAUNCHER_PATH = ROOT / "desktop" / "launcher.py"
LAUNCHER_SOURCE = LAUNCHER_PATH.read_text()


def _load_stream_guard():
    """Import just the guard, without the launcher's heavy module body."""
    namespace: dict = {"os": __import__("os"), "sys": sys}
    start = LAUNCHER_SOURCE.index("def _guarantee_standard_streams()")
    end = LAUNCHER_SOURCE.index("\n_guarantee_standard_streams()", start)
    exec(compile(LAUNCHER_SOURCE[start:end], str(LAUNCHER_PATH), "exec"), namespace)
    return namespace["_guarantee_standard_streams"]


class StreamGuardTests(unittest.TestCase):
    def setUp(self):
        self.saved = {
            name: getattr(sys, name, None)
            for name in ("stdout", "stderr", "__stdout__", "__stderr__")
        }

    def tearDown(self):
        for name, value in self.saved.items():
            setattr(sys, name, value)

    def test_none_streams_are_replaced_with_writable_objects(self):
        guard = _load_stream_guard()
        sys.stdout = None
        sys.stderr = None
        sys.__stdout__ = None
        sys.__stderr__ = None

        guard()

        for name in ("stdout", "stderr", "__stdout__", "__stderr__"):
            stream = getattr(sys, name)
            self.assertIsNotNone(stream, f"sys.{name} left as None")
            stream.write("probe")  # must not raise
        sys.stdout.close()
        sys.stderr.close()

    def test_real_streams_are_left_alone(self):
        guard = _load_stream_guard()
        marker = object()
        sys.stdout = marker
        sys.stderr = marker
        guard()
        self.assertIs(marker, sys.stdout)
        self.assertIs(marker, sys.stderr)

    def test_launcher_installs_the_guard_before_importing_the_backend(self):
        """Order matters: a late guard is no guard at all."""
        call = LAUNCHER_SOURCE.index("\n_guarantee_standard_streams()")
        backend_import = LAUNCHER_SOURCE.index("from bcdesktop.paths import")
        self.assertLess(call, backend_import)


class SpecMetadataTests(unittest.TestCase):
    """Packages that read their own version need their dist-info bundled."""

    def test_spec_copies_onnx_asr_metadata(self):
        self.assertIn("copy_metadata", SPEC)
        self.assertIn("onnx-asr", SPEC)

    def test_spec_collects_onnx_asr_data_files(self):
        """Metadata alone is not enough; the preprocessors read data files.

        Shipping the dist-info without data/fbanks.npz is what still broke
        every local transcription in v0.6.2 (ALP-376).
        """
        self.assertIn("collect_data_files", SPEC)
        self.assertIn('for _package in ("onnx_asr",)', SPEC)

    def test_spec_fails_the_build_when_no_data_is_collected(self):
        """A silent empty collection would ship the same broken bundle again."""
        self.assertIn("no data files collected", SPEC)

    def test_onnx_asr_data_files_exist_to_collect(self):
        spec = importlib.util.find_spec("onnx_asr.preprocessors")
        if spec is None or not spec.origin:
            self.skipTest("onnx-asr is not installed in this environment")
        data = Path(spec.origin).parent / "data"
        self.assertTrue((data / "fbanks.npz").is_file(), f"fbanks.npz missing under {data}")

    def test_onnx_asr_reads_its_own_version_at_import(self):
        """Guards the reason the metadata has to ship.

        onnx_asr calls importlib.metadata.version on itself at import time; if
        that stops being true the copy_metadata entry can go, but until then
        dropping it breaks every local transcription in a desktop build.
        """
        spec = importlib.util.find_spec("onnx_asr")
        if spec is None or not spec.origin:
            self.skipTest("onnx-asr is not installed in this environment")
        source = Path(spec.origin).read_text()
        self.assertIn("importlib.metadata", source)
        self.assertIn("onnx-asr", source)


if __name__ == "__main__":
    unittest.main()
