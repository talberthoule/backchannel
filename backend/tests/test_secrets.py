import os
import sys
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

    def test_mask_key_shows_only_the_last_four_characters(self):
        self.assertEqual("...wxyz", self.secrets.mask_key("AIzaSomethingLong-wxyz"))
        self.assertNotIn("AIza", self.secrets.mask_key("AIzaSomethingLong-wxyz"))
        self.assertEqual("", self.secrets.mask_key("short"))
        self.assertEqual("", self.secrets.mask_key(""))

    async def test_decrypted_and_saved_values_are_registered_for_log_redaction(self):
        from app.services import redaction

        redaction.clear_registered_secrets()
        await self.secrets.set_secret(None, "credentials.google.api_key", "AIzaSyRegisteredValue0123456789")
        self.assertEqual(
            "[redacted]", redaction.redact_text("AIzaSyRegisteredValue0123456789")
        )
        redaction.clear_registered_secrets()
        # A fresh process only ever sees the ciphertext; reading it back must
        # register the plaintext too.
        await self.secrets.get_secret(None, "credentials.google.api_key")
        self.assertIn("[redacted]", redaction.redact_text("key AIzaSyRegisteredValue0123456789 here"))

    def test_env_fallback_is_registered_for_log_redaction(self):
        from app.config import settings
        from app.services import redaction

        redaction.clear_registered_secrets()
        with mock.patch.object(settings, "OPENAI_API_KEY", "plain-env-value-that-is-long"):
            self.secrets.env_provider_key("openai")
        self.assertEqual("[redacted]", redaction.redact_text("plain-env-value-that-is-long"))


class MasterKeyProtectionTests(unittest.IsolatedAsyncioTestCase):
    """DPAPI wrapping of the master key file (opt-in via the environment)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["DATA_DIR"] = self.tmp.name
        os.environ.pop("CREDENTIALS_MASTER_KEY", None)
        os.environ.pop("CREDENTIALS_MASTER_KEY_PROTECTION", None)

        from app.services import secrets as secrets_mod

        self.secrets = secrets_mod
        self.secrets._fernet = None
        self.key_file = Path(self.tmp.name) / "master.key"

    def tearDown(self):
        os.environ.pop("CREDENTIALS_MASTER_KEY_PROTECTION", None)
        self.secrets._fernet = None
        self.tmp.cleanup()

    def _fake_dpapi(self):
        # A reversible stand-in for CryptProtectData/CryptUnprotectData so the
        # file format and upgrade path are exercised on every platform.
        return (
            mock.patch.object(self.secrets, "dpapi_available", lambda: True),
            mock.patch.object(self.secrets, "_dpapi_protect", lambda data: b"wrapped:" + data[::-1]),
            mock.patch.object(
                self.secrets,
                "_dpapi_unprotect",
                lambda blob: blob[len(b"wrapped:"):][::-1] if blob.startswith(b"wrapped:") else (_ for _ in ()).throw(self.secrets.MasterKeyUnavailable("bad blob")),
            ),
        )

    def test_plaintext_file_by_default(self):
        key = self.secrets._master_key()
        self.assertEqual(key, self.key_file.read_bytes().strip())
        self.assertFalse(self.key_file.read_bytes().startswith(b"dpapi:"))

    def test_wrapped_file_when_dpapi_mode_is_on(self):
        os.environ["CREDENTIALS_MASTER_KEY_PROTECTION"] = "dpapi"
        patches = self._fake_dpapi()
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        key = self.secrets._master_key()
        raw = self.key_file.read_bytes()
        self.assertTrue(raw.startswith(b"dpapi:"))
        self.assertNotIn(key, raw)
        # Reading it back yields the same key.
        self.assertEqual(key, self.secrets._master_key())

    def test_plaintext_file_is_upgraded_in_place(self):
        plain = self.secrets._master_key()
        self.secrets._fernet = None
        os.environ["CREDENTIALS_MASTER_KEY_PROTECTION"] = "dpapi"
        patches = self._fake_dpapi()
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.assertEqual(plain, self.secrets._master_key())
        self.assertTrue(self.key_file.read_bytes().startswith(b"dpapi:"))
        # Turning the mode off again leaves the wrapped file readable.
        os.environ.pop("CREDENTIALS_MASTER_KEY_PROTECTION")
        self.assertEqual(plain, self.secrets._master_key())

    async def test_unreadable_wrapped_file_reads_secrets_as_unset(self):
        self.key_file.write_bytes(b"dpapi:" + b"bm90LWEtcmVhbC1ibG9i")
        patches = self._fake_dpapi()
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.assertEqual("", self.secrets.decrypt_value("gAAAAAnot-a-token", "label"))
        with self.assertRaises(self.secrets.MasterKeyUnavailable):
            self.secrets.encrypt_value("anything")

    def test_fresh_key_falls_back_to_plaintext_when_dpapi_fails(self):
        os.environ["CREDENTIALS_MASTER_KEY_PROTECTION"] = "dpapi"

        def broken(_data):
            raise self.secrets.MasterKeyUnavailable("CryptProtectData failed (error 13)")

        with mock.patch.object(self.secrets, "dpapi_available", lambda: True), \
             mock.patch.object(self.secrets, "_dpapi_protect", broken), \
             self.assertLogs("app.services.secrets", level="WARNING") as captured:
            key = self.secrets._master_key()
        self.assertTrue(self.key_file.exists())
        self.assertEqual(key, self.key_file.read_bytes().strip())
        self.assertFalse(self.key_file.read_bytes().startswith(b"dpapi:"))
        self.assertIn("storing it unwrapped", "\n".join(captured.output))
        # And the app is usable with it.
        self.secrets._fernet = None
        token = self.secrets.encrypt_value("sk-live-value-0123456789abcdef")
        self.assertEqual("sk-live-value-0123456789abcdef", self.secrets.decrypt_value(token))

    def test_key_file_is_written_atomically(self):
        self.secrets._master_key()
        self.assertFalse((Path(self.tmp.name) / "master.key.tmp").exists())
        self.assertTrue(self.key_file.exists())
        # The upgrade path uses the same write.
        os.environ["CREDENTIALS_MASTER_KEY_PROTECTION"] = "dpapi"
        patches = self._fake_dpapi()
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.secrets._master_key()
        self.assertFalse((Path(self.tmp.name) / "master.key.tmp").exists())
        self.assertTrue(self.key_file.read_bytes().startswith(b"dpapi:"))

    async def test_empty_or_corrupt_key_file_reads_as_unset_with_a_clear_log(self):
        for content in (b"", b"   \n", b"not-a-fernet-key"):
            with self.subTest(content=content):
                self.key_file.write_bytes(content)
                self.secrets._fernet = None
                with self.assertLogs("app.services.secrets", level="WARNING") as captured:
                    value = self.secrets.decrypt_value("gAAAAAnot-a-real-token", "credentials.google.api_key")
                self.assertEqual("", value)
                output = "\n".join(captured.output)
                self.assertIn("master.key", output)
                self.assertIn(str(self.key_file), output)
                # Saving is refused with the recovery message rather than a 500.
                with self.assertRaises(self.secrets.MasterKeyUnavailable) as raised:
                    self.secrets.encrypt_value("sk-value-that-should-not-store-0123")
                message = self.secrets.master_key_recovery_message(raised.exception)
                self.assertIn(str(self.key_file), message)
                self.assertIn("delete that file", message)
                # The key file was not silently regenerated over the corrupt one.
                self.assertEqual(content, self.key_file.read_bytes())

    def test_wrapped_file_off_windows_is_reported_not_regenerated(self):
        self.key_file.write_bytes(b"dpapi:AAAA")
        with mock.patch.object(self.secrets, "dpapi_available", lambda: False):
            with self.assertRaises(self.secrets.MasterKeyUnavailable):
                self.secrets._master_key()
        self.assertEqual(b"dpapi:AAAA", self.key_file.read_bytes())

    @unittest.skipUnless(sys.platform == "win32", "DPAPI is a Windows API")
    def test_real_dpapi_round_trip(self):
        payload = b"master-key-material-0123456789"
        blob = self.secrets._dpapi_protect(payload)
        self.assertNotEqual(payload, blob)
        self.assertEqual(payload, self.secrets._dpapi_unprotect(blob))


if __name__ == "__main__":
    unittest.main()
