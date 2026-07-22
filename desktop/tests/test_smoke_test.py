import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import URLError

try:
    from desktop.scripts import smoke_test
except ModuleNotFoundError:
    from scripts import smoke_test


class _Response:
    status = 200
    headers = {"X-Backchannel-Instance": "ours"}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return b'{"status":"ok"}'


class SmokeTestTests(unittest.TestCase):
    def test_wait_for_health_retries_and_checks_instance_token(self):
        proc = Mock()
        proc.poll.return_value = None
        with tempfile.TemporaryDirectory() as tmp:
            lock = Path(tmp) / "launcher.json"
            lock.write_text(json.dumps({"port": 8474, "token": "ours"}))
            with (
                patch.object(
                    smoke_test.urllib.request,
                    "urlopen",
                    side_effect=[URLError("starting"), _Response()],
                ) as urlopen,
                patch.object(smoke_test.time, "sleep"),
            ):
                self.assertEqual(
                    smoke_test.wait_for_health(proc, lock, deadline=float("inf")),
                    8474,
                )

        self.assertEqual(urlopen.call_count, 2)

    def test_stop_process_repeats_signal_until_launcher_observes_it(self):
        proc = Mock()
        proc.poll.side_effect = [None, None, 0]
        proc.wait.side_effect = [subprocess.TimeoutExpired("Backchannel", 1), 0]
        with tempfile.TemporaryDirectory() as tmp:
            stop = Path(tmp) / "stop"
            with patch.object(smoke_test.time, "monotonic", side_effect=[0, 0, 1]):
                self.assertTrue(smoke_test.stop_process(proc, stop, timeout=5))

        self.assertEqual(proc.wait.call_count, 2)


if __name__ == "__main__":
    unittest.main()
