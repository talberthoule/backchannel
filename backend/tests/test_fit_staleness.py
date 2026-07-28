import unittest
from datetime import datetime, timedelta, timezone

from app.services.fit_staleness import (
    AGED,
    CURRENT,
    INCOMPATIBLE,
    SUPERSEDED,
    FIT_SCHEMA_VERSION,
    assess_fit_record,
    stamp_fit_record,
)


NOW = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)
SUBJECT = {"model_id": "endpoint:box:qwen", "endpoint_fingerprint": "http://box/v1|on_prem=true"}
HOST = {
    "device": "cuda",
    "gpu_name": "RTX 4080",
    "gpu_backend": "cuda",
    "gpu_memory_gb": 16.0,
}


def _record(**measurements):
    return {
        **stamp_fit_record(SUBJECT, HOST, measured_at=NOW),
        **measurements,
    }


class FitStalenessTests(unittest.TestCase):
    def test_legacy_record_is_incompatible(self):
        validity = assess_fit_record(
            {"real_time_factor": 0.2},
            current_subject=SUBJECT,
            current_host=HOST,
            required_fields=("real_time_factor",),
            now=NOW,
        )
        self.assertEqual(INCOMPATIBLE, validity["status"])

    def test_current_version_requires_every_measurement(self):
        record = _record(real_time_factor=0.2)
        validity = assess_fit_record(
            record,
            current_subject=SUBJECT,
            current_host=HOST,
            required_fields=("real_time_factor", "peak_memory_mb"),
            now=NOW,
        )
        self.assertEqual(FIT_SCHEMA_VERSION, record["schema_version"])
        self.assertEqual(INCOMPATIBLE, validity["status"])

    def test_subject_change_is_superseded(self):
        validity = assess_fit_record(
            _record(real_time_factor=0.2),
            current_subject={
                "model_id": SUBJECT["model_id"],
                "endpoint_fingerprint": "http://new-box/v1|on_prem=true",
            },
            current_host=HOST,
            required_fields=("real_time_factor",),
            now=NOW,
        )
        self.assertEqual(SUPERSEDED, validity["status"])
        self.assertIn("server", validity["reason"].lower())

    def test_hardware_change_is_superseded(self):
        validity = assess_fit_record(
            _record(real_time_factor=0.2),
            current_subject=SUBJECT,
            current_host={**HOST, "gpu_name": "Radeon RX 7900"},
            required_fields=("real_time_factor",),
            now=NOW,
        )
        self.assertEqual(SUPERSEDED, validity["status"])
        self.assertIn("RTX 4080", validity["reason"])
        self.assertIn("Radeon RX 7900", validity["reason"])

    def test_old_record_is_aged_but_still_gradeable(self):
        record = {
            **stamp_fit_record(
                SUBJECT,
                HOST,
                measured_at=NOW - timedelta(days=94),
            ),
            "real_time_factor": 0.2,
        }
        validity = assess_fit_record(
            record,
            current_subject=SUBJECT,
            current_host=HOST,
            required_fields=("real_time_factor",),
            now=NOW,
        )
        self.assertEqual(AGED, validity["status"])
        self.assertEqual(94, validity["age_days"])

    def test_matching_record_is_current(self):
        validity = assess_fit_record(
            _record(real_time_factor=0.2),
            current_subject=SUBJECT,
            current_host=HOST,
            required_fields=("real_time_factor",),
            now=NOW,
        )
        self.assertEqual(CURRENT, validity["status"])


if __name__ == "__main__":
    unittest.main()
