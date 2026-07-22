"""NeMo Sortformer diarizer adapter.

The app uses PCM16 16 kHz mono audio internally. Sortformer expects a file-like
audio input, so this adapter batches live PCM into short windows and converts
Sortformer turns back into the same DiarizedSegment shape used by the
lightweight diarizer.
"""

import logging
import os
import tempfile
from dataclasses import dataclass
from typing import Any, Callable, Iterable

import numpy as np

from app.config import settings
from app.services.audio_utils import make_wav_header
from app.services.diarization_diagnostics import (
    SORTFORMER_MODEL_ID,
    _load_sortformer_model,
    _prepare_model,
    _run_diarization,
)
from app.services.speaker_diarizer import DiarizedSegment, SpeakerRegistry, extract_speaker_embedding

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SortformerTurn:
    start_seconds: float
    end_seconds: float
    label: str


class SortformerDiarizer:
    """Batch-oriented live adapter for the NeMo Sortformer diarizer."""

    def __init__(
        self,
        model_id: str = SORTFORMER_MODEL_ID,
        sample_rate: int = 16000,
        window_ms: int | None = None,
        registry: SpeakerRegistry | None = None,
        embedding_extractor: Callable[[np.ndarray, int], np.ndarray] = extract_speaker_embedding,
    ):
        self._model_id = model_id
        self._sample_rate = sample_rate
        self._bytes_per_sample = 2
        self._window_bytes = int((window_ms or settings.SORTFORMER_WINDOW_MS) * sample_rate / 1000) * self._bytes_per_sample
        self._min_segment_bytes = int(settings.MIN_SEGMENT_MS * sample_rate / 1000) * self._bytes_per_sample
        self._min_new_speaker_bytes = (
            int(settings.MIN_NEW_SPEAKER_MS * sample_rate / 1000) * self._bytes_per_sample
        )
        self._pending_audio = bytearray()
        self._speaker_map: dict[str, str] = {}
        self._next_speaker_id = 1
        self._registry = registry or SpeakerRegistry()
        self._embedding_extractor = embedding_extractor
        self._model: Any | None = None

    def feed_audio(self, pcm16_bytes: bytes) -> list[DiarizedSegment]:
        self._pending_audio.extend(pcm16_bytes)
        segments: list[DiarizedSegment] = []
        while len(self._pending_audio) >= self._window_bytes:
            window = bytes(self._pending_audio[:self._window_bytes])
            self._pending_audio = self._pending_audio[self._window_bytes:]
            segments.extend(self._process_pcm_window(window))
        return segments

    def flush(self) -> DiarizedSegment | None:
        segments = self.flush_segments()
        return segments[0] if segments else None

    def flush_segments(self) -> list[DiarizedSegment]:
        if not self._pending_audio:
            return []
        window = bytes(self._pending_audio)
        self._pending_audio.clear()
        return self._process_pcm_window(window)

    def reset(self):
        self._pending_audio.clear()
        self._speaker_map.clear()
        self._next_speaker_id = 1

    def _process_pcm_window(self, pcm_bytes: bytes) -> list[DiarizedSegment]:
        try:
            result = self._run_sortformer(pcm_bytes)
            turns = extract_sortformer_turns(result)
        except Exception as exc:
            logger.warning(f"Sortformer diarization failed; dropping window: {exc}")
            return []

        segments: list[DiarizedSegment] = []
        for turn in turns:
            start = max(0, int(turn.start_seconds * self._sample_rate) * self._bytes_per_sample)
            end = max(start, int(turn.end_seconds * self._sample_rate) * self._bytes_per_sample)
            segment_pcm = pcm_bytes[start:end]
            if len(segment_pcm) < self._min_segment_bytes:
                continue
            speaker_id = self._speaker_id_for_segment(turn.label, segment_pcm)
            if speaker_id != "auto_unknown":
                segments.append(DiarizedSegment(speaker_id=speaker_id, pcm_bytes=segment_pcm))
        return segments

    def _run_sortformer(self, pcm_bytes: bytes) -> Any:
        if self._model is None:
            self._model = _load_sortformer_model(self._model_id)
            _prepare_model(self._model, _preferred_device())

        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp.write(make_wav_header(pcm_bytes))
                tmp.write(pcm_bytes)
                tmp_path = tmp.name
            return _run_diarization(self._model, tmp_path)
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def _speaker_id_for_label(self, label: str) -> str:
        if label not in self._speaker_map:
            self._speaker_map[label] = f"auto_{self._next_speaker_id}"
            self._next_speaker_id += 1
        return self._speaker_map[label]

    def _speaker_id_for_segment(self, label: str, pcm_bytes: bytes) -> str:
        try:
            pcm_float = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
            embedding = self._embedding_extractor(pcm_float, self._sample_rate)
            return self._registry.match_or_create(
                embedding,
                allow_create=len(pcm_bytes) >= self._min_new_speaker_bytes,
            )
        except Exception as exc:
            logger.warning(f"Sortformer speaker embedding failed; falling back to local label: {exc}")
            if len(pcm_bytes) < self._min_new_speaker_bytes and self._registry.profile_count == 0:
                return "auto_unknown"
            return self._speaker_id_for_label(label)


def extract_sortformer_turns(result: Any) -> list[SortformerTurn]:
    turns = sorted(_iter_sortformer_turns(result), key=lambda turn: (turn.start_seconds, turn.end_seconds))
    return [turn for turn in turns if turn.end_seconds > turn.start_seconds]


def _iter_sortformer_turns(result: Any) -> Iterable[SortformerTurn]:
    if result is None:
        return

    if hasattr(result, "itertracks"):
        for segment, _, label in result.itertracks(yield_label=True):
            start = float(getattr(segment, "start"))
            end = float(getattr(segment, "end"))
            yield SortformerTurn(start, end, str(label))
        return

    if isinstance(result, dict):
        direct = _turn_from_dict(result)
        if direct:
            yield direct
            return
        for value in result.values():
            yield from _iter_sortformer_turns(value)
        return

    if isinstance(result, str):
        turn = _turn_from_line(result)
        if turn:
            yield turn
        return

    if isinstance(result, Iterable):
        for item in result:
            yield from _iter_sortformer_turns(item)


def _turn_from_dict(value: dict[str, Any]) -> SortformerTurn | None:
    start = value.get("start") or value.get("start_time") or value.get("start_seconds")
    end = value.get("end") or value.get("end_time") or value.get("end_seconds")
    duration = value.get("duration")
    label = value.get("speaker") or value.get("label") or value.get("speaker_id")
    if start is None or label is None:
        return None
    if end is None and duration is not None:
        end = float(start) + float(duration)
    if end is None:
        return None
    return SortformerTurn(float(start), float(end), str(label))


def _turn_from_line(line: str) -> SortformerTurn | None:
    parts = line.strip().split()
    if len(parts) >= 8 and parts[0].upper() == "SPEAKER":
        start = float(parts[3])
        end = start + float(parts[4])
        return SortformerTurn(start, end, parts[7])

    if len(parts) >= 3:
        try:
            start = float(parts[0])
            end = float(parts[1])
        except ValueError:
            return None
        return SortformerTurn(start, end, parts[2])

    return None


def _preferred_device() -> str:
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"
