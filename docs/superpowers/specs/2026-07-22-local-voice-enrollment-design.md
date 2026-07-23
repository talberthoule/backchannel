# Local Voice Enrollment Design

**Issue:** ALP-114

**Date:** 2026-07-22

**Status:** Approved

## Purpose

Give the sole local app user a reusable voice profile so mic-only calls can identify that user's speech without assuming that the first detected voice is local. Keep the existing split-track ownership rule and generic handling of unknown voices.

## Scope

- Add one app-wide local voice profile because Backchannel has no durable account model and currently supports one local operator.
- Add record, replace, and delete controls under Admin -> Transcription & Audio.
- Show a small pre-call reminder linking to that setting when system-audio capture is disabled, the session has exactly one `is_user` speaker, and no voice profile exists.
- Apply enrollment only to the live microphone diarizer.

The feature does not enroll remote participants, change imports or retranscription, retain calibration audio, or add a database migration.

## Storage and privacy

The normalized embedding is serialized as a JSON number array and stored under a dedicated `AppSetting` key through the existing Fernet-backed `get_secret`/`set_secret` path. The API never returns the vector.

Enrollment accepts a bounded browser audio upload, converts it to PCM16 16 kHz mono in memory, rejects unsupported, oversized, shorter-than-4-second, longer-than-15-second, silent, invalid, or non-finite inputs, and extracts one normalized embedding. The Admin recorder stops automatically at 10 seconds. Temporary conversion files created by the existing ffmpeg fallback are deleted by `convert_to_pcm16`; no source audio is persisted by Backchannel.

Deleting a profile clears the encrypted setting. A missing, empty, corrupt, or wrong-shaped stored value is treated as no enrollment and logged without exposing biometric data.

## API

Extend the existing diagnostics router with:

- `GET /api/diagnostics/diarization/voice-profile` -> `{ "enrolled": boolean }`
- `PUT /api/diagnostics/diarization/voice-profile` with multipart audio -> validates, replaces the stored embedding, and returns `{ "enrolled": true }`
- `DELETE /api/diagnostics/diarization/voice-profile` -> clears it and returns no content

These endpoints reuse existing supported audio formats and conversion helpers. Upload size and decoded-duration checks are server-side trust-boundary validation.

## Runtime attribution

When a live audio WebSocket starts, the backend loads the local embedding alongside the session's speaker rows. If and only if the session has exactly one `is_user` row and the embedding is valid, the backend pre-enrolls the microphone registry with a reserved local ID.

The system-audio registry is never enrolled. Imports and retranscription are unchanged.

At transcript emission:

1. A split-track mic segment still maps directly to the sole local user, regardless of diarizer ID.
2. In mic-only mode, only the reserved enrolled ID maps to the sole local user.
3. System-track IDs never map through enrollment.
4. All other IDs follow the existing generic speaker map and creation flow.
5. Zero or multiple `is_user` rows fall back to existing behavior.

The reserved local ID stays out of `auto_speaker_map`, so it cannot consume or reorder remote participant slots.

## Unmatched short-segment safety

Today `SpeakerRegistry.match_or_create(..., allow_create=False)` reuses the closest existing profile for a short unmatched segment. Once a local profile is pre-enrolled, that fallback could incorrectly label any short unknown voice as local.

Add one profile-level fallback eligibility flag. Existing auto-created and explicitly enrolled profiles remain eligible by default. The local reserved profile is enrolled as ineligible for below-threshold fallback: it may match only at or above the configured similarity threshold. If it is the only profile and a short voice does not match, the registry returns `auto_unknown`, preserving generic/unknown handling.

## Admin and pre-call experience

Extend the existing `DiarizationCapabilityCard` rather than adding a new audio component. Reuse its `MediaRecorder`, MIME selection, cleanup, status, and error patterns. Voice enrollment uses mic constraints aligned with live mic-only capture: mono, automatic gain control, and no browser echo cancellation or noise suppression.

The card shows whether a profile exists and offers Record, Replace, and Delete. It explains that only the encrypted voice signature is retained. The pre-call reminder is informational and links to Admin; it never blocks starting a call.

## Error handling

- Microphone denial or unsupported browser recording leaves the existing profile untouched.
- Validation or embedding extraction failure leaves the existing profile untouched and returns a concise 400 response.
- A corrupt stored profile is ignored, not fatal to call startup.
- Replacement is atomic at the setting level: store only after full validation and extraction succeed.

## Verification

Backend tests cover encrypted normalized round-trip, clear, corrupt storage, duration, size, silence, non-finite values, API status, registry threshold matching, below-threshold mismatch safety, sole-user mapping, system-track rejection, split-track preservation, zero/multiple-user fallback, mic-registry enrollment, and system-registry isolation.

Frontend verification covers API typing, recorder state transitions where an existing test seam exists, the mic constraints, the pre-call reminder condition, and a production build. The final train gate is the complete backend `unittest` suite in Docker plus the frontend build.

## Deliberate ceiling

The profile is app-wide because there is no local account table. If Backchannel later adds authenticated local accounts, move the encrypted embedding to account-scoped storage. No account abstraction is introduced now.
