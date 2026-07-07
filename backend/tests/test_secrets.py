import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


class SecretsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["DATA_DIR"] = self.tmp.name
        os.environ.pop("CREDENTIALS_MASTER_KEY", None)

        from app.services import secrets as secrets_mod

        self.secrets = secrets_mod
        self.secrets._fernet = None

        self.store: dict[str, str] = {}

        async def fake_get(db, key, default=""):
            return self.store.get(key, default)

        async def fake_set(db, key, value):
            self.store[key] = value

        self.patches = [
            mock.patch.object(secrets_mod, "get_app_setting", fake_get),
            mock.patch.object(secrets_mod, "set_app_setting", fake_set),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.secrets._fernet = None
        self.tmp.cleanup()

    async def test_round_trip_and_ciphertext_at_rest(self):
        await self.secrets.set_secret(None, "credentials.google.api_key", "sk-test-secret-123")
        stored = self.store["credentials.google.api_key"]
        self.assertNotIn("sk-test-secret-123", stored)
        value = await self.secrets.get_secret(None, "credentials.google.api_key")
        self.assertEqual("sk-test-secret-123", value)

    async def test_unset_key_returns_empty(self):
        self.assertEqual("", await self.secrets.get_secret(None, "credentials.openai.api_key"))

    async def test_empty_value_clears_secret(self):
        await self.secrets.set_secret(None, "credentials.google.api_key", "something")
        await self.secrets.set_secret(None, "credentials.google.api_key", "")
        self.assertEqual("", await self.secrets.get_secret(None, "credentials.google.api_key"))

    async def test_master_key_file_created_private(self):
        await self.secrets.set_secret(None, "credentials.google.api_key", "x" * 20)
        key_file = Path(self.tmp.name) / "master.key"
        self.assertTrue(key_file.exists())
        self.assertEqual(0o600, key_file.stat().st_mode & 0o777)

    async def test_wrong_master_key_reads_as_unset(self):
        await self.secrets.set_secret(None, "credentials.google.api_key", "sk-original")
        # Simulate a replaced master key: force regeneration with a fresh key.
        (Path(self.tmp.name) / "master.key").unlink()
        self.secrets._fernet = None
        self.assertEqual("", await self.secrets.get_secret(None, "credentials.google.api_key"))

    async def test_provider_key_prefers_stored_over_env(self):
        from app.config import settings

        with mock.patch.object(settings, "OPENAI_API_KEY", "env-openai-key"):
            self.assertEqual("env-openai-key", await self.secrets.get_provider_key(None, "openai"))
            await self.secrets.set_secret(None, "credentials.openai.api_key", "stored-openai-key")
            self.assertEqual("stored-openai-key", await self.secrets.get_provider_key(None, "openai"))

    async def test_provider_key_google_env_fallback(self):
        from app.config import settings

        with mock.patch.object(settings, "GEMINI_API_KEY", "env-gemini-key"):
            self.assertEqual("env-gemini-key", await self.secrets.get_provider_key(None, "google"))

    def test_mask_key(self):
        self.assertEqual("AIza...wxyz", self.secrets.mask_key("AIzaSomethingLong-wxyz"))
        self.assertEqual("", self.secrets.mask_key("short"))
        self.assertEqual("", self.secrets.mask_key(""))


if __name__ == "__main__":
    unittest.main()
