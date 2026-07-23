import unittest

from app.services.audio_utils import convert_to_pcm16, make_wav_header


class AudioConversionTests(unittest.TestCase):
    def test_decode_limit_reads_only_one_sample_past_duration_cap(self):
        pcm = b"\x00\x00" * (20 * 16000)
        wav = make_wav_header(pcm) + pcm

        decoded = convert_to_pcm16(wav, "wav", max_seconds=15)

        self.assertEqual((15 * 16000 + 1) * 2, len(decoded))


if __name__ == "__main__":
    unittest.main()
