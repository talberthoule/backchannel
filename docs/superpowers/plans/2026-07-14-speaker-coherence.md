# Adaptive Speaker Coherence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent internally mixed long VAD segments from enrolling phantom speakers while preserving the released identity threshold, profile updates, and every PCM byte.

**Architecture:** Keep the current full-segment embedding as the fast identity probe. Only a long unmatched segment with an existing profile is divided into 3-second coherence windows; low adjacent similarity creates groups that are forced onto existing profiles using normalized means of the already-computed window embeddings. Production callers receive ordered lists through the existing batch-flush seam.

**Tech Stack:** Python 3.12, stdlib `unittest`, NumPy, existing Silero VAD and WeSpeaker ONNX runtime, Docker.

## Global Constraints

- Keep `SPEAKER_SIMILARITY_THRESHOLD=0.68`, `MIN_NEW_SPEAKER_MS=4000`, `SILENCE_GAP_MS=600`, `MAX_SEGMENT_MS=15000`, and `MAX_SPEAKER_PROFILES_PER_TRACK=4` unchanged.
- Add only `SPEAKER_COHERENCE_WINDOW_MS=3000` and `SPEAKER_COHERENCE_THRESHOLD=0.40`; the coherence threshold must remain independent from identity matching.
- Run coherence inference only for long unmatched segments when at least one profile already exists and at least two windows can be formed.
- A successful `SpeakerRegistry.match()` probe must pass the same full embedding through `match_or_create()` so the existing centroid update still occurs.
- Mixed-segment groups use the normalized mean of their already-computed window embeddings, call `match_or_create(..., allow_create=False)`, and never enroll a profile.
- Concatenating output PCM in order must equal input PCM byte-for-byte; merge adjacent groups assigned to the same speaker.
- Preserve split-track-only local mic binding, mic-only diarization, zero/multiple-user fallback, capture lifecycle behavior, and the optional Sortformer path.
- Add no dependency, exemplar bank, persistent enrollment, cross-track reconciliation, boundary search, or installer change.

---

### Task 1: Add Mixed-Turn Coherence to the Lightweight Diarizer

**Files:**
- Create: `backend/tests/test_speaker_diarizer.py`
- Modify: `backend/app/config.py:34-42`
- Modify: `backend/app/services/speaker_diarizer.py:303-423`
- Modify: `backend/scripts/diarizer_ab.py:24-92`

**Interfaces:**
- Consumes: `SpeakerRegistry.match(embedding) -> tuple[str | None, float]`, `SpeakerRegistry.match_or_create(embedding, allow_create=True) -> str`, and `flush_diarizer_segments(diarizer) -> list`.
- Produces: `SpeakerDiarizer.flush_segments() -> list[DiarizedSegment]`; `_finalize_segment() -> list[DiarizedSegment]`; `feed_audio()` extends completed output with every finalized piece.

- [ ] **Step 1: Write the failing diarizer tests**

Create `backend/tests/test_speaker_diarizer.py` with deterministic embeddings and no ONNX/model dependency:

```python
import unittest
from unittest.mock import Mock, patch

import numpy as np

from app.services.speaker_diarizer import (
    DiarizedSegment,
    SpeakerDiarizer,
    SpeakerRegistry,
    VoiceActivityDetector,
)


def embedding(*values: float) -> np.ndarray:
    vector = np.array(values, dtype=np.float32)
    return vector / np.linalg.norm(vector)


def pcm(seconds: float, value: int = 1) -> bytes:
    return np.full(int(16000 * seconds), value, dtype=np.int16).tobytes()


def finalize(diarizer: SpeakerDiarizer, audio: bytes, embeddings: list[np.ndarray]):
    diarizer._current_segment.extend(audio)
    with patch(
        "app.services.speaker_diarizer._extract_embedding",
        side_effect=embeddings,
    ) as extract:
        return diarizer._finalize_segment(), extract


class SpeakerDiarizerTests(unittest.TestCase):
    def test_matched_fast_path_updates_profile_without_windows(self):
        registry = SpeakerRegistry(threshold=0.68)
        registry.enroll("auto_1", embedding(1.0, 0.0))
        diarizer = SpeakerDiarizer(registry=registry)

        segments, extract = finalize(
            diarizer,
            pcm(6.0),
            [embedding(0.9, 0.43589)],
        )

        self.assertEqual(["auto_1"], [segment.speaker_id for segment in segments])
        self.assertEqual(1, extract.call_count)
        self.assertEqual(2, registry._profiles[0].sample_count)

    def test_coherent_unmatched_turn_enrolls_one_new_profile(self):
        registry = SpeakerRegistry(threshold=0.68)
        registry.enroll("auto_1", embedding(1.0, 0.0))
        diarizer = SpeakerDiarizer(registry=registry)

        segments, extract = finalize(
            diarizer,
            pcm(6.0),
            [
                embedding(0.0, 1.0),
                embedding(0.10, 0.995),
                embedding(0.20, 0.980),
            ],
        )

        self.assertEqual(["auto_2"], [segment.speaker_id for segment in segments])
        self.assertEqual(2, registry.profile_count)
        self.assertEqual(3, extract.call_count)

    def test_mixed_turn_splits_without_enrollment_or_pcm_loss(self):
        registry = SpeakerRegistry(threshold=0.90)
        registry.enroll("auto_1", embedding(1.0, 0.0))
        registry.enroll("auto_2", embedding(0.0, 1.0))
        diarizer = SpeakerDiarizer(registry=registry)
        audio = pcm(3.0, 1) + pcm(3.0, 2)

        segments, _ = finalize(
            diarizer,
            audio,
            [embedding(1.0, 1.0), embedding(1.0, 0.0), embedding(0.0, 1.0)],
        )

        self.assertEqual(["auto_1", "auto_2"], [segment.speaker_id for segment in segments])
        self.assertEqual(audio, b"".join(segment.pcm_bytes for segment in segments))
        self.assertEqual(2, registry.profile_count)

    def test_split_groups_use_normalized_window_means(self):
        class RecordingRegistry(SpeakerRegistry):
            def __init__(self):
                super().__init__(threshold=0.90)
                self.forced: list[np.ndarray] = []

            def match_or_create(self, value, allow_create=True):
                if not allow_create:
                    self.forced.append(value.copy())
                return super().match_or_create(value, allow_create=allow_create)

        registry = RecordingRegistry()
        registry.enroll("auto_1", embedding(1.0, 0.0))
        registry.enroll("auto_2", embedding(0.0, 1.0))
        diarizer = SpeakerDiarizer(registry=registry)
        windows = [
            embedding(1.0, 0.1),
            embedding(1.0, 0.2),
            embedding(0.1, 1.0),
            embedding(0.2, 1.0),
        ]

        segments, _ = finalize(
            diarizer,
            pcm(12.0),
            [embedding(1.0, 1.0), *windows],
        )

        expected = []
        for group in (windows[:2], windows[2:]):
            mean = np.mean(group, axis=0)
            expected.append(mean / np.linalg.norm(mean))
        self.assertEqual(["auto_1", "auto_2"], [segment.speaker_id for segment in segments])
        self.assertEqual(2, len(registry.forced))
        np.testing.assert_allclose(expected, registry.forced, atol=1e-6)

    def test_short_tail_is_merged_into_previous_window(self):
        registry = SpeakerRegistry(threshold=0.90)
        registry.enroll("auto_1", embedding(1.0, 0.0))
        diarizer = SpeakerDiarizer(registry=registry)
        lengths: list[int] = []

        def extract(samples, sample_rate):
            self.assertEqual(16000, sample_rate)
            lengths.append(len(samples))
            return embedding(0.0, 1.0) if len(lengths) == 1 else embedding(1.0, 0.0)

        diarizer._current_segment.extend(pcm(6.5))
        with patch("app.services.speaker_diarizer._extract_embedding", side_effect=extract):
            diarizer._finalize_segment()

        self.assertEqual([104000, 48000, 56000], lengths)

    def test_split_groups_assigned_to_same_profile_are_merged(self):
        registry = SpeakerRegistry(threshold=0.90)
        registry.enroll("auto_1", embedding(1.0, 0.0))
        diarizer = SpeakerDiarizer(registry=registry)
        audio = pcm(6.0)

        segments, _ = finalize(
            diarizer,
            audio,
            [embedding(0.0, 1.0), embedding(1.0, 0.0), embedding(-1.0, 0.0)],
        )

        self.assertEqual(1, len(segments))
        self.assertEqual("auto_1", segments[0].speaker_id)
        self.assertEqual(audio, segments[0].pcm_bytes)
        self.assertEqual(1, registry.profile_count)

    def test_first_and_short_segments_skip_window_analysis(self):
        cases = [
            (SpeakerRegistry(threshold=0.90), pcm(6.0)),
            (SpeakerRegistry(threshold=0.90), pcm(2.0)),
        ]
        cases[1][0].enroll("auto_1", embedding(1.0, 0.0))

        for registry, audio in cases:
            with self.subTest(profile_count=registry.profile_count, seconds=len(audio) / 32000):
                diarizer = SpeakerDiarizer(registry=registry)
                segments, extract = finalize(diarizer, audio, [embedding(0.0, 1.0)])
                self.assertEqual(1, len(segments))
                self.assertEqual(1, extract.call_count)

    def test_window_embedding_failure_falls_back_to_full_segment(self):
        registry = SpeakerRegistry(threshold=0.90)
        registry.enroll("auto_1", embedding(1.0, 0.0))
        diarizer = SpeakerDiarizer(registry=registry)
        audio = pcm(6.0)
        diarizer._current_segment.extend(audio)

        with patch(
            "app.services.speaker_diarizer._extract_embedding",
            side_effect=[embedding(0.0, 1.0), RuntimeError("window failed")],
        ):
            segments = diarizer._finalize_segment()

        self.assertEqual(1, len(segments))
        self.assertEqual(audio, segments[0].pcm_bytes)
        self.assertEqual(2, registry.profile_count)

    def test_mixed_first_appearance_waits_for_clean_turn_before_enrolling(self):
        registry = SpeakerRegistry(threshold=0.90)
        first = embedding(1.0, 0.0)
        second = embedding(0.0, 1.0)
        third = embedding(-1.0, 0.0)
        registry.enroll("auto_1", first)
        registry.enroll("auto_2", second)
        diarizer = SpeakerDiarizer(registry=registry)

        mixed, _ = finalize(
            diarizer,
            pcm(6.0),
            [embedding(1.0, 1.0), first, third],
        )
        self.assertEqual(2, registry.profile_count)
        self.assertEqual(["auto_1", "auto_2"], [segment.speaker_id for segment in mixed])

        clean, _ = finalize(
            diarizer,
            pcm(6.0),
            [third, third, third],
        )
        self.assertEqual(["auto_3"], [segment.speaker_id for segment in clean])
        self.assertEqual(3, registry.profile_count)

        later_mix, _ = finalize(
            diarizer,
            pcm(6.0),
            [embedding(-1.0, 1.0), second, third],
        )
        self.assertEqual(["auto_2", "auto_3"], [segment.speaker_id for segment in later_mix])
        self.assertEqual(3, registry.profile_count)

    def test_feed_audio_extends_all_finalized_pieces(self):
        diarizer = SpeakerDiarizer()
        diarizer._max_segment_samples = VoiceActivityDetector.FRAME_SAMPLES
        diarizer._vad.process_frame = Mock(return_value=1.0)
        pieces = [DiarizedSegment("auto_1", b"a"), DiarizedSegment("auto_2", b"b")]
        diarizer._finalize_segment = Mock(return_value=pieces)

        self.assertEqual(pieces, diarizer.feed_audio(bytes(VoiceActivityDetector.FRAME_SAMPLES * 2)))

    def test_flush_segments_returns_every_tail_piece(self):
        diarizer = SpeakerDiarizer()
        diarizer._current_segment.extend(pcm(1.0))
        pieces = [DiarizedSegment("auto_1", b"a"), DiarizedSegment("auto_2", b"b")]
        diarizer._finalize_segment = Mock(return_value=pieces)

        self.assertEqual(pieces, diarizer.flush_segments())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the focused test and verify RED**

Run from the repository root with the existing backend image:

```powershell
docker run --rm -e PYTHONDONTWRITEBYTECODE=1 `
  -v "${PWD}\backend\app:/app/app" `
  -v "${PWD}\backend\tests:/app/tests" `
  -w /app r2-master-rollout-backend:latest `
  python -m unittest tests.test_speaker_diarizer
```

Expected: FAIL because `_finalize_segment()` returns one segment, `feed_audio()` appends instead of extending, and `flush_segments()` does not exist.

- [ ] **Step 3: Add the two coherence settings**

Add beside the existing speaker settings in `backend/app/config.py`:

```python
    SPEAKER_COHERENCE_WINDOW_MS: int = 3000
    SPEAKER_COHERENCE_THRESHOLD: float = 0.40
```

- [ ] **Step 4: Implement the minimal list finalization and coherence path**

In `SpeakerDiarizer.__init__`, add:

```python
        self._coherence_window_samples = int(
            settings.SPEAKER_COHERENCE_WINDOW_MS * self._sample_rate / 1000
        )
        self._coherence_threshold = settings.SPEAKER_COHERENCE_THRESHOLD
```

Change both `feed_audio()` finalization sites to extend:

```python
                    completed.extend(self._finalize_segment())
```

Replace `flush()` and `_finalize_segment()` with:

```python
    def flush(self) -> DiarizedSegment | None:
        """Legacy single-segment flush; production callers use flush_segments."""
        segments = self.flush_segments()
        # ponytail: legacy API cannot represent split tails; remove after all external callers migrate.
        return segments[0] if segments else None

    def flush_segments(self) -> list[DiarizedSegment]:
        """Finalize every remaining buffered segment in order."""
        return self._finalize_segment() if self._current_segment else []

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

        segments: list[DiarizedSegment] = []
        group_start = 0
        for group_end in [*group_ends, len(windows)]:
            group_pcm = b"".join(windows[group_start:group_end])
            group_embedding = np.mean(window_embeddings[group_start:group_end], axis=0)
            norm = np.linalg.norm(group_embedding)
            if norm == 0:
                return assign_full()
            group_embedding = group_embedding / norm
            speaker_id = self._registry.match_or_create(group_embedding, allow_create=False)
            if segments and segments[-1].speaker_id == speaker_id:
                segments[-1].pcm_bytes += group_pcm
            else:
                segments.append(DiarizedSegment(speaker_id=speaker_id, pcm_bytes=group_pcm))
            group_start = group_end
        return segments
```

- [ ] **Step 5: Route the comparison script through the shared batch flush**

Add the existing helper import in `backend/scripts/diarizer_ab.py`:

```python
from app.services.diarizer_selection import flush_diarizer_segments  # noqa: E402
```

Replace its direct tail handling with:

```python
        segments.extend(flush_diarizer_segments(diarizer))
```

- [ ] **Step 6: Run focused tests and verify GREEN**

Run:

```powershell
docker run --rm -e PYTHONDONTWRITEBYTECODE=1 `
  -v "${PWD}\backend\app:/app/app" `
  -v "${PWD}\backend\tests:/app/tests" `
  -w /app r2-master-rollout-backend:latest `
  python -m unittest tests.test_speaker_diarizer tests.test_speaker_registry tests.test_diarizer_selection tests.test_audio_handler
```

Expected: PASS with no failure or error.

- [ ] **Step 7: Run the complete backend regression suite**

Run:

```powershell
docker run --rm -e PYTHONDONTWRITEBYTECODE=1 `
  -v "${PWD}\backend\app:/app/app" `
  -v "${PWD}\backend\tests:/app/tests" `
  -v "${PWD}\frontend:/frontend:ro" `
  -w /app r2-master-rollout-backend:latest `
  python -m unittest discover -s tests
```

Expected: all tests PASS; the released baseline was 200 tests before this file was added.

- [ ] **Step 8: Replay the stored Recorder fixture at the released threshold**

Run with the feature worktree mounted over the existing image and the running validation container's data volume:

```powershell
docker run --rm --volumes-from r2-master-rollout-backend-1 `
  -v "${PWD}\backend\app:/app/app" `
  -v "${PWD}\backend\scripts:/app/scripts" `
  -w /app r2-master-rollout-backend:latest `
  python scripts/diarizer_ab.py `
  /app/data/audio/3eb9b07e-9e28-45f0-9cda-a3359ae59f59/segment_1.wav `
  --threshold 0.68
```

Expected for the preferred ResNet152 model: exactly two unique speaker IDs; the two previously false-new mixed segments create no additional profile. Record segment/profile counts in ALP-77.

- [ ] **Step 9: Commit the verified diarization change**

```powershell
git add -- backend/app/config.py backend/app/services/speaker_diarizer.py backend/scripts/diarizer_ab.py backend/tests/test_speaker_diarizer.py
git diff --cached --check
git commit -m "fix: split internally mixed diarization turns"
```

Expected: one focused implementation commit with no frontend, database, dependency, Sortformer, or installer changes.
