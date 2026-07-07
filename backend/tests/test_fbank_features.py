import os
import tempfile
import unittest

import numpy as np

from app.services.speaker_diarizer import (
    EMBED_MODEL_FILENAME,
    LEGACY_EMBED_MODEL_FILENAME,
    _compute_fbank,
    resolve_embed_model_path,
)


def _test_signal(seconds: float = 1.0, sample_rate: int = 16000) -> np.ndarray:
    t = np.arange(int(seconds * sample_rate)) / sample_rate
    # Two tones plus noise so energy varies across mel bins
    rng = np.random.default_rng(42)
    signal = 0.4 * np.sin(2 * np.pi * 220 * t) + 0.2 * np.sin(2 * np.pi * 1760 * t)
    return (signal + 0.01 * rng.standard_normal(len(t))).astype(np.float32)


class FbankFeatureTests(unittest.TestCase):
    def test_shape_is_frames_by_80(self):
        feats = _compute_fbank(_test_signal(1.0))
        self.assertEqual(80, feats.shape[1])
        # ~1s of 25ms/10ms frames -> ~98 frames
        self.assertGreater(feats.shape[0], 90)

    def test_mean_only_cmn(self):
        feats = _compute_fbank(_test_signal(2.0))
        # Mean per mel bin removed
        np.testing.assert_allclose(feats.mean(axis=0), 0.0, atol=1e-3)
        # Variance NOT normalized: per-bin stds must differ meaningfully
        # (full CMVN would force every std to ~1.0)
        stds = feats.std(axis=0)
        self.assertGreater(float(stds.max() - stds.min()), 0.1)

    def test_scale_invariance_via_cmn(self):
        signal = _test_signal(1.0)
        feats_a = _compute_fbank(signal)
        feats_b = _compute_fbank(signal * 0.25)
        # A constant gain becomes a constant log-offset, removed by CMN
        np.testing.assert_allclose(feats_a, feats_b, atol=0.15)


class EmbedModelPathTests(unittest.TestCase):
    def test_prefers_resnet152_when_present(self):
        with tempfile.TemporaryDirectory() as models_dir:
            open(os.path.join(models_dir, EMBED_MODEL_FILENAME), "wb").close()
            open(os.path.join(models_dir, LEGACY_EMBED_MODEL_FILENAME), "wb").close()
            self.assertTrue(resolve_embed_model_path(models_dir).endswith(EMBED_MODEL_FILENAME))

    def test_falls_back_to_legacy_model(self):
        with tempfile.TemporaryDirectory() as models_dir:
            open(os.path.join(models_dir, LEGACY_EMBED_MODEL_FILENAME), "wb").close()
            self.assertTrue(resolve_embed_model_path(models_dir).endswith(LEGACY_EMBED_MODEL_FILENAME))


if __name__ == "__main__":
    unittest.main()
