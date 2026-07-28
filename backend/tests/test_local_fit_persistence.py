"""The local-model fit result survives a page reload (ALP-158).

Running the test costs real time on a local model. Losing the result to a
refresh means running it again, and it also made the applied per-model budgets
look like they had not been saved.
"""

import json
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest import mock

from app.services import local_fit
from app.services.fit_staleness import stamp_fit_record


HOST = {
    "device": "cuda",
    "gpu_name": "test-gpu",
    "gpu_backend": "cuda",
    "gpu_memory_gb": 16.0,
}


def _environment():
    return SimpleNamespace(**HOST)


def _current_result(**extra):
    return {
        "has_local_text_models": True,
        "text_models": [],
        **stamp_fit_record(
            {"model_id": "local-fit", "endpoint_fingerprint": None},
            HOST,
            measured_at=datetime(2026, 7, 28, tzinfo=timezone.utc),
        ),
        **extra,
    }


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
        self.enterContext(
            mock.patch.object(local_fit, "local_text_models", mock.AsyncMock(return_value=[]))
        )
        self.enterContext(
            mock.patch.object(local_fit, "probe_sortformer_environment", return_value=_environment())
        )

    async def test_a_current_stored_result_is_returned(self):
        result = _current_result()
        await local_fit.store_local_fit_result(self.db, result)

        loaded = await local_fit.load_local_fit_result(self.db)

        self.assertEqual(True, loaded["has_local_text_models"])
        self.assertEqual("current", loaded["validity"]["status"])

    async def test_the_result_has_the_four_field_provenance_stamp(self):
        await local_fit.store_local_fit_result(self.db, {"has_local_text_models": True})
        stored = json.loads(self.store.values[local_fit.LOCAL_FIT_RESULT_KEY])
        self.assertEqual(
            {"schema_version", "measured_at", "subject", "host"},
            {"schema_version", "measured_at", "subject", "host"} & stored.keys(),
        )

    async def test_storing_does_not_mutate_the_caller_payload(self):
        result = {"has_local_text_models": True}
        await local_fit.store_local_fit_result(self.db, result)
        # The live response the user is waiting on must not gain fields.
        self.assertNotIn("schema_version", result)

    async def test_frozen_judgments_are_not_persisted(self):
        result = _current_result(
            text_models=[{
                "roles": [{
                    "verdict": "green",
                    "recommended_interval_seconds": 10,
                    "changed": False,
                    "latency_seconds": 1.2,
                }]
            }],
            asr={"asr_models": [{"verdict": "green", "live_feasibility": "feasible"}]},
        )
        await local_fit.store_local_fit_result(self.db, result)
        stored = json.loads(self.store.values[local_fit.LOCAL_FIT_RESULT_KEY])
        self.assertEqual({"latency_seconds": 1.2}, stored["text_models"][0]["roles"][0])
        self.assertNotIn("verdict", stored["asr"]["asr_models"][0])

    async def test_legacy_result_reads_as_incompatible_without_numbers(self):
        self.store.values[local_fit.LOCAL_FIT_RESULT_KEY] = json.dumps(
            {"text_models": [{"model_id": "old", "short": {"latency_seconds": 1.0}}]}
        )
        loaded = await local_fit.load_local_fit_result(self.db)
        self.assertEqual("incompatible", loaded["validity"]["status"])
        self.assertEqual([], loaded["text_models"])

    async def test_repointed_endpoint_marks_only_its_model_superseded(self):
        measurement = {
            "model_id": "endpoint:box:model",
            "roles": [],
            **stamp_fit_record(
                {
                    "model_id": "endpoint:box:model",
                    "endpoint_fingerprint": "http://old/v1|on_prem=true",
                },
                HOST,
            ),
        }
        self.store.values[local_fit.LOCAL_FIT_RESULT_KEY] = json.dumps(
            _current_result(text_models=[measurement])
        )
        local_fit.local_text_models.return_value = [{
            "id": "endpoint:box:model",
            "endpoint_fingerprint": "http://new/v1|on_prem=true",
        }]
        with mock.patch.object(
            local_fit, "budgets_for_model", mock.AsyncMock(return_value={})
        ):
            loaded = await local_fit.load_local_fit_result(self.db)
        self.assertEqual("current", loaded["validity"]["status"])
        self.assertEqual("superseded", loaded["text_models"][0]["validity"]["status"])

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
            {local_fit.LOCAL_FIT_RESULT_KEY: json.dumps(_current_result())}
        )
        db = _FakeDB(store)
        with (
            mock.patch.object(local_fit, "get_app_setting", store.get),
            mock.patch.object(local_fit, "local_text_models", mock.AsyncMock(return_value=[])),
            mock.patch.object(local_fit, "current_intervals", mock.AsyncMock(return_value={})),
            mock.patch.object(local_fit, "local_models_all", mock.AsyncMock(return_value=[])),
            mock.patch.object(local_fit, "probe_sortformer_environment", return_value=_environment()),
        ):
            summary = await local_fit.summarize_local_fit(db)

        self.assertIn("last_result", summary)
        self.assertEqual("2026-07-28T00:00:00+00:00", summary["last_result"]["measured_at"])


if __name__ == "__main__":
    unittest.main()
