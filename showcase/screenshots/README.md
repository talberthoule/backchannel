# Backchannel showcase screenshots

Every asset here is captured from a **wholly fictional demo workspace**. No real
employer, client, or person appears in any of them. Safe for public use.

Twelve surfaces, each with a light and a `-dark` variant, all 1440x900 unless
cropped. The source data is "Northwind Logistics -- segmentation review": an
invented 46-minute discovery call between an account lead, a solutions
architect, and two customer-side people, seeded by `showcase/seed_demo.py`.

## Regenerating the whole set

```bash
docker compose up -d                        # app at localhost:3000
python showcase/seed_demo.py --reset --analyze
node showcase/capture.mjs
python showcase/encode.py                   # PNG -> site/assets/shots/*.webp
python showcase/crops.py                    # focused crops from those captures
```

`--analyze` runs the real analysis agents over the fictional transcript, so the
insights are genuinely model-generated rather than hand-written. It needs a
configured LLM key; without one, `seed_demo.py` falls back to a canned insight
set and `capture.mjs` skips the briefing and chat shots with a notice.

Repeat `POST /api/sessions/{id}/analyze` a few times to accumulate a fuller
insight set -- one pass produces roughly ten, and the committed captures show 56
after six passes. The live-call hero is captured separately with Chrome's fake
media device, since the live view needs a microphone stream to start.

## Asset guide

| Asset | Shows | Placement |
| --- | --- | --- |
| `live-call(-dark)` | Live call: dual Listening indicators, filterable rail of 56 live insights, answered objection cards with drafted responses, live speaker-attributed transcript | **Hero** |
| `live-answered(-dark)` | Crop: two Answered objection cards, each badged Objection Handler and attributed, with the drafted response beneath | "Questions answer themselves" |
| `postcall-briefing(-dark)` | Conversation briefing: TOP 3 OUTCOMES beside OBJECTIVES, each with owner and status | Briefing / results section |
| `postcall-insights(-dark)` | Insights tab: 56 total, 13 action items, 5 objections, 8 opportunities, 7 observations, 23 questions | Post-call results |
| `insights-attributed(-dark)` | Crop: insight cards carrying agent badge and speaker attribution | Agents feature; speaker re-attribution |
| `session-header(-dark)` | Crop: two call segments totalling 46m 12s, dated, 56 insights | Wrap-up proof strip |
| `postcall-transcript(-dark)` | Speaker-attributed transcript with timestamps | Transcription feature |
| `postcall-speakers(-dark)` | Speakers tab: name mapping, team/external tagging, merge controls | Diarization feature |
| `postcall-chat(-dark)` | Cross-session chat with a grounded answer and scope pickers | Cross-meeting Q&A |
| `admin-agents(-dark)` | Admin: Privacy First toggle, nine-agent lineup with per-agent models | Self-hosting / privacy |
| `admin-transcription(-dark)` | Admin: transcription and audio settings | Docs |
| `admin-api-keys(-dark)` | Admin: provider credentials | Docs |
| `admin-about(-dark)` | Admin: version and release notes | Docs |
| `offerings-catalog(-dark)` | Offerings catalog used by the opportunity specialist | Docs |
| `knowledge-sources(-dark)` | Knowledge sources configuration | Docs |

Admin and tool panels are cropped to drop the left sidebar (they are about the
panel); post-call shots keep it, because session and group organization is part
of what they demonstrate. See `CROP_SIDEBAR` in `showcase/encode.py`.

## Curation rules

Everything in this directory is fictional and safe. Keep it that way:

- **Never capture from a real call.** A previous asset family came from an
  unscrubbed real recording and had to be retired. Those files now live in
  `showcase/archive/2026-07-24-retired-user-assets/` for comparison only; do not
  return them to the site.
- **Never publish a real-to-pseudonym mapping.** Recording that "X stands for Y"
  in any tracked file re-identifies every screenshot the pseudonym protected.
  That mistake was made once in `lessons/showcase-session-teardown.md` and fixed.
- If you extend `seed_demo.py`, keep every company, person, and figure invented.
  Those rows become public screenshots.

## Badge labels: lenses vs agents

The insight-card badges -- "Question Hunter", "Opp. Scout", "Objection Handler"
-- are **current, user-visible labels**, not stale artifacts. They render today
from `AGENT_LABELS` in `frontend/src/components/ActiveCall/QuestionCard.tsx`. Do
not "correct" them in copy describing these images.

What they are NOT is three peer agents:

- `question_hunter` and `opportunity_scout` (plus `observer` and
  `action_tracker`) are per-item-type **source labels** stamped on insights from
  the single `consolidated_analyst` agent. See `AGENT_SOURCE_BY_TYPE` in
  `backend/app/services/agents/consolidated_analyst.py`. They are lenses of one
  agent.
- `objection_handler` is the only one of those badges that is an agent in its
  own right.

The authoritative roster is `backend/app/services/seed_agents.py`: nine agents
-- `audio_gateway`; five live (`consolidated_analyst`, `objection_handler`,
`synthesizer`, `opportunity_specialist`, `strategic_signals`); and three
briefing lenses (`brief_meeting_lens`, `brief_discovery_lens`, `brief_arbiter`).
Cite that file when counting agents; do not count badges.

## Known gaps

- **Post-processing progress strip.** No current equivalent; the homepage figure
  that used one was removed rather than filled with an unrelated image.
- **Enhanced-insights shot.** `POST /api/sessions/{id}/enhance-insights` returns
  `unchanged` against this demo, because the seeded speakers are named at
  creation so there is no re-attribution to apply. Producing a genuine one needs
  a session whose speakers start unmapped.
