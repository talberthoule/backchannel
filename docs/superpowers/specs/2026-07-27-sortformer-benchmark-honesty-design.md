# Sortformer benchmark honesty

## Goal

Only unlock enhanced diarization when one worker can sustain both live audio
tracks with enough reserve for the transcription stack, and make the measured
margin explicit.

## Design

The existing benchmark input remains one live-size audio window. The backend
replays that window three times through one loaded Sortformer model, then
classifies the aggregate real-time factor. This measures steady processing
without asking the user to record a longer sample.

The requirement is 3x realtime: 2x for mic plus system audio, multiplied by the
existing 1.5 contention reserve used by local-fit diagnostics. In RTF terms,
the passing threshold is `1 / (2 * 1.5)`, or about `0.333`.

The result keeps the raw per-track RTF and also emits the per-track
contention-adjusted RTF (`raw * 1.5`) for ALP-156's aggregate planner. During
model preparation and each sustained run, the benchmark samples resident
memory and reports the largest increase over its pre-load baseline as the
per-instance peak footprint in MB. That planner can multiply the footprint by track
count and add the ASR/caption footprints without double-counting them here.

The result reason states measured throughput, required throughput, and margin.
A passing result with less than 25% margin explicitly warns that lightweight
diarization remains safer under heavier load. The current result reason takes
precedence in the card after a benchmark so the unlock warning is visible.

## Alternatives declined

- Running ASR and live captions during this gate may load or download models
  and can recreate the destructive resource failure.
- ALP-155 does not sum whole-call memory or decide an aggregate admission.
  ALP-156 owns track-count multiplication and the other selected consumers.

## Verification

- A measurement that passed the former single-track threshold fails the new
  dual-track requirement.
- A fast result reports its measured speed, required speed, and margin.
- The real benchmark performs three diarization runs with one loaded model.
- The result persists the contention-adjusted per-track RTF and per-instance
  peak resident-memory footprint in MB for ALP-156.
- Focused backend tests, the full backend suite, frontend build, and Sentrux
  checks pass before review.
