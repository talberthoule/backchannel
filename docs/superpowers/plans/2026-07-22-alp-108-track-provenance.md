# ALP-108 Track Provenance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve aligned mic/system recordings for split-track calls and use them to retain local and remote speaker identity during post-call retranscription.

**Architecture:** Keep the existing mixed WAV as the playback and legacy fallback artifact. `TrackMixer` will return the mixed frame plus aligned mic and system frames, capture will persist all three only as database-linked artifacts for split-track segments, and retranscription will prefer split paths while sharing speaker state across segments.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy/Alembic, NumPy, stdlib `unittest`, Docker.

## Global Constraints

- Start from local commit `c689397` on branch `agent/alp-108-track-provenance` in its own worktree.
- Preserve `call_segments.audio_path` and legacy mixed-only retranscription behavior.
- Accept approximately 3x PCM storage only for split-track calls.
- Use test-first red/green cycles and run the backend gate in `r2-master-rollout-backend:latest`.
- Do not touch `master`, push a remote, or build installers.

---

### Task 1: Emit aligned track frames

**Files:**
- Modify: `backend/app/services/track_mixer.py`
- Test: `backend/tests/test_track_mixer.py`

**Interfaces:**
- Consumes: `TrackMixer.add(track: int, pcm: bytes)` input frames.
- Produces: `tuple[bytes, bytes, bytes] | None` ordered as mixed, mic, system; all three byte strings have equal length.

- [ ] **Step 1: Write failing alignment tests**

```python
def test_aligned_frames_include_source_tracks(self):
    self.assertIsNone(self.mixer.add(0, frame(1000)))
    mixed, mic, system = self.mixer.add(1, frame(2000))
    self.assertTrue(np.all(np.frombuffer(mixed, dtype=np.int16) == 3000))
    self.assertTrue(np.all(np.frombuffer(mic, dtype=np.int16) == 1000))
    self.assertTrue(np.all(np.frombuffer(system, dtype=np.int16) == 2000))

def test_solo_flush_silences_missing_track(self):
    self.now = 10.0
    mixed, mic, system = self.mixer.add(0, frame(500))
    self.assertEqual(mixed, mic)
    self.assertEqual(bytes(FRAME_BYTES), system)
```

- [ ] **Step 2: Run tests and verify the tuple assertions fail against the current bytes-only result**

Run: `python -m unittest tests.test_track_mixer`
Expected: FAIL because `TrackMixer.add` returns one `bytes` object.

- [ ] **Step 3: Return aligned frames with zero-filled absent tracks**

```python
mic_out = bytearray()
system_out = bytearray()
# Append both real frames while mixing; on solo flush append the real frame to
# its source output and bytes(FRAME_BYTES) to the missing source output.
return (bytes(out), bytes(mic_out), bytes(system_out)) if out else None
```

- [ ] **Step 4: Run `tests.test_track_mixer` and verify it passes**

- [ ] **Step 5: Commit with the capture task after its consumer is green**

### Task 2: Persist split-track provenance

**Files:**
- Modify: `backend/app/models.py`
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/services/audio_store.py`
- Modify: `backend/app/ws/audio_handler.py`
- Create: `backend/alembic/versions/016_add_call_segment_track_paths.py`
- Test: `backend/tests/test_audio_handler.py`
- Test: `backend/tests/test_audio_store.py`

**Interfaces:**
- Consumes: aligned `(mixed, mic, system)` frames from Task 1.
- Produces: nullable `CallSegment.mic_audio_path` and `CallSegment.system_audio_path`; `audio_path` remains the mixed WAV.

- [ ] **Step 1: Write failing writer and segment-path tests**

```python
def test_microphone_track_gets_own_file(self):
    session_id = uuid.uuid4()
    writer = SegmentAudioWriter(session_id, 2, track="mic")
    writer.append(b"\x00\x01" * 1600)
    writer.close()
    self.assertTrue(audio_file_path(session_id, 2, track="mic").name.endswith("_mic.wav"))
```

Update `CallSegmentStartTests` to require three writers with calls for mixed, mic, and sys, and add a focused close-path test proving mic/system database paths are retained only when `split_track_established` is true.

- [ ] **Step 2: Run the focused tests and verify they fail because only the mixed writer/path exists**

Run: `python -m unittest tests.test_audio_store tests.test_audio_handler`
Expected: FAIL on missing writers and track-path columns.

- [ ] **Step 3: Add the nullable schema and migration**

```python
mic_audio_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
system_audio_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
```

Migration `016` adds both nullable columns and `_add_missing_columns()` patches older local databases identically. `CallSegmentOut` exposes both optional fields.

- [ ] **Step 4: Persist aligned files from the websocket path**

Change `_start_call_segment` to create a writer dictionary for `mixed`, `mic`, and `system`. Append the three frames together, close all writers during finalization, retain mic/system paths only for split-track calls, and unlink their files for mic-only calls.

- [ ] **Step 5: Run the focused tests and verify they pass**

- [ ] **Step 6: Commit the aligned capture and schema change**

Run: `git commit -m "feat: preserve split-track call audio"`

### Task 3: Reuse provenance during retranscription

**Files:**
- Modify: `backend/app/routers/imports.py`
- Modify: `backend/app/routers/retranscribe.py`
- Create: `backend/tests/test_retranscribe.py`
- Test: `backend/tests/test_audio_import.py`

**Interfaces:**
- Consumes: optional mic/system paths from Task 2.
- Produces: retranscribed entries where a sole configured user owns mic speech and remote speaker registry/map state survives segment boundaries.

- [ ] **Step 1: Write a failing two-segment split-track test**

Create two `CallSegment` rows with mic/system paths, patch audio conversion/diarization/transcription with deterministic `auto_1` segments, and assert entries produced from both mic files use the sole `is_user=True` speaker while both system files use the same remote speaker.

- [ ] **Step 2: Write a failing legacy fallback test**

Create a segment with only `audio_path` and assert retranscription still invokes the existing mixed-audio path once.

- [ ] **Step 3: Run the focused tests and verify both behaviors fail before implementation**

Run: `python -m unittest tests.test_retranscribe tests.test_audio_import`
Expected: FAIL because retranscription ignores mic/system paths and import transcription cannot accept shared speaker state.

- [ ] **Step 4: Make import transcription accept optional shared state**

Add optional `registry`, `auto_speaker_map`, `runtime_config`, and `local_track` parameters. Use `resolve_live_mic_speaker(auto_id, speakers, local_track)` before generic mapping, reuse caller-provided dictionaries without replacing an empty dictionary, and keep all defaults behavior-compatible for normal imports.

- [ ] **Step 5: Prefer split paths and share state per track across segments**

In `retranscribe_session`, select segments where any stored path exists. For split rows, process mic with a shared mic registry/map and `local_track=True`, process system with a separate shared remote registry/map, and use `audio_path` unchanged for legacy rows.

- [ ] **Step 6: Run the focused tests and verify they pass**

- [ ] **Step 7: Commit retranscription continuity**

Run: `git commit -m "feat: retain track identity on retranscription"`

### Task 4: Document and verify

**Files:**
- Modify: `docs/audio-pipeline.md`

**Interfaces:**
- Consumes: final schema and runtime behavior.
- Produces: operator documentation for storage multiplier, migration, and legacy compatibility.

- [ ] **Step 1: Document the three-file split layout and compatibility**

State that split-track segments store mixed, `_mic`, and `_sys` WAV files (approximately 3x PCM), migration `016` adds nullable paths, startup patching handles older local databases, and mixed-only rows remain readable.

- [ ] **Step 2: Run focused tests**

Run: `python -m unittest tests.test_track_mixer tests.test_audio_store tests.test_audio_handler tests.test_audio_import tests.test_retranscribe`
Expected: PASS.

- [ ] **Step 3: Run the full Docker backend gate**

Run the branch-mounted backend and frontend through `r2-master-rollout-backend:latest` with `python -m unittest discover -s tests`.
Expected: 238 existing tests plus new tests, all PASS.

- [ ] **Step 4: Run structural and diff checks**

Run: `sentrux check .`, `git diff --check`, and `git status --short`.
Expected: no new structural violation or whitespace error; only ALP-108 files are changed.

- [ ] **Step 5: Commit final documentation/test adjustments**

Run: `git commit -m "docs: explain split-track audio storage"`

- [ ] **Step 6: Update coordination records**

Comment on ALP-108 with commits and gate evidence, mark it complete, update ALP-117's train row, and send the branch-ready commit to `w2:p9` through the audited wrapper. Do not push.
