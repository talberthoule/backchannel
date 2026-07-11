# Audio Pipeline

Everything in the live path operates on PCM16, 16 kHz, mono audio.

## Capture and framing

`frontend/src/hooks/useAudioCapture.ts` captures microphone audio with
`getUserMedia`, downsamples it to 16 kHz PCM16 in the browser, and sends
binary WebSocket frames. Tab/system audio, when enabled, is captured as a
second track. Each frame carries a 1-byte track prefix:

- `0x00` -- microphone
- `0x01` -- system/tab audio

Because PCM16 payloads are always even-length, the backend detects the
prefix by frame parity: odd-length frames are prefixed, even-length frames
are treated as legacy mic audio (`backend/app/ws/audio_handler.py`).

On the backend the two tracks are mixed into a single stream
(`backend/app/services/track_mixer.py`) for the interim audio gateway and
the session recording, while each track is diarized separately so remote
(system-audio) speakers get their own identities, prefixed `sys_`.

## Voice activity detection and segmentation

`backend/app/services/speaker_diarizer.py` runs Silero VAD over the incoming
stream and cuts speech into segments. Defaults live in
`backend/app/config.py` and can be adjusted at runtime through the Admin
diagnostics endpoints (`/api/diagnostics/diarization`):

| Setting | Default | Meaning |
| --- | --- | --- |
| `VAD_THRESHOLD` | 0.6 | Silero speech probability required to count as speech |
| `MIN_SEGMENT_MS` | 750 | Segments shorter than this are dropped |
| `MAX_SEGMENT_MS` | 15000 | Force a segment boundary after this much speech |
| `SILENCE_GAP_MS` | 600 | Silence long enough to close the current segment |
| `SPEAKER_SIMILARITY_THRESHOLD` | 0.68 | Cosine similarity required to match an existing speaker embedding |
| `MIN_NEW_SPEAKER_MS` | 4000 | Minimum speech needed before enrolling a new voice profile |
| `MAX_SPEAKER_PROFILES_PER_TRACK` | 4 | Safety cap for auto-enrolled profiles on each audio track |

## Speaker identification

Each closed segment gets a WeSpeaker ResNet152 embedding, compared against the
per-call `SpeakerRegistry`. A match reuses that auto ID; otherwise a new
`auto_N` identity is created after enough speech is available. Short unmatched
segments reuse the closest established profile without changing its centroid,
and each input track has a bounded profile count. The WebSocket handler maps auto IDs to
database `Speaker` rows, auto-creating "Participant N" (or "Remote
Participant N" for `sys_` IDs) rows when a new voice appears. A ghost filter
(`backend/app/services/speaker_ghost_filter.py`) defers short one-off
segments that would otherwise create a spurious new speaker.

The default live diarizer is the lightweight VAD+embedding pipeline
(`LIVE_DIARIZER=lightweight`). An NVIDIA Sortformer diarizer can be enabled
for GPU deployments (see [Deployment](deployment.md));
`backend/app/services/diarizer_factory.py` chooses the implementation from
runtime configuration.

Required ONNX models are expected at `backend/models/silero_vad.onnx` and
`backend/models/voxceleb_resnet152_LM.onnx` (the legacy
`backend/models/ecapa_tdnn.onnx` is used as a fallback when the new file is
absent); fetch them with `backend/scripts/download_models.py` (the Docker
build does this for you).

## Batch transcription

Diarized segments are transcribed in original audio order through
`OrderedTranscriptionQueue`. The transcriber is picked by model ID in
`create_transcriber` (`backend/app/services/local_transcriber.py`):

- `local-*` model IDs (for example `local-whisper-base`,
  `local-parakeet-tdt-0.6b`) run ONNX Whisper/Parakeet locally via
  `onnx-asr`. Weights download to `DATA_DIR/asr-models/` on first use; no
  API key required.
- Everything else goes to Gemini: the segment is wrapped as WAV and sent
  with a transcription prompt (`backend/app/services/batch_transcriber.py`).

The active model comes from the persisted `transcription.batch.model_id`
app setting (Admin panel), falling back to `BATCH_TRANSCRIBER_MODEL`.
Filters drop low-energy segments, known phantom phrases (common
hallucinations on near-silence), and single-word outputs before anything is
saved.

## Interim transcription

Independently of the batch path, the mixed stream is forwarded to the audio
gateway (Gemini Live or OpenAI Realtime) which streams back interim text
within seconds. Interim text is display-only; the diarized batch transcript
is the source of truth that agents analyze and that gets persisted.

## Audio storage and re-transcription

Mixed call audio is appended per call segment to
`DATA_DIR/audio/<session_id>/segment_<n>.wav`
(`backend/app/services/audio_store.py`); the path is stored on the
`call_segments` row when the segment closes.

Because raw audio is retained, a session can be re-transcribed later through
any batch-capable model with `POST /api/sessions/{id}/retranscribe`
(destructive to existing transcript entries), and individual segment
recordings can be fetched from
`GET /api/sessions/{id}/segments/{n}/audio`.

## Audio file import

`POST /api/sessions/{id}/import/audio` accepts `.wav`, `.mp3`, `.m4a`,
`.ogg`, and `.flac`, decodes with `soundfile` first and falls back to
`ffmpeg` for compressed formats, then runs the file through the same
diarization and transcription pipeline as a live call.
