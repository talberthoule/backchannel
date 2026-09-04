import unittest
import uuid

from app.services import transcription_jobs


class TranscriptionJobTests(unittest.TestCase):
    def setUp(self):
        transcription_jobs._jobs.clear()

    def tearDown(self):
        transcription_jobs._jobs.clear()

    def test_progress_and_cancellation_are_observable(self):
        session_id = uuid.uuid4()
        job = transcription_jobs.create_job(
            session_id,
            "retranscription",
            "local-whisper-base",
            3,
        )

        job.start()
        job.update_entries(7)
        job.finish_segment(9)
        self.assertEqual(
            ("running", 1, 3, 9, 33),
            tuple(
                job.snapshot()[key]
                for key in (
                    "status",
                    "segments_done",
                    "total_segments",
                    "entries",
                    "progress",
                )
            ),
        )

        job.cancel()
        self.assertEqual("canceling", job.snapshot()["status"])
        with self.assertRaises(transcription_jobs.JobCanceled):
            job.check_canceled()
        job.mark_canceled()
        self.assertEqual("canceled", job.snapshot()["status"])

    def test_a_session_cannot_start_overlapping_transcription_jobs(self):
        session_id = uuid.uuid4()
        transcription_jobs.create_job(session_id, "audio_import", "model", 1)

        with self.assertRaisesRegex(
            transcription_jobs.JobAlreadyRunning,
            "audio import",
        ):
            transcription_jobs.create_job(
                session_id,
                "retranscription",
                "model",
                2,
            )


if __name__ == "__main__":
    unittest.main()
