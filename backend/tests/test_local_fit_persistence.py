"""The local-model fit result survives a page reload (ALP-158).

Running the test costs real time on a local model. Losing the result to a
refresh means running it again, and it also made the applied per-model budgets
look like they had not been saved.
"""

import json
import unittest
from unittest import mock

from app.services import local_fit


class _FakeSettingsStore:
    """Stand-in for the app_settings table."""

    def __init__(self, values: dict | None = None):
        self.values = values or {}
        self.commits = 0

    async def get(self, db, key, default=""):
        return self.values.get(key, default)

    async def set(self, db, key, value):
        self.values[key] = value


class _FakeDB:
    def __init__(self, store):
        self.store = store

    async def commit(self):
        self.store.commits += 1


class FitResultPersistenceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.store = _FakeSettingsStore()
        self.db = _FakeDB(self.store)
        self.enterContext(
            mock.patch.object(local_fit, "get_app_setting", self.store.get)
        )
        self.enterContext(
            mock.patch.object(local_fit, "set_app_setting", self.store.set)
        )

    async def test_a_stored_result_is_returned_verbatim(self):
        result = {"has_local_text_models": True, "text_models": [{"id": "m"}]}
        await local_fit.store_local_fit_result(self.db, result)

        loaded = await local_fit.load_local_fit_result(self.db)

        self.assertEqual(True, loaded["has_local_text_models"])
        self.assertEqual([{"id": "m"}], loaded["text_models"])

    async def test_the_result_is_stamped_so_staleness_is_visible(self):
        await local_fit.store_local_fit_result(self.db, {"has_local_text_models": True})
        loaded = await local_fit.load_local_fit_result(self.db)
        self.assertIn("completed_at", loaded)

    async def test_storing_does_not_mutate_the_caller_payload(self):
        result = {"has_local_text_models": True}
        await local_fit.store_local_fit_result(self.db, result)
        # The live response the user is waiting on must not gain fields.
        self.assertNotIn("completed_at", result)

    async def test_no_previous_run_reads_as_none(self):
        self.assertIsNone(await local_fit.load_local_fit_result(self.db))

    async def test_corrupt_stored_json_is_ignored_rather_than_raising(self):
        self.store.values[local_fit.LOCAL_FIT_RESULT_KEY] = "{not json"
        self.assertIsNone(await local_fit.load_local_fit_result(self.db))

    async def test_a_non_object_payload_is_ignored(self):
        self.store.values[local_fit.LOCAL_FIT_RESULT_KEY] = json.dumps([1, 2])
        self.assertIsNone(await local_fit.load_local_fit_result(self.db))

    async def test_a_storage_failure_does_not_lose_the_users_benchmark(self):
        async def boom(db, key, value):
            raise RuntimeError("database is down")

        with mock.patch.object(local_fit, "set_app_setting", boom):
            # Must not raise: the caller still returns the live result.
            await local_fit.store_local_fit_result(self.db, {"ok": True})


class SummaryIncludesLastResultTests(unittest.IsolatedAsyncioTestCase):
    async def test_summary_exposes_the_last_result(self):
        store = _FakeSettingsStore(
            {local_fit.LOCAL_FIT_RESULT_KEY: json.dumps({"text_models": [{"id": "m"}]})}
        )
        db = _FakeDB(store)
        with (
            mock.patch.object(local_fit, "get_app_setting", store.get),
            mock.patch.object(local_fit, "local_text_models", mock.AsyncMock(return_value=[])),
            mock.patch.object(local_fit, "current_intervals", mock.AsyncMock(return_value={})),
            mock.patch.object(local_fit, "local_models_all", mock.AsyncMock(return_value=[])),
        ):
            summary = await local_fit.summarize_local_fit(db)

        self.assertIn("last_result", summary)
        self.assertEqual([{"id": "m"}], summary["last_result"]["text_models"])


if __name__ == "__main__":
    unittest.main()
