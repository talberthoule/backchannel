---
name: Speaker Diarization
description: Add speaker identification/tokenization to transcripts
status: planned
---

## Task: Speaker Diarization

Tokenize speakers in transcripts — identify who is speaking and place speaker labels next to processed text.

### Approach Options:
1. **Client-side**: Use Web Speech API's speaker detection if available
2. **Server-side**: Process audio chunks through a diarization model (e.g., pyannote.audio, Google Speech-to-Text with diarization)
3. **Retroactive**: Post-process the full audio/transcript after the call to assign speaker labels

### Implementation:
- Add `speaker` field to `TranscriptEntry` model (nullable string, e.g., "Speaker 1", "Speaker 2")
- Process in parallel during the call or retroactively after
- Display speaker labels in the transcript panel with distinct colors per speaker
- Export should include speaker labels

### Why:
- Makes transcripts much more readable
- Enables per-speaker analysis (who talked most, who asked what)
- Critical for multi-party calls
