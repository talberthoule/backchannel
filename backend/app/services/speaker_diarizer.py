"""Speaker diarization using Silero VAD + WeSpeaker voice embeddings.

Pipeline: PCM16 audio → VAD (speech detection) → speaker embedding → match/enroll.
"""

import logging
import math
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


def _vad_session_options() -> ort.SessionOptions:
    """Single-threaded: the VAD has nothing worth parallelizing.

    Silero VAD is an LSTM over one 512-sample frame. ORT's default pool of one
    thread per core costs 5x the CPU (0.53ms vs 0.11ms per frame on 28 cores)
    and buys roughly 9% of wall time back, which is not a trade worth making
    for something that runs 31 times a second per track (ALP-289).
    """
    options = ort.SessionOptions()
    options.intra_op_num_threads = settings.DIARIZER_VAD_ONNX_THREADS
    return options


def _embed_session_options() -> ort.SessionOptions:
    """A small bounded pool for the embedding model.

    ResNet152 does parallelize, unlike the VAD, but nowhere near one thread
    per core: on 28 cores the default drew 19 cores' worth of CPU for a single
    5s segment to go 4.4x faster than one thread - 23% parallel efficiency, so
    77% of that CPU was pool overhead rather than arithmetic. Bounding the
    pool cuts that CPU about 4x and does
    cost wall time - a 5s segment goes 158ms to 326ms, five minutes of audio
    14.3s to 22.1s. Live that is invisible (7% of realtime), but a foreground
    audio import on a many-core box is around 1.5x slower.

    Spinning is off because segments arrive seconds apart and ORT keeps the
    pool hot in between, charging that spin to whatever runs next - the VAD
    (ALP-289).
    """
    options = ort.SessionOptions()
    options.intra_op_num_threads = settings.DIARIZER_EMBED_ONNX_THREADS
    if not settings.DIARIZER_EMBED_ONNX_SPIN:
        options.add_session_config_entry("session.intra_op.allow_spinning", "0")
    return options


def _get_vad_model() -> ort.InferenceSession:
    global _vad_session
    if _vad_session is None:
        path = os.path.join(MODELS_DIR, "silero_vad.onnx")
        _vad_session = ort.InferenceSession(
            path, _vad_session_options(), providers=["CPUExecutionProvider"]
        )
        logger.info(
            f"Loaded Silero VAD model (intra-op threads: {settings.DIARIZER_VAD_ONNX_THREADS})"
        )
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
        _embed_session = ort.InferenceSession(
            path, _embed_session_options(), providers=["CPUExecutionProvider"]
        )
        logger.info(
            f"Loaded speaker embedding model: {os.path.basename(path)} "
            f"(intra-op threads: {settings.DIARIZER_EMBED_ONNX_THREADS})"
        )
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
    fallback_for_unmatched: bool = True


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

    @property
    def fallback_profile_count(self) -> int:
        return sum(profile.fallback_for_unmatched for profile in self._profiles)

    def enroll(
        self,
        speaker_id: str,
        embedding: np.ndarray,
        fallback_for_unmatched: bool = True,
    ):
        """Pre-register a speaker with a known ID."""
        norm = np.linalg.norm(embedding)
        if norm > 0:
            embedding = embedding / norm
        self._profiles.append(
            _SpeakerProfile(
                speaker_id=speaker_id,
                embedding=embedding,
                fallback_for_unmatched=fallback_for_unmatched,
            )
        )

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

        best_fallback, fallback_sim = self._best_profile(embedding, fallback_only=True)
        if not allow_create:
            if not best_fallback:
                logger.info("Deferring short segment without an eligible speaker profile")
                return "auto_unknown"
            logger.info(
                "Reusing closest speaker %s for %s (similarity %.3f)",
                best_fallback.speaker_id,
                "short segment",
                fallback_sim,
            )
            return best_fallback.speaker_id

        if best_fallback and self.fallback_profile_count >= self._max_profiles:
            logger.info(
                "Reusing closest speaker %s for %s (similarity %.3f)",
                best_fallback.speaker_id,
                "profile limit",
                fallback_sim,
            )
            return best_fallback.speaker_id

        # New speaker
        while any(profile.speaker_id == f"auto_{self._next_id}" for profile in self._profiles):
            self._next_id += 1
        new_id = f"auto_{self._next_id}"
        self._next_id += 1
        self.enroll(new_id, embedding)
        logger.info(f"New speaker enrolled: {new_id} (best sim was {sim:.3f})")
        return new_id

    def _best_profile(
        self,
        embedding: np.ndarray,
        fallback_only: bool = False,
    ) -> tuple[_SpeakerProfile | None, float]:
        profiles = [
            profile
            for profile in self._profiles
            if profile.embedding.shape == embedding.shape
            and (not fallback_only or profile.fallback_for_unmatched)
        ]
        if not profiles:
            return None, 0.0
        best_profile = max(
            profiles,
            key=lambda profile: float(np.dot(embedding, profile.embedding)),
        )
        return best_profile, float(np.dot(embedding, best_profile.embedding))

    def _update_profile(self, speaker_id: str, embedding: np.ndarray) -> None:
        for profile in self._profiles:
            if profile.speaker_id != speaker_id:
                continue
            if not profile.fallback_for_unmatched:
                return
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
    start_sample: int | None = None


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
        self._processed_samples = 0
        self._current_segment_start_sample: int | None = None

        # VAD diagnostics, rolled over every ~10s window in feed_audio.
        # _diag_max_energy holds a sum of squares, not an RMS; feed_audio
        # converts once per window.
        self._diag_frames = 0
        self._diag_max_prob = 0.0
        self._diag_max_energy = 0.0

    @property
    def registry(self) -> SpeakerRegistry:
        return self._registry

    def feed_audio(self, pcm16_bytes: bytes) -> list[DiarizedSegment]:
        """Process incoming PCM16 audio. Returns completed segments."""
        self._pending_audio.extend(pcm16_bytes)
        completed: list[DiarizedSegment] = []

        frame_bytes = VoiceActivityDetector.FRAME_SAMPLES * self._bytes_per_sample
        while len(self._pending_audio) >= frame_bytes:
            frame_start_sample = self._processed_samples
            frame_pcm = bytes(self._pending_audio[:frame_bytes])
            # In place: rebinding to a slice copied the whole remaining buffer
            # once per frame, which grows with the incoming chunk size
            # (109us vs 16us per 1000ms chunk) for no benefit (ALP-290).
            del self._pending_audio[:frame_bytes]

            frame_float = np.frombuffer(frame_pcm, dtype=np.int16).astype(np.float32) / 32768.0
            speech_prob = self._vad.process_frame(frame_float)
            is_speech = speech_prob >= self._vad._threshold

            # Diagnostic: loudest RMS + max VAD prob per ~10s window. The line
            # stays - it is the quickest way to tell a dead mic from a quiet
            # room - and so does RMS, which a single click or DC glitch cannot
            # fool the way a peak can. Only the arithmetic changed: every
            # frame is the same length, so tracking the largest sum of squares
            # and taking one square root per window is exactly the old
            # max-of-RMS at roughly a ninth of the cost (0.5us vs 4.8us per
            # frame): np.dot beats sqrt(mean(f ** 2)), which allocated a
            # squared copy of every frame to report one number every 312
            # (ALP-290).
            self._diag_frames += 1
            energy = float(np.dot(frame_float, frame_float))
            if energy > self._diag_max_energy:
                self._diag_max_energy = energy
            if speech_prob > self._diag_max_prob:
                self._diag_max_prob = speech_prob
            # 512 samples/frame @ 16kHz = 32ms; 312 frames ~= 10s
            if self._diag_frames >= 312:
                max_rms = math.sqrt(self._diag_max_energy / VoiceActivityDetector.FRAME_SAMPLES)
                logger.info(
                    f"VAD diag (10s window): max_rms={max_rms:.4f} "
                    f"max_speech_prob={self._diag_max_prob:.3f} "
                    f"threshold={self._vad._threshold}"
                )
                self._diag_frames = 0
                self._diag_max_prob = 0.0
                self._diag_max_energy = 0.0

            if is_speech:
                if not self._in_speech:
                    self._current_segment_start_sample = frame_start_sample
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

            self._processed_samples += VoiceActivityDetector.FRAME_SAMPLES

        return completed

    def flush(self) -> DiarizedSegment | None:
        """Legacy single-segment flush; production callers use flush_segments."""
        segments = self.flush_segments()
        # ponytail: legacy API loses split speaker attribution; remove after external callers migrate.
        return (
            DiarizedSegment(segments[0].speaker_id, b"".join(segment.pcm_bytes for segment in segments))
            if segments
            else None
        )

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
        self._processed_samples = 0
        self._current_segment_start_sample = None

    def _finalize_segment(self) -> list[DiarizedSegment]:
        """Extract embeddings, split internally mixed audio, and assign speakers."""
        pcm_bytes = bytes(self._current_segment)
        start_sample = self._current_segment_start_sample
        self._current_segment.clear()
        self._silence_count = 0
        self._in_speech = False
        self._current_segment_start_sample = None

        segment_samples = len(pcm_bytes) // self._bytes_per_sample
        if segment_samples < self._min_segment_samples:
            return []

        pcm_float = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        try:
            full_embedding = _extract_embedding(pcm_float, self._sample_rate)
        except Exception as e:
            logger.warning(f"Embedding extraction failed: {e}")
            return [DiarizedSegment("auto_unknown", pcm_bytes, start_sample)]

        allow_create = segment_samples >= self._min_new_speaker_samples

        def assign_full() -> list[DiarizedSegment]:
            speaker_id = self._registry.match_or_create(
                full_embedding,
                allow_create=allow_create,
            )
            if speaker_id == "auto_unknown":
                return []
            return [DiarizedSegment(speaker_id, pcm_bytes, start_sample)]

        matched_id, _ = self._registry.match(full_embedding)
        if matched_id or not allow_create or self._registry.fallback_profile_count == 0:
            return assign_full()

        try:
            groups = self._coherence_groups(pcm_bytes, full_embedding)
        except Exception as e:
            logger.warning(f"Coherence embedding extraction failed: {e}")
            return assign_full()
        if groups is None:
            return assign_full()

        return self._assign_coherence_groups(groups, start_sample)

    def _coherence_groups(
        self,
        pcm_bytes: bytes,
        full_embedding: np.ndarray,
    ) -> list[tuple[bytes, np.ndarray]] | None:
        """Return adjacent coherence groups, or None when no split is justified."""
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
            return None

        window_embeddings = [
            _extract_embedding(
                np.frombuffer(window, dtype=np.int16).astype(np.float32) / 32768.0,
                self._sample_rate,
            )
            for window in windows
        ]

        group_ends = [
            index + 1
            for index in range(len(window_embeddings) - 1)
            if float(np.dot(window_embeddings[index], window_embeddings[index + 1]))
            < self._coherence_threshold
        ]
        if not group_ends:
            return None

        groups: list[tuple[bytes, np.ndarray]] = []
        group_start = 0
        for group_end in [*group_ends, len(windows)]:
            group_pcm = b"".join(windows[group_start:group_end])
            group_embedding = np.mean(window_embeddings[group_start:group_end], axis=0)
            norm = np.linalg.norm(group_embedding)
            if norm == 0:
                return [(pcm_bytes, full_embedding)]
            groups.append((group_pcm, group_embedding / norm))
            group_start = group_end
        return groups

    def _assign_coherence_groups(
        self,
        groups: list[tuple[bytes, np.ndarray]],
        start_sample: int | None = None,
    ) -> list[DiarizedSegment]:
        """Assign non-enrolling speaker IDs and merge adjacent identical groups."""
        segments: list[DiarizedSegment] = []
        group_start = start_sample
        for group_pcm, group_embedding in groups:
            speaker_id = self._registry.match_or_create(group_embedding, allow_create=False)
            if segments and segments[-1].speaker_id == speaker_id:
                segments[-1].pcm_bytes += group_pcm
            else:
                segments.append(DiarizedSegment(speaker_id, group_pcm, group_start))
            if group_start is not None:
                group_start += len(group_pcm) // self._bytes_per_sample
        return segments
