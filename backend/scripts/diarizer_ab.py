"""A/B the lightweight diarizer's embedding models over recorded audio.

Three modes:

  pipeline   Run the full VAD -> embedding -> match/enroll pipeline once per
             embedding model and report speaker counts plus matched-vs-new
             similarity distributions. No ground truth.

  margin     Ground-truth separation analysis over dual-track recordings.
             Backchannel stores `segment_N_mic.wav` (local user) and
             `segment_N_sys.wav` (remote participants) alongside the mixed
             `segment_N.wav`. Those tracks are labels: within-mic pairs are
             same-speaker, mic-vs-sys pairs are different-speaker. Reports the
             two cosine distributions separately, their overlap, the equal
             error rate, and the error rates at a given threshold.

             Tracks are only trustworthy when the local user wore headphones.
             With open speakers the remote audio echoes into the mic track and
             the labels are junk, so this mode runs an echo test per recording
             and refuses contaminated pairs unless --allow-echo is passed. It
             further keeps only segments during which the opposite track is
             silent (exclusive activity), which removes crosstalk.

  cost       Measure CPU per embedding for each model under explicit
             onnxruntime SessionOptions. Session options are set here rather
             than inherited so the numbers are self-contained.

Usage (from backend/, or inside the backend container at /app):
    python scripts/diarizer_ab.py pipeline audio1.wav [...] [--threshold 0.72]
    python scripts/diarizer_ab.py margin --audio-root /path/to/data/audio
    python scripts/diarizer_ab.py cost --audio-root /path/to/data/audio

Audio is expected as WAV; anything not 16 kHz mono is converted.
The ResNet34-LM comparison model is an opt-in download:
    python scripts/download_models.py --optional
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import os
import sys
import tempfile
import time
import wave

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import onnxruntime as ort  # noqa: E402
import soundfile as sf  # noqa: E402

from app.config import settings  # noqa: E402
from app.services import speaker_diarizer as sd  # noqa: E402
from app.services.diarizer_selection import flush_diarizer_segments  # noqa: E402
from app.services.speaker_diarizer import (  # noqa: E402
    SpeakerDiarizer,
    SpeakerRegistry,
    VoiceActivityDetector,
)

RESNET34_FILENAME = "voxceleb_resnet34_LM.onnx"

# (label, filename). The legacy ecapa_tdnn.onnx file holds ResNet34-LM under a
# misleading name; it is only used when the correctly named export is absent.
CANDIDATES = [
    ("resnet152-lm", sd.EMBED_MODEL_FILENAME),
    ("resnet34-lm", RESNET34_FILENAME),
    ("resnet34-lm (legacy ecapa_tdnn.onnx)", sd.LEGACY_EMBED_MODEL_FILENAME),
]

FRAME_MS = 100  # energy-envelope resolution for the exclusivity/echo tests


# --------------------------------------------------------------------------
# audio helpers
# --------------------------------------------------------------------------


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


def load_float_16k(path: str) -> np.ndarray:
    with wave.open(path, "rb") as handle:
        rate = handle.getframerate()
        raw = handle.readframes(handle.getnframes())
    mono = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if rate != 16000:
        target_len = int(len(mono) / rate * 16000)
        mono = np.interp(
            np.linspace(0.0, len(mono) - 1, target_len),
            np.arange(len(mono)),
            mono,
        ).astype(np.float32)
    return mono


def rms_envelope(audio: np.ndarray, frame_ms: int = FRAME_MS) -> np.ndarray:
    frame_len = int(16000 * frame_ms / 1000)
    frames = audio.size // frame_len
    if frames == 0:
        return np.zeros(0, dtype=np.float32)
    block = audio[: frames * frame_len].reshape(frames, frame_len)
    return np.sqrt(np.mean(block ** 2, axis=1))


def _xcorr_peak(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    x = x - np.mean(x)
    y = y - np.mean(y)
    nx, ny = float(np.linalg.norm(x)), float(np.linalg.norm(y))
    if nx == 0.0 or ny == 0.0:
        return 0.0, 0.0
    size = 1
    while size < (x.size + y.size):
        size <<= 1
    correlation = np.fft.irfft(np.fft.rfft(x, size) * np.conj(np.fft.rfft(y, size)), size)
    max_lag = 8000  # +/- 500 ms
    window = np.concatenate([correlation[-max_lag:], correlation[: max_lag + 1]]) / (nx * ny)
    index = int(np.argmax(np.abs(window)))
    return float(np.abs(window[index])), (index - max_lag) * 1000.0 / 16000.0


def echo_peak(mic: np.ndarray, remote: np.ndarray) -> tuple[float, float]:
    """Worst-case normalized cross-correlation between the tracks, and its lag.

    A user on open speakers produces a delayed copy of the remote audio in the
    mic track, which shows up as a sharp peak at a lag of roughly 50-400 ms.
    Ordinary turn-taking does not correlate at the sample level.

    Echo can only be observed where both tracks carry signal, so candidate
    windows are restricted to those where each track is active. Scoring a
    window in which the mic happens to be muted reports a spurious 0.0, which
    is exactly the false "clean" verdict this check exists to prevent.
    """
    length = min(mic.size, remote.size)
    if length == 0:
        return 0.0, 0.0
    mic_env = rms_envelope(mic[:length])
    sys_env = rms_envelope(remote[:length])
    frames = min(mic_env.size, sys_env.size)
    win_frames = 300  # 30 s
    if frames < win_frames:
        return _xcorr_peak(mic[:length], remote[:length])

    frame_len = int(16000 * FRAME_MS / 1000)
    best_peak, best_lag = 0.0, 0.0
    scored = []
    for start in range(0, frames - win_frames + 1, win_frames):
        mic_slice = mic_env[start:start + win_frames]
        sys_slice = sys_env[start:start + win_frames]
        # both tracks must actually be carrying audio in this window
        activity = min(float(np.mean(mic_slice > 0.01)), float(np.mean(sys_slice > 0.01)))
        if activity > 0.1:
            scored.append((activity, start))
    scored.sort(reverse=True)
    for _, start in scored[:8]:
        lo = start * frame_len
        hi = min(length, (start + win_frames) * frame_len)
        peak, lag = _xcorr_peak(mic[lo:hi], remote[lo:hi])
        if peak > best_peak:
            best_peak, best_lag = peak, lag
    return best_peak, best_lag


# --------------------------------------------------------------------------
# onnxruntime session construction (explicit, never inherited)
# --------------------------------------------------------------------------


def make_session(model_path: str, intra_op: int = 0, inter_op: int = 0,
                 spin: bool = True, use_app_options: bool = False) -> ort.InferenceSession:
    """Build an inference session with options this harness sets explicitly.

    intra_op/inter_op of 0 keeps the onnxruntime default (one thread per
    physical core for intra-op). Anything else is pinned. Session options are
    never inherited by accident: the point of the sweep is that the two models
    are compared under identical, stated settings.

    use_app_options instead borrows `speaker_diarizer._embed_session_options()`
    so the "as the application would run it" row tracks whatever ALP-289 tunes
    the defaults to, rather than freezing a copy of them here.
    """
    if use_app_options:
        options = sd._embed_session_options()
    else:
        options = ort.SessionOptions()
        options.intra_op_num_threads = intra_op
        options.inter_op_num_threads = inter_op
        if not spin:
            # ORT keeps the intra-op pool spinning after a call returns. Live
            # segments arrive seconds apart, so that spin is charged to
            # whatever runs next rather than to the embedding (ALP-289).
            options.add_session_config_entry("session.intra_op.allow_spinning", "0")
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    return ort.InferenceSession(
        model_path,
        sess_options=options,
        providers=["CPUExecutionProvider"],
    )


def available_models(models_dir: str) -> list[tuple[str, str]]:
    """Resolve candidate (label, path) pairs that exist on disk, deduped."""
    found: list[tuple[str, str]] = []
    have_resnet34 = os.path.exists(os.path.join(models_dir, RESNET34_FILENAME))
    for label, filename in CANDIDATES:
        if filename == sd.LEGACY_EMBED_MODEL_FILENAME and have_resnet34:
            continue
        path = os.path.join(models_dir, filename)
        if not os.path.exists(path):
            print(f"skipping {label}: {filename} not found in {models_dir}")
            continue
        found.append((label, path))
    return found


# --------------------------------------------------------------------------
# mode: pipeline (original behaviour, plus explicit session options)
# --------------------------------------------------------------------------


class RecordingRegistry(SpeakerRegistry):
    """SpeakerRegistry that records each match/enroll decision."""

    def __init__(self, threshold: float | None = None):
        super().__init__(threshold=threshold)
        self.matched_sims: list[float] = []
        self.new_speaker_sims: list[float] = []

    def match_or_create(self, embedding: np.ndarray, allow_create: bool = True) -> str:
        speaker_id, sim = self.match(embedding)
        if speaker_id:
            self.matched_sims.append(sim)
        else:
            self.new_speaker_sims.append(sim)
        return super().match_or_create(embedding, allow_create=allow_create)


def percentile_line(values: list[float]) -> str:
    if not values:
        return "n=0"
    arr = np.array(values)
    return (
        f"n={len(arr)} p10={np.percentile(arr, 10):.3f} "
        f"p50={np.percentile(arr, 50):.3f} p90={np.percentile(arr, 90):.3f}"
    )


def diarize_file(path: str) -> list:
    registry = RecordingRegistry(threshold=None)
    diarizer = SpeakerDiarizer(registry=registry)
    pcm = load_pcm16_mono_16k(path)
    segments = []
    chunk = 32000  # 1 s of PCM16 @ 16 kHz
    for index in range(0, len(pcm), chunk):
        segments.extend(diarizer.feed_audio(pcm[index:index + chunk]))
    segments.extend(flush_diarizer_segments(diarizer))
    return segments, registry


def run_pipeline_model(label: str, model_path: str, audio_files: list[str],
                       threshold: float, intra_op: int) -> dict[str, list]:
    sd._embed_session = make_session(model_path, intra_op=intra_op)
    print(f"\n=== {label} ({os.path.basename(model_path)}) "
          f"threshold={threshold} intra_op={intra_op or 'default'} ===")

    all_matched: list[float] = []
    all_new: list[float] = []
    assignments: dict[str, list] = {}
    for path in audio_files:
        registry = RecordingRegistry(threshold=threshold)
        diarizer = SpeakerDiarizer(registry=registry)
        pcm = load_pcm16_mono_16k(path)
        segments = []
        chunk = 32000
        for index in range(0, len(pcm), chunk):
            segments.extend(diarizer.feed_audio(pcm[index:index + chunk]))
        segments.extend(flush_diarizer_segments(diarizer))

        speakers = sorted({segment.speaker_id for segment in segments})
        print(f"  {os.path.basename(path)}: {len(segments)} segments, "
              f"{len(speakers)} speakers {speakers}")
        assignments[path] = [
            (segment.start_sample, len(segment.pcm_bytes) // 2, segment.speaker_id)
            for segment in segments
        ]
        all_matched.extend(registry.matched_sims)
        all_new.extend(registry.new_speaker_sims)

    print(f"  matched-segment similarity: {percentile_line(all_matched)}")
    print(f"  new-speaker best-similarity: {percentile_line(all_new)}")
    if all_matched and all_new:
        suggested = (float(np.median(all_matched)) + float(np.median(all_new))) / 2
        print(f"  suggested threshold (midpoint of medians): {suggested:.2f}")
    return assignments


def agreement(a: dict[str, list], b: dict[str, list]) -> None:
    """Per-segment label agreement between two models, over shared segments."""
    print("\n=== per-segment assignment agreement (mixed tracks) ===")
    for path in a:
        if path not in b:
            continue
        left = {start: label for start, _, label in a[path] if start is not None}
        right = {start: label for start, _, label in b[path] if start is not None}
        shared = sorted(set(left) & set(right))
        if not shared:
            print(f"  {os.path.basename(path)}: no aligned segments")
            continue
        left_labels = sorted({left[s] for s in shared})
        right_labels = sorted({right[s] for s in shared})
        matrix = np.zeros((len(left_labels), len(right_labels)), dtype=np.int64)
        for start in shared:
            matrix[left_labels.index(left[start]), right_labels.index(right[start])] += 1
        try:
            from scipy.optimize import linear_sum_assignment

            rows, cols = linear_sum_assignment(-matrix)
            best = int(matrix[rows, cols].sum())
        except Exception:  # greedy fallback
            best, used_r, used_c = 0, set(), set()
            order = np.dstack(np.unravel_index(np.argsort(-matrix, axis=None), matrix.shape))[0]
            for r, c in order:
                if r in used_r or c in used_c:
                    continue
                used_r.add(int(r))
                used_c.add(int(c))
                best += int(matrix[r, c])
        total_a = len(a[path])
        total_b = len(b[path])
        print(f"  {os.path.basename(path)}: {len(shared)} aligned of "
              f"{total_a}/{total_b} segments, best-permutation agreement "
              f"{best}/{len(shared)} = {100.0 * best / len(shared):.1f}% "
              f"({len(left_labels)} vs {len(right_labels)} speakers)")


# --------------------------------------------------------------------------
# mode: margin (ground truth from the split tracks)
# --------------------------------------------------------------------------


def vad_mask(audio: np.ndarray) -> np.ndarray:
    """Per-100ms speech mask from the production Silero VAD.

    The VAD runs on 512-sample (32 ms) frames; a 100 ms frame counts as speech
    when the majority of its subframes do. Model independent, so it is computed
    once per track and reused by every embedding model.
    """
    vad = VoiceActivityDetector()
    frame = VoiceActivityDetector.FRAME_SAMPLES
    count = audio.size // frame
    probs = np.zeros(count, dtype=np.float32)
    for index in range(count):
        probs[index] = vad.process_frame(audio[index * frame:(index + 1) * frame])
    speech = probs >= settings.VAD_THRESHOLD

    frame_len = int(16000 * FRAME_MS / 1000)
    out_frames = audio.size // frame_len
    mask = np.zeros(out_frames, dtype=bool)
    per_out = frame_len / float(frame)  # 3.125 VAD frames per 100 ms
    for index in range(out_frames):
        lo = int(index * per_out)
        hi = max(lo + 1, int((index + 1) * per_out))
        chunk = speech[lo:min(hi, speech.size)]
        if chunk.size:
            mask[index] = bool(np.mean(chunk) >= 0.5)
    return mask


def exclusive_windows(own_env, own_speech, other_env, other_speech,
                      own_min_rms, other_max_rms, window_seconds):
    """Fixed-length windows where this track speaks and the other is silent.

    Whole VAD turns almost never stay exclusive in a real conversation, so
    exclusivity is decided per 100 ms frame and maximal exclusive runs are then
    cut into equal windows. Equal length also removes segment duration as a
    confound between the two models being compared.
    """
    keep = exclusive_mask(own_env, own_speech, other_env, other_speech,
                          own_min_rms, other_max_rms)
    frames = keep.size
    if frames == 0:
        return []
    frame_len = int(16000 * FRAME_MS / 1000)
    per_window = max(1, int(round(window_seconds * 1000.0 / FRAME_MS)))

    windows = []
    run_start = None
    for index in range(frames + 1):
        active = bool(keep[index]) if index < frames else False
        if active and run_start is None:
            run_start = index
        elif not active and run_start is not None:
            length = index - run_start
            for offset in range(0, length - per_window + 1, per_window):
                lo = (run_start + offset) * frame_len
                windows.append((lo, lo + per_window * frame_len))
            run_start = None
    return windows


def dilate(mask: np.ndarray, frames: int) -> np.ndarray:
    """Widen a boolean mask by `frames` on both sides."""
    if frames <= 0 or mask.size == 0:
        return mask
    out = mask.copy()
    for shift in range(1, frames + 1):
        out[shift:] |= mask[:-shift]
        out[:-shift] |= mask[shift:]
    return out


def exclusive_mask(own_env, own_speech, other_env, other_speech,
                   own_min_rms, other_max_rms, guard_frames: int = 3) -> np.ndarray:
    """Frames where this track carries speech and the other carries none.

    The bar for the other track is "no speech", not "digital silence": a
    conference bridge streams continuous room tone well above the noise floor,
    so demanding true silence rejects almost everything. Its VAD mask is
    dilated by a guard band so speech onsets and tails cannot leak in.
    """
    frames = min(own_env.size, other_env.size, own_speech.size, other_speech.size)
    if frames == 0:
        return np.zeros(0, dtype=bool)
    other_busy = dilate(other_speech[:frames], guard_frames)
    return (
        own_speech[:frames]
        & (own_env[:frames] > own_min_rms)
        & ~other_busy
        & (other_env[:frames] < other_max_rms)
    )


def exclusive_run_lengths(own_env, own_speech, other_env, other_speech,
                          own_min_rms, other_max_rms) -> np.ndarray:
    """Durations (seconds) of the maximal exclusive-activity runs."""
    keep = exclusive_mask(own_env, own_speech, other_env, other_speech,
                          own_min_rms, other_max_rms)
    if keep.size == 0:
        return np.zeros(0)
    padded = np.concatenate([[False], keep, [False]])
    edges = np.diff(padded.astype(np.int8))
    starts = np.flatnonzero(edges == 1)
    ends = np.flatnonzero(edges == -1)
    return (ends - starts) * FRAME_MS / 1000.0


def run_summary(runs: np.ndarray) -> str:
    if runs.size == 0:
        return "n=0"
    return f"{np.percentile(runs, 50):.1f}/{np.percentile(runs, 90):.1f}s"


def speech_windows(env, speech, min_rms, window_seconds, min_seconds):
    """Cut VAD speech runs into windows of a fixed length.

    Used for tracks that are single-source by construction, where no
    exclusivity filter is needed: a headphone mic carries only the local user,
    and the application output track carries only remote participants.
    Equal-length windows also keep duration from confounding the comparison.
    """
    frames = min(env.size, speech.size)
    if frames == 0:
        return []
    keep = speech[:frames] & (env[:frames] > min_rms)
    frame_len = int(16000 * FRAME_MS / 1000)
    per_window = max(1, int(round(window_seconds * 1000.0 / FRAME_MS)))
    min_frames = max(1, int(round(min_seconds * 1000.0 / FRAME_MS)))

    windows = []
    run_start = None
    for index in range(frames + 1):
        active = bool(keep[index]) if index < frames else False
        if active and run_start is None:
            run_start = index
        elif not active and run_start is not None:
            length = index - run_start
            offset = 0
            while offset < length:
                take = min(per_window, length - offset)
                if take >= min_frames:
                    lo = (run_start + offset) * frame_len
                    windows.append((lo, lo + take * frame_len))
                offset += per_window
            run_start = None
    return windows


def cached_track_features(path: str, cache_dir: str):
    """(rms envelope, VAD speech mask) for a track, cached on disk.

    The VAD pass is minutes of single-threaded ONNX per hour of audio and is
    identical for every embedding model, so it is computed once and reused
    across runs and across parameter sweeps.
    """
    audio = load_float_16k(path)
    if not cache_dir:
        return audio, rms_envelope(audio), vad_mask(audio)
    os.makedirs(cache_dir, exist_ok=True)
    stat = os.stat(path)
    key = f"{os.path.basename(os.path.dirname(path))}_{os.path.basename(path)}"
    key = f"{key}_{int(stat.st_mtime)}_{stat.st_size}_{settings.VAD_THRESHOLD}.npz"
    cache_path = os.path.join(cache_dir, key.replace(os.sep, "_"))
    if os.path.exists(cache_path):
        blob = np.load(cache_path)
        return audio, blob["env"], blob["speech"]
    env, speech = rms_envelope(audio), vad_mask(audio)
    np.savez_compressed(cache_path, env=env, speech=speech)
    return audio, env, speech


def embed_spans(audio: np.ndarray, spans) -> np.ndarray:
    out = np.zeros((len(spans), 256), dtype=np.float32)
    for index, (lo, hi) in enumerate(spans):
        out[index] = sd.extract_speaker_embedding(audio[lo:hi])
    return out


def cached_embeddings(model_path, key, track, spans, audio, cache_dir):
    """Embeddings for one track, cached per (model, track, exact window set)."""
    if not spans:
        return np.zeros((0, 256), dtype=np.float32)
    if not cache_dir:
        return embed_spans(audio, spans)
    os.makedirs(cache_dir, exist_ok=True)
    digest = hashlib.sha1(
        f"{os.path.basename(model_path)}|{key}|{track}|{spans}".encode()
    ).hexdigest()[:20]
    path = os.path.join(cache_dir, f"emb_{digest}.npy")
    if os.path.exists(path):
        return np.load(path)
    out = embed_spans(audio, spans)
    np.save(path, out)
    return out


def single_speaker_report(embeddings: np.ndarray) -> str:
    """Crude check that a track really holds one voice.

    A single speaker gives a unimodal, high self-similarity cloud. Several
    voices in one track (an in-person meeting captured on the laptop mic) drag
    the median down and stretch the spread, which invalidates any use of that
    track as a same-speaker label.
    """
    if embeddings.shape[0] < 4:
        return "n<4"
    sim = embeddings @ embeddings.T
    iu = np.triu_indices(embeddings.shape[0], k=1)
    values = sim[iu]
    centroid = embeddings.mean(axis=0)
    norm = np.linalg.norm(centroid)
    tightness = float(norm) if norm else 0.0
    return (f"p50={np.median(values):.3f} p10={np.percentile(values, 10):.3f} "
            f"p90={np.percentile(values, 90):.3f} |centroid|={tightness:.3f}")


def centroid_scores(own: np.ndarray, other: np.ndarray):
    """Similarities against a running profile, as SpeakerRegistry computes them.

    Production never compares two segments directly: it compares a new
    embedding against a profile that is the renormalized running mean of the
    embeddings already assigned to that speaker. Averaging suppresses
    per-segment noise, so profile similarities sit higher than pairwise ones,
    and a threshold derived from pairwise numbers would be set too low.
    Enrollment here follows ground truth rather than the match decision, so the
    profile never drifts onto the wrong speaker.
    """
    if own.shape[0] < 2:
        return np.zeros(0), np.zeros(0)
    centroid = own[0].astype(np.float64).copy()
    count = 1
    same = []
    for index in range(1, own.shape[0]):
        same.append(float(np.dot(own[index], centroid)))
        centroid = (centroid * count + own[index]) / (count + 1)
        norm = np.linalg.norm(centroid)
        if norm > 0:
            centroid = centroid / norm
        count += 1
    diff = other @ centroid if other.shape[0] else np.zeros(0)
    return np.array(same), np.asarray(diff)


def overlap_rate(pos: np.ndarray, neg: np.ndarray) -> float:
    """P(a different-speaker pair scores at least as high as a same-speaker pair).

    Computed by sorting rather than an outer product; the pair sets reach
    hundreds of thousands of entries and the dense form does not fit in memory.
    """
    if pos.size == 0 or neg.size == 0:
        return float("nan")
    ordered = np.sort(neg)
    ge = neg.size - np.searchsorted(ordered, pos, side="left")
    return float(np.sum(ge) / (float(pos.size) * float(neg.size)))


def error_curves(pos: np.ndarray, neg: np.ndarray):
    """Return (eer, eer_threshold, best_threshold, best_total_error)."""
    if pos.size == 0 or neg.size == 0:
        return float("nan"), float("nan"), float("nan"), float("nan")
    grid = np.linspace(-0.2, 1.0, 1201)
    frr = np.array([float(np.mean(pos < t)) for t in grid])   # same speaker split
    far = np.array([float(np.mean(neg >= t)) for t in grid])  # different merged
    cross = int(np.argmin(np.abs(frr - far)))
    total = frr + far
    best = int(np.argmin(total))
    return (frr[cross] + far[cross]) / 2.0, grid[cross], grid[best], total[best]


def tail_mass(pos: np.ndarray, neg: np.ndarray) -> np.ndarray:
    """Per-positive false-accept mass: fraction of negatives scoring at least
    as high as that positive. Its mean is the overlap rate."""
    if pos.size == 0 or neg.size == 0:
        return np.zeros(0)
    ordered = np.sort(neg)
    return (neg.size - np.searchsorted(ordered, pos, side="left")) / float(neg.size)


def paired_bootstrap(results: dict, samples: int) -> None:
    """Compare two models on the same positive pairs.

    Both models score an identical, identically ordered set of pairs, so the
    comparison is paired and far more sensitive than comparing two independent
    error rates. The statistic is the per-positive false-accept mass; the
    resampling is over positives, which is where the uncertainty lives (the
    negative set is three orders of magnitude larger).
    """
    labels = [k for k, v in results.items() if v["a_pos"].size]
    if len(labels) != 2 or samples <= 0:
        return
    left, right = labels
    a = tail_mass(results[left]["a_pos"], results[left]["a_neg"])
    b = tail_mass(results[right]["a_pos"], results[right]["a_neg"])
    if a.size != b.size or a.size == 0:
        return

    diff = b - a  # positive means `left` is the better model
    rng = np.random.default_rng(0)
    index = rng.integers(0, a.size, size=(samples, a.size))
    means = diff[index].mean(axis=1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    print(f"\n=== paired bootstrap, {left} vs {right} "
          f"({a.size} shared positive pairs, {samples} resamples) ===")
    print(f"  overlap rate {left}: {a.mean() * 100:.3f}%   "
          f"{right}: {b.mean() * 100:.3f}%")
    print(f"  difference ({right} - {left}): {diff.mean() * 100:+.3f}% "
          f"95% CI [{lo * 100:+.3f}%, {hi * 100:+.3f}%]")
    better = float(np.mean(means > 0))
    print(f"  P({left} better than {right}) = {better * 100:.1f}%")
    print("  verdict: " + (
        f"{left} is better at the 95% level" if lo > 0 else
        f"{right} is better at the 95% level" if hi < 0 else
        "no difference resolved at the 95% level"))


def describe(name: str, values: np.ndarray) -> None:
    if values.size == 0:
        print(f"    {name:28} n=0")
        return
    p = np.percentile(values, [1, 5, 10, 25, 50, 75, 90, 95, 99])
    print(f"    {name:28} n={values.size:<8} mean={values.mean():.3f} "
          f"p1={p[0]:.3f} p5={p[1]:.3f} p25={p[3]:.3f} p50={p[4]:.3f} "
          f"p75={p[5]:.3f} p95={p[7]:.3f} p99={p[8]:.3f}")


def find_dual_track_recordings(audio_root: str) -> list[tuple[str, str, str, str]]:
    """Return (session, stem, mic_path, sys_path) for every split recording."""
    out = []
    for mic_path in sorted(glob.glob(os.path.join(audio_root, "*", "*_mic.wav"))):
        sys_path = mic_path[: -len("_mic.wav")] + "_sys.wav"
        if not os.path.exists(sys_path):
            continue
        session = os.path.basename(os.path.dirname(mic_path))
        stem = os.path.basename(mic_path)[: -len("_mic.wav")]
        out.append((session, stem, mic_path, sys_path))
    return out


def _stack(parts: list) -> np.ndarray:
    return np.concatenate(parts) if parts else np.zeros(0)


def classify_recording(mic_path: str, sys_path: str, args):
    """Decide which of a recording's two tracks carry trustworthy labels.

    The mic track is only the local user if nothing can echo into it: either
    the output track is digitally silent, or the sample-level echo test is
    clean. The output track carries remote participants either way.
    """
    mic = load_float_16k(mic_path)
    remote = load_float_16k(sys_path)
    length = min(mic.size, remote.size)
    mic, remote = mic[:length], remote[:length]
    mic_rms = float(np.sqrt(np.mean(mic ** 2)))
    sys_rms = float(np.sqrt(np.mean(remote ** 2)))
    sys_silent = sys_rms < 0.001
    peak, lag = (0.0, 0.0) if sys_silent else echo_peak(mic, remote)

    if mic_rms < 0.001:
        mic_state = "skip-silent"
    elif sys_silent:
        mic_state = "USE (no output)"
    elif peak > args.echo_limit and not args.allow_echo:
        mic_state = "skip-echo"
    else:
        mic_state = "USE (clean)"
    sys_state = "skip-silent" if sys_silent else "USE"
    del mic, remote
    return length, mic_rms, sys_rms, peak, lag, mic_state, sys_state


def validate_tracks(recordings, args) -> list:
    """Survey every dual-track recording and report which tracks are usable."""
    print("=== dual-track survey and label validation ===")
    print("mic is trustworthy when nothing can echo into it: either the output")
    print("track is digitally silent, or the sample-level echo test is clean.")
    print("The output track only ever carries remote participants, so it is")
    print("trustworthy regardless of echo.")
    print(f"\n{'session':16} {'stem':10} {'dur_s':>8} {'micRMS':>8} {'sysRMS':>8} "
          f"{'echo':>6} {'lag_ms':>7}  mic     sys")
    usable = []
    for session, stem, mic_path, sys_path in recordings:
        (length, mic_rms, sys_rms, peak, lag,
         mic_state, sys_state) = classify_recording(mic_path, sys_path, args)
        print(f"{session[:14]:16} {stem:10} {length/16000.0:8.1f} {mic_rms:8.5f} "
              f"{sys_rms:8.5f} {peak:6.3f} {lag:7.1f}  {mic_state:15} {sys_state}")
        if mic_state.startswith("USE") or sys_state == "USE":
            usable.append((session, stem, mic_path, sys_path,
                           mic_state.startswith("USE"), sys_state == "USE"))
    return usable


def window_tracks(usable, args) -> list:
    """Cut every trustworthy track into equal-length windows.

    The VAD pass behind this is model independent, so it runs once here and
    every embedding model reuses the same windows.
    """
    print(f"\n=== windowing (window={args.window_seconds}s, "
          f"min={settings.MIN_SEGMENT_MS / 1000.0}s, min_rms={args.own_min_rms}) ===")
    print(f"{'session':16} {'stem':10} {'micWin':>7} {'micSec':>8} "
          f"{'sysWin':>7} {'sysSec':>8}")
    prepared = []
    min_seconds = settings.MIN_SEGMENT_MS / 1000.0
    for session, stem, mic_path, sys_path, use_mic, use_sys in usable:
        mic = remote = None
        mic_keep: list = []
        sys_keep: list = []
        if use_mic:
            mic, mic_env, mic_speech = cached_track_features(mic_path, args.cache_dir)
            mic_keep = speech_windows(mic_env, mic_speech, args.own_min_rms,
                                      args.window_seconds, min_seconds)
        if use_sys:
            remote, sys_env, sys_speech = cached_track_features(sys_path, args.cache_dir)
            sys_keep = speech_windows(sys_env, sys_speech, args.own_min_rms,
                                      args.window_seconds, min_seconds)
        if args.max_segments:
            mic_keep = mic_keep[: args.max_segments]
            sys_keep = sys_keep[: args.max_segments]
        mic_sec = sum(hi - lo for lo, hi in mic_keep) / 16000.0
        sys_sec = sum(hi - lo for lo, hi in sys_keep) / 16000.0
        print(f"{session[:14]:16} {stem:10} {len(mic_keep):7} {mic_sec:8.1f} "
              f"{len(sys_keep):7} {sys_sec:8.1f}")
        prepared.append((session, stem, mic, remote, mic_keep, sys_keep))
    return prepared


def embed_prepared(path: str, prepared, args) -> dict:
    """Embed every window with one model, serving from cache where possible."""
    mic_embeddings, sys_embeddings, mic_starts = {}, {}, {}
    mic_spans, sys_spans = {}, {}
    started = time.process_time()
    for session, stem, mic, remote, mic_keep, sys_keep in prepared:
        key = f"{session}/{stem}"
        mic_embeddings[key] = cached_embeddings(path, key, "mic", mic_keep,
                                                mic, args.cache_dir)
        sys_embeddings[key] = cached_embeddings(path, key, "sys", sys_keep,
                                                remote, args.cache_dir)
        mic_spans[key] = mic_keep
        sys_spans[key] = sys_keep
        mic_starts[key] = np.array([lo / 16000.0 for lo, _ in mic_keep])
    cpu = time.process_time() - started
    embedded = sum(v.shape[0] for v in mic_embeddings.values())
    embedded += sum(v.shape[0] for v in sys_embeddings.values())
    print(f"  embedded {embedded} windows, {cpu:.1f}s CPU "
          f"({1000.0 * cpu / max(embedded, 1):.0f} ms CPU each incl. fbank; "
          f"0 if served from cache)")
    return dict(mic=mic_embeddings, sys=sys_embeddings, mic_starts=mic_starts,
                mic_spans=mic_spans, sys_spans=sys_spans,
                cpu_ms=1000.0 * cpu / max(embedded, 1))


def report_track_purity(mic_embeddings: dict, sys_embeddings: dict) -> None:
    """Show whether each track plausibly holds a single voice."""
    print("  per-track self-similarity (is this really one speaker?)")
    for name, store in (("mic", mic_embeddings), ("sys", sys_embeddings)):
        for key in sorted(store):
            if store[key].shape[0]:
                print(f"    {name} {key[:14]}/{key.split('/')[-1]:10} "
                      f"n={store[key].shape[0]:<5} "
                      f"{single_speaker_report(store[key])}")


def restrict_positives(mic_embeddings: dict, mic_starts: dict, tokens) -> None:
    """Drop mic tracks that should not supply same-speaker pairs."""
    allowed = [k for k in mic_embeddings
               if any(token in k for token in tokens)]
    dropped = sorted(set(mic_embeddings) - set(allowed))
    print(f"  positives restricted to: {sorted(allowed)}")
    if dropped:
        print(f"  positives excluded: {dropped}")
    for key in dropped:
        mic_embeddings[key] = np.zeros((0, 256), dtype=np.float32)
        mic_starts[key] = np.zeros(0)


def track_label_pairs(mic_embeddings, sys_embeddings, mic_starts, min_pair_gap):
    """Pairs built from the mic-is-local, output-is-remote track labels.

    Section 3 of the ALP-292 report explains why these labels do not hold on
    the recorded corpus; they are still computed so the failure is visible
    rather than assumed.
    """
    pos_parts, neg_parts, unknown_parts, far_parts = [], [], [], []
    for key in mic_embeddings:
        mic_e, sys_e = mic_embeddings[key], sys_embeddings[key]
        if mic_e.shape[0] >= 2:
            sim = mic_e @ mic_e.T
            iu = np.triu_indices(mic_e.shape[0], k=1)
            pos_parts.append(sim[iu])
            # Adjacent windows can come from one breath; requiring a wide
            # time gap makes the positives near-independent samples.
            starts = mic_starts[key]
            gap = np.abs(starts[:, None] - starts[None, :])[iu]
            far_parts.append(sim[iu][gap >= min_pair_gap])
        if mic_e.shape[0] and sys_e.shape[0]:
            neg_parts.append((mic_e @ sys_e.T).ravel())
        if sys_e.shape[0] >= 2:
            sim = sys_e @ sys_e.T
            iu = np.triu_indices(sys_e.shape[0], k=1)
            unknown_parts.append(sim[iu])

    # The local user is never a remote participant in their own call, so
    # mic-of-A against sys-of-B is a different-speaker pair too.
    cross_parts = []
    keys = sorted(mic_embeddings)
    for i in range(len(keys)):
        for j in range(len(keys)):
            if i == j:
                continue
            left, right = mic_embeddings[keys[i]], sys_embeddings[keys[j]]
            if left.shape[0] and right.shape[0]:
                neg_parts.append((left @ right.T).ravel())
            if j > i:
                left, right = mic_embeddings[keys[i]], mic_embeddings[keys[j]]
                if left.shape[0] and right.shape[0]:
                    cross_parts.append((left @ right.T).ravel())

    return (_stack(pos_parts), _stack(neg_parts), _stack(unknown_parts),
            _stack(cross_parts), _stack(far_parts))


def profile_pairs(mic_embeddings: dict, sys_embeddings: dict):
    """Similarities against a running profile, the regime the threshold gates."""
    all_remote = [sys_embeddings[k] for k in sys_embeddings if sys_embeddings[k].shape[0]]
    remote_stack = np.concatenate(all_remote) if all_remote else np.zeros((0, 256))
    c_same_parts, c_diff_parts = [], []
    for key in mic_embeddings:
        same_c, diff_c = centroid_scores(mic_embeddings[key], remote_stack)
        if same_c.size:
            c_same_parts.append(same_c)
        if diff_c.size:
            c_diff_parts.append(diff_c)
    return _stack(c_same_parts), _stack(c_diff_parts)


def label_free_pairs(mic_embeddings, sys_embeddings, mic_spans, sys_spans):
    """Pairs that need no track labels at all.

    Same speaker: two windows carved from one uninterrupted VAD speech run.
    Different speaker: output tracks belonging to two different calls.
    """
    adj_parts, xsess_by_session = [], {}
    for key in mic_embeddings:
        for store, spans_by_key in ((mic_embeddings, mic_spans),
                                    (sys_embeddings, sys_spans)):
            vectors, spans = store[key], spans_by_key[key]
            for index in range(len(spans) - 1):
                if spans[index][1] == spans[index + 1][0]:
                    adj_parts.append(float(np.dot(vectors[index],
                                                  vectors[index + 1])))
        session_key = key.split("/")[0]
        if sys_embeddings[key].shape[0]:
            xsess_by_session.setdefault(session_key, []).append(sys_embeddings[key])
    adjacent = np.array(adj_parts) if adj_parts else np.zeros(0)

    stacks = {s: np.concatenate(v) for s, v in xsess_by_session.items()}
    xsess_parts = []
    names = sorted(stacks)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            xsess_parts.append((stacks[names[i]] @ stacks[names[j]].T).ravel())
    return adjacent, _stack(xsess_parts)


def report_profile_regime(c_same, c_diff, threshold):
    print("  profile regime (running-mean centroid, as SpeakerRegistry does)")
    describe("SAME vs own profile", c_same)
    describe("DIFF vs local profile", c_diff)
    if not (c_same.size and c_diff.size):
        return float("nan"), float("nan"), float("nan")
    c_eer, c_eer_t, c_best_t, c_best = error_curves(c_same, c_diff)
    c_at_frr = float(np.mean(c_same < threshold))
    c_at_far = float(np.mean(c_diff >= threshold))
    print(f"    EER {c_eer * 100:.2f}% at t={c_eer_t:.3f}; min total error "
          f"{c_best * 100:.2f}% at t={c_best_t:.3f}; "
          f"at t={threshold:.2f} split-same={c_at_frr * 100:.2f}% "
          f"merged-diff={c_at_far * 100:.2f}%")
    return c_eer, c_eer_t, c_best_t


def report_label_free(adjacent, cross_session):
    print("  label-free comparison (no track labels needed)")
    describe("SAME: contiguous windows", adjacent)
    describe("DIFF: output tracks, 2 calls", cross_session)
    if not (adjacent.size and cross_session.size):
        return float("nan"), float("nan"), float("nan"), float("nan")
    a_eer, a_eer_t, a_best_t, a_best = error_curves(adjacent, cross_session)
    a_ovl = overlap_rate(adjacent, cross_session)
    print(f"    EER {a_eer * 100:.2f}% at t={a_eer_t:.3f}; min total error "
          f"{a_best * 100:.2f}% at t={a_best_t:.3f}; "
          f"overlap {a_ovl * 100:.3f}%; "
          f"separation p5(SAME)-p95(DIFF)="
          f"{np.percentile(adjacent, 5) - np.percentile(cross_session, 95):+.3f}")
    return a_eer, a_eer_t, a_best_t, a_ovl


def report_track_metrics(pos, neg, threshold):
    eer, eer_t, best_t, best_err = error_curves(pos, neg)
    overlap = overlap_rate(pos, neg)
    margin = (float(np.percentile(pos, 5)) - float(np.percentile(neg, 95))
              if pos.size and neg.size else float("nan"))
    at_t_frr = float(np.mean(pos < threshold)) if pos.size else float("nan")
    at_t_far = float(np.mean(neg >= threshold)) if neg.size else float("nan")
    print(f"  separation p5(SAME) - p95(DIFF)   : {margin:+.3f}")
    print(f"  median gap  p50(SAME) - p50(DIFF) : "
          f"{np.median(pos) - np.median(neg):+.3f}")
    print(f"  overlap P(DIFF >= SAME)           : {overlap * 100:.2f}%")
    print(f"  equal error rate                  : {eer * 100:.2f}% at t={eer_t:.3f}")
    print(f"  min total error                   : {best_err * 100:.2f}% at t={best_t:.3f}")
    print(f"  at threshold {threshold:.2f}: split-same={at_t_frr * 100:.2f}% "
          f"merged-diff={at_t_far * 100:.2f}% total={100 * (at_t_frr + at_t_far):.2f}%")
    return eer, eer_t, best_t, best_err, overlap, margin


def analyze_model(label: str, path: str, prepared, args) -> dict:
    """Embed and score one model over the prepared windows."""
    sd._embed_session = make_session(path, intra_op=args.intra_op)
    print(f"\n=== {label} ({os.path.basename(path)}) ===")
    store = embed_prepared(path, prepared, args)
    mic_embeddings, sys_embeddings = store["mic"], store["sys"]

    report_track_purity(mic_embeddings, sys_embeddings)
    if args.positive_sessions:
        restrict_positives(mic_embeddings, store["mic_starts"], args.positive_sessions)

    pos, neg, unknown, cross, far = track_label_pairs(
        mic_embeddings, sys_embeddings, store["mic_starts"], args.min_pair_gap
    )
    print("  cosine similarity distributions")
    describe("SAME local user (in call)", pos)
    describe(f"SAME local user (>{args.min_pair_gap:.0f}s apart)", far)
    describe("DIFF local vs remote", neg)
    describe("SAME local user (across calls)", cross)
    describe("UNKNOWN remote vs remote", unknown)
    if far.size and neg.size:
        f_eer, f_eer_t, f_best_t, f_best = error_curves(far, neg)
        print(f"  time-separated positives: EER={f_eer * 100:.2f}% at "
              f"t={f_eer_t:.3f}, min total error {f_best * 100:.2f}% at "
              f"t={f_best_t:.3f}")

    c_same, c_diff = profile_pairs(mic_embeddings, sys_embeddings)
    c_eer, c_eer_t, c_best_t = report_profile_regime(c_same, c_diff, args.threshold)

    adjacent, cross_session = label_free_pairs(
        mic_embeddings, sys_embeddings, store["mic_spans"], store["sys_spans"]
    )
    a_eer, a_eer_t, a_best_t, a_ovl = report_label_free(adjacent, cross_session)

    eer, eer_t, best_t, best_err, overlap, margin = report_track_metrics(
        pos, neg, args.threshold
    )
    return dict(
        eer=eer, eer_t=eer_t, best_t=best_t, best_err=best_err,
        overlap=overlap, margin=margin, cpu_ms=store["cpu_ms"],
        c_eer=c_eer, c_eer_t=c_eer_t, c_best_t=c_best_t,
        a_eer=a_eer, a_eer_t=a_eer_t, a_best_t=a_best_t, a_ovl=a_ovl,
        a_pos=adjacent, a_neg=cross_session,
    )


def print_margin_summary(results: dict) -> None:
    print("\n=== summary ===")
    print("track  = same/different from the mic-vs-output track labels")
    print("free   = contiguous windows vs output tracks of two different calls")
    print(f"\n{'model':22} | {'trackEER%':>9} {'trackOvlp%':>10} | {'freeEER%':>8} "
          f"{'freeEERt':>8} {'freeBestt':>9} {'freeOvlp%':>9} | {'ms/emb':>7}")
    for label, r in results.items():
        print(f"{label:22} | {r['eer']*100:9.2f} {r['overlap']*100:10.3f} | "
              f"{r['a_eer']*100:8.2f} {r['a_eer_t']:8.3f} {r['a_best_t']:9.3f} "
              f"{r['a_ovl']*100:9.3f} | {r['cpu_ms']:7.0f}")


def run_margin(args) -> int:
    models = available_models(sd.MODELS_DIR)
    if len(models) < 2:
        print("margin mode needs both embedding models; "
              "run scripts/download_models.py --optional")
        return 1

    recordings = find_dual_track_recordings(args.audio_root)
    if not recordings:
        print(f"no dual-track recordings under {args.audio_root}")
        return 1

    usable = validate_tracks(recordings, args)
    if not any(flag for *_, flag, _ in usable):
        print("\nno recording has a trustworthy mic track; cannot measure margin")
        return 1
    print(f"\ntrustworthy mic tracks: {sum(1 for *_, m, _ in usable if m)}, "
          f"trustworthy output tracks: {sum(1 for *_, s in usable if s)}, "
          f"of {len(recordings)} dual-track recordings")

    prepared = window_tracks(usable, args)
    total_mic = sum(len(m) for *_, m, _ in prepared)
    total_sys = sum(len(s) for *_, s in prepared)
    print(f"total: {total_mic} local-user windows, {total_sys} remote windows")
    if args.yield_only:
        return 0

    results = {label: analyze_model(label, path, prepared, args)
               for label, path in models}
    paired_bootstrap(results, args.bootstrap)
    print_margin_summary(results)
    return 0


# --------------------------------------------------------------------------
# mode: cost
# --------------------------------------------------------------------------


def run_cost(args) -> int:
    models = available_models(sd.MODELS_DIR)
    if not models:
        print("No embedding models found; run scripts/download_models.py first.")
        return 1

    rng = np.random.default_rng(0)
    seconds = args.segment_seconds
    audio = (rng.standard_normal(int(16000 * seconds)) * 0.05).astype(np.float32)
    feats = sd._compute_fbank(audio).reshape(1, -1, 80)
    print(f"segment={seconds:.1f}s -> feats {feats.shape}, "
          f"{args.repeats} timed runs after {args.warmup} warmups")
    print("cpu_ms/s_audio normalizes for the segment length, so it stays "
          "comparable\nwhen two models segment the audio differently.")

    def time_session(session):
        for _ in range(args.warmup):
            session.run(["embs"], {"feats": feats})
        wall0, cpu0 = time.perf_counter(), time.process_time()
        for _ in range(args.repeats):
            session.run(["embs"], {"feats": feats})
        return ((time.perf_counter() - wall0) * 1000.0 / args.repeats,
                (time.process_time() - cpu0) * 1000.0 / args.repeats)

    header = (f"\n{'model':22} {'intra_op':>9} {'spin':>5} {'wall_ms':>9} "
              f"{'cpu_ms':>9} {'cpu_ms/s_audio':>15} {'x_cpu':>7}")
    print(header)
    for spin in ([True, False] if args.both_spin else [not args.no_spin]):
        for intra_op in args.intra_op:
            baseline = None
            for label, path in models:
                session = make_session(path, intra_op=intra_op, spin=spin)
                wall, cpu = time_session(session)
                if baseline is None:
                    baseline = cpu
                print(f"{label:22} {intra_op or 'default':>9} {str(spin):>5} "
                      f"{wall:9.1f} {cpu:9.1f} {cpu / seconds:15.1f} "
                      f"{baseline / max(cpu, 1e-6):7.2f}")
                del session

    # The row the application actually runs, straight from the shared helper,
    # so it tracks the tuned defaults instead of a copy of them.
    print(f"\nas the application configures it "
          f"(_embed_session_options: {settings.DIARIZER_EMBED_ONNX_THREADS} threads, "
          f"spin={settings.DIARIZER_EMBED_ONNX_SPIN})")
    baseline = None
    for label, path in models:
        session = make_session(path, use_app_options=True)
        wall, cpu = time_session(session)
        if baseline is None:
            baseline = cpu
        print(f"{label:22} {'app':>9} {'-':>5} {wall:9.1f} {cpu:9.1f} "
              f"{cpu / seconds:15.1f} {baseline / max(cpu, 1e-6):7.2f}")
        del session

    # fbank cost for context: charged once per segment regardless of model
    wall0, cpu0 = time.perf_counter(), time.process_time()
    for _ in range(args.repeats):
        sd._compute_fbank(audio)
    print(f"\n{'fbank frontend':22} {'-':>9} {'-':>5} "
          f"{(time.perf_counter() - wall0) * 1000.0 / args.repeats:9.1f} "
          f"{(time.process_time() - cpu0) * 1000.0 / args.repeats:9.1f}")
    return 0


# --------------------------------------------------------------------------


def run_pipeline(args) -> int:
    models = available_models(sd.MODELS_DIR)
    if not models:
        print("No embedding models found; run scripts/download_models.py first.")
        return 1
    threshold = args.threshold or settings.SPEAKER_SIMILARITY_THRESHOLD
    assignments = {}
    for label, path in models:
        assignments[label] = run_pipeline_model(
            label, path, args.audio, threshold, args.intra_op
        )
    labels = list(assignments)
    for i in range(len(labels)):
        for j in range(i + 1, len(labels)):
            print(f"\n--- {labels[i]} vs {labels[j]} ---")
            agreement(assignments[labels[i]], assignments[labels[j]])
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="A/B diarizer embedding models")
    parser.add_argument("--intra-op", type=int, default=0,
                        help="onnxruntime intra_op_num_threads (0 = ORT default)")
    sub = parser.add_subparsers(dest="mode", required=True)

    p_pipe = sub.add_parser("pipeline", help="full pipeline over mixed audio")
    p_pipe.add_argument("audio", nargs="+", help="WAV file(s) to diarize")
    p_pipe.add_argument("--threshold", type=float, default=None,
                        help="similarity threshold (default: app setting)")
    p_pipe.set_defaults(func=run_pipeline)

    p_margin = sub.add_parser("margin", help="ground-truth separation from split tracks")
    p_margin.add_argument("--audio-root", required=True,
                          help="DATA_DIR/audio containing <session>/segment_N_*.wav")
    p_margin.add_argument("--threshold", type=float,
                          default=settings.SPEAKER_SIMILARITY_THRESHOLD)
    p_margin.add_argument("--echo-limit", type=float, default=0.15,
                          help="max mic/sys cross-correlation before a pair is rejected")
    p_margin.add_argument("--allow-echo", action="store_true",
                          help="keep echo-contaminated recordings (labels are unreliable)")
    p_margin.add_argument("--own-min-rms", type=float, default=0.015)
    p_margin.add_argument("--other-max-rms", type=float, default=0.004)
    p_margin.add_argument("--window-seconds", type=float, default=3.0,
                          help="length of each exclusive-activity window")
    p_margin.add_argument("--min-pair-gap", type=float, default=60.0,
                          help="seconds apart for the independent positive set")
    p_margin.add_argument("--max-segments", type=int, default=0,
                          help="cap windows per track per recording (0 = no cap)")
    p_margin.add_argument("--cache-dir", default=os.path.join(
        tempfile.gettempdir(), "diarizer_ab_cache"),
        help="where to cache the per-track VAD pass ('' disables)")
    p_margin.add_argument("--yield-only", action="store_true",
                          help="stop after windowing; use to sweep filter settings")
    p_margin.add_argument("--bootstrap", type=int, default=5000,
                          help="paired bootstrap resamples (0 disables)")
    p_margin.add_argument("--positive-sessions", nargs="*", default=None,
                          help="only these mic tracks supply same-speaker pairs "
                               "(substring match); use after checking the "
                               "per-track self-similarity report")
    p_margin.set_defaults(func=run_margin)

    p_cost = sub.add_parser("cost", help="CPU per embedding under explicit options")
    p_cost.add_argument("--segment-seconds", type=float, default=5.0)
    p_cost.add_argument("--repeats", type=int, default=20)
    p_cost.add_argument("--warmup", type=int, default=3)
    p_cost.add_argument("--intra-op", type=int, nargs="+", default=[0, 1, 2, 4])
    p_cost.add_argument("--no-spin", action="store_true",
                        help="disable the intra-op spin wait")
    p_cost.add_argument("--both-spin", action="store_true",
                        help="report both spin settings")
    p_cost.set_defaults(func=run_cost)

    args = parser.parse_args()
    if args.mode == "cost":
        return args.func(args)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
