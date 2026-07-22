# Gemini 3.6 / 3.5 Flash-Lite Default Models

**Date:** 2026-07-22
**Target release:** v0.2.5

## Goal

Expose Google's stable `gemini-3.6-flash` and `gemini-3.5-flash-lite`
models in every compatible Backchannel selector and make them the active
defaults for the requested agents and batch transcription.

## Assignments

`gemini-3.6-flash` becomes the default for:

- Consolidated Analyst
- Opportunity Specialist
- Briefing Meeting Lens
- Briefing Discovery Lens
- Briefing Arbiter

`gemini-3.5-flash-lite` becomes the default for:

- Objection Handler
- Batch Transcription

Audio Bridge remains on `gemini-3.1-flash-live-preview`; neither new model
supports the Live API. Principal Agent remains unchanged.

## Implementation

Add both models to `MODEL_REGISTRY` as stable Google models supporting text
and batch audio, but not live audio. The existing `/api/models` response and
capability-filtered frontend selectors then expose them without frontend,
schema, or API changes.

Update the fresh-install defaults in `Settings` and `SEED_CONFIGS`.

Add a versioned startup seed step using the existing `create_all` and seed
path. When `defaults.models.version` is not `v0.2.5`, it:

1. sets the five named agent rows to `gemini-3.6-flash`;
2. sets Objection Handler to `gemini-3.5-flash-lite`; and
3. inserts or replaces `transcription.batch.model_id` with
   `gemini-3.5-flash-lite`.

The versioned seed intentionally replaces existing selections. It runs once, so
users can still choose another model afterward and that selection will
survive restarts. Backchannel's production databases are created and evolved
through this startup path rather than Alembic, so no unused migration revision
is added.

## API Compatibility

Backchannel's current Gemini text, structured-output, document, and audio
calls do not send `top_p`, `top_k`, `candidate_count`, prefilled model turns,
or a temperature value. No request-shape migration is required for these two
models. Existing live-audio routing remains isolated from the new entries.

## Verification

- Registry tests assert both IDs, provider, tier, key requirement, and
  text/batch/live capabilities.
- Seed tests assert the six requested agent assignments.
- Transcription tests assert `gemini-3.5-flash-lite` is the supported batch
  default and both new models are excluded from live audio.
- Startup acceptance starts from saved non-default values, applies the missing
  `v0.2.5` marker, and verifies all seven forced assignments plus the marker.
- Run the complete backend suite, frontend tests/build, desktop release
  contracts, and v0.2.5 release gates before tagging.

## Non-goals

- Do not change Audio Bridge, Principal Agent, prompts, intervals, API keys,
  or privacy behavior.
- Do not remove older models from the selectors.
- Do not change the Gemini SDK or adopt the Interactions API in this release.
