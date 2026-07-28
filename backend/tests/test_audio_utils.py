import subprocess
import unittest
from unittest.mock import Mock, patch

from app.services.audio_utils import convert_to_pcm16, make_wav_header


class AudioConversionTests(unittest.TestCase):
    def test_decode_limit_reads_only_one_sample_past_duration_cap(self):
        pcm = b"\x00\x00" * (20 * 16000)
        wav = make_wav_header(pcm) + pcm

        decoded = convert_to_pcm16(wav, "wav", max_seconds=15)

        self.assertEqual((15 * 16000 + 1) * 2, len(decoded))

    def test_ffmpeg_fallback_pipes_source_and_pcm_without_temp_files(self):
        completed = Mock(stdout=b"\x01\x00")

        with (
            patch("app.services.audio_utils.resolve_ffmpeg", return_value="ffmpeg"),
            patch("subprocess.run", return_value=completed) as run,
        ):
            decoded = convert_to_pcm16(b"encoded webm", "webm")

        self.assertEqual(b"\x01\x00", decoded)
        command = run.call_args.args[0]
        self.assertEqual("pipe:0", command[command.index("-i") + 1])
        self.assertEqual("pipe:1", command[-1])
        self.assertEqual(b"encoded webm", run.call_args.kwargs["input"])
        self.assertEqual(60, run.call_args.kwargs["timeout"])

    def test_ffmpeg_timeout_does_not_expose_server_paths(self):
        with (
            patch(
                "app.services.audio_utils.resolve_ffmpeg",
                return_value=r"C:\private\ffmpeg.exe",
            ),
            patch(
                "subprocess.run",
                side_effect=subprocess.TimeoutExpired(
                    [r"C:\private\ffmpeg.exe", "-i", r"C:\private\voice.webm"],
                    60,
                ),
            ),
            self.assertRaisesRegex(RuntimeError, "timed out") as raised,
        ):
            convert_to_pcm16(b"encoded webm", "webm")

        self.assertNotIn("private", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
