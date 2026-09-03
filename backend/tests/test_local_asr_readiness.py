"""The local ASR runtime must be proven, not assumed.

Two shipped desktop builds in a row reported transcription as ready and then
failed every single job, because readiness only asked whether the module name
resolved. v0.6.1 could not read onnx-asr's version metadata; v0.6.2, after
that was fixed, could not read its data files. Both import cleanly, so the
name check said yes both times (ALP-376).
"""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from cryptography.fernet import Fernet

os.environ.setdefault("CREDENTIALS_MASTER_KEY", Fernet.generate_key().decode())

from app.services import transcription_readiness as readiness  # noqa: E402


class ProbeTests(unittest.TestCase):
    def setUp(self):
        readiness.reset_local_asr_probe_for_tests()
        self.addCleanup(readiness.reset_local_asr_probe_for_tests)

    def test_missing_package_is_reported(self):
        with patch.object(readiness.importlib.util, "find_spec", return_value=None):
            usable, why = readiness.local_asr_status()
        self.assertFalse(usable)
        self.assertIn("not installed", why)

    def test_import_failure_is_reported_not_raised(self):
        """v0.6.1's shape: the package is present but raises on import."""
        with patch.object(readiness.importlib.util, "find_spec", return_value=object()), \
                patch.dict(sys.modules, {"onnx_asr.preprocessors": None}):
            with patch("builtins.__import__", side_effect=ImportError(
                    "No package metadata was found for onnx-asr")):
                usable, why = readiness.local_asr_status()
        self.assertFalse(usable)
        self.assertIn("failed to load", why)
        self.assertIn("onnx-asr", why)

    def test_missing_data_files_are_reported(self):
        """v0.6.2's shape: imports fine, but the data it reads is not bundled."""
        missing = SimpleNamespace(is_file=lambda: False)
        data = SimpleNamespace(joinpath=lambda name: missing)
        package = SimpleNamespace(joinpath=lambda name: data)
        with patch.object(readiness.importlib.util, "find_spec", return_value=object()), \
                patch("importlib.resources.files", return_value=package):
            usable, why = readiness.local_asr_status()
        self.assertFalse(usable)
        self.assertIn("data files", why)
        self.assertIn("fbanks.npz", why)

    def test_usable_when_everything_resolves(self):
        present = SimpleNamespace(is_file=lambda: True)
        data = SimpleNamespace(joinpath=lambda name: present)
        package = SimpleNamespace(joinpath=lambda name: data)
        with patch.object(readiness.importlib.util, "find_spec", return_value=object()), \
                patch("importlib.resources.files", return_value=package):
            usable, why = readiness.local_asr_status()
        self.assertTrue(usable)
        self.assertEqual("", why)

    def test_result_is_cached(self):
        calls = []

        def probe():
            calls.append(1)
            return True, ""

        with patch.object(readiness, "_probe_local_asr", probe):
            for _ in range(5):
                readiness.local_asr_status()
        self.assertEqual(1, len(calls))

    def test_the_real_environment_is_usable(self):
        """Guards this checkout: if this fails, a bundle built here is broken."""
        usable, why = readiness.local_asr_status()
        self.assertTrue(usable, f"local ASR runtime unusable here: {why}")


class ReadinessMessageTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        readiness.reset_local_asr_probe_for_tests()
        self.addCleanup(readiness.reset_local_asr_probe_for_tests)

    async def test_reason_names_the_actual_defect(self):
        """The old message always blamed a missing install, whatever was wrong."""
        runtime = SimpleNamespace(batch_model_id="local-whisper-base")
        with patch.object(readiness, "get_transcription_runtime_config", return_value=runtime), \
                patch.object(readiness, "local_asr_status",
                             return_value=(False, "the onnx-asr runtime is missing its data files (fbanks.npz)")):
            result = await readiness.get_transcription_readiness(object())
        self.assertFalse(result.ready)
        self.assertIn("data files", result.reason)
        self.assertIn("fbanks.npz", result.reason)


if __name__ == "__main__":
    unittest.main()
