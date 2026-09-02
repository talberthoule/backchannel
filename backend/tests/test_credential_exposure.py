"""A stored provider key never comes back out of the API or the logs.

Drives the real routers through the real app (Host guard included) with the
database replaced by an in-memory stand-in, saves a key, then reads every
surface that describes credentials - the credentials list, the endpoint list,
connection-test results, provider error responses - and checks the plaintext
and its Fernet ciphertext appear in none of them.
"""

import os
import tempfile
import unittest
from datetime import datetime, timezone
from unittest import mock

import httpx
from fastapi.testclient import TestClient

from app.models import CustomEndpoint

SECRET = "AIzaSyStoredKeyThatMustNeverLeak0123456789"
ENDPOINT_SECRET = "endpoint-proxy-token-0a1b2c3d4e5f6789"


class FakeDb:
    def __init__(self):
        self.rows: dict[str, object] = {}

    async def get(self, _model, key):
        return self.rows.get(key)

    async def commit(self):
        pass

    async def flush(self):
        pass

    async def refresh(self, _obj):
        pass


class CredentialExposureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(
            os.environ,
            {"DATA_DIR": self.tmp.name},
            clear=False,
        )
        self.env.start()
        os.environ.pop("CREDENTIALS_MASTER_KEY", None)
        os.environ.pop("CREDENTIALS_MASTER_KEY_PROTECTION", None)

        from app.database import get_db
        from app.main import app
        from app.routers import credentials as credentials_router
        from app.routers import endpoints as endpoints_router
        from app.services import provider_health, redaction
        from app.services import secrets as secrets_mod

        secrets_mod._fernet = None
        redaction.clear_registered_secrets()
        self.secrets = secrets_mod
        self.redaction = redaction
        self.db = FakeDb()
        self.settings_store: dict[str, str] = {}

        async def fake_get(db, key, default=""):
            return self.settings_store.get(key, default)

        async def fake_set(db, key, value):
            self.settings_store[key] = value

        self.patches = [
            mock.patch.object(secrets_mod, "get_app_setting", fake_get),
            mock.patch.object(secrets_mod, "set_app_setting", fake_set),
            mock.patch.object(provider_health, "get_app_setting", fake_get),
            mock.patch.object(provider_health, "set_app_setting", fake_set),
            mock.patch.object(provider_health, "env_provider_key", lambda provider: ""),
        ]
        for p in self.patches:
            p.start()

        async def override_db():
            yield self.db

        app.dependency_overrides[get_db] = override_db
        self.app = app
        self.get_db = get_db
        self.credentials_router = credentials_router
        self.endpoints_router = endpoints_router
        self.client = TestClient(app, base_url="http://localhost")

    def tearDown(self):
        self.app.dependency_overrides.pop(self.get_db, None)
        for p in self.patches:
            p.stop()
        self.secrets._fernet = None
        self.redaction.clear_registered_secrets()
        self.env.stop()
        self.tmp.cleanup()

    def _assert_clean(self, text: str, *values: str):
        for value in values:
            self.assertNotIn(value, text)
        self.assertNotIn("gAAAA", text, "a Fernet ciphertext escaped into a response")

    def test_saved_key_is_never_returned(self):
        with mock.patch.object(
            self.credentials_router, "run_connection_test", mock.AsyncMock(return_value=(True, "Connection successful"))
        ):
            saved = self.client.put("/api/credentials/google", json={"api_key": SECRET})
        self.assertEqual(200, saved.status_code, saved.text)
        self._assert_clean(saved.text, SECRET)
        self.assertEqual("..." + SECRET[-4:], saved.json()["masked"])
        self.assertTrue(saved.json()["configured"])

        listed = self.client.get("/api/credentials")
        self.assertEqual(200, listed.status_code, listed.text)
        self._assert_clean(listed.text, SECRET)
        google = next(row for row in listed.json() if row["provider"] == "google")
        self.assertTrue(google["configured"])
        self.assertLessEqual(len(google["masked"]), 7)

        # The row in the settings store is ciphertext only.
        self.assertNotIn(SECRET, self.settings_store["credentials.google.api_key"])

    def _make_master_key_unusable(self):
        # A DPAPI blob this account cannot unwrap (or a folder moved to
        # another PC): readable-looking file, no usable key.
        key_file = os.path.join(self.tmp.name, "master.key")
        with open(key_file, "wb") as handle:
            handle.write(b"dpapi:AAAA")
        self.secrets._fernet = None
        patch = mock.patch.object(self.secrets, "dpapi_available", lambda: False)
        patch.start()
        self.addCleanup(patch.stop)
        return key_file

    def test_saving_a_key_with_an_unusable_master_key_is_a_503_with_recovery_steps(self):
        key_file = self._make_master_key_unusable()
        response = self.client.put("/api/credentials/google", json={"api_key": SECRET})
        self.assertEqual(503, response.status_code, response.text)
        detail = response.json()["detail"]
        self.assertIn(key_file, detail)
        self.assertIn("delete that file", detail)
        self.assertIn("re-enter the provider keys", detail)
        self._assert_clean(response.text, SECRET)
        # Reads still answer, reporting the provider as unconfigured.
        listed = self.client.get("/api/credentials")
        self.assertEqual(200, listed.status_code, listed.text)
        self.assertFalse(next(row for row in listed.json() if row["provider"] == "google")["configured"])

    def test_saving_an_endpoint_key_with_an_unusable_master_key_is_a_503(self):
        from app.services import custom_endpoints

        key_file = self._make_master_key_unusable()

        async def no_endpoints(db):
            return []

        with mock.patch.object(custom_endpoints, "list_endpoints", no_endpoints), \
             mock.patch.object(self.endpoints_router, "list_endpoints", no_endpoints):
            response = self.client.post(
                "/api/endpoints",
                json={"name": "Proxy", "base_url": "https://proxy.example/v1", "api_key": ENDPOINT_SECRET},
            )
        self.assertEqual(503, response.status_code, response.text)
        self.assertIn(key_file, response.json()["detail"])
        self._assert_clean(response.text, ENDPOINT_SECRET)

    def test_connection_test_failure_message_is_scrubbed(self):
        self.settings_store["credentials.google.api_key"] = self.secrets.encrypt_value(SECRET)
        # Simulate an SDK failure that quotes the request it made.
        boom = RuntimeError(f"401 for url https://generativelanguage.googleapis.com/v1beta/models?key={SECRET}")
        with mock.patch("google.genai.Client", side_effect=boom):
            response = self.client.post("/api/credentials/google/test")
        self.assertEqual(200, response.status_code, response.text)
        self.assertFalse(response.json()["ok"])
        self._assert_clean(response.text, SECRET)
        self.assertIn("[redacted]", response.json()["message"])

    def test_endpoint_list_and_probe_never_return_the_key(self):
        endpoint = CustomEndpoint(
            id="proxy",
            name="Proxy",
            base_url="https://proxy.example/v1",
            api_key=self.secrets.encrypt_value(ENDPOINT_SECRET),
            models=[{"id": "m", "label": "m"}],
            enabled=True,
            display_order=0,
            last_status="",
            last_error="",
            last_checked_at=None,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            deleted_at=None,
        )
        self.db.rows["proxy"] = endpoint

        async def fake_list(db):
            return [endpoint]

        failed_probe = mock.AsyncMock(
            return_value=(False, f"HTTP 401 for https://proxy.example/v1/models with Bearer {ENDPOINT_SECRET}", [])
        )
        with mock.patch.object(self.endpoints_router, "list_endpoints", fake_list), \
             mock.patch.object(self.endpoints_router, "probe", failed_probe):
            listed = self.client.get("/api/endpoints")
            self.assertEqual(200, listed.status_code, listed.text)
            self._assert_clean(listed.text, ENDPOINT_SECRET)
            self.assertTrue(listed.json()[0]["has_api_key"])
            self.assertNotIn("api_key", listed.json()[0])

            tested = self.client.post("/api/endpoints/proxy/test")
            self.assertEqual(200, tested.status_code, tested.text)
            self._assert_clean(tested.text, ENDPOINT_SECRET)
            # The probe was handed the decrypted key (so the test is real)...
            self.assertEqual(ENDPOINT_SECRET, failed_probe.await_args.args[1])
            # ...and the stored/returned error text is scrubbed.
            self.assertIn("[redacted]", endpoint.last_error)

            listed_again = self.client.get("/api/endpoints")
            self._assert_clean(listed_again.text, ENDPOINT_SECRET)

    def test_unsaved_probe_error_is_scrubbed(self):
        from app.services import custom_endpoints

        boom = httpx.HTTPStatusError(
            f"Client error '401' for url 'https://proxy.example/v1/models?api_key={ENDPOINT_SECRET}'",
            request=httpx.Request("GET", "https://proxy.example/v1/models"),
            response=httpx.Response(401, request=httpx.Request("GET", "https://proxy.example/v1/models")),
        )

        class FailingClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def get(self, *args, **kwargs):
                raise RuntimeError(f"transport failure while sending Bearer {ENDPOINT_SECRET}")

        with mock.patch.object(custom_endpoints.httpx, "AsyncClient", FailingClient):
            response = self.client.post(
                "/api/endpoints/probe",
                json={"base_url": "https://proxy.example/v1", "api_key": ENDPOINT_SECRET},
            )
        self.assertEqual(200, response.status_code, response.text)
        self._assert_clean(response.text, ENDPOINT_SECRET)
        del boom

    def test_provider_error_response_and_log_are_scrubbed(self):
        from app.services import provider_errors

        self.redaction.register_secret(SECRET)
        request = httpx.Request("POST", f"https://api.openai.com/v1/chat/completions?key={SECRET}")
        exc = httpx.HTTPStatusError(
            f"Client error '401 Unauthorized' for url '{request.url}'",
            request=request,
            response=httpx.Response(401, request=request, text="{}"),
        )
        with self.assertLogs("app.services.provider_errors", level="WARNING") as captured:
            http_exc = provider_errors.provider_error_to_http("openai", exc)
        self.assertNotIn(SECRET, http_exc.detail)
        self.assertNotIn(SECRET, "\n".join(captured.output))

    def test_gateway_exception_logs_are_scrubbed(self):
        import logging

        self.redaction.register_secret(SECRET)
        logger = logging.getLogger("app.services.gemini_live")
        with self.assertLogs(logger, level="WARNING") as captured:
            try:
                raise RuntimeError(f"websocket rejected x-goog-api-key: {SECRET}")
            except RuntimeError as e:
                logger.warning(f"Error closing Gemini session: {e}")
                logger.exception("session failed")
        self.assertNotIn(SECRET, "\n".join(captured.output))


if __name__ == "__main__":
    unittest.main()
