"""The model-download registry, and the NER loader that used to wedge the app.

The regression under test (ALP-373): the PII NER loader held one global lock
across a hub download, and the download deadlocked because tqdm's clear() takes
its process-global write lock, writes to a stream that is None in the frozen
desktop build, and releases only on the line after the write. The lock leaked,
the next progress bar blocked on it forever, and every PII-protected write --
including creating a session -- queued behind it and never returned.

So the tests here care about two things above all: nothing on the ingest path
waits on a download, and a download that fails or hangs leaves the rest of the
app answering.
"""

import io
import os
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet

os.environ.setdefault("CREDENTIALS_MASTER_KEY", Fernet.generate_key().decode())

from app.services import model_downloads  # noqa: E402
from app.services.pii import ner  # noqa: E402

KEY = "test-model"


class RegistryTests(unittest.TestCase):
    def setUp(self):
        model_downloads.reset()
        self.addCleanup(model_downloads.reset)

    def test_claim_is_single_flight(self):
        self.assertTrue(model_downloads.claim(KEY, "Test", "Testing"))
        self.assertFalse(model_downloads.claim(KEY, "Test", "Testing"))
        self.assertTrue(model_downloads.is_running(KEY))

    def test_a_finished_job_can_be_claimed_again(self):
        model_downloads.claim(KEY, "Test")
        model_downloads.finish(KEY)
        self.assertFalse(model_downloads.is_running(KEY))
        self.assertTrue(model_downloads.claim(KEY, "Test"))

    def test_a_failed_job_can_be_claimed_again(self):
        model_downloads.claim(KEY, "Test")
        model_downloads.fail(KEY, "no network")
        self.assertEqual("error", model_downloads.get(KEY)["state"])
        self.assertTrue(model_downloads.claim(KEY, "Test"))

    def test_progress_reports_percent_only_with_a_total(self):
        model_downloads.claim(KEY, "Test")
        model_downloads.advance(KEY, 50, 200)
        self.assertEqual(25, model_downloads.get(KEY)["percent"])

        model_downloads.reset()
        model_downloads.claim(KEY, "Test")
        model_downloads.advance(KEY, 50)
        self.assertIsNone(model_downloads.get(KEY)["percent"])

    def test_progress_never_goes_backwards(self):
        model_downloads.claim(KEY, "Test")
        model_downloads.advance(KEY, 100, 200)
        model_downloads.advance(KEY, 40, 200)
        self.assertEqual(100, model_downloads.get(KEY)["downloaded"])

    def test_finish_fills_in_the_total(self):
        model_downloads.claim(KEY, "Test")
        model_downloads.advance(KEY, 90, 100)
        model_downloads.finish(KEY)
        job = model_downloads.get(KEY)
        self.assertEqual("installed", job["state"])
        self.assertEqual(100, job["downloaded"])
        self.assertEqual("", job["error"])

    def test_snapshot_counts_active_and_failed(self):
        model_downloads.claim("a", "A")
        model_downloads.begin("a")
        model_downloads.claim("b", "B")
        model_downloads.fail("b", "boom")
        model_downloads.claim("c", "C")
        model_downloads.finish("c")
        snap = model_downloads.snapshot()
        self.assertEqual(1, snap["active"])
        self.assertEqual(1, snap["failed"])
        self.assertEqual(3, len(snap["downloads"]))

    def test_download_context_records_failure_and_reraises(self):
        model_downloads.claim(KEY, "Test")
        with self.assertRaises(ValueError):
            with model_downloads.download(KEY, "Test"):
                raise ValueError("nope")
        job = model_downloads.get(KEY)
        self.assertEqual("error", job["state"])
        self.assertIn("ValueError: nope", job["error"])

    def test_fail_truncates_a_runaway_message(self):
        model_downloads.claim(KEY, "Test")
        model_downloads.fail(KEY, "x" * 5000)
        self.assertLessEqual(len(model_downloads.get(KEY)["error"]), 400)


class ProgressReporterTests(unittest.TestCase):
    """The tqdm stand-in handed to huggingface_hub as `tqdm_class`."""

    def setUp(self):
        model_downloads.reset()
        self.addCleanup(model_downloads.reset)

    def test_updates_land_in_the_registry(self):
        model_downloads.claim(KEY, "Test")
        cls = model_downloads.reporter_for(KEY)
        bar = cls(total=400)
        bar.update(100)
        bar.update(100)
        job = model_downloads.get(KEY)
        self.assertEqual(200, job["downloaded"])
        self.assertEqual(400, job["total"])
        self.assertEqual(50, job["percent"])

    def test_base_and_total_make_one_bar_across_several_files(self):
        model_downloads.claim(KEY, "Test")
        first = model_downloads.reporter_for(KEY, base=0, total=300)(total=100)
        first.update(100)
        self.assertEqual(100, model_downloads.get(KEY)["downloaded"])
        # Second file starts where the first left off rather than back at zero.
        second = model_downloads.reporter_for(KEY, base=100, total=300)(total=200)
        second.update(50)
        job = model_downloads.get(KEY)
        self.assertEqual(150, job["downloaded"])
        self.assertEqual(300, job["total"])

    def test_survives_none_streams_and_holds_no_lock(self):
        """The exact condition that deadlocked v0.6.1.

        With console=False there is no stdout or stderr. Real tqdm raises
        AttributeError from inside its global write lock and never releases it;
        this reporter must touch neither.
        """
        model_downloads.claim(KEY, "Test")
        cls = model_downloads.reporter_for(KEY)
        with patch.object(sys, "stderr", None), patch.object(sys, "stdout", None):
            with cls(total=10) as bar:
                bar.update(5)
                bar.clear()
                bar.refresh()
                bar.set_description("x")
        # A second bar must not block on anything the first one left behind.
        done = threading.Event()

        def again():
            cls(total=10).update(1)
            done.set()

        thread = threading.Thread(target=again, daemon=True)
        thread.start()
        self.assertTrue(done.wait(5), "a second progress bar blocked; a lock leaked")

    def test_writes_nothing_to_a_real_stream(self):
        model_downloads.claim(KEY, "Test")
        buffer = io.StringIO()
        with patch.object(sys, "stderr", buffer):
            bar = model_downloads.reporter_for(KEY)(total=10)
            bar.update(10)
            bar.close()
        self.assertEqual("", buffer.getvalue())


class NerLoaderTests(unittest.TestCase):
    """The ingest path must never download and never wait on one."""

    def setUp(self):
        ner.reset_for_tests()
        model_downloads.reset()
        self.addCleanup(model_downloads.reset)
        self.addCleanup(ner.reset_for_tests)

    def test_find_entities_does_not_download(self):
        with patch.object(ner, "is_installed", return_value=False), \
                patch.object(ner, "ensure_downloaded") as fetch:
            self.assertEqual([], ner.find_entities("Sarah Connor", {"PERSON"}))
        fetch.assert_not_called()

    def test_get_model_defaults_to_not_downloading(self):
        with patch.object(ner, "is_installed", return_value=False), \
                patch.object(ner, "ensure_downloaded") as fetch:
            self.assertIsNone(ner.get_model())
        fetch.assert_not_called()

    def test_ingest_does_not_block_behind_a_running_install(self):
        """The regression: a stuck download must not stall detection.

        A thread holding the install lock stands in for a download in flight.
        `find_entities` has to come straight back rather than queue behind it.
        """
        held = threading.Event()
        release = threading.Event()

        def holder():
            with ner._install_lock:
                held.set()
                release.wait(10)

        thread = threading.Thread(target=holder, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(release.set)
        self.assertTrue(held.wait(5))

        returned = threading.Event()

        def ingest():
            with patch.object(ner, "is_installed", return_value=True):
                ner.find_entities("Sarah Connor", {"PERSON"})
            returned.set()

        worker = threading.Thread(target=ingest, daemon=True)
        worker.start()
        self.assertTrue(returned.wait(5), "find_entities blocked on an in-flight download")
        release.set()

    def test_a_permanent_failure_is_not_retried_on_every_call(self):
        calls = []

        def boom():
            calls.append(1)
            raise RuntimeError("no network")

        with patch.object(ner, "ensure_downloaded", side_effect=boom):
            self.assertIsNone(ner.get_model(download=True))
        self.assertEqual(1, len(calls))
        self.assertIn("RuntimeError: no network", ner.load_error() or "")

        # Later ingest calls must not re-attempt the fetch.
        with patch.object(ner, "ensure_downloaded", side_effect=boom):
            for _ in range(5):
                ner.find_entities("Sarah Connor", {"PERSON"})
        self.assertEqual(1, len(calls))

    def test_install_records_the_failure_in_the_registry(self):
        with patch.object(ner, "ensure_downloaded", side_effect=RuntimeError("offline")):
            self.assertIsNone(ner.install())
        job = model_downloads.get(ner.DOWNLOAD_KEY)
        self.assertEqual("error", job["state"])
        self.assertIn("offline", job["error"])

    def test_install_is_single_flight(self):
        model_downloads.claim(ner.DOWNLOAD_KEY, ner.DOWNLOAD_LABEL)
        with patch.object(ner, "ensure_downloaded") as fetch:
            ner.install()
        fetch.assert_not_called()

    def test_ensure_downloaded_passes_a_reporting_tqdm_class(self):
        """The fetch must report progress, and must not use real tqdm."""
        seen = {}

        def fake_download(repo, name, local_dir=None, tqdm_class=None):
            seen[name] = tqdm_class
            target = Path(local_dir) / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"data")
            return str(target)

        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "bert-base-NER"
            with patch.object(ner, "model_dir", return_value=root), \
                    patch.object(ner, "is_installed", return_value=False), \
                    patch.object(ner, "_remote_total", return_value=1234), \
                    patch.dict(sys.modules, {}, clear=False), \
                    patch("huggingface_hub.hf_hub_download", fake_download):
                model_downloads.claim(ner.DOWNLOAD_KEY, ner.DOWNLOAD_LABEL)
                ner.ensure_downloaded()

        self.assertEqual(set(ner._MODEL_FILES), set(seen))
        for cls in seen.values():
            self.assertIsNotNone(cls, "no tqdm_class passed; real tqdm would be used")
            self.assertTrue(issubclass(cls, model_downloads.ProgressReporter))
        self.assertEqual(1234, model_downloads.get(ner.DOWNLOAD_KEY)["total"])


if __name__ == "__main__":
    unittest.main()
