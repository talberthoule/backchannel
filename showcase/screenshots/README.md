# Backchannel showcase screenshots

Every asset here is captured from a **wholly fictional demo workspace**. No real
employer, client, or person appears in any of them. Safe for public use.

Twenty-three surfaces, each with a light and a `-dark` variant, all 1440x900
before encoding. The source data is "Alderwake Health Network - recovery
readiness review": an invented 46-minute services-integration call between a
distributed account team and two customer-side leaders, seeded by
`showcase/seed_demo.py`. The fixture also seeds five sibling sessions (so the
sidebar passes the six-session threshold where its find box appears) and one
session left in `pre_call` state for the setup screen.

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

The default fixture also inserts eleven `token_usage` rows, one per source
and model, so the Overview's spend tile and the Tokens tab report a real
figure instead of zero. Cached and audio counts are slices of the input total,
never additions; `test_showcase_assets.py` enforces that.

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
| `precall-setup(-dark)` | The redesigned setup screen: the action button pinned at the top with a readiness line, and the steps below as collapsed cards whose headers say what they hold | Pre-call / setup section |
| `postcall-overview(-dark)` | The Overview a completed session opens on: the briefing's top outcome, the counts row including estimated spend, the "9 shielded" badge, and the head of the digest | Post-call results |
| `postcall-overview-digest(-dark)` | The same page scrolled: the four digest lists with owners and status, the participation talk-share table, and the call-rhythm chart | Post-call results |
| `postcall-tokens(-dark)` | The Tokens tab: estimated cost, then per-source and per-model tables with cached and audio columns | Cost transparency |
| `admin-privacy(-dark)` | The PII Shield switched on: the "Personal data tokenized" badge, the four-row coverage list, and the vault count | **PII Shield section** |
| `admin-privacy-preview(-dark)` | The same card in full: categories, the on-device model's state, protected terms, and the try-a-sentence box with its result | PII Shield section, crop source |
| `pii-preview(-dark)` | Crop: a sentence in, the tokenized sentence a model actually receives out, and the legend naming each token's value and how it was found | **PII Shield hero crop** |
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
panel); post-call and pre-call shots keep it, because session and group
organization is part of what they demonstrate. See `CROP_SIDEBAR` in
`showcase/encode.py`.

## The PII Shield in the capture

`capture.mjs` runs `POST /api/sessions/{id}/pii/protect` on the demo session
before any page opens, then hands the shield straight back off. That is the
product's documented path for data recorded before the shield existed, and it
does two things for the asset family:

- The Privacy card reports a real vault count instead of "0 protected values
  across all sessions", which would read as a claim the product is not keeping.
- Every other shot then carries real names on screen while the database holds
  only tokens, so the screenshots are themselves the evidence that
  reveal-at-the-edge works.

The shield is left **off** for every non-privacy surface, because that is the
state a new install is in. The privacy pass turns it on, shoots, and the
`withShieldRestored` wrapper turns it off again - a later pass that started
with it on would lock the audio models and change shots that are not about
privacy.

Note that `pii_vault_entries` holds a foreign key to `sessions` with no
cascade. `reset()` therefore has to empty it (and every other session-scoped
table) before deleting sessions, and `psql()` runs with `ON_ERROR_STOP=1`:
without it psql exits 0 even when a statement raised, so a failed reset
reported success and the seed built a second workspace on top of the first.

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
