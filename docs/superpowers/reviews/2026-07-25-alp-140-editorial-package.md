# ALP-140 Editorial Review Package

Reviewer: `claude-2` (`w2:pG`)

## Draft

- Branch: `talberthoule/alp-140-demo-assets`
- Content commit: `2a5ae2b`
- Compare: `git diff master...2a5ae2b`
- Scope: 63 files, including 24 source PNGs, 30 published WebPs, fixture/capture code, a showcase contract, and homepage copy.

The replacement story is wholly fictional. Alderwake Health Network is a
distributed customer team reviewing an eight-hour recovery result against a
two-hour objective before September board and insurer deadlines. The service
integrator proposes a non-disruptive, isolated pilot below the customer's
single-source procurement threshold, plus a separately priced managed recovery
option.

## Homepage Copy for Review

Hero figure:

> A high-stakes recovery review, handled remotely: objections surface with
> responses already drafted beside the attributed transcript. **24 insights**
> from one 46-minute call, distilled into a single briefing.

During-the-call setup:

> Built for high-stakes sales, discovery, and service-delivery calls -
> especially when the account team is remote. Provider-flexible, centered on a
> transcript you can trust.

Animated objection:

> You are not yet an approved services supplier, although we can buy the
> recovery software through our reseller agreement.

Animated response:

> Keep the fixed recovery pilot below the $90K single-source threshold while
> the broader supplier review continues.

Results:

> A 46-minute call produced 24 grounded signals. You never wade through them.
> Backchannel distills the whole conversation into one briefing of outcomes and
> objectives, so you start from the point instead of the pile.

Insight figure:

> All 24, kept and attributed - 5 action items, 4 objections, 4 opportunities,
> 5 observations, 6 questions.

## Screenshot Manifest

All source PNGs are 1440x900 and exist in light and `-dark` variants.

| Surface | Published dimensions | Content |
| --- | --- | --- |
| `live-call` | 1440x900 | Active recovery review, dual Listening state, two answered objections, attributed transcript |
| `postcall-briefing` | 1440x900 | Fixture-backed outcomes and client objectives |
| `postcall-insights` | 1440x900 | Exact 24-item distribution |
| `postcall-transcript` | 1440x900 | Me, Leah, Owen, and Maya |
| `postcall-speakers` | 1440x900 | Four-person team/external mapping |
| `postcall-chat` | 1440x900 | Grounded commitment and risk answer |
| `admin-agents` | 1185x900 | Nine-agent administration |
| `admin-transcription` | 1185x900 | Transcription and audio settings |
| `admin-api-keys` | 1185x900 | Provider credentials |
| `admin-about` | 1185x900 | Version and release notes |
| `offerings-catalog` | 1185x900 | Three filtered recovery services |
| `knowledge-sources` | 1185x900 | Three selected recovery delivery playbooks |

Derived crops, each in light and dark:

| Crop | Dimensions | Source |
| --- | --- | --- |
| `live-answered` | 732x508 | Two answered Objection Handler cards |
| `insights-attributed` | 1032x460 | Speaker-attributed action items |
| `session-header` | 1032x166 | Original and resumed call segments |

## Representative Captures

- Hero: `showcase/screenshots/live-call.png`
- Hero dark: `showcase/screenshots/live-call-dark.png`
- Briefing: `showcase/screenshots/postcall-briefing.png`
- Insights dark: `showcase/screenshots/postcall-insights-dark.png`
- Chat: `showcase/screenshots/postcall-chat.png`
- Catalog dark: `showcase/screenshots/offerings-catalog-dark.png`
- Knowledge dark: `showcase/screenshots/knowledge-sources-dark.png`
- Answered crop: `site/assets/shots/live-answered.webp`
- Answered crop dark: `site/assets/shots/live-answered-dark.webp`
- Attribution crop: `site/assets/shots/insights-attributed.webp`
- Session crop: `site/assets/shots/session-header.webp`

## Checks Already Run

- `python -m unittest showcase.test_showcase_assets -v`: 5 passed
- Capture run: all 12 surfaces in both themes
- `npm run build` in `docs-site`: passed, 12 docs pages assembled
- Local homepage: 1440px and 320px, no horizontal overflow, new count present,
  retired count absent

## Requested Verdict

Review clarity, credibility, internal consistency, claim accuracy, privacy,
alt/caption accuracy, and whether the story communicates value for distributed
teams in consequential customer calls.

Return one of:

- `APPROVED` with optional polish notes, or
- `CHANGES REQUIRED` with exact actionable edits.
