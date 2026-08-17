# Backchannel showcase screenshots

Every asset here is captured from a **wholly fictional demo workspace**. No real
employer, client, or person appears in any of them. Safe for public use.

Sixteen surfaces, each with a light and a `-dark` variant, all 1440x900 before
encoding. The source data is "Alderwake Health Network - recovery readiness
review": an invented 46-minute services-integration call between a distributed
account team and two customer-side leaders, seeded by `showcase/seed_demo.py`.

## Regenerating the whole set

Capture against an isolated compose project, never the long-lived dev stack:
`seed_demo.py --reset` deletes every session in whatever database it reaches
(it nearly cost the ALP-295/ALP-301 validation sessions once).

```bash
docker compose -f docker-compose.yml -f showcase/docker-compose.capture.yml \
  -p backchannel-capture up --build -d    # app at localhost:3100
COMPOSE_PROJECT_NAME=backchannel-capture BACKCHANNEL_SHOWCASE_BASE=http://localhost:3100 \
  python showcase/seed_demo.py --reset
BACKCHANNEL_SHOWCASE_BASE=http://localhost:3100 node showcase/capture.mjs
python showcase/encode.py                   # PNG -> site/assets/shots/*.webp
python showcase/crops.py                    # focused crops from those captures
node showcase/og_card.mjs                   # site/assets/og-image.png
docker compose -p backchannel-capture down -v
```

Reseed immediately before capturing, and capture once. Reaching the live view
resumes the session, so every extra capture run adds another call segment to
the fixture and the session header drifts from "across 2 calls".

The default fixture is intentionally deterministic: it inserts 125 insights
(24 curated, transcript-grounded rows plus 2 `asked` rows, which top every
newest-first list and are the only cards visible in shots, plus 99 generated
filler rows seeded earlier in the call to make the counts read like a dense
46-minute session), a completed briefing, and a `live` synthesis row carrying
the five strategic-signal cards and six kept signals; it seeds three recovery
offerings and three delivery playbooks, and injects a canned chat exchange
through the product's real session-storage contract. No LLM key is required.
Use `--analyze` only for local exploratory runs; do not use it for committed
assets. The capture script starts the real live view with Chrome's fake media
device and restores the session to completed when it finishes.

## Asset guide

| Asset | Shows | Placement |
| --- | --- | --- |
| `live-call(-dark)` | Live recovery review: Listening status, the live strategic-signal strip, 125 saved insights, an answered mid-call question, and a speaker-attributed transcript | **Hero**, README, OG card, comparison pages |
| `live-ask(-dark)` | The same call with a question typed into the command bar, unsent | "Ask the call a question" |
| `live-objections(-dark)` | The live feed filtered to objections, leading with the answered card and its drafted response | Comparison pages (objection handling) |
| `live-questions(-dark)` | The live feed filtered to questions, leading with the synthesizer's full story on one card | Crop source |
| `live-answered(-dark)` | Crop: the answered question card - marked Answered, answer summarized, follow-up spun off | "Questions answer themselves" |
| `ask-bar(-dark)` | Crop: the command bar with its Chat/Directive modes and the answering model chip | Detail strip |
| `postcall-briefing(-dark)` | Conversation briefing: at-a-glance strip, kept signal history, and TOP 3 OUTCOMES with named owners | Briefing / results section |
| `postcall-signals(-dark)` | Strategic Signal History expanded: six kept signals with counts and first/last sighting | "Nothing raised is quietly dropped" |
| `postcall-insights(-dark)` | Insights tab: 125 total, 2 asked, 24 action items, 16 objections, 18 opportunities, 31 observations, 34 questions | Post-call results |
| `postcall-attributed(-dark)` | The same tab scrolled to the action items themselves | Crop source |
| `insights-attributed(-dark)` | Crop: insight cards carrying speaker attribution and follow-up state | Speaker re-attribution |
| `session-header(-dark)` | Crop: two call segments totalling 46m 12s, dated, 125 insights | Wrap-up proof strip |
| `postcall-transcript(-dark)` | Speaker-attributed transcript with timestamps | Transcription feature |
| `postcall-speakers(-dark)` | Speakers tab: name mapping, team/external tagging, merge controls | Diarization feature |
| `postcall-chat(-dark)` | Fixture-backed cross-session chat answer with scope pickers | Cross-meeting Q&A |
| `admin-agents(-dark)` | Admin: Privacy First toggle, nine-agent lineup with per-agent models | Self-hosting / privacy |
| `admin-transcription(-dark)` | Admin: transcription and audio settings | Docs |
| `admin-api-keys(-dark)` | Admin: provider credentials | Docs |
| `admin-about(-dark)` | Admin: version and release notes | Docs |
| `offerings-catalog(-dark)` | Three recovery services in the catalog used by the opportunity specialist | Docs |
| `knowledge-sources(-dark)` | Selected recovery-delivery collection with three fictional playbooks | Docs |

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
