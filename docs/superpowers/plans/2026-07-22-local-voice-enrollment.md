# Local Voice Enrollment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enroll one encrypted local voice profile and use it to identify the sole local user in mic-only live calls without mislabeling unmatched voices.

**Architecture:** Store one normalized embedding in the existing encrypted `AppSetting` path and expose status/replace/delete through the diagnostics router. Pre-enroll only the live microphone `SpeakerRegistry` with a reserved ID; mapping that ID to the sole `is_user` row bypasses generic speaker ordering, while system audio and non-matches retain existing behavior. Extend the existing Admin diarization recorder and show a non-blocking pre-call reminder when mic-only capture lacks enrollment.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async sessions, NumPy, existing Fernet secret storage, React 18, TypeScript, browser `MediaRecorder`, stdlib `unittest`, Docker Compose.

## Global Constraints

- Persist only the normalized embedding; never persist or return calibration audio.
- Encrypt the embedding through existing `get_secret`/`set_secret`; add no schema migration or dependency.
- Accept 4-15 seconds of decoded PCM and cap browser recording at 10 seconds.
- Apply enrollment only to the live mic registry; never system audio, imports, or retranscription.
- Match at the existing configured threshold, currently `0.68`.
- Require exactly one session `is_user` row; zero or multiple rows use existing fallback behavior.
- Preserve split-track direct mic ownership and keep the reserved local ID out of `auto_speaker_map`.
- Unmatched voices must remain generic/unknown and must never be forced onto the local profile.

---

## File map

- Create `backend/app/services/voice_enrollment.py`: validation, normalization, encrypted serialization, status/load/save/clear constants.
- Create `backend/tests/test_voice_enrollment.py`: service privacy and validation checks.
- Modify `backend/app/routers/diagnostics.py`: status/replace/delete API and upload trust-boundary checks.
- Modify `backend/tests/test_diarization_diagnostics.py`: upload-format, size, and API behavior checks.
- Modify `backend/app/services/speaker_diarizer.py`: profile-level unmatched-fallback eligibility and dimension-safe matching.
- Modify `backend/tests/test_speaker_registry.py`: threshold match and mismatch regressions.
- Modify `backend/app/services/speaker_assignment.py`: mic-only reserved-ID ownership rule.
- Modify `backend/tests/test_speaker_assignment.py`: sole-user, system, split-track, and topology checks.
- Modify `backend/app/ws/audio_handler.py`: load enrollment and seed only the mic registry.
- Modify `backend/tests/test_audio_handler.py`: mic/system registry isolation seam.
- Modify `frontend/src/hooks/useAudioCapture.ts`: export/reuse aligned mic-only constraints.
- Modify `frontend/src/hooks/useAudioCapture.test.mjs`: mic constraint regression.
- Modify `frontend/src/services/api.ts`: voice-profile API calls.
- Modify `frontend/src/components/DiarizationCapabilityCard.tsx`: record/replace/delete status UI using its current recorder lifecycle.
- Modify `frontend/src/components/PreCall/PreCallView.tsx`: mic-only missing-profile reminder.
- Modify `frontend/src/App.tsx`: open Admin directly to Transcription & Audio from the reminder.

---

### Task 1: Encrypted voice-profile service and API

**Files:**
- Create: `backend/app/services/voice_enrollment.py`
- Create: `backend/tests/test_voice_enrollment.py`
- Modify: `backend/app/routers/diagnostics.py`
- Modify: `backend/tests/test_diarization_diagnostics.py`

**Interfaces:**
- Produces: `LOCAL_VOICE_PROFILE_ID`, `VoiceEnrollmentError`, `extract_enrollment_embedding(pcm_bytes, extractor=...) -> np.ndarray`, `load_local_voice_embedding(db) -> np.ndarray | None`, `save_local_voice_embedding(db, embedding) -> None`, and `clear_local_voice_embedding(db) -> None`.
- Produces: `GET/PUT/DELETE /api/diagnostics/diarization/voice-profile`, returning only `{ "enrolled": bool }` or 204.

- [ ] **Step 1: Write failing service tests**

Add `backend/tests/test_voice_enrollment.py` with tests that use a temporary `DATA_DIR`, patch `app_settings` as `test_secrets.py` does, and assert ciphertext-at-rest, normalized round-trip, clear, corrupt JSON fallback, duration rejection, silence rejection, and non-finite extractor rejection:

```python
class VoiceEnrollmentTests(unittest.IsolatedAsyncioTestCase):
    async def test_round_trip_is_normalized_and_encrypted(self):
        await save_local_voice_embedding(None, np.array([3.0, 4.0], dtype=np.float32))
        self.assertNotIn("3.0", self.store[SETTING_LOCAL_VOICE_EMBEDDING])
        np.testing.assert_allclose(
            await load_local_voice_embedding(None),
            np.array([0.6, 0.8], dtype=np.float32),
        )

    async def test_clear_and_corrupt_storage_read_as_unenrolled(self):
        await save_local_voice_embedding(None, np.array([1.0, 0.0], dtype=np.float32))
        await clear_local_voice_embedding(None)
        self.assertIsNone(await load_local_voice_embedding(None))
        await self.secrets.set_secret(None, SETTING_LOCAL_VOICE_EMBEDDING, "not-json")
        self.assertIsNone(await load_local_voice_embedding(None))

    def test_extract_rejects_duration_silence_and_non_finite_output(self):
        with self.assertRaisesRegex(VoiceEnrollmentError, "at least 4 seconds"):
            extract_enrollment_embedding(b"\x01\x00" * (16000 * 3), extractor=lambda *_: np.ones(2))
        with self.assertRaisesRegex(VoiceEnrollmentError, "audible speech"):
            extract_enrollment_embedding(b"\x00\x00" * (16000 * 4), extractor=lambda *_: np.ones(2))
        voiced = np.full(16000 * 4, 1000, dtype=np.int16).tobytes()
        with self.assertRaisesRegex(VoiceEnrollmentError, "invalid"):
            extract_enrollment_embedding(voiced, extractor=lambda *_: np.array([np.nan]))
```

- [ ] **Step 2: Run the new tests and verify RED**

Run from `backend/`:

```powershell
python -m unittest tests.test_voice_enrollment -v
```

Expected: import failure because `app.services.voice_enrollment` does not exist.

- [ ] **Step 3: Implement the minimal service**

Create `backend/app/services/voice_enrollment.py` with these exact policies:

```python
SETTING_LOCAL_VOICE_EMBEDDING = "diarization.local_voice_embedding"
LOCAL_VOICE_PROFILE_ID = "enrolled_local_user"
MIN_ENROLLMENT_SECONDS = 4
MAX_ENROLLMENT_SECONDS = 15
MAX_ENROLLMENT_UPLOAD_BYTES = 8 * 1024 * 1024
PCM_BYTES_PER_SECOND = 16000 * 2

class VoiceEnrollmentError(ValueError):
    pass

def normalize_embedding(value: np.ndarray) -> np.ndarray:
    embedding = np.asarray(value, dtype=np.float32)
    if embedding.ndim != 1 or embedding.size == 0 or not np.isfinite(embedding).all():
        raise VoiceEnrollmentError("Speaker embedding is invalid.")
    norm = float(np.linalg.norm(embedding))
    if norm <= 0:
        raise VoiceEnrollmentError("Speaker embedding is invalid.")
    return embedding / norm

def extract_enrollment_embedding(pcm_bytes: bytes, extractor=extract_speaker_embedding) -> np.ndarray:
    seconds = len(pcm_bytes) / PCM_BYTES_PER_SECOND
    if seconds < MIN_ENROLLMENT_SECONDS:
        raise VoiceEnrollmentError("Voice sample must be at least 4 seconds long.")
    if seconds > MAX_ENROLLMENT_SECONDS:
        raise VoiceEnrollmentError("Voice sample must be no longer than 15 seconds.")
    if not _audio_has_speech_energy(pcm_bytes):
        raise VoiceEnrollmentError("Voice sample must contain audible speech.")
    return normalize_embedding(extractor(pcm16_to_float32(pcm_bytes), 16000))

async def load_local_voice_embedding(db) -> np.ndarray | None:
    raw = await get_secret(db, SETTING_LOCAL_VOICE_EMBEDDING)
    if not raw:
        return None
    try:
        return normalize_embedding(np.asarray(json.loads(raw), dtype=np.float32))
    except (TypeError, ValueError, json.JSONDecodeError):
        logger.warning("Ignoring invalid stored local voice profile")
        return None

async def save_local_voice_embedding(db, embedding: np.ndarray) -> None:
    normalized = normalize_embedding(embedding)
    await set_secret(db, SETTING_LOCAL_VOICE_EMBEDDING, json.dumps(normalized.tolist()))

async def clear_local_voice_embedding(db) -> None:
    await set_secret(db, SETTING_LOCAL_VOICE_EMBEDDING, "")
```

Reuse `_audio_has_speech_energy`, `pcm16_to_float32`, `extract_speaker_embedding`, and the existing secret service; do not add a new audio or crypto implementation.

- [ ] **Step 4: Run service tests and verify GREEN**

Run: `python -m unittest tests.test_voice_enrollment -v`

Expected: all new service tests pass.

- [ ] **Step 5: Write failing API boundary tests**

Extend `backend/tests/test_diarization_diagnostics.py` to assert `.webm` acceptance, `MAX_ENROLLMENT_UPLOAD_BYTES + 1` rejection through a pure `is_enrollment_upload_too_large(size)` helper, and direct async endpoint behavior with patched conversion/extraction/storage:

```python
def test_enrollment_upload_size_is_bounded(self):
    self.assertFalse(is_enrollment_upload_too_large(MAX_ENROLLMENT_UPLOAD_BYTES))
    self.assertTrue(is_enrollment_upload_too_large(MAX_ENROLLMENT_UPLOAD_BYTES + 1))

async def test_voice_profile_replacement_commits_only_after_extraction(self):
    file = UploadFile(filename="voice.webm", file=io.BytesIO(b"encoded"))
    db = AsyncMock()
    with patch("app.routers.diagnostics.convert_to_pcm16", return_value=b"pcm"), \
         patch("app.routers.diagnostics.extract_enrollment_embedding", return_value=np.array([1.0, 0.0])), \
         patch("app.routers.diagnostics.save_local_voice_embedding", new=AsyncMock()) as save:
        self.assertEqual({"enrolled": True}, await replace_voice_profile(file, db))
    save.assert_awaited_once()
    db.commit.assert_awaited_once()

async def test_voice_profile_status_and_delete_never_return_embedding(self):
    db = AsyncMock()
    with patch("app.routers.diagnostics.load_local_voice_embedding", new=AsyncMock(return_value=np.ones(2))):
        self.assertEqual({"enrolled": True}, await get_voice_profile_status(db))
    with patch("app.routers.diagnostics.clear_local_voice_embedding", new=AsyncMock()) as clear:
        await delete_voice_profile(db)
    clear.assert_awaited_once_with(db)
    db.commit.assert_awaited()
```

- [ ] **Step 6: Run diagnostics tests and verify RED**

Run: `python -m unittest tests.test_diarization_diagnostics -v`

Expected: failure because the enrollment endpoints and size helper do not exist.

- [ ] **Step 7: Implement status, replace, and delete endpoints**

In `backend/app/routers/diagnostics.py`, add:

```python
def is_enrollment_upload_too_large(size: int) -> bool:
    return size > MAX_ENROLLMENT_UPLOAD_BYTES

@router.get("/diarization/voice-profile")
async def get_voice_profile_status(db: AsyncSession = Depends(get_db)):
    return {"enrolled": await load_local_voice_embedding(db) is not None}

@router.put("/diarization/voice-profile")
async def replace_voice_profile(file: UploadFile, db: AsyncSession = Depends(get_db)):
    filename = file.filename or ""
    ext = os.path.splitext(filename)[1].lower()
    if not is_supported_benchmark_audio_filename(filename):
        raise HTTPException(400, f"Unsupported audio format: {ext}")
    content = await file.read(MAX_ENROLLMENT_UPLOAD_BYTES + 1)
    if is_enrollment_upload_too_large(len(content)):
        raise HTTPException(413, "Voice sample is too large.")
    try:
        pcm_data = convert_to_pcm16(content, ext.lstrip("."))
        embedding = extract_enrollment_embedding(pcm_data)
    except VoiceEnrollmentError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(400, f"Audio conversion failed: {exc}") from exc
    await save_local_voice_embedding(db, embedding)
    await db.commit()
    return {"enrolled": True}

@router.delete("/diarization/voice-profile", status_code=204)
async def delete_voice_profile(db: AsyncSession = Depends(get_db)):
    await clear_local_voice_embedding(db)
    await db.commit()
```

- [ ] **Step 8: Run focused backend tests and commit**

Run:

```powershell
python -m unittest tests.test_voice_enrollment tests.test_diarization_diagnostics tests.test_secrets -v
```

Expected: all focused tests pass.

Commit:

```powershell
git add backend/app/services/voice_enrollment.py backend/app/routers/diagnostics.py backend/tests/test_voice_enrollment.py backend/tests/test_diarization_diagnostics.py
git commit -m "feat: store encrypted local voice profile"
```

---

### Task 2: Safe mic-only attribution

**Files:**
- Modify: `backend/app/services/speaker_diarizer.py`
- Modify: `backend/tests/test_speaker_registry.py`
- Modify: `backend/app/services/speaker_assignment.py`
- Modify: `backend/tests/test_speaker_assignment.py`
- Modify: `backend/app/ws/audio_handler.py`
- Modify: `backend/tests/test_audio_handler.py`

**Interfaces:**
- Consumes: `LOCAL_VOICE_PROFILE_ID` and `load_local_voice_embedding(db)` from Task 1.
- Produces: `SpeakerRegistry.enroll(speaker_id, embedding, fallback_for_unmatched=True)` and `_new_speaker_registry(threshold, local_embedding=None)`.
- Preserves: all existing `SpeakerRegistry.enroll` callers through the default `fallback_for_unmatched=True`.

- [ ] **Step 1: Write failing registry mismatch tests**

Extend `backend/tests/test_speaker_registry.py`:

```python
def test_enrolled_local_matches_only_at_threshold(self):
    registry = SpeakerRegistry(threshold=0.9, max_profiles=4)
    registry.enroll("enrolled_local_user", embedding(1.0, 0.0), fallback_for_unmatched=False)
    self.assertEqual("enrolled_local_user", registry.match_or_create(embedding(1.0, 0.0), False))
    self.assertEqual("auto_unknown", registry.match_or_create(embedding(0.0, 1.0), False))

def test_enrolled_local_does_not_consume_generic_profile_capacity(self):
    registry = SpeakerRegistry(threshold=0.9, max_profiles=1)
    registry.enroll("enrolled_local_user", embedding(1.0, 0.0), fallback_for_unmatched=False)
    self.assertEqual("auto_1", registry.match_or_create(embedding(0.0, 1.0), True))
```

Add a different-dimension case that asserts no `np.dot` exception and creates a generic profile.

- [ ] **Step 2: Run registry tests and verify RED**

Run: `python -m unittest tests.test_speaker_registry -v`

Expected: `SpeakerRegistry.enroll()` rejects the new keyword or mismatch returns the local profile.

- [ ] **Step 3: Implement profile fallback eligibility**

In `backend/app/services/speaker_diarizer.py`:

```python
@dataclass
class _SpeakerProfile:
    speaker_id: str
    embedding: np.ndarray
    sample_count: int = 1
    fallback_for_unmatched: bool = True

def enroll(self, speaker_id: str, embedding: np.ndarray, fallback_for_unmatched: bool = True):
    normalized = embedding / np.linalg.norm(embedding) if np.linalg.norm(embedding) > 0 else embedding
    self._profiles.append(_SpeakerProfile(speaker_id, normalized, fallback_for_unmatched=fallback_for_unmatched))

def _best_profile(self, embedding: np.ndarray, fallback_only: bool = False):
    candidates = [
        profile for profile in self._profiles
        if profile.embedding.shape == embedding.shape
        and (profile.fallback_for_unmatched or not fallback_only)
    ]
    if not candidates:
        return None, 0.0
    best = max(candidates, key=lambda profile: float(np.dot(embedding, profile.embedding)))
    return best, float(np.dot(embedding, best.embedding))
```

Change `match_or_create` so below-threshold `allow_create=False` considers only fallback-eligible profiles and otherwise returns `auto_unknown`. Count only fallback-eligible profiles against `_max_profiles`; when that limit is reached, reuse only the closest fallback-eligible generic profile. Exact threshold matches still consider every compatible profile.

- [ ] **Step 4: Run registry tests and verify GREEN**

Run: `python -m unittest tests.test_speaker_registry tests.test_speaker_diarizer tests.test_sortformer_diarizer -v`

Expected: all existing and new registry/diarizer tests pass.

- [ ] **Step 5: Write failing ownership and registry-isolation tests**

Extend `backend/tests/test_speaker_assignment.py`:

```python
def test_enrolled_mic_only_voice_resolves_to_sole_user(self):
    user = _speaker("Me", True)
    self.assertIs(user, resolve_live_mic_speaker(LOCAL_VOICE_PROFILE_ID, [user], False))
    self.assertIsNone(resolve_live_mic_speaker("auto_1", [user], False))
    self.assertIsNone(resolve_live_mic_speaker(f"sys_{LOCAL_VOICE_PROFILE_ID}", [user], True))
```

Keep the existing split-track and zero/multiple-user cases unchanged. Extend `backend/tests/test_audio_handler.py`:

```python
def test_local_embedding_is_enrolled_only_when_passed_to_registry(self):
    local = np.array([1.0, 0.0], dtype=np.float32)
    mic = audio_handler._new_speaker_registry(0.68, local)
    system = audio_handler._new_speaker_registry(0.68)
    self.assertEqual(LOCAL_VOICE_PROFILE_ID, mic.match(local)[0])
    self.assertIsNone(system.match(local)[0])
```

- [ ] **Step 6: Run ownership tests and verify RED**

Run: `python -m unittest tests.test_speaker_assignment tests.test_audio_handler -v`

Expected: mic-only reserved ID does not resolve and `_new_speaker_registry` does not exist.

- [ ] **Step 7: Implement ownership and live mic seeding**

Update `resolve_live_mic_speaker`:

```python
if auto_id.startswith("sys_"):
    return None
users = [speaker for speaker in speakers if speaker.is_user]
if len(users) != 1:
    return None
return users[0] if split_track_established or auto_id == LOCAL_VOICE_PROFILE_ID else None
```

In `backend/app/ws/audio_handler.py`, add:

```python
def _new_speaker_registry(threshold: float, local_embedding=None) -> SpeakerRegistry:
    registry = SpeakerRegistry(threshold=threshold)
    if local_embedding is not None:
        registry.enroll(LOCAL_VOICE_PROFILE_ID, local_embedding, fallback_for_unmatched=False)
    return registry
```

Load `local_voice_embedding = await load_local_voice_embedding(db)` in the initial DB context. Pass it to `_new_speaker_registry` only when `len([s for s in speaker_rows if s.is_user]) == 1`. Create the system registry with `_new_speaker_registry(threshold)` and no embedding. Leave imports and retranscription untouched.

- [ ] **Step 8: Run focused attribution tests and commit**

Run:

```powershell
python -m unittest tests.test_speaker_registry tests.test_speaker_assignment tests.test_speaker_diarizer tests.test_sortformer_diarizer tests.test_audio_handler -v
```

Expected: all focused attribution tests pass.

Commit:

```powershell
git add backend/app/services/speaker_diarizer.py backend/app/services/speaker_assignment.py backend/app/ws/audio_handler.py backend/tests/test_speaker_registry.py backend/tests/test_speaker_assignment.py backend/tests/test_audio_handler.py
git commit -m "feat: identify enrolled voice on live mic"
```

---

### Task 3: Admin calibration and pre-call reminder

**Files:**
- Modify: `frontend/src/hooks/useAudioCapture.ts`
- Modify: `frontend/src/hooks/useAudioCapture.test.mjs`
- Modify: `frontend/src/services/api.ts`
- Modify: `frontend/src/components/DiarizationCapabilityCard.tsx`
- Modify: `frontend/src/components/PreCall/PreCallView.tsx`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Consumes: Task 1 voice-profile endpoints.
- Produces: `MIC_ONLY_AUDIO_CONSTRAINTS`, `getVoiceProfileStatus()`, `replaceVoiceProfile(file)`, and `deleteVoiceProfile()`.
- Produces: `PreCallView.onOpenVoiceSettings: () -> void`.

- [ ] **Step 1: Write the failing shared mic-constraint test**

Extend `frontend/src/hooks/useAudioCapture.test.mjs`:

```javascript
test("voice enrollment uses live mic-only capture constraints", async () => {
  const { MIC_ONLY_AUDIO_CONSTRAINTS } = await import("./useAudioCapture.ts");
  assert.deepEqual(MIC_ONLY_AUDIO_CONSTRAINTS, {
    channelCount: 1,
    echoCancellation: false,
    noiseSuppression: false,
    autoGainControl: true,
  });
});
```

- [ ] **Step 2: Run the frontend test and verify RED**

Run from `frontend/`: `npm test`

Expected: `MIC_ONLY_AUDIO_CONSTRAINTS` is undefined.

- [ ] **Step 3: Export and reuse mic-only constraints**

In `frontend/src/hooks/useAudioCapture.ts`:

```typescript
export const MIC_ONLY_AUDIO_CONSTRAINTS: MediaTrackConstraints = {
  channelCount: 1,
  echoCancellation: false,
  noiseSuppression: false,
  autoGainControl: true,
};
```

Build the live `getUserMedia` audio object from this constant, overriding only echo/noise suppression with `options?.systemAudio ?? false` for split capture. The enrollment recorder imports the unchanged constant.

- [ ] **Step 4: Run the frontend test and verify GREEN**

Run: `npm test`

Expected: all Node tests pass.

- [ ] **Step 5: Add typed voice-profile API calls**

In `frontend/src/services/api.ts` near the diagnostics calls:

```typescript
export interface VoiceProfileStatus { enrolled: boolean }

export const getVoiceProfileStatus = () =>
  request<VoiceProfileStatus>("/diagnostics/diarization/voice-profile");

export const replaceVoiceProfile = async (file: File): Promise<VoiceProfileStatus> => {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(`${BASE}/diagnostics/diarization/voice-profile`, { method: "PUT", body: form });
  if (!response.ok) throw new Error(await response.text());
  return response.json();
};

export const deleteVoiceProfile = () =>
  request<void>("/diagnostics/diarization/voice-profile", { method: "DELETE" });
```

- [ ] **Step 6: Reuse the Admin recorder for enrollment**

In `DiarizationCapabilityCard.tsx`, load voice status with diagnostics, replace the benchmark-only recording boolean with `recordingMode: "benchmark" | "voice" | null`, and use one `MediaRecorder` lifecycle. For voice mode use `MIC_ONLY_AUDIO_CONSTRAINTS`, stop at 10 seconds, call `api.replaceVoiceProfile(file)` only after stop, and set `voiceEnrolled` from the response. Keep benchmark behavior at its existing 20-second cap.

Add one compact panel below speaker matching with:

```tsx
<p className="font-body text-xs text-brand-gray">
  {voiceEnrolled
    ? "Your encrypted voice signature is ready for mic-only speaker matching."
    : "Record 4-10 seconds of your voice. Calibration audio is discarded; only its encrypted voice signature is kept."}
</p>
<button type="button" onClick={recordingMode === "voice" ? stopRecording : startVoiceEnrollment}>
  {recordingMode === "voice" ? `Stop (${recordingSeconds}s)` : voiceEnrolled ? "Replace Voice Profile" : "Record Voice Profile"}
</button>
{voiceEnrolled && <button type="button" onClick={removeVoiceProfile}>Delete</button>}
```

On microphone denial, upload failure, or early stop, keep the prior `voiceEnrolled` value and show the existing diagnostic error surface.

- [ ] **Step 7: Add the non-blocking pre-call hint**

Add `onOpenVoiceSettings` to `PreCallView` props. Fetch `api.getVoiceProfileStatus()` on mount. When `captureSystemAudio === false`, exactly one speaker has `is_user`, and status is definitively `false`, render:

```tsx
<p className="rounded border border-amber-200 bg-amber-50 px-3 py-2 font-body text-xs text-amber-800">
  Mic-only calls identify you more reliably after a voice calibration.{" "}
  <button type="button" onClick={onOpenVoiceSettings} className="font-semibold underline">
    Open Transcription & Audio
  </button>
</p>
```

In `App.tsx`, define `handleOpenVoiceSettings = useCallback(() => openAdmin("transcription"), [openAdmin])` and pass it to `PreCallView`. The reminder must not disable Start Call.

- [ ] **Step 8: Run frontend checks and commit**

Run from `frontend/`:

```powershell
npm test
npm run build
```

Expected: all Node tests pass; TypeScript and Vite production build succeed.

Commit:

```powershell
git add frontend/src/hooks/useAudioCapture.ts frontend/src/hooks/useAudioCapture.test.mjs frontend/src/services/api.ts frontend/src/components/DiarizationCapabilityCard.tsx frontend/src/components/PreCall/PreCallView.tsx frontend/src/App.tsx
git commit -m "feat: add local voice calibration controls"
```

---

### Task 4: Full verification and branch handoff

**Files:**
- Modify only if verification exposes an ALP-114 regression.

**Interfaces:**
- Consumes: all prior tasks.
- Produces: a clean, review-approved branch with Docker and frontend evidence for ALP-114 and ALP-117.

- [ ] **Step 1: Run all backend tests locally**

From `backend/`:

```powershell
python -m unittest discover -s tests
```

Expected: all tests pass, with a count at least six greater than the 238-test baseline.

- [ ] **Step 2: Build the backend Docker image**

From repository root:

```powershell
docker compose build backend
```

Expected: image builds successfully with no dependency changes.

- [ ] **Step 3: Run the full backend suite in Docker**

```powershell
docker compose run --rm --no-deps backend python -m unittest discover -s tests
```

Expected: the same complete suite passes inside the production backend image.

- [ ] **Step 4: Run frontend and structural gates**

```powershell
npm test --prefix frontend
npm run build --prefix frontend
& 'C:\Users\thoule\.local\bin\sentrux.exe' check .
& 'C:\Users\thoule\.local\bin\sentrux.exe' gate .
git diff master...HEAD --check
git status --short --branch
```

Expected: frontend tests/build pass; Sentrux reports only documented baseline exceptions; diff check is clean; only intentional ALP-114 changes are present.

- [ ] **Step 5: Run the private two-person acceptance checklist**

Before review, run the user-facing acceptance checklist against the approved two-person Recorder fixture in a Docker-served build: enroll Talbert, run mic-only playback, and confirm exactly two displayed participants with enrolled speech mapped to Talbert and the other voice generic/remote. Repeat once with a deliberately mismatched voice and once after deleting calibration; both must remain generic rather than claiming Talbert. Record this as manual evidence because the private recording is not checked into the repository.

- [ ] **Step 6: Request code review and address only verified findings**

Provide the reviewer the design spec, implementation plan, `git diff master...HEAD`, and exact gate output. Re-run the narrowest failing test before changing code for any finding, then repeat the full affected gate.

- [ ] **Step 7: Update Linear and Herdr without pushing remote**

Add an ALP-114 comment containing commit SHAs, test counts, Docker result, privacy behavior, and manual checklist: enroll/replace/delete; known voice; mismatched voice; mic-only; split-track; zero/multiple user. Move ALP-114 to the train's review-ready state and report branch/head to w2:p9. Do not push, tag, package, or merge.
