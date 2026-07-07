import importlib.util
import unittest
from pathlib import Path
from unittest import mock

# Import by file path: inside the Docker image a site-packages "scripts"
# package (pulled in by NeMo dependencies) shadows backend/scripts.
_spec = importlib.util.spec_from_file_location(
    "install_sortformer_under_test",
    Path(__file__).resolve().parents[1] / "scripts" / "install_sortformer.py",
)
_install_sortformer = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_install_sortformer)
CUDA_TORCH_INDEX_URL = _install_sortformer.CUDA_TORCH_INDEX_URL
CPU_TORCH_INDEX_URL = _install_sortformer.CPU_TORCH_INDEX_URL
resolve_torch_index_url = _install_sortformer.resolve_torch_index_url


class FakeDb:
    async def commit(self):
        pass


class TorchIndexUrlTests(unittest.TestCase):
    def test_shorthand_channel_maps_to_pytorch_index(self):
        self.assertEqual("https://download.pytorch.org/whl/cpu", resolve_torch_index_url("cpu"))
        self.assertEqual("https://download.pytorch.org/whl/rocm6.4", resolve_torch_index_url("rocm6.4"))

    def test_full_url_passes_through(self):
        url = "https://download.pytorch.org/whl/cu130"
        self.assertEqual(url, resolve_torch_index_url(url))

    def test_auto_uses_cuda_when_nvidia_gpu_present(self):
        with mock.patch.object(_install_sortformer, "nvidia_gpu_present", lambda: True):
            self.assertEqual(CUDA_TORCH_INDEX_URL, resolve_torch_index_url("auto"))
            self.assertEqual(CUDA_TORCH_INDEX_URL, resolve_torch_index_url(""))

    def test_auto_uses_cpu_without_nvidia_gpu(self):
        with mock.patch.object(_install_sortformer, "nvidia_gpu_present", lambda: False):
            self.assertEqual(CPU_TORCH_INDEX_URL, resolve_torch_index_url("auto"))
            self.assertEqual(CPU_TORCH_INDEX_URL, resolve_torch_index_url(""))


class ProviderHealthTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        from app.services import provider_health

        self.health = provider_health
        self.settings_store: dict[str, str] = {}
        self.secrets_store: dict[str, str] = {}
        self.db = FakeDb()

        async def fake_get_setting(db, key, default=""):
            return self.settings_store.get(key, default)

        async def fake_set_setting(db, key, value):
            self.settings_store[key] = value

        async def fake_get_secret(db, key):
            return self.secrets_store.get(key, "")

        self.patches = [
            mock.patch.object(provider_health, "get_app_setting", fake_get_setting),
            mock.patch.object(provider_health, "set_app_setting", fake_set_setting),
            mock.patch.object(provider_health, "get_secret", fake_get_secret),
            mock.patch.object(provider_health, "env_provider_key", lambda provider: ""),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    async def test_no_key_is_unavailable_and_disconnected(self):
        status = await self.health.get_provider_status(self.db, "google")
        self.assertFalse(status["key_available"])
        self.assertFalse(status["connected"])
        self.assertFalse(status["configured"])

    async def test_untested_key_is_available_but_not_connected(self):
        self.secrets_store["credentials.google.api_key"] = "stored-key-12345"
        status = await self.health.get_provider_status(self.db, "google")
        self.assertTrue(status["key_available"])
        self.assertFalse(status["connected"])

    async def test_passing_test_marks_connected(self):
        self.secrets_store["credentials.google.api_key"] = "stored-key-12345"
        await self.health.record_test_outcome(self.db, "google", "stored-key-12345", True)
        status = await self.health.get_provider_status(self.db, "google")
        self.assertTrue(status["connected"])
        self.assertTrue(status["key_available"])

    async def test_failing_test_locks_provider(self):
        self.secrets_store["credentials.google.api_key"] = "stored-key-12345"
        await self.health.record_test_outcome(self.db, "google", "stored-key-12345", False)
        status = await self.health.get_provider_status(self.db, "google")
        self.assertFalse(status["connected"])
        self.assertFalse(status["key_available"])

    async def test_replacing_a_failed_key_resets_to_untested_available(self):
        self.secrets_store["credentials.google.api_key"] = "bad-key-1234567"
        await self.health.record_test_outcome(self.db, "google", "bad-key-1234567", False)
        self.secrets_store["credentials.google.api_key"] = "new-key-1234567"
        status = await self.health.get_provider_status(self.db, "google")
        self.assertTrue(status["key_available"])
        self.assertFalse(status["connected"])

    async def test_env_fallback_reported(self):
        with mock.patch.object(self.health, "env_provider_key", lambda provider: "env-key-1234567"):
            status = await self.health.get_provider_status(self.db, "openai")
        self.assertTrue(status["env_fallback"])
        self.assertFalse(status["configured"])
        self.assertTrue(status["key_available"])


if __name__ == "__main__":
    unittest.main()
