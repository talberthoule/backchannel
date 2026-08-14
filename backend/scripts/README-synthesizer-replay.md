# Synthesizer replay harness

Offline A/B for the synthesizer's prompt payload, used to measure ALP-283
(working-set serialization) and its interaction with ALP-285 (prompt caching).

`synthesizer_replay.py` loads the real shipped `_build_insights_json` from a git
ref and from the working tree, then replays a captured insight corpus through
both at the real cycle times. Neither side is a reimplementation.

## Why this exists rather than an end-to-end test

`POST /api/sessions/{id}/analyze` is a single-shot call. It never instantiates
the orchestrator and never invokes the synthesizer, so importing a transcript
and analyzing it cannot exercise the synthesizer at all. A live call can, but
costs real API spend and takes as long as the meeting.

## The captured corpus is not in this repository

This repository is public. A captured corpus is a real meeting: `t.json` holds
verbatim transcript text and `q.json` holds insight rationale and
`source_context` derived from it. Neither is committed, and neither should be.

Point the harness at a directory outside the repository:

```
export BACKCHANNEL_REPLAY_DATA=/path/to/captured/session
```

## Capturing a corpus

Any completed session works. Against a running backend (Docker on :8001, or the
desktop instance on the port in its `launcher.json` — neither needs auth from
localhost):

```
curl -s "$API/api/sessions/$SID/questions"              > q.json
curl -s "$API/api/sessions/$SID/transcripts?limit=5000" > t.json
curl -s "$API/api/sessions/$SID/speakers"               > speakers.json
```

Note `/transcripts` is plural. Capture `GET /api/sessions/$SID/token-usage` too
if you want to check replay fidelity against real billed input.

## Running

From `backend/`:

```
python scripts/synthesizer_replay.py payload
python scripts/synthesizer_replay.py prefix
python scripts/synthesizer_replay.py scale --baseline origin/master
```

- `payload` — input-token totals, baseline vs working tree
- `prefix` — cacheable-prefix retention between consecutive cycles
- `scale` — how both vary with call length

## Reading the output honestly

**Ratios, not absolutes.** The replay fires cycles on a strict cooldown; real
cycles sometimes space wider, so totals over-predict a measured run by roughly a
quarter. Both sides share the model, so the ratio survives what the absolute
does not.

**`raw win` needs no assumptions. `net win` needs two.** Raw is payload
reduction with no caching anywhere, which is the current state of the codebase.
Net additionally assumes ALP-285's 75 percent cached-input discount — explicitly
unverified for the Gemini versions in use — and assumes the corpus is in prefix
position at all, which on any install with pre-existing `agent_configs.prompt`
rows requires an operator prompt reset first (ALP-285). Quote raw freely; always
qualify net.

**Call length changes the answer.** A record cannot flip full-to-stub before
ageing past `SYNTHESIZER_WORKING_SET_SECONDS`, so a short validation call shows
no conflict and produces a false all-clear. Run `scale` before designing a paid
validation call.

**Token counts are `chars / 4.0`**, calibrated against a measured reference blob
and accurate there to within a few percent. It avoids a paid `count_tokens`
round trip. If a provider's tokenizer diverges materially, recalibrate before
trusting cross-provider comparisons.
