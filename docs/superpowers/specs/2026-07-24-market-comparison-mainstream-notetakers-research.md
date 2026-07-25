# Mainstream AI notetakers - competitive research (2026-07-24)

Lead E. All vendor facts below were fetched live on 2026-07-24 unless a
different access date is noted. Every price and limit is a snapshot; treat
anything older than about 60 days as suspect before it ships on a public page.

## Category summary

This is the commodity tier: the highest search volume in the category and the
lowest strategic depth. Four things changed since the Otter, Fireflies, and
Granola pages were published (schema `dateModified` 2026-07-13) and they change
what a Backchannel page in this tier can honestly claim.

**1. Bot-free capture stopped being a differentiator.** Fathom shipped bot-free
capture on 2026-04-15 as part of Fathom 3.0 (Mac only; Windows "coming soon").
Avoma's own pricing page lists "Bot-less Native Recording and Bot-based
Recording". Granola and Otter already had non-bot desktop capture. The bot is
still the loudest complaint in G2 reviews for Fireflies, tl;dv, and Read AI, but
"no bot joins the call" is now a feature the incumbents advertise too. Leading
with it in 2026 makes Backchannel look like a follower.

**2. Real-time in-call assistance stopped being a differentiator, at a price.**
Otter shipped Live Assist on 2026-07-21 -- three days before this research --
positioned as "the first real-time AI coaching agent that joins any call",
Enterprise-only. Fathom's Mac desktop app now shows live summaries and an
in-meeting scratchpad, with "Real-Time Coaching" marked "Coming soon". Read AI
has had a live meeting dashboard with real-time sentiment, engagement, talk
time, and coaching tips for some time. Avoma sells a "Real-time Answer
Assistant" inside its $29-35/user/mo Conversation Intelligence add-on.

What survives is narrower and still true: nobody in this tier gives you
**content-level** live assistance -- the specific next question, a scripted
response to the objection that was just raised, an opportunity flagged against
your own offerings catalog -- for free, on hardware you control, with the
prompt and model of each agent editable. Otter and Avoma gate it behind
Enterprise or an add-on; Fathom and Read AI's live layer is summaries and
behavioral metrics (talk time, filler words, sentiment), not tactical content.

**3. Free tiers diverged violently.** Fathom's free tier is genuinely excellent
and we cannot beat it on cost-of-entry. tl;dv's and Read AI's free tiers got
meaningfully worse. Avoma removed the permanent free plan entirely.

**4. The open-source niche has an incumbent.** Meetily (MIT, ~25.7k GitHub
stars) now ranks on page one for "Read AI alternative", is listed on
openalternative.co as the open alternative to Granola/Otter/tl;dv, and
publishes its own per-competitor "vs" pages. It is the project Backchannel has
to beat in the only sub-SERP of this category that is actually winnable.

The strategic conclusion, stated up front: **do not write four pages.** Write
two, fold two, and add a hub page that competes where the SERP is soft.

## Per-competitor profiles

### Fathom (primary target)

**Positioning.** The default free AI notetaker. Rebranded from fathom.video to
fathom.ai (fathom.video/pricing now 301s to fathom.ai/pricing; the help center
still lives on help.fathom.video). Homepage claims "Used at 300K+ companies" and
"SOC 2 Type II | GDPR | HIPAA Compliant | SSO / SCIM". Roughly 6,780 G2 reviews
at about 5.0 -- an order of magnitude more than Grain, Spinach, or Circleback,
and the best popularity proxy in this set.

**Pricing (fathom.ai/pricing, accessed 2026-07-24).**

| Plan | Monthly | Annual |
| --- | --- | --- |
| Free | $0 "Free forever" | $0 |
| Premium (individual) | $20/user | $16/user/mo |
| Team (min 2 users) | $19/user | $15/user/mo |
| Business | $34/user | $25/user/mo |
| Enterprise | Custom | Custom |

**What the free tier actually includes.** This is where honesty matters most.
The pricing page advertises "Unlimited recordings + transcriptions", "Instant AI
call summaries", "Clips, playlists + search across calls", and "Choice of
bot-free (in beta) or bot capture-types". Fathom's own help center
(help.fathom.video/en/articles/5290881) adds the catch: Free and Premium both
get "Unlimited recordings & storage" and "Unlimited transcriptions in 38
languages", but Free gets "Advanced summaries for your first 5 calls each month"
and only general templates after that. AI Action Items, AI Follow-Up Emails,
custom summaries, and Ask Fathom are Premium-only. CRM sync (HubSpot,
Salesforce, Close) is on both tiers for up to 3 users per email domain.

**The honest concession, stated plainly.** Unlimited recording, unlimited
storage, and unlimited transcription in 38 languages, forever, for $0, with
zero setup, is a better cost-of-entry story than Backchannel's. Backchannel is
$0 in license terms but costs a Docker host, a GPU-optional server, and either
LLM API spend or the accuracy hit of local ONNX models. Anyone who claims
Backchannel is "cheaper than Fathom" for a single user is lying. The cost
argument only works at team scale (Fathom Business is $25/user/mo annual, so 20
seats is $6,000/yr) or when the buyer's constraint is data location rather than
money.

**Capture model.** Bot participant by default; bot-free capture via the desktop
app, Mac only, with Windows listed as "coming soon" on fathom.ai/whats-new.
"Bot-free recording means Fathom now works in Slack Huddles". iOS app and a CLI
with "local export of your call data in open formats" are both "coming soon".

**Where audio is processed.** Fathom's cloud. Per Fathom's privacy
documentation, Fathom "may use de-identified data generated from Meeting Content
Information ... training, improving, and customizing their in-house artificial
intelligence models, based on how you configure your account settings", with an
opt-out in account settings and an org-wide opt-out for Team Edition. Third-party
subprocessors (Anthropic, OpenAI, Google) are contractually barred from training
on customer data. This is the sharpest true hook against Fathom: the free tool
is free partly because the meetings feed the model, and the control is an
opt-out rather than an opt-in.

**Real-time vs post-call.** Both, now. Fathom 3.0 (2026-04-15) added "Live
summaries update as your call unfolds" plus "a built-in scratchpad ... to
capture personal notes in real time". Real-Time Coaching is listed as "Coming
soon!" in the desktop app help article. So Fathom has live *recording of what
happened*; it does not yet have live *advice about what to do next*.

**Diarization.** Speaker identification is present but not marketed as a
differentiator, and speaker-attribution errors appear in third-party reviews.
Not verified in vendor documentation; low confidence.

**Genuine overlaps.** Bot-free browser/desktop capture across any meeting app;
unmetered recording and transcription; live in-meeting surface; works with Zoom,
Meet, Teams without per-platform integration; MIT-adjacent openness gestures
(CLI with open-format export, ChatGPT/Claude MCP).

**What Backchannel has that Fathom lacks.** Audio and transcripts that never
reach a vendor; no de-identified training on your conversations at all; a live
crew of content agents (consolidated analyst, objection handler with a suggested
response plus underlying concern, strategic signals cards, opportunity matching
against your own offerings catalog) rather than a live summary; per-agent model,
prompt, and trigger editable in an admin panel; fully offline transcription via
local ONNX Whisper/Parakeet; a bot-free path that works on Windows and Linux
today, not "coming soon"; re-transcription of stored audio through a different
model later.

**What Fathom has that Backchannel lacks (ruthlessly).** A free tier with better
zero-setup economics than ours. 38 languages with a stated matrix; we have no
marketed language support at all. SOC 2 Type II, GDPR, HIPAA badges, SSO/SCIM.
CRM sync to HubSpot/Salesforce/Close. Clips, playlists, account-wide search
across every call. ChatGPT and Claude MCP integrations. 300K+ companies of
social proof and ~6,780 G2 reviews vs our zero. A polished native desktop app.
Slack Huddles support. Coming: iOS and in-person capture.

**Recurring complaints.** The visible "Fathom Notetaker" participant is the
single most common negative theme on G2 (reported at roughly 415 negative
mentions; medium confidence, third-party aggregation). No in-person or wearable
capture. Hallucinated transcript segments reported on Zoom. No mobile app yet.
Cannot transcribe uploaded audio files (medium confidence). Training-on-data is
opt-out rather than opt-in.

**Sharpest true differentiator.** Not price and not "no bot". It is: *Fathom's
free tier is paid for with de-identified training on your meetings and storage
in Fathom's cloud; Backchannel's is paid for with a Docker host you already
own.* Second: live tactical content agents vs live summaries.

**Distinctness from our existing pages.** Genuinely distinct. Otter's page is
built on minute caps, Fireflies' on the bot plus storage meters, Granola's on
local capture with cloud processing plus a history paywall. None of them
addresses "the free tool is actually free and actually bot-free -- so why would
I self-host?" That is a new and harder objection, and it is the one the largest
audience in this category is asking.

**Sources.** https://fathom.ai/pricing ; https://help.fathom.video/en/articles/5290881 ;
https://www.fathom.ai/ ; https://www.fathom.ai/whats-new ;
https://help.fathom.video/en/articles/449088 ;
https://www.businesswire.com/news/home/20260415965820/en/Fathom-Unveils-Major-Platform-Update-Adding-Bot-Free-Capture-Account-Wide-Meeting-Insights-and-Widely-Expanded-LLM-Integrations (title and date verified via search; body 403/ECONNRESET on fetch)

### Read AI

**Positioning.** A cross-surface "connected intelligence" product: meetings plus
email plus messaging, with engagement analytics and a Read Score. Native apps on
Windows, macOS, Android, iOS plus a web extension.

**Pricing (read.ai/pricing, accessed 2026-07-24).**

| Plan | Annual (25% off) | Monthly | Meeting cap |
| --- | --- | --- | --- |
| Free | $0 | $0 | 1 hour |
| Pro | $15/mo | $19.75/mo | 4 hours |
| Enterprise | $22.50/mo | $29.75/mo | 4 hours |
| Enterprise+ (5+ licenses) | $29.75/mo | $39.75/mo | 8 hours |

**Free tier limits.** "5 meeting transcripts per month" and 5 meeting reports per
month, 1 hour maximum meeting length. Included free: unlimited enterprise
search, summaries across meetings/email/messaging, personalized meeting coach,
basic integrations, Topic Readouts, 20+ languages. Notably, **audio and video
playback is an Enterprise-tier feature** -- neither Free nor Pro gets recording
playback. Pro adds unlimited transcripts, 100 file-upload credits/mo, and
premium integrations (Notion, Salesforce, HubSpot, Jira, Confluence, Zapier,
webhooks). Enterprise+ adds HIPAA, SAML/SCIM, domain capture, and custom data
retention.

**Capture model.** Bot participant that auto-joins from calendar. This is the
crux of Read AI's reputation problem.

**Where audio is processed.** Read AI's cloud. The security overview page
returned 403 to automated fetch, so specifics on subprocessors and residency are
unverified here; do not make claims about them on a public page.

**Real-time vs post-call.** Genuinely real-time, but behavioral rather than
tactical. Read's live meeting dashboard shows real-time sentiment and engagement
scores, meeting timer, talk time, words per minute, and coaching tips, and
flags significant swings in sentiment or engagement. Read's marketing states the
scores come from analyzing "facial and verbal elements of all meeting attendees"
-- i.e. camera analysis of everyone in the call, including people who never
agreed to be scored. (Medium confidence: Read's own help center article on
Sentiment, Engagement and the Read Score returned 403; the facial-analysis
description comes from Read's marketing pages via search summary. Verify before
publishing.)

**Genuine overlaps.** Real-time in-meeting surface; speaker-level analytics;
multi-meeting search; cross-surface chat over your own history.

**What Backchannel has that Read AI lacks.** No bot that can appear in someone
else's meeting; no calendar auto-join; no analysis of participants' faces; audio
that never leaves your server; unlimited transcripts on the free (only) tier
vs Read's 5/month; recording playback and re-transcription without an Enterprise
upgrade; open source you can hand to an IT security reviewer instead of a
questionnaire.

**What Read AI has that Backchannel lacks.** Native apps on four platforms plus
a browser extension. Email and chat ingestion, not just meetings. Engagement and
sentiment scoring as a product. 20+ languages. Premium integrations across
Notion, Salesforce, HubSpot, Jira, Confluence, Zapier, webhooks. HIPAA, SAML,
SCIM, domain capture, custom retention at Enterprise+.

**Recurring complaints.** These are unusually severe and unusually
well-documented, which is what makes this target worth a page:

- Chapman University IS&T published a security notice on 2025-08-13 stating "the
  use of Read AI is prohibited due to security, privacy, and institutional data
  risks", and is "blocking the addition of the Read AI app in both Zoom and
  Microsoft Teams".
- UW-Madison's IT knowledge base (created 2024-07-25, updated 2025-04-24)
  documents that "if you intentionally create a read.ai account, it will
  automatically join your meetings by default", and that "if you click an email
  invite/link to view someone else's read.ai report, we have seen that read.ai
  can create an account for you without knowing. Then it starts joining your
  meetings."
- Microsoft Q&A threads exist specifically asking how to block Read.ai from
  joining Teams meetings.
- Reported behavior of sending summaries automatically to external attendees,
  which means internal commentary can reach a customer.

Read AI disputes the framing, stating it requests permission, appears as a
participant, posts a chat message explaining itself, and never joins meetings it
was not added to by an invited user. Present both sides; the documented
institutional bans are the load-bearing fact, not the characterization.

**Sharpest true differentiator.** *Backchannel cannot show up in a meeting you
did not put it in, cannot spread through your calendar, and cannot score
anyone's face -- because it is a browser tab on your side of the call running on
your own server.* This is an IT/security-reviewer objection, not a rep
objection, and none of our existing pages speaks to it.

**Distinctness from our existing pages.** The most distinct target in the set.
The Fireflies page argues "a bot in the room is awkward on external calls" -- a
sales-rep framing. The Read AI objection is "a tool I never approved is joining
meetings across my organization and my university/employer banned it" -- a
governance framing, and it comes with citable primary sources from institutions.
That is a different page with a different buyer and different proof.

**Sources.** https://www.read.ai/pricing ;
https://blogs.chapman.edu/information-systems/2025/08/13/security-notice-regarding-read-ai/ ;
https://kb.wisc.edu/138719 ; https://www.read.ai/meeting-tools ;
https://support.read.ai/hc/en-us/articles/33462537362579-Using-Read-s-live-meeting-dashboard (title only; 403 on body)

### tl;dv

**Positioning.** Berlin-based, EU-hosted, sales-coaching-leaning meeting recorder
with an aggressive free tier headline and severe fine print. Roughly 512 G2
reviews.

**Pricing.** The canonical pricing page is https://tldv.io/app/pricing/ ;
https://tldv.io/pricing/ now 404s and the live page returned only metadata to
automated fetch, so the tier prices below are **third-party, low-to-medium
confidence** and must be re-verified in a browser before publication: Pro about
$29/user/mo monthly or $18/user/mo annual; Business about $98/user/mo monthly or
$59/user/mo annual; Enterprise custom. A 40% annual promotion is running.

**Free tier limits (vendor help center, last updated 2025-11-24 -- high
confidence).** Unlimited recordings and transcripts, but:

- "Your first 10 meetings will have automatic AI notes"; after that "only the
  first 10 minutes of each meeting will have automatic AI notes".
- "You get 10 free AI prompts" and "You can receive 10 free AI Reports".
- "These limits are for the lifetime of the account, they do not renew monthly."
- "Recordings on the Free plan are stored for 3 months", with a 4-week download
  warning window; outside that window free-plan recordings cannot be downloaded
  at all.
- After 3 days, free recordings move to archived storage; unarchiving "can take
  up to an hour and a half".
- 3-hour maximum per recorded or uploaded meeting; 4 free clips; 5 free file
  uploads; 20 integration credits; no simultaneous or overlapping recordings.

**Capture model.** Visible bot participant.

**Where audio is processed.** tl;dv's cloud, but EU/EEA only: GCP, AWS, and
Hetzner data centers in Europe, with object storage on Wasabi S3, AES-256 at
rest, and ISO 27001 / SOC 1 and 2 certified facilities. This is a real strength
and it partially neutralizes our data-sovereignty pitch for EU buyers, who can
get GDPR-native residency without running anything.

**Real-time vs post-call.** Post-call. Live transcript display exists; the AI
value lands afterward.

**Genuine overlaps.** Multi-platform meeting coverage; transcript plus AI notes;
cross-meeting search on paid tiers.

**What Backchannel has that tl;dv lacks.** No bot; no lifetime AI caps; no
3-month deletion; live content agents; local diarization; self-hosting; source
you can audit.

**What tl;dv has that Backchannel lacks.** 30+ languages. EU data residency with
certified facilities. CRM sync and sales playbooks on Business. Mobile apps.
An actual company with support.

**Recurring complaints.** Intrusive bot; the "unlimited" headline colliding with
lifetime AI caps and 3-month deletion; slow support at peak; misassigned
speakers; mobile app upload and sync bugs.

**Sharpest true differentiator.** "Unlimited recordings" that quietly become
10-minute AI notes forever and vanish after 3 months, versus a database you own
where nothing expires. It is a good line -- but it is the *same* line as the
Otter page ("the free tier is metered") and the Fireflies page ("meters
everywhere").

**Distinctness from our existing pages.** Low. The bot objection duplicates
Fireflies. The metering objection duplicates Otter and Fireflies. The history
objection duplicates Granola. Its one distinct attribute -- EU residency --
argues for tl;dv, not for us. **A standalone tl;dv page would cannibalize three
existing pages and win nothing.**

**Sources.** https://intercom.help/tldv/en/articles/8919450-what-are-the-limits-of-the-free-plan ;
https://tldv.io/app/pricing/ (metadata only) ;
https://www.claap.io/blog/tl-dv-pricing (competitor blog, 2025-12-30; prices
low confidence) ; https://tldv.io/features/security-commitment/ (via search
summary)

### Avoma

**Positioning.** Not a notetaker. A revenue platform: meeting assistant plus
scheduling plus conversation intelligence plus revenue intelligence plus lead
routing. The buyer is RevOps or a sales leader, not an individual.

**Pricing (avoma.com/pricing, accessed 2026-07-24).**

| Plan | Annual | Monthly | Seats |
| --- | --- | --- | --- |
| Startup | $19/user/mo | $29/user/mo | up to 25 paid |
| Organization | $24/user/mo | $39/user/mo | up to 100 paid |
| Enterprise | $39/user/mo (annual only) | $39/user/mo | min 10 paid |
| Conversation Intelligence add-on | $29/user/mo | $35/user/mo | -- |
| Revenue Intelligence add-on | $29/user/mo | $35/user/mo | -- |
| Lead Router add-on | $19/user/mo | $25/user/mo | -- |

**Free tier.** None permanently. A 14-day unrestricted Organization trial with
all add-ons, no credit card, plus "Viewers and Collaborators are always free" for
read-only access. (Note: at least one third-party blog claims an Avoma "Basic"
$0 plan with about 10 meetings/month still exists; G2 and ZoomInfo both state
there is no permanent free plan, and the vendor pricing page shows only the
trial. Treat "no free tier" as medium-high confidence and re-verify before
publishing a claim either way.)

**Capture model.** Both. The pricing page lists "Bot-less Native Recording and
Bot-based Recording".

**Where audio is processed.** Avoma's cloud. Unlimited recording storage on all
tiers. HIPAA, SSO (SAML/OIDC), custom retention, and mutually signed DPAs at
Enterprise.

**Real-time vs post-call.** Real-time transcription in 70+ languages on all base
plans, with speaker identification. A "Real-time Answer Assistant" sits inside
the $29-35/user/mo Conversation Intelligence add-on. This is the closest
commercial analog to Backchannel's live objection handler in the entire
mainstream tier -- and it costs about $53-74/user/mo all-in to reach.

**Genuine overlaps.** Real-time transcription; speaker identification; live
in-call answer assistance; an ask-your-meetings chat surface; Avoma even ships an
MCP server exposing transcripts to Claude Desktop and ChatGPT (medium
confidence).

**What Backchannel has that Avoma lacks.** Self-hosting; $0; no bot required at
all; open source; per-agent prompt editing.

**What Avoma has that Backchannel lacks (this list is long and that is the
point).** Native CRM integration with Salesforce, HubSpot, Zoho, Pipedrive, and
Copper. AI deal risk alerts, deal health scores, roll-up forecasting, win-loss
analysis, pipeline reports. Auto call scoring and custom AI scorecards for
SPICED, Sandler, MEDDICC, MEDDIC, BANT. Smart playlists and rule-based curation.
Scheduling, round-robin routing, and inbound lead qualification. 70+ languages.
Coaching recommendations. A designated CSM. Unlimited free viewer seats. HIPAA,
SSO, DPAs.

**Recurring complaints.** Price stacking via add-ons; complexity; the platform
is overkill for teams that only want notes.

**Sharpest true differentiator.** Honestly, there is not a clean one, because
Backchannel is not in Avoma's category. The only true statement is "if all you
wanted from Avoma was the real-time answer assistant, Backchannel does that part
for free on your own hardware" -- which is a narrow, defensible, and small
claim.

**Distinctness from our existing pages.** Distinct buyer, but for the wrong
reason: Avoma's buyer wants CRM sync, forecasting, and methodology scorecards,
and Backchannel has none of those. A page would either be dishonest or would
spend most of its length listing what we do not have.

**Sources.** https://www.avoma.com/pricing ; https://www.g2.com/products/avoma/pricing
(free-plan status corroboration) ; https://pipeline.zoominfo.com/sales/avoma-review

### Fifth target: recommendation is to add none

Candidates were Supernormal, Circleback, Grain, and Spinach. Popularity proxies
put all of them an order of magnitude below Fathom: Grain has about 307 G2
reviews against Fathom's roughly 6,780. Circleback's live dashboard and
Supernormal's bot-less positioning are interesting but neither carries enough
demand to justify a dedicated page ahead of the hub page recommended below, and
each additional near-identical page raises the internal-cannibalization risk
that is already the main threat in this tier. Recommendation: cover all four as
rows in the hub page instead. If one must be promoted later, Circleback is the
best candidate because it already ranks on page one for "Read AI alternative"
and shares the live-dashboard framing, which lets it ride the Read AI page's
internal links.

## Overlap and novelty matrix

Backchannel column reflects `CLAUDE.md`, `docs/agents.md`, `docs/audio-pipeline.md`,
and `site/llms.txt` as of 2026-07-24.

| Dimension | Fathom | tl;dv | Read AI | Avoma | Backchannel |
| --- | --- | --- | --- | --- | --- |
| Free tier exists | Yes, strong | Yes, heavily capped | Yes, 5 transcripts/mo | No (14-day trial) | N/A -- entire product is free |
| Free tier hard caps | 5 advanced summaries/mo | 10 AI notes lifetime; 3-month deletion | 5 transcripts/mo; 1h meetings; no playback | -- | None; disk and API budget only |
| Entry paid price (annual) | $16/user/mo | ~$18/user/mo (low conf.) | $15/user/mo | $19/user/mo | $0 |
| Bot-free capture | Yes, Mac only, Windows "coming soon" | No | No | Yes (bot-less native option) | Yes, all platforms, always |
| Where audio is processed | Fathom cloud | tl;dv cloud, EU/EEA only | Read AI cloud | Avoma cloud | Your server |
| Fully offline transcription | No | No | No | No | Yes, local ONNX Whisper/Parakeet |
| Trains vendor models on your data | De-identified, opt-out | Not verified | Not verified | Not verified | Never -- no vendor in the path |
| Real-time in-call output | Live summaries + scratchpad (Mac) | None | Sentiment, engagement, talk time, coaching tips | Real-time Answer Assistant (paid add-on) | Questions, objection responses with strategy, opportunities, action items, strategic signal cards |
| Live output is tactical content | No | No | No, behavioral | Yes, but $53-74/user/mo all-in | Yes, free |
| Speaker diarization | Yes, not marketed | Yes, error complaints | Yes | Yes | Yes -- local Silero VAD + WeSpeaker ResNet152; optional NVIDIA Sortformer on GPU |
| Split mic/system speaker identities | No | No | No | No | Yes, dual-track with `sys_` remote IDs |
| Re-transcribe stored audio with another model | No | No | No | No | Yes, `POST /api/sessions/{id}/retranscribe` |
| Editable agent prompts/models | No | No | No | No | Yes, per agent in Admin |
| Languages marketed | 38 | 30+ | 20+ | 70+ | None marketed |
| CRM sync | HubSpot, Salesforce, Close | Business tier | Salesforce, HubSpot (Pro) | Salesforce, HubSpot, Zoho, Pipedrive, Copper | None |
| Mobile apps | iOS "coming soon" | Yes | Yes, iOS + Android | Yes | None |
| Compliance badges | SOC 2 Type II, GDPR, HIPAA, SSO/SCIM | ISO 27001, SOC 1/2 facilities, GDPR | HIPAA, SAML/SCIM at Enterprise+ | HIPAA, SSO, DPAs at Enterprise | None -- architectural argument only |
| Open source | No | No | No | No | Yes, MIT |
| Post-call briefing / synthesis | Summaries | Summaries | Reports, Read Score | Notes + scorecards | Three-lens briefing (meeting lens, discovery lens, arbiter) |
| Documented institutional bans | No | No | Yes (Chapman, 2025-08-13) | No | N/A |

## Search demand and winnability assessment

**Method caveat, stated honestly.** No keyword-volume tool was available for this
pass (no DataForSEO or Ahrefs credentials in this environment). Demand below is a
*qualitative* ranking from G2 review counts, brand prominence in third-party
listicles, and the density of competitor content targeting each term. Before
committing build effort, confirm with the gsc MCP (existing impressions for
these terms on backchannel.page) and, if available, a volume API. Do not treat
the demand column as measured.

| Target | Demand proxy | Observed SERP character for "<name> alternative" | Difficulty | Priority |
| --- | --- | --- | --- | --- |
| Fathom | Highest in set (~6,780 G2 reviews, 300K+ companies) | Page one is 100% vendor-owned content marketing: HappyScribe, Avoma, Read.ai, Plaud, Jamie, Bluedot, thebusinessdive, UMEVO. Zero independent editorial. | Very high on the head term | 1, but target the modified term |
| Read AI | High, and unusually high *negative* intent | Mixed and softer: Bluedot, Read.ai's own page, Circleback, tldv.io, HappyScribe, prospeo, alternativeto -- **and Meetily's "Open Source Privacy-First Alternative" page ranks on page one.** | Medium | 2 |
| tl;dv | Medium (~512 G2 reviews) | tldv.io's own blog ranks #1 for its own alternative term; rest is Notta, Jamie, G2, HappyScribe, Fellow, ticnote, Sally, alfred_. Dense affiliate/vendor wall. | High | Fold |
| Avoma | Lowest of the four, and it is RevOps intent | Coffee.ai, Avoma's own comparison pages, Claap, Demodesk, Kendo, Outdoo. A revenue-intelligence vendor knife fight. | High, and wrong audience | Skip |
| Open-source / self-hosted hub | Medium and rising | **Softest SERP found in this research.** Page one for "best open source AI meeting notetaker self-hosted 2026" is Anarlog, Meetily (x2 own blog), two DEV Community posts, OpenWhispr. For "AI notetaker without bot self-hosted privacy alternative Fathom open source" it is Jamie, Anarlog, Bluedot, Meetily, DEV, OpenWhispr, Char, Nod. These are small projects, not affiliate machines. | Low-medium | 3, and the best ROI per hour |

**The key winnability finding.** Backchannel cannot win "fathom alternative" --
that page one is a wall of funded vendors buying the term with content. It can
plausibly win the *modified* long tail where the OSS incumbents already rank:
"open source fathom alternative", "self-hosted ai notetaker", "ai notetaker no
bot self-hosted", "open source read ai alternative". Every Fathom and Read AI
page we build should be optimized for the modified term first and the head term
second, and should be internally linked from a hub that targets the category
term directly.

**One more actionable finding.** openalternative.co lists Meetily as the open
alternative to Granola, Otter.ai, and tl;dv. Backchannel is not listed. Getting
listed there is cheaper than a page and feeds the same intent. Same for the
"open source alternative to X" directories generally.

## Consolidation recommendation

**Build a dedicated page for two targets only.**

1. **Fathom -- build.** Highest demand in the category by a wide margin, and the
   objection is genuinely new to our page set. Every existing page argues from
   metering or the bot; against Fathom neither works. The page must argue from
   data ownership and training policy, and from tactical-vs-descriptive live
   output. Critically, this page has to concede the cost point in the first
   screen or it will read as dishonest to anyone who has used Fathom free.

2. **Read AI -- build.** Second-highest strategic value despite lower demand,
   because it is the only target with *citable primary-source institutional
   bans* and a governance-shaped objection our page set does not cover. It is
   also the target where the OSS-privacy angle already demonstrably ranks
   (Meetily's page is on page one today). Cheapest page to make credible: the
   proof is external and quotable.

**Fold two targets.**

3. **tl;dv -- fold into the hub.** Its three objections are respectively the
   Fireflies page, the Otter page, and the Granola page. A standalone page would
   compete with our own three existing pages for overlapping queries and add a
   fourth near-identical asset to maintain. Represent tl;dv as a row in the hub
   table with its genuinely distinctive fine print (10 AI notes *lifetime*,
   3-month deletion) which is a strong, quotable detail -- just not a page's
   worth.

4. **Avoma -- skip entirely, for now.** Wrong category, wrong buyer, wrong
   feature comparison. Any honest Avoma page would be 60% concession. The one
   defensible narrow claim (free self-hosted real-time answer assistance vs a
   $29-35/user/mo add-on) belongs as a single sentence in the Fathom page's
   pricing section or in the hub, not as a page. Revisit only if Backchannel
   ever ships CRM sync.

**Add one page that is not a competitor page.**

5. **"Best open-source, self-hosted AI notetaker" hub -- build.** This is the
   highest-ROI asset identified in this research. It targets the softest SERP
   found, it absorbs tl;dv, Avoma, Supernormal, Circleback, Grain, and Spinach
   as table rows without four thin pages, it consolidates link equity instead of
   splitting it, and it is the natural internal-link hub for the existing Otter,
   Fireflies, Granola, and Meetily pages plus the two new ones. It also gives us
   a page to nominate to open-source-alternative directories. The honest risk:
   Meetily is the incumbent there with ~25.7k stars and its own comparison-page
   machine, so the hub must be genuinely more useful than a listicle -- lead
   with the dimensions nobody else tabulates (where audio is processed, whether
   the vendor trains on your data, whether live output is tactical or
   descriptive, whether agent prompts are editable).

**Net result: 3 new pages instead of 4, and one of the 3 is a hub rather than a
fourth interchangeable competitor page.**

## Existing published pages audit

Each item below is a claim currently live on backchannel.page that this research
found to be stale, unverifiable, or self-underselling. Ordered by severity.

**1. `site/fireflies-alternative/index.html` -- "Four agents" understates the
product. (HIGH -- factual, and it works against us.)**
Two places say four: the FAQ answer ("Four agents (an analyst, a fast objection
handler, a synthesizer, and an opportunity specialist)") and the body ("an
analyst, a low-latency objection handler, a synthesizer, and an opportunity
specialist"). `docs/agents.md` lists nine agent slugs, and
`backend/app/services/agents/strategic_signals.py` and
`backend/app/services/briefing_synthesis.py` both exist in the tree.
*Suggested correction:* "five live agents -- an analyst, a low-latency objection
handler, a synthesizer, an opportunity specialist, and a strategic-signals agent
-- plus a three-lens post-call briefing that reconciles two independent drafts."

**2. `site/llms.txt` line 28-29 -- same four-agent understatement. (HIGH.)**
"Agents: consolidated analyst, objection handler, synthesizer, opportunity
specialist -- each with a configurable model, prompt, and trigger."
*Suggested correction:* add `strategic_signals` and the three briefing lenses,
matching `docs/agents.md`. This file is the canonical machine-readable summary,
so an understatement here propagates into AI answers about Backchannel.

**3. `site/otter-alternative/index.html` -- "40M+ claimed users". (MEDIUM --
factually wrong, in Otter's favor.)**
Otter's own most recent public claim, in its 2026-04-28 announcement, is "Used
by more than 35 million people, across over one billion meetings."
*Suggested correction:* "35M+ claimed users across a billion-plus meetings."
Cite otter.ai's own post so the number is defensible.

**4. `site/otter-alternative/index.html` -- "Live coaching is Enterprise-only"
card and the "Real-time in-call insights" table row now under-describe Otter.
(MEDIUM -- three days stale as of this research.)**
Both currently say Otter's real-time coaching "ships in its Enterprise Sales
Notetaker at custom pricing." On 2026-07-21 Otter announced **Live Assist**, a
dedicated real-time AI coaching agent that works over Zoom, Google Meet,
Microsoft, or the Otter desktop app -- available on Otter Enterprise.
*Suggested correction:* keep the Enterprise gate (it is still true and it is
still the point) but name the product: "Otter shipped Live Assist in July 2026 --
a real-time coaching agent that joins any call. It is Enterprise-only."
Understating a competitor's newest feature is the fastest way to lose a reader
who just read Otter's launch post.

**5. All three pages -- "no bot joins the call" as the lead differentiator is
positionally stale. (MEDIUM -- not an error, a weakening argument.)**
Fathom shipped bot-free capture 2026-04-15, Avoma sells bot-less native
recording, and the Otter page itself already acknowledges "bot-free desktop
recording." Bot-free is trending toward table stakes in this category.
*Suggested correction:* demote "no bot" from the hero line to a supporting
bullet on future pages, and lead with the two claims that remain structurally
unmatched: audio that never reaches a vendor, and live tactical content agents
you can reconfigure. Existing pages do not need rewriting for this, but the hero
copy should not be copied forward into new pages unchanged.

**6. `site/fireflies-alternative/index.html` -- "200+ AI Skills". (MEDIUM --
could not verify.)**
Current Fireflies marketing prominently claims "200+ integrations". A current
"200+ AI Skills" claim could not be confirmed on fireflies.ai.
*Suggested correction:* change to "200+ integrations, dashboards, sentiment, and
topic trackers" or drop the number. Do not keep an unverifiable competitor
statistic on a page whose whole value proposition is honesty.

**7. `site/otter-alternative/index.html` -- free-tier description is accurate but
incomplete. (LOW -- an improvement, not a fix.)**
The page cites 300 minutes/month, 3 lifetime imports, and 1 concurrent meeting,
all still correct. It omits Otter Basic's **30-minute maximum per conversation**,
which is the limit users actually hit first.
*Suggested correction:* add "30 minutes per conversation" to the "free tier is
metered" card. Otter's pricing page states it plainly.

**8. All three pages -- "as of mid-2026" and `dateModified: 2026-07-13`. (LOW.)**
Still defensible in July 2026. Re-verified this pass:
- Otter: Pro $8.33 annual, Business $19.99, free 300 min/mo + 3 lifetime imports
  + 1 concurrent -- **all still accurate**.
- Fireflies: Pro $10 / Business $19 / Enterprise $39 annual, free 400 min/team,
  Pro 8,000 min/seat, private storage at Enterprise -- **all still accurate**.
- Granola: Business $14/user/mo, Enterprise $35/user/mo, free tier limits older
  history -- **all still accurate**.
*Suggested action:* bump `dateModified` when items 1, 3, 4, 6, and 7 are applied;
no pricing edits required.

**9. `site/granola-alternative/index.html` -- platform list "macOS, Windows, iOS,
Android". (LOW -- unverified this pass.)**
Granola's pricing page mentions "Granola for mobile" without naming platforms.
*Suggested action:* spot-check granola.ai/download before the next edit; do not
change without evidence.

## Page recommendation and priority

| # | Page | Target terms (modified term first) | Rationale | Effort |
| --- | --- | --- | --- | --- |
| 1 | `/fathom-alternative/` | "open source fathom alternative", "self-hosted fathom alternative", "fathom ai alternative" | Largest audience in the category by an order of magnitude, and the only target whose buyer objection is genuinely absent from our existing three pages. Must lead with data ownership and the opt-out training policy, must concede cost in the first screen, must contrast live *tactical* agents against Fathom's live *summaries*. | 5-7 h (highest verification burden: Fathom ships fast, and half the differentiating facts are "coming soon" items that will move) |
| 2 | `/read-ai-alternative/` | "open source read ai alternative", "how to block read ai", "read ai alternative" | Only target with citable primary-source institutional bans (Chapman 2025-08-13; UW-Madison KB). Governance-shaped objection our page set does not cover. Meetily already proves an OSS-privacy page ranks on this SERP. Cheapest credible page because the proof is external. Must present Read AI's rebuttal fairly. | 4-5 h |
| 3 | `/open-source-ai-notetaker/` (hub) | "best open source ai notetaker", "self-hosted ai meeting assistant", "ai notetaker no bot self-hosted" | Softest SERP found in this research. Consolidates tl;dv, Avoma, Supernormal, Circleback, Grain, and Spinach into one table instead of four thin pages. Becomes the internal-link hub for Otter, Fireflies, Granola, Meetily, Fathom, and Read AI pages. Nominate to openalternative.co and similar directories once live. Must out-inform Meetily's comparison pages on dimensions nobody else tabulates. | 8-10 h (largest table, most claims to verify, highest ongoing maintenance) |
| -- | tl;dv page | -- | **Do not build.** Near-duplicate of the Fireflies and Otter objections; its distinctive attribute (EU residency) argues against us. Ship as a hub row quoting the lifetime AI-note cap and 3-month deletion. | 0 |
| -- | Avoma page | -- | **Do not build.** Wrong category and wrong buyer; an honest page would be mostly concessions. One sentence in the Fathom page or hub covers the defensible claim. | 0 |
| 4 | Existing-page fixes | -- | Apply audit items 1-4 and 6-7 (agent count in the Fireflies page and llms.txt, Otter user count, Otter Live Assist, Fireflies "200+ AI Skills", Otter 30-min cap) and bump `dateModified`. Do this **before** shipping new pages so the new pages can copy corrected boilerplate. | 1.5-2 h |

**Suggested sequence:** item 4 (fixes) -> item 1 (Fathom) -> item 3 (hub) ->
item 2 (Read AI). The hub goes before Read AI because both new competitor pages
should link into it, and because it is where the winnable traffic is.

## QA/QC pass

### Claim verification table

All access dates 2026-07-24 unless noted. "Verified" means fetched from the
named source in this session; "partial" means the fact came from a search-result
summary of that source rather than a successful direct page fetch.

| Claim | Source URL | Access date | Verified | Confidence |
| --- | --- | --- | --- | --- |
| Fathom Free is $0 "Free forever" with unlimited recordings + transcriptions | https://fathom.ai/pricing | 2026-07-24 | Yes | High |
| Fathom Premium $20/mo, $16/mo annual; Team $19/$15; Business $34/$25; Enterprise custom | https://fathom.ai/pricing | 2026-07-24 | Yes | High |
| Fathom Free capped at "Advanced summaries for your first 5 calls each month" | https://help.fathom.video/en/articles/5290881 | 2026-07-24 | Yes | High |
| Fathom: "Unlimited transcriptions in 38 languages" on Free and Premium | https://help.fathom.video/en/articles/5290881 | 2026-07-24 | Yes | High |
| Fathom Free offers "Choice of bot-free (in beta) or bot capture-types" | https://fathom.ai/pricing | 2026-07-24 | Yes | High |
| Fathom bot-free capture is Mac only; Windows/PC and iOS "coming soon" | https://www.fathom.ai/whats-new | 2026-07-24 | Yes | High |
| Fathom desktop app has live summaries and in-meeting scratchpad; "Real-Time Coaching" coming soon | https://www.fathom.ai/whats-new + https://help.fathom.video/en/articles/449088 | 2026-07-24 | Yes | High |
| Fathom 3.0 launched 2026-04-15 with bot-free capture, account-wide insights, ChatGPT/Claude integrations | Businesswire 20260415965820 | 2026-07-24 | Partial (title/date via search; body 403/ECONNRESET) | Medium |
| Fathom: "Used at 300K+ companies"; "SOC 2 Type II \| GDPR \| HIPAA Compliant \| SSO / SCIM" | https://www.fathom.ai/ | 2026-07-24 | Yes | High |
| Fathom may train in-house models on de-identified meeting data, opt-out in settings; subprocessors barred from training | https://www.fathom.ai/privacy | 2026-07-24 | Partial (search summary; direct fetch of /security 404) | Medium |
| Fathom ~6,780 G2 reviews at ~5.0 | G2 via search summary | 2026-07-24 | No (third-party aggregate) | Medium-low |
| "Presence as meeting participant" is Fathom's top G2 negative theme (~415 mentions) | Third-party review aggregation via search | 2026-07-24 | No | Low |
| Fathom cannot transcribe uploaded audio; no mobile app | Third-party reviews via search | 2026-07-24 | No | Low |
| Read AI Free: 5 meeting transcripts/mo, 5 reports/mo, 1h max meeting | https://www.read.ai/pricing | 2026-07-24 | Yes | High |
| Read AI Pro $15 annual / $19.75 monthly; Enterprise $22.50/$29.75; Enterprise+ $29.75/$39.75 (5+ licenses) | https://www.read.ai/pricing | 2026-07-24 | Yes | High |
| Read AI audio/video playback is Enterprise-tier only | https://www.read.ai/pricing | 2026-07-24 | Yes | High |
| Chapman University: "the use of Read AI is prohibited due to security, privacy, and institutional data risks", blocking the app in Zoom and Teams | https://blogs.chapman.edu/information-systems/2025/08/13/security-notice-regarding-read-ai/ | 2026-07-24 (published 2025-08-13) | Yes | High |
| UW-Madison KB: Read.ai "will automatically join your meetings by default"; clicking a shared report link "can create an account for you without knowing" | https://kb.wisc.edu/138719 | 2026-07-24 (created 2024-07-25, updated 2025-04-24) | Yes | High |
| Read AI live dashboard shows real-time sentiment, engagement, talk time, WPM, coaching tips | https://www.read.ai/meeting-tools + support.read.ai live dashboard article | 2026-07-24 | Partial (support.read.ai 403) | Medium |
| Read AI sentiment/engagement derived from "facial and verbal elements of all meeting attendees" | Read AI marketing via search summary | 2026-07-24 | No (help center 403) | Low-medium |
| Read AI auto-sends summaries to external attendees | Third-party via search | 2026-07-24 | No | Low |
| tl;dv Free: first 10 meetings get AI notes, then only first 10 minutes; 10 AI prompts; 10 AI Reports; lifetime not monthly | https://intercom.help/tldv/en/articles/8919450-what-are-the-limits-of-the-free-plan | 2026-07-24 (updated 2025-11-24) | Yes | High |
| tl;dv Free: recordings stored 3 months, archived after 3 days, unarchive up to 1.5 h, 3h max meeting, 4 clips, 5 uploads, 20 integration credits, no simultaneous recording | same as above | 2026-07-24 | Yes | High |
| tl;dv Pro ~$29 monthly / ~$18 annual; Business ~$98 / ~$59 | https://www.claap.io/blog/tl-dv-pricing (competitor blog, 2025-12-30) | 2026-07-24 | No (vendor page returned metadata only) | Low |
| tl;dv data stored and processed in EU/EEA (GCP, AWS, Hetzner, Wasabi), AES-256, ISO 27001 / SOC 1-2 facilities | https://tldv.io/features/security-commitment/ | 2026-07-24 | Partial (search summary) | Medium |
| tl;dv ~512 G2 reviews | G2 via search summary | 2026-07-24 | No | Low |
| Avoma Startup $19/$29, Organization $24/$39, Enterprise $39; CI and RI add-ons $29/$35; Lead Router $19/$25 | https://www.avoma.com/pricing | 2026-07-24 | Yes | High |
| Avoma has no permanent free plan; 14-day Organization trial; viewers/collaborators always free | https://www.avoma.com/pricing (corroborated by G2 and ZoomInfo) | 2026-07-24 | Yes, with one dissenting third-party source | Medium-high |
| Avoma supports "Bot-less Native Recording and Bot-based Recording" | https://www.avoma.com/pricing | 2026-07-24 | Yes | High |
| Avoma "Real-time Answer Assistant" is in the Conversation Intelligence add-on | https://www.avoma.com/pricing | 2026-07-24 | Yes | High |
| Avoma real-time transcription in 70+ languages with speaker identification | https://www.avoma.com/pricing | 2026-07-24 | Yes | High |
| Avoma ships a public MCP server for Claude Desktop / ChatGPT | Third-party via search | 2026-07-24 | No | Low |
| Otter Basic free: 300 min/mo, 30 min/conversation, 3 lifetime imports, 1 concurrent | https://otter.ai/pricing | 2026-07-24 | Yes | High |
| Otter Pro $8.33 annual, Business $19.99 annual, Enterprise custom | https://otter.ai/pricing | 2026-07-24 | Yes | High |
| Otter claims "more than 35 million people, across over one billion meetings" (2026-04-28) | https://otter.ai/blog/otter-ai-evolves-from-ai-notetaker-to-create-100b-enterprise-conversational-knowledge-engine-market | 2026-07-24 | Yes | High |
| Otter Live Assist announced 2026-07-21, Enterprise-only, works over Zoom/Meet/Microsoft or Otter desktop | Businesswire 20260721446216 + martechseries coverage | 2026-07-24 | Partial (via search summary of the release) | Medium-high |
| Fireflies Free 400 min storage/team, 20 AI credits; Pro $10 annual / 8,000 min/seat; Business $19; Enterprise $39 with private storage | https://fireflies.ai/pricing | 2026-07-24 | Yes | High |
| Fireflies markets "200+ integrations" (not verified as "200+ AI Skills") | https://fireflies.ai/blog + guide.fireflies.ai via search | 2026-07-24 | Partial | Medium |
| Granola Basic $0 with limited meeting history; Business $14/user/mo; Enterprise $35/user/mo | https://www.granola.ai/pricing | 2026-07-24 | Yes | High |
| Meetily is MIT-licensed with ~25,762 GitHub stars and ranks page one for "Read AI alternative" | meetily.ai + openalternative.co + observed SERP | 2026-07-24 | Partial (star count via search summary) | Medium |
| Grain has ~307 G2 reviews | G2 via search summary | 2026-07-24 | No | Low |
| Backchannel runs nine agent slugs including strategic_signals and three briefing lenses | `docs/agents.md`; `backend/app/services/agents/strategic_signals.py`; `backend/app/services/briefing_synthesis.py` | 2026-07-24 | Yes (repo) | High |
| Backchannel diarization: local Silero VAD + WeSpeaker ResNet152, optional NVIDIA Sortformer on GPU | `docs/audio-pipeline.md` | 2026-07-24 | Yes (repo) | High |
| Backchannel supports fully offline transcription via local ONNX Whisper/Parakeet | `docs/audio-pipeline.md`; `CLAUDE.md` | 2026-07-24 | Yes (repo) | High |
| Backchannel supports re-transcription of stored audio via `POST /api/sessions/{id}/retranscribe` | `docs/audio-pipeline.md`; `CLAUDE.md` | 2026-07-24 | Yes (repo) | High |

### Flagged and unverifiable claims -- do not publish without re-verification

**Do not put on a public page in current form:**

- **tl;dv paid pricing ($18/$59 annual).** Only source is a competitor's blog
  (Claap) dated 2025-12-30. The vendor's own pricing page moved to
  `tldv.io/app/pricing/` and returns only metadata to automated fetch. If tl;dv
  appears in the hub table, either open the page in a real browser first or
  publish only the free-tier limits, which are vendor-documented and strong
  enough on their own.
- **Read AI facial/camera analysis for sentiment scoring.** This is the most
  rhetorically powerful claim available against Read AI and it is the least
  verified -- Read's own help center article returned 403. Fetch it manually
  before writing a single word about cameras. If it cannot be confirmed from
  Read's own documentation, write the page around the documented auto-join,
  accidental-account-creation, and institutional-ban facts instead, which are
  fully sourced.
- **Fathom's "~415 negative mentions" G2 figure and the ~6,780 review count.**
  Third-party aggregations. Either cite G2 directly after checking it, or use
  qualitative language ("the most common complaint in Fathom's public reviews").
- **"Fathom cannot transcribe uploaded audio" and "no mobile app".** Low
  confidence and both are the kind of gap a fast-shipping vendor closes without
  announcement. Fathom's own page already lists an iOS app as coming soon.
  Omit or verify.
- **Avoma MCP server.** Single third-party mention. Omit unless confirmed on
  avoma.com.
- **Read AI auto-sending summaries to external attendees.** Single third-party
  mention of a serious behavior. Omit unless confirmed in Read's documentation.

**Known conflicts left unresolved:**

- **Avoma free plan.** The vendor pricing page and two review databases (G2,
  ZoomInfo) say there is no permanent free plan; one third-party blog (Nimitai,
  May 2026) describes a Basic $0 plan with about 10 meetings/month. Vendor page
  wins, but since Avoma is recommended as skip/hub-row, this does not block
  anything. Do not state "Avoma has no free plan" as a headline claim without a
  fresh check.
- **Fathom free-tier framing.** The pricing page's "Instant AI call summaries"
  and the help center's "first 5 calls each month" are both true and describe
  different things (basic vs advanced summaries). Any page must state both or it
  will read as either naive or misleading. Recommended phrasing: "unlimited
  recording and transcription genuinely free, with advanced AI summaries capped
  at 5 calls a month."

**Structural caveat on the whole demand assessment.** No keyword-volume data was
obtainable in this environment. The priority ranking is defensible on SERP
composition and popularity proxies, but the *magnitude* of the demand gap
between Fathom and Read AI is an estimate. Run the gsc MCP against
backchannel.page for existing impressions on these terms, and a volume API if
one is available, before allocating the 8-10 hours the hub page needs.
