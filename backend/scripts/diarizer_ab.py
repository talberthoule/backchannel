"""A/B the lightweight diarizer's embedding models over recorded audio.

Runs the full VAD -> embedding -> match/enroll pipeline once per available
embedding model and reports, for each: speaker count, per-decision cosine
similarities for matched segments vs. new-speaker enrollments, and a crude
suggested similarity threshold (midpoint of the two distributions).

Usage (from backend/, or inside the backend container at /app):
    python scripts/diarizer_ab.py path/to/audio1.wav [audio2.wav ...] [--threshold 0.72]

Audio is expected as WAV; anything not 16 kHz mono is converted.
"""

from __future__ import annotations

import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import onnxruntime as ort  # noqa: E402
import soundfile as sf  # noqa: E402

from app.services import speaker_diarizer as sd  # noqa: E402
from app.services.speaker_diarizer import SpeakerDiarizer, SpeakerRegistry  # noqa: E402

CANDIDATES = [
    ("resnet152-lm", sd.EMBED_MODEL_FILENAME),
    ("resnet34-lm (legacy)", sd.LEGACY_EMBED_MODEL_FILENAME),
]


class RecordingRegistry(SpeakerRegistry):
    """SpeakerRegistry that records each match/enroll decision."""

    def __init__(self, threshold: float | None = None):
        super().__init__(threshold=threshold)
        self.matched_sims: list[float] = []
        self.new_speaker_sims: list[float] = []

    def match_or_create(self, embedding: np.ndarray) -> str:
        speaker_id, sim = self.match(embedding)
        if speaker_id:
            self.matched_sims.append(sim)
        else:
            self.new_speaker_sims.append(sim)
        return super().match_or_create(embedding)


def load_pcm16_mono_16k(path: str) -> bytes:
    audio, rate = sf.read(path, dtype="float32", always_2d=True)
    mono = audio.mean(axis=1)
    if rate != 16000:
        duration = len(mono) / rate
        target_len = int(duration * 16000)
        mono = np.interp(
            np.linspace(0.0, len(mono) - 1, target_len),
            np.arange(len(mono)),
            mono,
        ).astype(np.float32)
    return (np.clip(mono, -1.0, 1.0) * 32767).astype(np.int16).tobytes()


def percentile_line(values: list[float]) -> str:
    if not values:
        return "n=0"
    arr = np.array(values)
    return (
        f"n={len(arr)} p10={np.percentile(arr, 10):.3f} "
        f"p50={np.percentile(arr, 50):.3f} p90={np.percentile(arr, 90):.3f}"
    )


def run_model(label: str, model_path: str, audio_files: list[str], threshold: float) -> None:
    sd._embed_session = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
    print(f"\n=== {label} ({os.path.basename(model_path)}) threshold={threshold} ===")

    all_matched: list[float] = []
    all_new: list[float] = []
    for path in audio_files:
        registry = RecordingRegistry(threshold=threshold)
        diarizer = SpeakerDiarizer(registry=registry)
        pcm = load_pcm16_mono_16k(path)
        segments = []
        chunk = 32000  # 1s of PCM16 @16k
        for i in range(0, len(pcm), chunk):
            segments.extend(diarizer.feed_audio(pcm[i:i + chunk]))
        tail = diarizer.flush()
        if tail:
            segments.append(tail)

        speakers = sorted({s.speaker_id for s in segments})
        print(f"  {os.path.basename(path)}: {len(segments)} segments, {len(speakers)} speakers {speakers}")
        all_matched.extend(registry.matched_sims)
        all_new.extend(registry.new_speaker_sims)

    print(f"  matched-segment similarity: {percentile_line(all_matched)}")
    print(f"  new-speaker best-similarity: {percentile_line(all_new)}")
    if all_matched and all_new:
        suggested = (float(np.median(all_matched)) + float(np.median(all_new))) / 2
        print(f"  suggested threshold (midpoint of medians): {suggested:.2f}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio", nargs="+", help="WAV file(s) to diarize")
    parser.add_argument("--threshold", type=float, default=None, help="similarity threshold (default: app setting)")
    args = parser.parse_args()

    from app.config import settings

    threshold = args.threshold or settings.SPEAKER_SIMILARITY_THRESHOLD
    found_any = False
    for label, filename in CANDIDATES:
        model_path = os.path.join(sd.MODELS_DIR, filename)
        if not os.path.exists(model_path):
            print(f"skipping {label}: {filename} not found in {sd.MODELS_DIR}")
            continue
        found_any = True
        run_model(label, model_path, args.audio, threshold)

    if not found_any:
        print("No embedding models found; run scripts/download_models.py first.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
