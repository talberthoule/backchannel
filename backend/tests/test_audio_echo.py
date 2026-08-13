import unittest
import wave
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from app.services.audio_echo import (
    build_echo_cancelled_mix,
    cancel_and_mix,
    cancel_echo,
    delay_trajectory,
)

RATE = 16000
DRIFT = 0.29  # samples per second, the 18 ppm slide measured on a real call


def speechlike(seconds, rate=RATE, seed=0, level=3000.0):
    """Noise shaped like speech: falling spectrum, and gated into bursts.

    Flat noise would flatter the canceller - it is the easiest thing an NLMS
    filter can be handed. Real material is spectrally tilted, which makes the
    per-bin normalisation matter, and intermittent, which is what exercises the
    activity gate and the filter-swap decisions.
    """
    rng = np.random.default_rng(seed)
    n = int(seconds * rate)
    spectrum = np.fft.rfft(rng.normal(0, 1, n))
    freqs = np.fft.rfftfreq(n, 1 / rate)
    spectrum *= 1.0 / (1.0 + (freqs / 300.0) ** 1.4)
    signal = np.fft.irfft(spectrum, n)
    envelope = rng.random(int(seconds * 4) + 1) < 0.72
    envelope = np.repeat(envelope.astype(float), rate // 4)[:n]
    kernel = np.hanning(rate // 8)
    envelope = np.convolve(envelope, kernel / kernel.sum(), mode="same")
    signal *= envelope
    return signal / (np.sqrt(np.mean(signal ** 2)) or 1.0) * level


def echo_path(reference, rate=RATE, delay_ms=230.0, drift=DRIFT, seed=1):
    """Reference as a microphone hears it: a room response, arriving late, with
    the delay sliding because the two capture clocks disagree."""
    index = np.arange(len(reference), dtype=np.float64)
    moved = np.interp(index - drift * index / rate, index, reference)
    rng = np.random.default_rng(seed)
    taps = int(0.110 * rate)
    impulse = np.zeros(int(delay_ms / 1000 * rate) + taps + 1)
    start = int(delay_ms / 1000 * rate)
    impulse[start] = 1.0
    impulse[start + 1:] = (rng.normal(0, 0.22, taps)
                           * np.exp(-np.arange(taps) / (0.030 * rate)))
    impulse /= np.sqrt((impulse ** 2).sum())
    size = 1 << int(np.ceil(np.log2(len(moved) + len(impulse))))
    convolved = np.fft.irfft(
        np.fft.rfft(moved, size) * np.fft.rfft(impulse, size), size)[: len(reference)]
    return convolved


def scale_to(signal, reference, ratio):
    energy = np.sum(signal ** 2) or 1.0
    return signal * ratio * np.sqrt(np.sum(reference ** 2) / energy)


class DelayTrajectoryTests(unittest.TestCase):
    def test_tracks_a_sliding_delay_to_a_fraction_of_a_sample(self):
        far = speechlike(60, seed=2)
        near = far * 0.0 + echo_path(far)

        trajectory = delay_trajectory(near, far, RATE)

        self.assertIsNotNone(trajectory)
        # Each point describes the centre of its 4 s segment, so the first sits
        # at t = 2 s and they step by the 2 s hop.
        centres = (np.arange(len(trajectory)) * 2.0 + 2.0) * RATE
        expected = 0.230 * RATE + DRIFT * centres / RATE
        # The whole point of measuring the trajectory is that integer accuracy
        # is not enough: a quantised delay is a staircase the filter then has
        # to chase, and chasing it is what costs 10 dB.
        self.assertLess(np.max(np.abs(trajectory - expected)), 1.0)
        self.assertLess(np.median(np.abs(trajectory - expected)), 0.5)

    def test_declines_to_guess_when_there_is_no_echo(self):
        far = speechlike(60, seed=3)
        near = speechlike(60, seed=4)

        self.assertIsNone(delay_trajectory(near, far, RATE))


class CancelEchoTests(unittest.TestCase):
    def test_removes_echo_that_arrives_late_and_drifts(self):
        far = speechlike(90, seed=5)
        near = speechlike(90, seed=6, level=1200.0)
        echo = scale_to(echo_path(far), near, 1.6)

        cleaned = cancel_echo(near + echo, far, RATE)

        # cleaned = near + (echo - estimate), so the residual echo is exact.
        residual = cleaned - near[: len(cleaned)]
        erle = 10 * np.log10(np.sum(echo[: len(cleaned)] ** 2) / np.sum(residual ** 2))
        self.assertGreater(erle, 9.0)

    def test_does_not_touch_audio_that_has_no_echo_in_it(self):
        far = speechlike(90, seed=7)
        near = speechlike(90, seed=8)

        cleaned = cancel_echo(near, far, RATE)

        # Not "close enough": a filter with nothing to cancel must never be
        # promoted into the output at all, so this is exact. A canceller that
        # merely does little damage here would pass a tolerance and still add
        # up to 7 dB of noise on the real recording that motivated this.
        np.testing.assert_array_equal(near[: len(cleaned)], cleaned)

    def test_keeps_near_end_speech_while_cancelling(self):
        far = speechlike(90, seed=9)
        near = speechlike(90, seed=10, level=1200.0)
        echo = scale_to(echo_path(far), near, 1.6)

        base = cancel_echo(near + echo, far, RATE)
        probe = speechlike(90, seed=11, level=1200.0)
        with_probe = cancel_echo(near + echo + probe, far, RATE)

        # How much of a known extra near-end signal comes back out. The near-end
        # track legitimately gets quieter when most of what was in it was echo,
        # so a level check cannot tell preservation from over-cancellation.
        survived = with_probe - base
        kept = float(survived @ probe[: len(survived)]) / float(
            probe[: len(survived)] @ probe[: len(survived)])
        self.assertGreater(kept, 0.95)
        self.assertLess(kept, 1.05)

    def test_is_a_no_op_while_the_far_end_is_silent(self):
        far = speechlike(90, seed=12)
        far[40 * RATE: 60 * RATE] = 0.0
        near = speechlike(90, seed=13, level=1200.0)
        echo = scale_to(echo_path(far), near, 1.6)

        cleaned = cancel_echo(near + echo, far, RATE)

        # One tap span past the last far-end sample there is nothing left for an
        # FIR of the reference to subtract, so the microphone must survive
        # untouched however badly the filter is doing elsewhere.
        quiet = slice(42 * RATE, 60 * RATE)
        np.testing.assert_allclose(near[quiet], cleaned[quiet], atol=1e-6)

    def test_passes_through_when_the_far_end_track_is_silent(self):
        near = speechlike(40, seed=14)
        far = np.zeros_like(near)

        cleaned = cancel_echo(near, far, RATE)

        np.testing.assert_array_equal(near[: len(cleaned)], cleaned)

    def test_returns_exactly_as_many_samples_as_it_was_given(self):
        # A partial trailing block must be passed through, not dropped: the
        # caller sums this with the system track and writes the result.
        far = speechlike(45, seed=23)
        near = speechlike(45, seed=24, level=1200.0)
        odd = len(near) - 517

        cleaned = cancel_echo(near[:odd] + scale_to(echo_path(far), near, 1.6)[:odd],
                              far[:odd], RATE)

        self.assertEqual(odd, len(cleaned))

    def test_handles_clips_shorter_than_the_filter(self):
        near = speechlike(0.2, seed=15)
        far = speechlike(0.2, seed=16)

        cleaned = cancel_echo(near, far, RATE)

        self.assertEqual(len(near), len(cleaned))
        np.testing.assert_array_equal(near, cleaned)


class MixTests(unittest.TestCase):
    def test_mix_restores_the_far_end_at_full_level(self):
        far = speechlike(40, seed=17)
        near = speechlike(40, seed=18)

        mixed = cancel_and_mix(near, far, RATE)

        self.assertEqual(len(near), len(mixed))
        # Nothing to cancel, so the mix is exactly the sum it always was.
        np.testing.assert_allclose(np.clip(near + far, -32768, 32767), mixed)

    def test_mix_stays_inside_int16(self):
        near = np.full(RATE * 3, 30000.0)
        far = np.full(RATE * 3, 30000.0)

        mixed = cancel_and_mix(near, far, RATE)

        self.assertLessEqual(np.abs(mixed).max(), 32767)


class BuildMixTests(unittest.TestCase):
    def _write(self, path, samples, rate=RATE):
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(rate)
            handle.writeframes(np.rint(samples).astype(np.int16).tobytes())

    def test_writes_a_matching_wav_from_the_two_tracks(self):
        far = speechlike(30, seed=19)
        near = speechlike(30, seed=20, level=1200.0)
        echo = scale_to(echo_path(far), near, 1.6)

        with TemporaryDirectory() as directory:
            root = Path(directory)
            self._write(root / "mic.wav", near + echo)
            self._write(root / "sys.wav", far)
            out = root / "nested" / "clean.wav"

            result = build_echo_cancelled_mix(root / "mic.wav", root / "sys.wav", out)

            self.assertEqual(out, result)
            with wave.open(str(out)) as handle:
                self.assertEqual(1, handle.getnchannels())
                self.assertEqual(2, handle.getsampwidth())
                self.assertEqual(RATE, handle.getframerate())
                self.assertEqual(len(near), handle.getnframes())

    def test_refuses_tracks_recorded_at_different_rates(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self._write(root / "mic.wav", speechlike(2, seed=21))
            self._write(root / "sys.wav", speechlike(2, seed=22), rate=8000)

            with self.assertRaises(ValueError):
                build_echo_cancelled_mix(
                    root / "mic.wav", root / "sys.wav", root / "clean.wav")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
