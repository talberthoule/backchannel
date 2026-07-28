import subprocess
import unittest
from pathlib import Path
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

    def test_mp4_family_uses_seekable_temp_input_and_removes_it(self):
        encoded = b"x" * 9_700_000

        for source_format in ("m4a", "mp4", "mov"):
            with self.subTest(source_format=source_format):
                input_path = None

                def run(command, **kwargs):
                    nonlocal input_path
                    input_arg = command[command.index("-i") + 1]
                    self.assertNotEqual("pipe:0", input_arg)
                    self.assertEqual("pipe:1", command[-1])
                    self.assertIsNone(kwargs.get("input"))
                    input_path = Path(input_arg)
                    self.assertEqual(f".{source_format}", input_path.suffix)
                    self.assertEqual(encoded, input_path.read_bytes())
                    return Mock(stdout=b"\x01\x00")

                with (
                    patch("app.services.audio_utils.resolve_ffmpeg", return_value="ffmpeg"),
                    patch("subprocess.run", side_effect=run),
                ):
                    decoded = convert_to_pcm16(encoded, source_format)

                self.assertEqual(b"\x01\x00", decoded)
                self.assertIsNotNone(input_path)
                self.assertFalse(input_path.exists())

    def test_mp4_temp_input_is_removed_when_ffmpeg_fails(self):
        input_path = None

        def fail(command, **_kwargs):
            nonlocal input_path
            input_arg = command[command.index("-i") + 1]
            if input_arg != "pipe:0":
                input_path = Path(input_arg)
            raise subprocess.CalledProcessError(
                1,
                command,
                stderr=f"invalid data in {input_arg}".encode(),
            )

        with (
            patch("app.services.audio_utils.resolve_ffmpeg", return_value="ffmpeg"),
            patch("subprocess.run", side_effect=fail),
            self.assertRaisesRegex(RuntimeError, "could not decode") as raised,
        ):
            convert_to_pcm16(b"encoded m4a", "m4a")

        self.assertIsNotNone(input_path)
        self.assertFalse(input_path.exists())
        self.assertNotIn(str(input_path), str(raised.exception))

    def test_zero_byte_ffmpeg_output_is_a_conversion_failure(self):
        completed = Mock(stdout=b"", stderr=b"partial file")

        with (
            patch("app.services.audio_utils.resolve_ffmpeg", return_value="ffmpeg"),
            patch("subprocess.run", return_value=completed),
            self.assertRaisesRegex(RuntimeError, "produced no audio"),
        ):
            convert_to_pcm16(b"encoded webm", "webm")

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
