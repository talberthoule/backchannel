"""Speaker diarization using Silero VAD + WeSpeaker voice embeddings.

Pipeline: PCM16 audio → VAD (speech detection) → speaker embedding → match/enroll.
"""

import logging
import os
from dataclasses import dataclass

import numpy as np
import onnxruntime as ort

from app.config import settings

try:
    import kaldi_native_fbank as knf
except ImportError:  # pragma: no cover - exercised via the numpy fallback path
    knf = None

logger = logging.getLogger(__name__)

MODELS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "models")

# WeSpeaker ResNet152-LM (VoxCeleb). The legacy filename is misleading: it
# holds WeSpeaker ResNet34-LM, not ECAPA-TDNN. Kept as a fallback so
# deployments that have not re-run download_models.py keep working.
EMBED_MODEL_FILENAME = "voxceleb_resnet152_LM.onnx"
LEGACY_EMBED_MODEL_FILENAME = "ecapa_tdnn.onnx"

# Singletons
_vad_session: ort.InferenceSession | None = None
_embed_session: ort.InferenceSession | None = None


def _get_vad_model() -> ort.InferenceSession:
    global _vad_session
    if _vad_session is None:
        path = os.path.join(MODELS_DIR, "silero_vad.onnx")
        _vad_session = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
        logger.info("Loaded Silero VAD model")
    return _vad_session


def resolve_embed_model_path(models_dir: str = MODELS_DIR) -> str:
    preferred = os.path.join(models_dir, EMBED_MODEL_FILENAME)
    if os.path.exists(preferred):
        return preferred
    return os.path.join(models_dir, LEGACY_EMBED_MODEL_FILENAME)


def _get_embed_model() -> ort.InferenceSession:
    global _embed_session
    if _embed_session is None:
        path = resolve_embed_model_path()
        _embed_session = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
        logger.info(f"Loaded speaker embedding model: {os.path.basename(path)}")
    return _embed_session


def _compute_fbank(pcm_float: np.ndarray, sample_rate: int = 16000, n_mels: int = 80) -> np.ndarray:
    """Kaldi-compatible log Mel fbank matching WeSpeaker's training frontend.

    25ms/10ms hamming frames, dither off, int16 sample scale, and mean-only
    CMN (WeSpeaker does NOT apply variance normalization).
    """
    if knf is not None:
        feats = _kaldi_fbank(pcm_float, sample_rate, n_mels)
    else:
        feats = _numpy_fbank(pcm_float, sample_rate, n_mels)
    # Mean-only CMN; this also cancels any constant gain/scale offset
    feats = feats - feats.mean(axis=0)
    return feats.astype(np.float32)


def _kaldi_fbank(pcm_float: np.ndarray, sample_rate: int, n_mels: int) -> np.ndarray:
    opts = knf.FbankOptions()
    opts.frame_opts.samp_freq = sample_rate
    opts.frame_opts.dither = 0.0
    opts.frame_opts.window_type = "hamming"
    opts.mel_opts.num_bins = n_mels
    extractor = knf.OnlineFbank(opts)
    # Kaldi expects int16-range sample values
    extractor.accept_waveform(sample_rate, (pcm_float * 32768.0).astype(np.float32))
    extractor.input_finished()
    frames = [extractor.get_frame(i) for i in range(extractor.num_frames_ready)]
    if not frames:
        return np.zeros((1, n_mels), dtype=np.float32)
    return np.stack(frames)


def _numpy_fbank(pcm_float: np.ndarray, sample_rate: int, n_mels: int) -> np.ndarray:
    """Approximate Kaldi fbank; used only when kaldi_native_fbank is missing."""
    frame_length_ms = 25
    frame_shift_ms = 10
    frame_length = int(sample_rate * frame_length_ms / 1000)
    frame_shift = int(sample_rate * frame_shift_ms / 1000)
    n_fft = 512

    # Pre-emphasis
    emphasized = np.append(pcm_float[0], pcm_float[1:] - 0.97 * pcm_float[:-1])

    # Framing
    num_frames = max(1, 1 + (len(emphasized) - frame_length) // frame_shift)
    frames = np.zeros((num_frames, frame_length), dtype=np.float32)
    for i in range(num_frames):
        start = i * frame_shift
        end = min(start + frame_length, len(emphasized))
        frames[i, :end - start] = emphasized[start:end]

    # Hamming window
    window = np.hamming(frame_length).astype(np.float32)
    frames *= window

    # FFT
    mag = np.abs(np.fft.rfft(frames, n=n_fft))
    power = mag ** 2

    # Mel filterbank
    low_freq = 20.0
    high_freq = sample_rate / 2.0
    mel_low = 2595.0 * np.log10(1.0 + low_freq / 700.0)
    mel_high = 2595.0 * np.log10(1.0 + high_freq / 700.0)
    mel_points = np.linspace(mel_low, mel_high, n_mels + 2)
    hz_points = 700.0 * (10.0 ** (mel_points / 2595.0) - 1.0)
    bins = np.floor((n_fft + 1) * hz_points / sample_rate).astype(int)

    fbank_matrix = np.zeros((n_mels, n_fft // 2 + 1), dtype=np.float32)
    for m in range(n_mels):
        for k in range(bins[m], bins[m + 1]):
            if bins[m + 1] != bins[m]:
                fbank_matrix[m, k] = (k - bins[m]) / (bins[m + 1] - bins[m])
        for k in range(bins[m + 1], bins[m + 2]):
            if bins[m + 2] != bins[m + 1]:
                fbank_matrix[m, k] = (bins[m + 2] - k) / (bins[m + 2] - bins[m + 1])

    fbank = np.dot(power, fbank_matrix.T)
    fbank = np.where(fbank > 0, fbank, np.finfo(float).eps)
    return np.log(fbank).astype(np.float32)


def _extract_embedding(pcm_float: np.ndarray, sample_rate: int = 16000) -> np.ndarray:
    """Extract a speaker embedding vector from float32 audio."""
    session = _get_embed_model()

    # Compute Fbank features: [T, 80]
    feats = _compute_fbank(pcm_float, sample_rate)
    # Model expects [batch, T, 80]
    feats = feats.reshape(1, -1, 80)

    result = session.run(["embs"], {"feats": feats})
    embedding = result[0].flatten()
    # L2 normalize
    norm = np.linalg.norm(embedding)
    if norm > 0:
        embedding = embedding / norm
    return embedding


def extract_speaker_embedding(pcm_float: np.ndarray, sample_rate: int = 16000) -> np.ndarray:
    """Extract a normalized speaker embedding from float32 audio."""
    return _extract_embedding(pcm_float, sample_rate)


class VoiceActivityDetector:
    """Wraps Silero VAD ONNX with stateful LSTM hidden state."""

    FRAME_SAMPLES = 512  # 32ms at 16kHz

    CONTEXT_SIZE = 64  # samples prepended to each frame (required by Silero VAD)

    def __init__(self, threshold: float | None = None):
        self._threshold = threshold or settings.VAD_THRESHOLD
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._context = np.zeros(self.CONTEXT_SIZE, dtype=np.float32)
        self._sr = np.array(16000, dtype=np.int64)

    def process_frame(self, frame_float: np.ndarray) -> float:
        """Process a 512-sample frame, return speech probability."""
        session = _get_vad_model()
        # Prepend context from previous frame (required by Silero VAD)
        frame_with_ctx = np.concatenate([self._context, frame_float]).reshape(1, -1).astype(np.float32)

        inputs = {
            "input": frame_with_ctx,
            "state": self._state,
            "sr": self._sr,
        }
        output, self._state = session.run(None, inputs)
        # Update context with last 64 samples of current input
        self._context = frame_with_ctx[0, -self.CONTEXT_SIZE:].copy()
        return float(output[0][0])

    def is_speech(self, frame_float: np.ndarray) -> bool:
        return self.process_frame(frame_float) >= self._threshold

    def reset(self):
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._context = np.zeros(self.CONTEXT_SIZE, dtype=np.float32)


@dataclass
class _SpeakerProfile:
    speaker_id: str
    embedding: np.ndarray
    sample_count: int = 1


class SpeakerRegistry:
    """Manages speaker voice profiles with cosine similarity matching."""

    def __init__(self, threshold: float | None = None, max_profiles: int | None = None):
        self._threshold = threshold if threshold is not None else settings.SPEAKER_SIMILARITY_THRESHOLD
        configured_limit = max_profiles if max_profiles is not None else settings.MAX_SPEAKER_PROFILES_PER_TRACK
        self._max_profiles = max(1, configured_limit)
        self._profiles: list[_SpeakerProfile] = []
        self._next_id = 1

    @property
    def profile_count(self) -> int:
        return len(self._profiles)

    def enroll(self, speaker_id: str, embedding: np.ndarray):
        """Pre-register a speaker with a known ID."""
        norm = np.linalg.norm(embedding)
        if norm > 0:
            embedding = embedding / norm
        self._profiles.append(_SpeakerProfile(speaker_id=speaker_id, embedding=embedding))

    def match(self, embedding: np.ndarray) -> tuple[str | None, float]:
        """Find best matching speaker. Returns (speaker_id, similarity) or (None, 0)."""
        best_profile, best_sim = self._best_profile(embedding)

        if best_profile and best_sim >= self._threshold:
            return best_profile.speaker_id, best_sim
        return None, best_sim

    def match_or_create(self, embedding: np.ndarray, allow_create: bool = True) -> str:
        """Match to existing speaker or auto-enroll as new. Returns speaker_id."""
        speaker_id, sim = self.match(embedding)

        if speaker_id:
            self._update_profile(speaker_id, embedding)
            return speaker_id

        best_profile, _ = self._best_profile(embedding)
        if best_profile and (not allow_create or len(self._profiles) >= self._max_profiles):
            reason = "short segment" if not allow_create else "profile limit"
            logger.info(
                "Reusing closest speaker %s for %s (similarity %.3f)",
                best_profile.speaker_id,
                reason,
                sim,
            )
            return best_profile.speaker_id

        # New speaker
        while any(profile.speaker_id == f"auto_{self._next_id}" for profile in self._profiles):
            self._next_id += 1
        new_id = f"auto_{self._next_id}"
        self._next_id += 1
        self.enroll(new_id, embedding)
        logger.info(f"New speaker enrolled: {new_id} (best sim was {sim:.3f})")
        return new_id

    def _best_profile(self, embedding: np.ndarray) -> tuple[_SpeakerProfile | None, float]:
        if not self._profiles:
            return None, 0.0
        best_profile = max(
            self._profiles,
            key=lambda profile: float(np.dot(embedding, profile.embedding)),
        )
        return best_profile, float(np.dot(embedding, best_profile.embedding))

    def _update_profile(self, speaker_id: str, embedding: np.ndarray) -> None:
        for profile in self._profiles:
            if profile.speaker_id != speaker_id:
                continue
            sample_count = profile.sample_count
            profile.embedding = (profile.embedding * sample_count + embedding) / (sample_count + 1)
            norm = np.linalg.norm(profile.embedding)
            if norm > 0:
                profile.embedding = profile.embedding / norm
            profile.sample_count += 1
            return

    def reset(self):
        self._profiles.clear()
        self._next_id = 1


@dataclass
class DiarizedSegment:
    speaker_id: str
    pcm_bytes: bytes


class SpeakerDiarizer:
    """Segments audio into per-speaker turns using VAD + embeddings.

    feed_audio(pcm16_bytes) → list of completed (speaker_id, pcm_bytes) segments.
    Turn boundaries: silence ≥ SILENCE_GAP_MS or max segment MAX_SEGMENT_MS.
    Minimum segment MIN_SEGMENT_MS to avoid noise-triggered embeddings.
    """

    def __init__(self, registry: SpeakerRegistry | None = None):
        self._vad = VoiceActivityDetector()
        self._registry = registry or SpeakerRegistry()
        self._sample_rate = 16000
        self._bytes_per_sample = 2  # PCM16

        # Config
        self._silence_gap_samples = int(settings.SILENCE_GAP_MS * self._sample_rate / 1000)
        self._max_segment_samples = int(settings.MAX_SEGMENT_MS * self._sample_rate / 1000)
        self._min_segment_samples = int(settings.MIN_SEGMENT_MS * self._sample_rate / 1000)
        self._min_new_speaker_samples = int(settings.MIN_NEW_SPEAKER_MS * self._sample_rate / 1000)
        self._coherence_window_samples = int(
            settings.SPEAKER_COHERENCE_WINDOW_MS * self._sample_rate / 1000
        )
        self._coherence_threshold = settings.SPEAKER_COHERENCE_THRESHOLD

        # State
        self._pending_audio = bytearray()  # unprocessed PCM16 bytes
        self._current_segment = bytearray()  # current speech segment PCM16
        self._silence_count = 0  # consecutive silence samples
        self._in_speech = False

    @property
    def registry(self) -> SpeakerRegistry:
        return self._registry

    def feed_audio(self, pcm16_bytes: bytes) -> list[DiarizedSegment]:
        """Process incoming PCM16 audio. Returns completed segments."""
        self._pending_audio.extend(pcm16_bytes)
        completed: list[DiarizedSegment] = []

        frame_bytes = VoiceActivityDetector.FRAME_SAMPLES * self._bytes_per_sample
        while len(self._pending_audio) >= frame_bytes:
            frame_pcm = bytes(self._pending_audio[:frame_bytes])
            self._pending_audio = self._pending_audio[frame_bytes:]

            frame_float = np.frombuffer(frame_pcm, dtype=np.int16).astype(np.float32) / 32768.0
            speech_prob = self._vad.process_frame(frame_float)
            is_speech = speech_prob >= self._vad._threshold

            # Diagnostic: track RMS + max VAD prob per ~10s window
            if not hasattr(self, "_diag_frames"):
                self._diag_frames = 0
                self._diag_max_prob = 0.0
                self._diag_max_rms = 0.0
            self._diag_frames += 1
            rms = float(np.sqrt(np.mean(frame_float ** 2)))
            if rms > self._diag_max_rms:
                self._diag_max_rms = rms
            if speech_prob > self._diag_max_prob:
                self._diag_max_prob = speech_prob
            # 512 samples/frame @ 16kHz = 32ms; 312 frames ≈ 10s
            if self._diag_frames >= 312:
                logger.info(
                    f"VAD diag (10s window): max_rms={self._diag_max_rms:.4f} "
                    f"max_speech_prob={self._diag_max_prob:.3f} "
                    f"threshold={self._vad._threshold}"
                )
                self._diag_frames = 0
                self._diag_max_prob = 0.0
                self._diag_max_rms = 0.0

            if is_speech:
                self._current_segment.extend(frame_pcm)
                self._silence_count = 0
                self._in_speech = True

                # Check max segment length
                segment_samples = len(self._current_segment) // self._bytes_per_sample
                if segment_samples >= self._max_segment_samples:
                    completed.extend(self._finalize_segment())
            else:
                if self._in_speech:
                    self._silence_count += VoiceActivityDetector.FRAME_SAMPLES
                    # Still append silence to segment (natural pauses)
                    self._current_segment.extend(frame_pcm)

                    if self._silence_count >= self._silence_gap_samples:
                        # Turn boundary detected
                        completed.extend(self._finalize_segment())

        return completed

    def flush(self) -> DiarizedSegment | None:
        """Legacy single-segment flush; production callers use flush_segments."""
        segments = self.flush_segments()
        # ponytail: legacy API cannot represent split tails; remove after all external callers migrate.
        return segments[0] if segments else None

    def flush_segments(self) -> list[DiarizedSegment]:
        """Finalize every remaining buffered segment in order."""
        return self._finalize_segment() if self._current_segment else []

    def reset(self):
        """Clear all state."""
        self._vad.reset()
        self._pending_audio.clear()
        self._current_segment.clear()
        self._silence_count = 0
        self._in_speech = False

    def _finalize_segment(self) -> list[DiarizedSegment]:
        """Extract embeddings, split internally mixed audio, and assign speakers."""
        pcm_bytes = bytes(self._current_segment)
        self._current_segment.clear()
        self._silence_count = 0
        self._in_speech = False

        segment_samples = len(pcm_bytes) // self._bytes_per_sample
        if segment_samples < self._min_segment_samples:
            return []

        pcm_float = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        try:
            full_embedding = _extract_embedding(pcm_float, self._sample_rate)
        except Exception as e:
            logger.warning(f"Embedding extraction failed: {e}")
            return [DiarizedSegment(speaker_id="auto_unknown", pcm_bytes=pcm_bytes)]

        allow_create = segment_samples >= self._min_new_speaker_samples

        def assign_full() -> list[DiarizedSegment]:
            speaker_id = self._registry.match_or_create(
                full_embedding,
                allow_create=allow_create,
            )
            return [DiarizedSegment(speaker_id=speaker_id, pcm_bytes=pcm_bytes)]

        matched_id, _ = self._registry.match(full_embedding)
        if matched_id or not allow_create or self._registry.profile_count == 0:
            return assign_full()

        window_bytes = self._coherence_window_samples * self._bytes_per_sample
        windows = [
            pcm_bytes[start:start + window_bytes]
            for start in range(0, len(pcm_bytes), window_bytes)
        ]
        min_bytes = self._min_segment_samples * self._bytes_per_sample
        if len(windows) > 1 and len(windows[-1]) < min_bytes:
            tail = windows.pop()
            windows[-1] += tail
        if len(windows) < 2:
            return assign_full()

        try:
            window_embeddings = [
                _extract_embedding(
                    np.frombuffer(window, dtype=np.int16).astype(np.float32) / 32768.0,
                    self._sample_rate,
                )
                for window in windows
            ]
        except Exception as e:
            logger.warning(f"Coherence embedding extraction failed: {e}")
            return assign_full()

        group_ends = [
            index + 1
            for index in range(len(window_embeddings) - 1)
            if float(np.dot(window_embeddings[index], window_embeddings[index + 1]))
            < self._coherence_threshold
        ]
        if not group_ends:
            return assign_full()

        groups: list[tuple[bytes, np.ndarray]] = []
        group_start = 0
        for group_end in [*group_ends, len(windows)]:
            group_pcm = b"".join(windows[group_start:group_end])
            group_embedding = np.mean(window_embeddings[group_start:group_end], axis=0)
            norm = np.linalg.norm(group_embedding)
            if norm == 0:
                speaker_id = self._registry.match_or_create(
                    full_embedding,
                    allow_create=False,
                )
                return [DiarizedSegment(speaker_id=speaker_id, pcm_bytes=pcm_bytes)]
            groups.append((group_pcm, group_embedding / norm))
            group_start = group_end

        segments: list[DiarizedSegment] = []
        for group_pcm, group_embedding in groups:
            speaker_id = self._registry.match_or_create(group_embedding, allow_create=False)
            if segments and segments[-1].speaker_id == speaker_id:
                segments[-1].pcm_bytes += group_pcm
            else:
                segments.append(DiarizedSegment(speaker_id=speaker_id, pcm_bytes=group_pcm))
        return segments
