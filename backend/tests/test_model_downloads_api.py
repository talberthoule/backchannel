"""The /api/model-downloads surface and the non-blocking NER install.

The install endpoint must answer immediately. Sitting on the transfer is how
the old one turned a slow first-use fetch into something indistinguishable
from a hang (ALP-373).
"""

import os
import unittest
from unittest.mock import patch

from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("CREDENTIALS_MASTER_KEY", Fernet.generate_key().decode())

from app.routers import model_downloads as router_module  # noqa: E402
from app.routers import pii_shield  # noqa: E402
from app.services import model_downloads  # noqa: E402
from app.services.pii import ner  # noqa: E402


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router_module.router)
    app.include_router(pii_shield.router)
    return TestClient(app)


class ListTests(unittest.TestCase):
    def setUp(self):
        model_downloads.reset()
        self.addCleanup(model_downloads.reset)
        self.client = _client()

    def test_empty_when_nothing_has_been_fetched(self):
        body = self.client.get("/api/model-downloads").json()
        self.assertEqual({"downloads": [], "active": 0, "failed": 0}, body)

    def test_reports_an_in_flight_download(self):
        model_downloads.claim("pii-ner", "Name recognition model", "PII Shield")
        model_downloads.advance("pii-ner", 25, 100)
        body = self.client.get("/api/model-downloads").json()
        self.assertEqual(1, body["active"])
        entry = body["downloads"][0]
        self.assertEqual("downloading", entry["state"])
        self.assertEqual(25, entry["percent"])
        self.assertEqual("PII Shield", entry["purpose"])

    def test_reports_a_failure_with_its_reason(self):
        model_downloads.claim("pii-ner", "Name recognition model")
        model_downloads.fail("pii-ner", "ConnectError: offline")
        body = self.client.get("/api/model-downloads").json()
        self.assertEqual(1, body["failed"])
        self.assertIn("offline", body["downloads"][0]["error"])


class RetryTests(unittest.TestCase):
    def setUp(self):
        model_downloads.reset()
        self.addCleanup(model_downloads.reset)
        self.client = _client()

    def test_retry_clears_the_old_failure_and_starts_again(self):
        model_downloads.claim(ner.DOWNLOAD_KEY, "Name recognition model")
        model_downloads.fail(ner.DOWNLOAD_KEY, "offline")
        with patch.object(ner, "install") as install:
            response = self.client.post(f"/api/model-downloads/{ner.DOWNLOAD_KEY}/retry")
        self.assertEqual(202, response.status_code)
        install.assert_called_once()

    def test_retry_of_a_running_download_does_not_start_a_second(self):
        model_downloads.claim(ner.DOWNLOAD_KEY, "Name recognition model")
        model_downloads.begin(ner.DOWNLOAD_KEY)
        with patch.object(ner, "install") as install:
            response = self.client.post(f"/api/model-downloads/{ner.DOWNLOAD_KEY}/retry")
        self.assertEqual(202, response.status_code)
        install.assert_not_called()

    def test_unknown_key_is_a_404(self):
        self.assertEqual(404, self.client.post("/api/model-downloads/nope/retry").status_code)

    def test_an_asr_download_is_not_retryable_from_here(self):
        """Nothing sensible to kick off: the transcription that needs it fetches it."""
        response = self.client.post("/api/model-downloads/asr:local-whisper-base/retry")
        self.assertEqual(404, response.status_code)


class DismissTests(unittest.TestCase):
    def setUp(self):
        model_downloads.reset()
        self.addCleanup(model_downloads.reset)
        self.client = _client()

    def test_dismiss_forgets_a_failed_entry(self):
        model_downloads.claim("pii-ner", "Name recognition model")
        model_downloads.fail("pii-ner", "offline")
        self.assertEqual(204, self.client.delete("/api/model-downloads/pii-ner").status_code)
        self.assertIsNone(model_downloads.get("pii-ner"))

    def test_a_running_download_cannot_be_dismissed(self):
        model_downloads.claim("pii-ner", "Name recognition model")
        model_downloads.begin("pii-ner")
        self.assertEqual(409, self.client.delete("/api/model-downloads/pii-ner").status_code)


class InstallEndpointTests(unittest.TestCase):
    def setUp(self):
        model_downloads.reset()
        self.addCleanup(model_downloads.reset)
        self.client = _client()

    def test_install_returns_without_waiting_for_the_download(self):
        with patch.object(ner, "is_installed", return_value=False), \
                patch.object(ner, "install") as install:
            response = self.client.post("/api/pii-shield/ner/install")
        self.assertEqual(202, response.status_code)
        self.assertEqual("queued", response.json()["state"])
        install.assert_called_once()

    def test_install_does_not_stack_a_second_fetch(self):
        model_downloads.claim(ner.DOWNLOAD_KEY, ner.DOWNLOAD_LABEL)
        model_downloads.begin(ner.DOWNLOAD_KEY)
        with patch.object(ner, "is_installed", return_value=False), \
                patch.object(ner, "install") as install:
            response = self.client.post("/api/pii-shield/ner/install")
        self.assertEqual(202, response.status_code)
        install.assert_not_called()


if __name__ == "__main__":
    unittest.main()
