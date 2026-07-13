import unittest

from app.ws import audio_handler


class AudioFrameDecodingTests(unittest.TestCase):
    def test_decodes_prefixed_and_legacy_frames(self):
        self.assertTrue(hasattr(audio_handler, "_decode_audio_frame"))
        decode_audio_frame = audio_handler._decode_audio_frame
        cases = [
            (b"\x00\x01\x02", (0, b"\x01\x02")),
            (b"\x01\x03\x04", (1, b"\x03\x04")),
            (b"\x07\x05\x06", (0, b"\x05\x06")),
            (b"\x08\x09", (0, b"\x08\x09")),
        ]

        for raw_frame, expected in cases:
            with self.subTest(raw_frame=raw_frame):
                self.assertEqual(expected, decode_audio_frame(raw_frame))


if __name__ == "__main__":
    unittest.main()
