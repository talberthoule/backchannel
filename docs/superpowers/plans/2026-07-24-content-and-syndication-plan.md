# Backchannel content and syndication plan (2026-07-24)

**Nothing in this document gets published, posted, submitted, or syndicated
without an explicit go-ahead.** Every draft below is a draft. Every submission
target below is a candidate. Treat the whole plan as staged work awaiting a
decision, not a queue that runs itself.

- Linear: **ALP-136** (this plan), **ALP-137** (configurable LLM endpoint for
  Ollama and LM Studio), **ALP-138** (search-demand verification).
- Supersedes: the earlier draft "Launch Kit" (four posts, four-agent claim,
  dev.to treated as canonical). See "What we kept and what we discarded" below.
- Internal document. `docs-site/sync-docs.mjs` reads `docs/` non-recursively, so
  files under `docs/superpowers/` are tracked in git and never published to
  backchannel.page. Nothing here is customer-facing copy until it is moved into
  `site/` by whoever owns `site/`.
- Evidence base: the five research documents at
  `docs/superpowers/specs/2026-07-24-market-comparison-*-research.md`. Cited
  below as **[MN]** mainstream-notetakers, **[ACH]** ambient-capture-hardware,
  **[LFO]** local-first-oss, **[BI]** bundled-incumbents, **[RI]**
  revenue-intelligence. Every claim in every draft must trace to a row in one of
  those documents' claim-verification tables, with its access date and
  confidence level carried forward.
- Tone reference: the twelve live comparison pages under `site/`. The standard
  they set is that the concession comes before the pitch, on the same screen,
  in the same voice. `site/open-source-meeting-assistants/index.html` opens with
  "We build one of the tools on this page, so read it with that in mind" and
  then recommends Meetily and Buzz by name. That is the bar.

## Ground truth: the nine agents we actually ship

Authoritative source: `backend/app/services/seed_agents.py` (`SEED_CONFIGS`).
`docs/agents.md` agrees. `CLAUDE.md` does **not** -- it still describes four
agents at 15s and 5s intervals and omits `strategic_signals` and the three
briefing lenses. Anything drafted from `CLAUDE.md` will be wrong. This is a
known repo-hygiene defect flagged independently by [RI], [BI], and [ACH].

| Slug | Name | Type | Trigger | Seeded model |
| --- | --- | --- | --- | --- |
| `audio_gateway` | Audio Bridge | audio | continuous stream, silent listener | `gemini-3.1-flash-live-preview` |
| `consolidated_analyst` | Consolidated Analyst | text | every 40s | `gemini-3.6-flash` |
| `objection_handler` | Objection Handler | text | every 10s over the last ~90s | `gemini-3.5-flash-lite` |
| `synthesizer` | Principal Agent | meta | 75s cooldown on insight events | `gemini-3.1-pro-preview` |
| `opportunity_specialist` | Opportunity Specialist | db | 55s cooldown on new opportunities | `gemini-3.6-flash` |
| `strategic_signals` | Strategic Signals | meta | every 45s | `gemini-3.6-flash` |
| `brief_meeting_lens` | Briefing Meeting Lens | meta | call end | `gemini-3.6-flash` |
| `brief_discovery_lens` | Briefing Discovery Lens | meta | call end | `gemini-3.6-flash` |
| `brief_arbiter` | Briefing Arbiter | meta | call end, after both lenses | `gemini-3.6-flash` |

The public phrasing that is both accurate and legible: **an audio gateway, five
live insight agents, and a three-agent post-call briefing pass -- nine seeded
agents, each with a configurable model, prompt, and trigger.** `site/llms.txt`
already carries this wording; copy it rather than re-inventing it.

Interval numbers are database-seeded defaults a user can change. Prefer
"roughly every 10 seconds" over a hard constant in prose, and never cite an
interval that is not in `SEED_CONFIGS`.

## Claim guardrails (non-negotiable, applies to every artifact below)

1. **Never claim fully offline end to end.** Verified 2026-07-24:
   `backend/app/services/llm.py:24` hardcodes
   `OPENAI_BASE_URL = "https://api.openai.com/v1"` with no override, and the
   local model entries in `backend/app/config.py` carry `"supports_text": False`.
   Transcription and diarization run locally; the agents always need a Gemini or
   OpenAI key today. Privacy First mode gives fully local transcription and
   diarization and turns **every** LLM agent off, including `objection_handler`
   ([RI] rows 64, 58). The honest sentence is: audio stays on your machine;
   transcript text goes to the provider whose key you supplied.
2. **Never claim real-time in-call assistance is novel or unique.** Amurex
   (AGPL-3.0, 2,858 stars) shipped a live in-meeting copilot and has had no push
   since 2025-05-27 ([LFO]). Clari Copilot ships live cues and monologue alerts,
   Attention markets "Real-time objection handling", Otter shipped Live Assist on
   2026-07-21, and Zoom Sales Assist reached GA on 2026-07-22 ([RI], [MN], [BI]).
   The durable claim is **mechanism plus price plus deployment**: a response
   generated against the objection that was actually raised, on hardware you own,
   at zero per-seat cost. Not "first". Not "only".
3. **Never claim cross-platform coverage is uniquely ours.** Google announced on
   2026-04-22 that "Take Notes for me" works "regardless of whether your meeting
   is in-person, or hosted on another provider like Zoom or Teams" from the Meet
   home screen ([BI], vendor-primary, high confidence). Zoom AI Companion joins
   Meet and Teams as a visible branded participant. Also: **do not** claim Google
   needs a bot and we do not -- Google has not stated the capture mechanism, and
   asserting it either way is exactly the unverified swing that discredits a page.
4. **Never claim our diarizer architecture is novel.** Vibe's `pyannote-rs` uses
   pyannote segmentation-3.0 plus WeSpeaker embeddings on onnxruntime --
   essentially our approach ([LFO]). What is distinctive is that we run it live,
   per segment, during the call, with voice enrollment and split mic/system-track
   identities, feeding agents.
5. **Never claim we are cheaper than Fathom for one user.** Fathom Free is $0
   forever with unlimited recording, unlimited storage, and unlimited
   transcription in 38 languages ([MN], high confidence). We cost a Docker host
   plus API spend. The cost argument only works at team scale or when the
   constraint is data location.
6. **Never imply enterprise readiness.** No `User` model, no authentication
   dependency in any router, single-worker deployment ([RI] row 60, [BI]).
7. **Never imply a Gong integration exists.** The WAV files and Gong's `add new
   call` API make one architecturally possible. Nothing is shipped ([RI] row 65).
8. **Never say four agents or five agents.** Nine.
9. **Date every vendor number** with its access date and the "as of July 2026,
   check current pricing" caveat the comparison pages already use.
10. **Do not publish anything on the do-not-publish list** in the source
    research documents. Article 6 exists precisely so that list has a home.

## A. Six articles

Ordering note: the brief's priority order is publication order, and it is driven
by decay rate, not by evidence quality. Article 1 has a hard expiry. Articles 6
and 2 have the strongest evidence in the set (our own verification log, and
vendor-primary termination notices) but no expiry, so they can wait. The
"Evidence" column below makes the tension visible rather than hiding it.

| # | Working title | Evidence strength | Decay | Primary comparison page | Canonical slug |
| --- | --- | --- | --- | --- | --- |
| 1 | Live meeting AI arrived in one week, and all of it is Enterprise-gated | High (vendor-primary Zoom; Otter partial) | **Days** | `/vs-clari-copilot/` | `/blog/live-meeting-ai-enterprise-gate/` |
| 2 | Your AI recorder got acquired. Where did your recordings go? | Very high (vendor-primary) | Low | `/plaud-alternative/` | `/blog/when-your-ai-recorder-gets-acquired/` |
| 3 | "No bot" is not "private" | Very high (two vendor-primary docs in conflict) | Low | `/plaud-alternative/` | `/blog/no-bot-is-not-private/` |
| 4 | Who said what is now a premium feature | High (Meetily); medium (Anarlog price) | Medium | `/vs-meetily/` | `/blog/who-said-what-premium-feature/` |
| 5 | Bundled AI is not adopted AI | High, one derived figure | Medium | `/teams-premium-alternative/` | `/blog/bundled-ai-is-not-adopted-ai/` |
| 6 | What we cut and why | Highest (first-party) | None | `/open-source-meeting-assistants/` | `/blog/what-we-cut-and-why/` |

A seventh canonical post exists: the **dev.to build log** in section B. It is
product-story rather than competitive evidence, so it is not one of the six, but
it is published on backchannel.page first like everything else.

---

### 1. Live meeting AI arrived in one week, and all of it is Enterprise-gated

**Thesis.** Between 2026-07-21 and 2026-07-22, two of the largest vendors in the
category shipped proactive live in-call assistance to general availability. Both
put it behind an Enterprise tier or a sales-tool price. The interesting question
is no longer whether live assistance is possible -- it is what it costs, who is
allowed to have it, and how the guidance is produced.

**Sourced evidence.**

- Otter **Live Assist**, announced 2026-07-21, positioned as "the first
  real-time AI coaching agent that joins any call", works over Zoom, Google Meet,
  Microsoft, or the Otter desktop app, **Otter Enterprise only**. [MN], via
  Businesswire 20260721446216 and martechseries coverage. Confidence
  medium-high, **partial** -- obtained through a search summary of the release.
  **Gate: fetch the release directly before this article ships.**
- Zoom **Revenue Accelerator Sales Assist**, GA 2026-07-22, surfacing
  "competitive intelligence, objection guidance, discovery prompts, battlecards,
  and configurable framework capture in real time" during live calls.
  **Essentials $66/user/month annual (from August 2026), Premium $99.99/
  user/month annual.** [RI] row 67, [BI] -- vendor-primary
  (news.zoom.com), high confidence. This is the only competitor in the entire
  research set with fully public real-time pricing.
- The mechanism, and this is the load-bearing part: Zoom's guidance is
  pre-configured. Per support.zoom.com KB0087752, an admin enters questions or
  guidance per topic category (discovery, objection handling, pricing,
  competitor talking points, functionalities), attaches knowledge collections,
  and rule-based live signals plus timer reminders drive display. [RI] row 68,
  vendor-primary, high confidence. Zoom is the **best-documented example of the
  pre-authored pattern** in the whole research set and is current (July 2026).
  Use Zoom, not Clari, whenever the copy needs a concrete illustration.
- Avoma's "Real-time Answer Assistant" sits in the $29-35/user/month
  Conversation Intelligence add-on on top of a $19-39/user/month base -- roughly
  **$53-74/user/month all-in**. [MN], vendor-primary, high confidence.
- Fathom's desktop app has live summaries and an in-meeting scratchpad; "Real-Time
  Coaching" is listed as "Coming soon". [MN], high confidence.
- Read AI's live dashboard is behavioral -- sentiment, engagement, talk time,
  words per minute, coaching tips -- not tactical content. [MN], medium.
- Attention markets "AI powered battlecards help you answer any prospect question
  while on the call" and publishes no pricing. [RI] rows 50, 54.

**Do not include.** Any characterization of Clari Copilot's matching mechanism or
a desktop-app requirement. Both rest on 2023-dated community posts; Clari's
current KB (Copilot-Level-3) confirms live cues and monologue alerts and is
**silent** on both points, and both were formally dropped ([RI] row 70). Describe
Clari only in Clari's own current words, and say explicitly that we are not
characterizing their internals.

**What we say about ourselves.** `objection_handler` runs roughly every 10
seconds over the trailing 90 seconds and emits a `response_now` -- one or two
conversational sentences you could say in the next ten seconds -- paired with a
`bigger_picture` naming the underlying concern and the strategic angle
(`backend/app/services/agents/prompts.py`, [RI] row 59). It is generated from the
transcript window, not selected from a pre-authored card. Concede in the same
breath: a curated battlecard is deterministic and enablement-approved, and an LLM
output is neither ([RI] concession 4).

**Links.** Primary `/vs-clari-copilot/`. Secondary `/otter-alternative/` and
`/gong-and-backchannel/`. Hub link to `/open-source-meeting-assistants/`.

**Expiry.** The "in one week" hook dies around mid-August 2026. After that, this
becomes an evergreen "what live in-call assistance costs in 2026" piece and drops
to priority 4. If the Otter release cannot be fetched directly within the window,
publish the Zoom half alone -- it is vendor-primary and priced.

---

### 2. Your AI recorder got acquired. Where did your recordings go?

**Thesis.** Vendor continuity risk is not a hypothetical in this category. It
already happened twice in twelve months, and one of the two ended with paying
customers in seven markets getting fourteen days to export their data.

**Sourced evidence.** All [ACH], all vendor-primary unless noted, all high
confidence.

- Meta acquired Limitless; announced 2025-12-09 (TechInformed). Pendant sales
  ended **2025-12-05** per limitless.ai.
- Service was **discontinued entirely** in Brazil, China, the EU, Israel, South
  Korea, Turkey, and the UK effective 2025-12-05, with a data export deadline of
  **2025-12-19** before permanent deletion. That is fourteen days.
- Desktop and web app recording were disabled. The Rewind app was sunset with
  capture disabled 2025-12-19.
- Existing owners were moved to the Unlimited plan free of charge, with support
  pledged for "at least another year" and archive access through 2026.
- Amazon announced its acquisition of Bee on **2025-07-22** (TechCrunch, high).
  Bee Pioneer is $49.99; Bee's own page currently states no subscription is
  required, a change from the $19/month launch model.
- Useful secondary beat: Forbes Vetted, dated 2026-07-24, still listed the
  Limitless Pendant at $199 as buyable with a $19-29 monthly subscription, which
  the vendor's own site contradicts. Publish this as "Forbes says X, the vendor
  says Y" -- it is a lesson about roundup articles, not an attack on Forbes.

**Do not include.** Any real-world battery figure sourced to the UMEVO audit via
bigguyonstuff (Plaud 4-6h, Limitless 6-14h, Bee 1.5-2 days) -- third-hand
aggregation, flagged do-not-publish ([ACH]). Omi pricing -- four sources, four
different answers.

**The concession this article must carry, prominently.** Backchannel cannot
capture a hallway conversation, a phone call, a car ride, or a coffee meeting you
walked to. No mobile app, no wearable. If your meetings are mostly in person, buy
a recorder -- and note that Plaud exports MP3/WAV and
`POST /api/sessions/{id}/import/audio` accepts `.m4a`, `.mp3`, `.wav`, `.ogg`,
`.flac` through the same pipeline as a live call, so the two compose ([ACH],
verified at `backend/app/routers/imports.py:323`). Second concession: MIT source
cannot be switched off by an acquisition, but our agents still depend on a
third-party API key, so the continuity claim is about the software, not about
independence from all vendors.

**Links.** Primary `/plaud-alternative/` (which already carries the Limitless
section). Hub link.

---

### 3. "No bot" is not "private"

**Thesis.** Bot-free capture became table stakes in 2026 and it was never the
part that saw your audio. The question that separates these products is where the
conversation is decrypted, and at least one vendor's marketing page and its own
privacy notice do not agree on the answer.

**Sourced evidence.** All [ACH] unless noted.

- **Bee's product page** (bee.computer/bee-pioneer, vendor-primary, direct fetch,
  high): conversations are processed in real time, immediately deleted, never
  saved or stored, with "no sharing with third parties", no model training, and
  no monetization.
- **Bee's own privacy notice** (bee.computer/privacy, vendor-primary, direct
  fetch, high): personal information may be shared with service providers
  including "AI or machine learning services"; input, output, and personal
  information will be shared with and processed by AI Service Providers
  **including Google Cloud AI**; and Bee "may share your personal information
  with third-party advertising partners" for interest-based, personalized, or
  targeted advertising.
- Present this as **a documented discrepancy between two of Bee's own documents,
  quoting each**, not as an accusation. That framing is prescribed by the
  research and it is the only version that survives scrutiny.
- BGR additionally reports Bee has shared limited data with third-party
  advertisers in the past year -- attribute to BGR, do not state as fact
  (medium).
- Category context: Plaud's AI cannot be run locally at all (PCWorld, independent
  review, explicit, high). Omi is MIT end to end but its shipped default path
  puts VAD, diarization, Deepgram STT, and the LLM calls in Omi's cloud backend
  (GitHub README, high) -- open source alone is not data sovereignty when the
  default is a vendor cloud.
- Bot-free is table stakes: Fathom shipped it 2026-04-15 (Mac only, Windows
  "coming soon"), Avoma sells "Bot-less Native Recording", Plaud Desktop has
  been free on every plan including Starter since January 2026 ([MN], [ACH]).

**What we say about ourselves, and this article is where we say it most
plainly.** Diarization always runs locally (Silero VAD plus WeSpeaker ResNet152
ONNX). Transcription can run fully offline through local ONNX Whisper or
Parakeet. The agents still need a Gemini or OpenAI key -- verified at
`llm.py:24` and in the `supports_text: False` local registry entries. An article
whose entire thesis is "read the second document" cannot be caught rounding its
own story up. Say it in the body, not a footnote.

**Links.** Primary `/plaud-alternative/`. Secondary `/read-ai-alternative/`.
Hub link.

---

### 4. Who said what is now a premium feature

**Thesis.** The two leading open-source meeting notetakers both put automatic
speaker attribution behind a paid tier in 2026. Ours is free, local, live, and in
the MIT repo with nothing above it.

**Sourced evidence.** All [LFO].

- **Meetily**: speaker diarization shipped in **Meetily Pro 1.8.2** -- "live as
  you record and on audio you import or re-transcribe" -- and is **not** in the
  MIT Community Edition. meetily.ai/downloads lists "Speaker diarization (who
  said what)" under Pro only. Pro is **$10/user/month billed annually
  ($120/year)**. Vendor-primary, high confidence.
- **Anarlog** (formerly Hyprnote, briefly Char; MIT since the 2026-05-03 rename):
  the docs describe assigning speaker labels **manually**; automatic speaker
  indexes come from the transcription provider (merged PR #5834, 2026-07-01); a
  local pyannote-ONNX diarization PR (#3821) was **closed unmerged** on
  2026-05-01; and hosted speaker identification is a **Pro** feature.
  **Phrase it exactly that way.** Do not write "Anarlog has no diarization" --
  the research flags that as unfair and probably wrong for provider-backed
  configurations.
- **Anarlog Pro pricing ($15/month or $150/year) is medium confidence** --
  anarlog.so/pricing/ returned 404 to direct fetch. **Gate: verify in a browser
  or omit the number and say "a paid tier".**
- Also do not quote Anarlog's 2026-05-03 "free forever -- there is no paid tier"
  line. It is contradicted by the current site and quoting it would look like
  misrepresentation.

**The counterweight this article must include or it is dishonest.** MacWhisper's
**free** tier includes Automatic Speaker Recognition (macOS, proprietary). Vibe
and Buzz both ship free local diarization. So the claim is narrow and must be
stated narrowly: among the two leading open-source **meeting notetakers**,
who-said-what is paid; free local diarization is common in transcription tools.
And per guardrail 4, our architecture is not novel -- Vibe uses the same
WeSpeaker embedding approach. What is ours is live per-segment attribution during
the call, voice enrollment, split mic/system-track identities, and the fact that
those labels feed nine agents.

**Second concession -- RESOLVED in v0.3.7 (2026-07-25).** This previously read
that Meetily CE, Anarlog, and Vibe all summarize fully offline through Ollama
and we could not. ALP-137 shipped, so the agents now target any
OpenAI-compatible endpoint and a deployment can run end to end with no cloud
key. The remaining, narrower concession is that the Privacy First switch still
disables the agents, because its gate recognizes only the local transcription
models -- so a fully local setup is configured through the endpoint rather than
that toggle. Meetily's Ollama-first design is still smoother on that one path;
say so.

**Links.** Primary `/vs-meetily/`. Secondary `/vs-anarlog/`. Hub link.

---

### 5. Bundled AI is not adopted AI

**Thesis.** "It comes with the platform" and "people have it" are different
claims. Microsoft's meeting AI is a paid license roughly nineteen out of twenty
commercial seats do not carry, and Google ships automatic note-taking turned
**off** by default on its three enterprise editions.

**Sourced evidence.** All [BI].

- Microsoft reported **more than 20 million paid Copilot seats** in FY26 Q3,
  announced 2026-04-29 (CNBC, high) against **roughly 450 million Microsoft 365
  commercial seats** reported in FY26 Q2 (office365itpros, medium-high).
  Under 5 percent. **Present the two figures and the arithmetic separately** so
  the reader can check the derivation.
- Intelligent Meeting Recap, AI-generated notes and tasks, recap for meetings you
  missed, live translated captions, multilingual meeting support, speaker
  timeline markers, and autogenerated chapters are **not in base Teams**. They
  require **Teams Premium at $10.00/user/month paid yearly**, or a Microsoft 365
  Copilot license. learn.microsoft.com feature comparison table, vendor-primary,
  high.
- Microsoft 365 Copilot Business is **$18.00/user/month paid yearly**
  (promotional, regular $21.00). Vendor-primary, high.
- **Google's admin default is the single best primary-source fact in this
  article**: per workspaceupdates.googleblog.com, "Take notes for me" is **ON by
  default for Business Standard and Business Plus** and **OFF by default for
  Enterprise Standard, Enterprise Plus, Frontline Plus, and the Google AI Pro for
  Education add-on**. Vendor-primary, high. Also: a new "three or more people"
  option rolls out through 2026-08-03, an end-user equivalent arrives no sooner
  than 2026-09-21, and there is "no impact to the end user experience on any plan
  before September 21, 2026".
- Zoom's in-meeting questions feature is **not on by default** and the host must
  start it; admins can disable AI at account, group, or user level and lock the
  toggle. support.zoom.com KB0057748, vendor-primary, high.
- Microsoft shipped a mid-meeting kill switch in July 2026 letting organizers and
  presenters disable Copilot, Facilitator, and recap, and that toggle does not
  appear at all if the tenant admin has locked meeting AI off (medium, two
  independent outlets).

**Do not include.** The $30/user/month enterprise Copilot price (not on a
Microsoft-owned page). Microsoft 365 E7 at $99 (single-tier secondary). The
Copilot EU flex-routing default -- it would be our sharpest data-sovereignty
line, which is exactly why it cannot rest on secondary analysis of a message
center post we never fetched; verify MC1269223 first. Teams Premium "3 million
seats / 400% YoY" (stale 2024 figure recycled into 2026 roundups). The July 2026
AI-notetaker consent survey unless the sponsor and methodology are named.

**The concession that must lead, not trail.** If your employer already pays for
Teams Premium, Microsoft 365 Copilot, a paid Zoom Workplace seat, or Google
Workspace Business Standard or above, you already have working post-call recap
that costs nothing extra, requires no setup, and has passed your compliance team.
We do not replace that. Second concession: the platform vendors know exactly who
is speaking because they own the audio stream; we infer it acoustically and will
sometimes be wrong. Third: per guardrail 3, cross-platform is not ours alone.

**Audience discipline.** Target the individual practitioner inside the
enterprise, never enterprise IT or procurement. We have no auth boundary, no SSO,
no DLP, no eDiscovery, no retention policy, and no certifications ([BI]).

**Links.** Primary `/teams-premium-alternative/`. Hub link.

---

### 6. What we cut and why

**Thesis.** A comparison page is only worth reading if you believe the author
threw things away. Here is our verification log: the claims we could have made
about competitors, why each one failed, and the corrections we made to our own
pages.

This is the lowest-risk and highest-trust article in the set, it costs almost
nothing to write because the material already exists, and it is what makes
articles 1 through 5 credible. It is also probably the safest first post and the
best fit for Hacker News of the six.

**What it publishes -- competitor claims we killed.**

- **tl;dv paid pricing.** Only source was a competitor's blog dated 2025-12-30;
  tldv.io/pricing 404s and the live pricing page returns only metadata to
  automated fetch. We published tl;dv's vendor-documented free-tier limits
  instead, which are stronger anyway ([MN]).
- **Read AI's facial/camera sentiment analysis.** The most rhetorically powerful
  line available against Read AI, and the least verified -- Read's own help
  center article returned 403. Cut. The Read AI page was built on the documented
  auto-join behavior, the accidental-account-creation report in UW-Madison's KB,
  and Chapman University's 2025-08-13 security notice instead, all of which are
  fully sourced and quotable ([MN]).
- **Gong contract-term specifics** -- platform fee dollar ranges, a 15-seat
  minimum, implementation fees, renewal uplift percentages, no seat true-down.
  Competitor-blog only, and partially contradicted by Gong's own plans-and-seats
  documentation, which states no minimum seat requirement ([RI] rows 20, 3).
- **"Gong support collapsed" and "Gong takes 20-30 minutes to process a call".**
  Competitor-blog only. Capterra rates Gong support 4.7/5 ([RI] rows 21, 22).
- **Gong's internal-surveillance complaints.** Real, well-sourced Capterra
  verbatims. Cut anyway, for brand reasons: leaning on them positions Backchannel
  as shadow IT and surveillance evasion ([RI] row 18).
- **ZoomInfo's auto-renewal litigation.** Real and independently sourced, but
  they are allegations and they are off-thesis. Omitted ([RI] row 46).
- **Clari Copilot's trigger-phrase mechanism and desktop-app requirement.** Both
  were re-verification targets and both failed: the only sources are 2023-dated
  community posts and Clari's current KB is silent on both. Dropped from the
  shipped page, which now uses Zoom Sales Assist as the verified example of the
  pre-configured pattern and says outright that we are not characterizing Clari's
  internals ([RI] row 70).
- **Teams Premium seat counts, the $30 enterprise Copilot price, and the
  Microsoft EU flex-routing default** ([BI]).
- **Real-world battery numbers for Plaud, Limitless, and Bee** -- third-hand
  aggregation of an audit we could not read ([ACH]).
- **Omi's device price and subscription tiers** -- four sources, four answers
  ([ACH]).
- **Anarlog Pro's price** -- pending browser verification ([LFO]).
- **Avoma's MCP server, Fathom's G2 review counts, "Fathom cannot transcribe
  uploaded audio"** -- single third-party mentions or aggregations ([MN]).

**What it publishes -- corrections to our own pages.**

- We said **four agents** on `/fireflies-alternative/` and in `site/llms.txt`.
  We ship nine. We understated ourselves in the machine-readable file that feeds
  AI answers about us, which is the worst place to be wrong ([MN] audit items
  1-2).
- We said Otter had "40M+ claimed users". Otter's own 2026-04-28 post says "more
  than 35 million people, across over one billion meetings". Corrected downward,
  in Otter's favor ([MN] audit item 3).
- We said "No open-source tool other than Backchannel ships this today" about
  live in-call agents. That was an overclaim. Corrected to "no **actively
  maintained** open-source meeting tool", naming Amurex (AGPL-3.0, no push since
  2025-05-27) as the precedent -- naming the counterexample is what makes the
  claim survive ([LFO] audit item 2).
- We said Meetily's diarization was "not shipped; planned". It shipped in Pro
  1.8.2 and costs $120/year. The corrected version is a stronger argument than
  the wrong one was ([LFO] audit item 1).
- We described only the Docker path and omitted that the desktop downloads
  require an approved Backchannel account, while every peer is an ungated
  download ([LFO] audit item 8).

**Links.** Primary `/open-source-meeting-assistants/`. This article links to
every comparison page it corrects, which is the one permitted exception to the
two-secondary-links rule in section D.

## B. The four refreshed Launch Kit posts

Voice check for all four: a maker sharing a tool, not a company running an ad.
First person singular. No adjectives a press release would use. The caveat block
is not a disclaimer at the bottom -- it is part of the pitch, because these
audiences read a missing caveat as a lie.

---

### B1. Show HN

**Title** (69 chars): `Show HN: Self-hosted meeting assistant with live in-call agents (MIT)`

**Submission URL**: `https://backchannel.page/` -- the canonical site, not
dev.to, not the GitHub repo. The repo link goes in the first comment.

**Timing**: Tuesday, Wednesday, or Thursday, 08:00-10:00 ET. One submission
only. No vote solicitation of any kind. Be present in the thread for the first
four hours; the comments are the post.

**First comment (maker's note), draft:**

> I built this because I kept finishing sales and discovery calls and only then
> realizing what I should have asked. Everything in this category records the
> meeting well and tells you about it afterwards. I wanted something that reads
> the transcript while the call is still running and puts a card on my second
> monitor.
>
> How it works: the browser captures mic plus tab/system audio as PCM16 16 kHz
> mono and streams it over a WebSocket with a one-byte track prefix. On the
> server, Silero VAD segments speech and WeSpeaker ResNet152 embeddings assign
> speaker identities -- both ONNX, both always local. Segments go to a batch
> transcriber (Gemini, or a local ONNX Whisper/Parakeet model). The transcript
> feeds nine seeded agents: an audio gateway, five live insight agents
> (consolidated analyst every ~40s, objection handler every ~10s over the last
> ~90s, a synthesizer, an opportunity specialist, and a strategic-signals agent
> every ~45s), and a three-agent post-call briefing pass where two independent
> lenses draft and an arbiter reconciles them. Every agent's model, prompt, and
> trigger interval is editable in an admin panel.
>
> The objection handler is the part I actually use. It returns two things: one or
> two sentences I could say in the next ten seconds, and the underlying concern
> plus a strategic angle for later in the call.
>
> Things you should know before you try it:
>
> - **It is not fully offline.** Transcription and diarization run locally and
>   can run with the network off. The agents cannot -- they route to Gemini or
>   OpenAI on your own key. There is no Ollama or LM Studio support yet; the
>   OpenAI base URL is currently hardcoded. That is the top item on my list.
> - **Live in-call assistance is not new and I did not invent it.** Amurex did it
>   in open source and has been dormant since May 2025. Clari Copilot and
>   Attention sell it. Otter shipped Live Assist on July 21 and Zoom took Sales
>   Assist to GA on July 22 at $66-99.99/user/month. What is different here is
>   that the response is generated against the objection that was actually
>   raised rather than selected from a card an admin wrote in advance, and that
>   it runs on your hardware for free. It is also less predictable than a curated
>   battlecard, which is a real tradeoff, not a rhetorical one.
> - **The diarizer is not novel either.** Vibe uses essentially the same
>   pyannote-segmentation-plus-WeSpeaker approach. What is different is running
>   it live per segment with voice enrollment and separate mic/system-track
>   identities.
> - **There is no authentication.** No user model, no roles, single worker. Run
>   it on your own machine or behind something. Do not expose it.
> - No mobile app, no wearable, no documented language support (English-first in
>   practice), no CRM sync, no compliance attestations.
> - Setup is `docker compose up --build` after copying `.env.example`. That is
>   five to seven steps and the first build takes minutes. Meetily, Anarlog,
>   Vibe, and Buzz are a download and a model file. If you want a mature
>   transcription tool rather than a meeting assistant, use Buzz -- it is four
>   years old, 20k stars, and 27 open issues.
>
> Repo: https://github.com/talberthoule/backchannel (MIT). Quickstart:
> https://backchannel.page/docs/quickstart/. Happy to answer anything about the
> audio path or the agent orchestration.

---

### B2. r/selfhosted

**Title**: `Backchannel: self-hosted AI meeting assistant with local diarization and live in-call agents (MIT, docker compose)`

**Flair**: Release / Self Promotion, per current subreddit rules. Disclose
authorship in the first line -- this subreddit punishes an undisclosed author far
harder than it punishes a rough tool.

**Deliberate choice, carried over from the original Launch Kit and kept on
purpose:** this post points at `docker compose`, not at the desktop downloads.
The desktop builds are delivered through an authenticated portal and need an
approved Backchannel account. Pitching an account-gated binary to r/selfhosted
would be the single fastest way to lose that room. The compose path is ungated
and stays that way. Say so in the post rather than letting someone discover it.

**Body, draft:**

> I wrote this, so treat it as self-promotion.
>
> **What it is.** A self-hosted meeting assistant that captures your mic plus tab
> or system audio in the browser -- no bot joins the call, so it works with Zoom,
> Meet, Teams, or anything that makes noise on the machine -- builds a
> speaker-attributed transcript, and runs agents over that transcript while the
> call is still happening.
>
> **What runs where.** Voice activity detection (Silero VAD) and speaker
> embeddings (WeSpeaker ResNet152) are ONNX and always run on your box.
> Transcription is either a local ONNX Whisper/Parakeet model or a cloud model,
> your choice. As of v0.3.7 the insight agents can point at any
> OpenAI-compatible server -- Ollama, LM Studio, vLLM -- so the whole stack can
> run with no key from anyone. One honest caveat I will not paper over: the
> Privacy First switch still turns the agents off, because it only recognizes
> the local transcription models. A fully local setup means configuring the
> endpoint yourself rather than flipping that toggle.
>
> **Stack.** React + TypeScript frontend, FastAPI backend, PostgreSQL 16, all in
> compose. Recorded audio lands as per-segment WAV on disk, so you can
> re-transcribe a session later through a different model without recording it
> again.
>
> **Install.**
>
> ```
> git clone https://github.com/talberthoule/backchannel
> cd backchannel
> cp .env.example .env    # then edit
> docker compose up --build
> ```
>
> Frontend on :3000, backend on :8001, Postgres on :5432. nginx in the frontend
> container proxies `/api` and `/ws`, so the browser only ever talks to :3000.
> First build downloads the ONNX models and takes a few minutes. `docker compose
> down -v` removes the database and audio volumes.
>
> There are also prebuilt desktop bundles for Windows, macOS, and Linux, but they
> come through an authenticated portal that needs an approved account, so I am
> pointing this post at compose instead. Compose needs no account and never will.
>
> **Caveats, up front:**
>
> - **No authentication of any kind.** No user model, no roles, single worker.
>   This is designed to sit on your own machine or your own LAN behind something
>   else. Do not put it on the public internet.
> - Not fully offline, per above.
> - Diarization is acoustic and inferred. It gets speakers wrong sometimes,
>   especially with crosstalk. There is voice enrollment to help, and mic and
>   system audio are tracked separately so remote speakers get their own IDs.
> - No mobile app. No documented multi-language support.
> - The project is young and small. If you want a mature offline transcriber,
>   Buzz and Vibe are both excellent and MIT. If you want fully offline
>   summarization today, Meetily does that with Ollama and I would point you
>   there.
>
> Repo (MIT): https://github.com/talberthoule/backchannel
> Docs: https://backchannel.page/docs/
>
> Happy to answer setup questions, and genuinely interested in what people want
> the agents to do that they do not do yet.

---

### B3. dev.to build log (syndicated copy -- canonical lives on backchannel.page)

**This is the correction the earlier Launch Kit most needed.** The build log is
published **first** at `https://backchannel.page/blog/nine-agents-build-log/`.
The dev.to copy carries `canonical_url` pointing home. Hacker News and Reddit
link to the backchannel.page URL, never to dev.to. dev.to ranks on dev.to's
domain; a canonical tag is the only thing that routes that authority back.

**dev.to frontmatter:**

```yaml
---
title: "Nine agents on a live meeting transcript: what broke"
published: false
canonical_url: https://backchannel.page/blog/nine-agents-build-log/
tags: python, ai, opensource, selfhosted
---
```

Hashnode: set the canonical URL field in post settings before publishing. Medium:
use "Import a story" against the canonical URL, which sets `rel=canonical`
automatically. Never paste into Medium's editor.

**Outline (build log, not a pitch -- ~1,400 words):**

1. **The problem.** Post-call summaries arrive after the only moment they could
   have changed anything.
2. **Two audio paths, not one.** Why the browser sends the same PCM16 16 kHz mono
   stream into both an interim gateway (a silent live listener that relays
   `input_transcription` events for immediate on-screen text) and a diarized
   batch path (VAD segments -> WAV -> transcriber -> saved transcript entries).
   The interim text is for the human; the batch text is for the agents. Mixing
   the two was the first thing I got wrong.
3. **One byte of protocol.** A one-byte track prefix (`0x00` mic, `0x01` system)
   on each binary frame, and why that beat a second WebSocket: it keeps ordering,
   it survives reconnects, and it is what lets remote speakers get their own
   `sys_` identities instead of colliding with local ones.
4. **Why local VAD plus embeddings instead of a hosted diarizer.** Cost per
   minute, latency, and the fact that a hosted diarizer would have made the
   privacy claim false. Credit where it is due: Vibe's `pyannote-rs` uses
   essentially the same segmentation-plus-WeSpeaker approach, so this is a
   well-trodden path, not an invention. Kaldi fbank features with mean-only CMN
   to match WeSpeaker's training frontend, which is the detail that moved
   accuracy most.
5. **Why nine agents instead of one big prompt.** Different jobs have different
   latency budgets. The objection handler has ten seconds and uses a
   flash-lite-class model over a 90-second window; the consolidated analyst has
   forty and runs four lenses in one call; the synthesizer is a slower,
   larger-model pass that reconciles what the fast agents produced. One prompt
   forces one latency budget and one model, and it loses every time.
6. **The dedup problem.** Independent agents rediscover the same insight. Current
   answer is word-overlap similarity within a 60-second sliding window in the
   orchestrator, which is crude and works better than it should. Honest about
   what it misses.
7. **The arbiter pattern for briefings.** Two independent lenses draft the
   post-call briefing without seeing each other -- a meeting-record lens and a
   discovery lens -- and a third agent reconciles agreement and conflict. Two
   drafts plus a referee beat one draft plus a critic in every comparison I ran,
   and it is cheap because the briefing runs once.
8. **What I would do differently.** The interval-based triggers should be
   event-based with backpressure. The dedup should be embedding-based. And the
   LLM route should have been an OpenAI-compatible base URL from day one.
   Hardcoding `https://api.openai.com/v1` was the single biggest limitation in
   the project until v0.3.7 fixed it (ALP-137) -- worth telling as a mistake we
   made and corrected, which reads better than presenting it as a feature.
9. **Honest limits** -- the same caveat block as the Show HN comment, compressed.
10. **Links.** Canonical article, and the repo. Nothing else. (See section D.)

---

### B4. YouTube demo script (90 seconds)

Silent-capable: every claim also appears as an on-screen caption, because most
views are muted. No music bed over the voiceover. Real session, real audio, no
mocked cards. Redact any real customer name in post.

| Time | Shot | Voiceover | On-screen caption |
| --- | --- | --- | --- |
| 0:00-0:08 | Pre-call view, session already created, cursor arms mic and tab audio | "This is Backchannel. It runs on my own machine and it listens to my meetings from my side of the call." | Self-hosted. MIT. No bot joins the call. |
| 0:08-0:18 | Call starts; interim transcript ticks in; diarized lines land with speaker labels | "Nothing joins the meeting. The browser captures my mic and the tab audio, and speaker labels are worked out locally." | Local VAD + speaker embeddings. Audio stays on your box. |
| 0:18-0:38 | The prospect raises a price objection; an objection card appears; zoom to show both halves | "Ten seconds after that objection, this card appears. The top half is what I could say right now. The bottom half is what the objection is actually about, and where to take it later in the call." | Objection handler: ~every 10s over the last 90s. |
| 0:38-0:52 | Strategic signals card set; a question card; an opportunity card matched against the offerings catalog | "Four more agents run alongside it -- an analyst, a synthesizer, an opportunity specialist matching against my own catalog, and a strategic-signals pass." | Five live agents. Nine in total. |
| 0:52-1:04 | Call ends; briefing renders; scroll it | "When the call ends, two independent briefing lenses write their own version and a third agent reconciles them." | Three-agent post-call briefing. |
| 1:04-1:18 | Admin panel: agent list, then open one agent and edit model, prompt, and interval | "Every agent's model, prompt, and trigger is editable. If you do not like what one of them says, you change the prompt." | Per-agent model, prompt, and interval. |
| 1:18-1:30 | Terminal running `docker compose up --build`, then the app at localhost:3000; end card | "It is MIT, it is a docker compose away, and transcription and diarization run locally. The agents still need your own Gemini or OpenAI key -- local model support is next." | MIT - github.com/talberthoule/backchannel - agents currently require a cloud API key |

The final caption is not optional. A 90-second demo that implies fully offline
operation would be the exact claim guardrail 1 forbids, and it is the one a
technical viewer will check first.

## C. Submission targets and order

Sequence is deliberate: the canonical must exist and be indexed before anything
syndicates, syndication must exist before communities send traffic, and
directories reward a site that already has writing on it.

**Phase 0 -- prerequisite (see section E).** No `/blog/` surface exists today.
Nothing in phase 1 can run until it does.

**Phase 1 -- owned site, canonical.**

1. Publish the article at `https://backchannel.page/blog/<slug>/`.
2. `Article` JSON-LD with `headline`, `datePublished`, `dateModified`, `author`,
   `mainEntityOfPage`, matching the `FAQPage` / `BreadcrumbList` pattern the
   comparison pages already use.
3. Add the URL to `site/sitemap.xml` with `lastmod`.
4. Register it in `site/llms.txt` under a new `## Writing` section, in the same
   shape as the existing `## Compare` block.
5. Add the reciprocal link on the primary comparison page (section D rule 2).
6. Submit for indexing (GSC, and IndexNow via the Bing route if it is wired).

**Phase 2 -- syndication, 24 to 72 hours after the canonical is indexed.**
Syndicating before the canonical is indexed risks the copy being crawled first.

| Target | Canonical mechanism | Notes |
| --- | --- | --- |
| dev.to | `canonical_url:` in frontmatter | Best fit for the build log and article 6. Tag conservatively. |
| Hashnode | Canonical URL field in post settings | Same body, no edits. |
| Medium | "Import a story" from the canonical URL | Sets `rel=canonical` automatically. Never paste into the editor. |

All three carry the same body. None of them gets an exclusive.

**Phase 3 -- communities.** One community submission per week, maximum. Never the
same article to Hacker News twice.

| Target | Article fit | Timing / rules |
| --- | --- | --- |
| Hacker News (Show HN) | B1 for the product; article 6 or 1 as a standalone link post | Weekday, 08:00-10:00 ET, Tue-Thu preferred. One submission. No vote solicitation. Author in-thread for the first four hours. |
| r/selfhosted | B2 | Disclose authorship in the first line. Correct flair. Compose path only. |
| r/LocalLLaMA | **Unblocked as of v0.3.7** | ALP-137 shipped 2026-07-25. Lead with the OpenAI-compatible endpoint and name the Privacy First caveat up front; this audience will find it. |
| r/opensource | Article 4 or article 6 | Project-and-license framing, not a pitch. |
| r/SideProject | B1 body, softened | Lowest signal of the four; use it last. |

Every community post links to the **backchannel.page** URL, not to dev.to,
Hashnode, or Medium.

**Phase 4 -- directories.**

| Target | Priority | Why |
| --- | --- | --- |
| **openalternative.co** | **Highest** | Meetily is listed there as the open alternative to Granola, Otter.ai, and tl;dv. We are absent. It serves exactly the intent our hub page targets, it is cheaper than building a page, and being missing from it while our closest competitor is listed is a standing loss ([MN]). Submit `/open-source-meeting-assistants/` as the landing target. |
| AlternativeTo | High | Same intent, larger surface, community-voted. Needs a maintained listing rather than a one-time submission. |
| awesome-selfhosted | Medium | A PR against a curated list with strict inclusion criteria (license, docs, description format, and project-age or activity requirements). **Read the current CONTRIBUTING before opening anything** -- the criteria change and a rejected PR is a visible miss. |
| Product Hunt | Last | Needs a polished asset set, a single-day push, and someone present all day. Do not attempt until the blog, the demo video, and screenshots all exist. |

**Cadence.** One article per one to two weeks. No two community submissions in
the same week. Directories are one-time-plus-maintenance and can run in parallel
with anything.

## D. Cross-linking rules

1. **One primary, at most two secondaries.** Each article links to exactly one
   primary comparison page, in prose, in the body -- not a footer link farm --
   plus at most two secondary comparison pages. Article 6 is the single exception:
   it links to every page it corrects, because that is its subject.
2. **Reciprocity is same-change.** The primary comparison page gets a link back
   to the article in a "Further reading" slot, added in the same commit as the
   article. An article that links out without a link back is a leak.
3. **The hub is the single consolidation point.** Every article links once to
   `/open-source-meeting-assistants/`. Articles do **not** link to each other, and
   they do not build a mesh across comparison pages. Equity consolidates at the
   hub; the hub already links out to the individual pages.
4. **Syndicated copies link only to the canonical and to the repo.** No deep
   links from dev.to, Hashnode, or Medium into comparison pages. Two reasons: it
   splits the authority the canonical tag is meant to route home, and those
   communities read a post full of deep marketing links as link-dropping. Two
   links out, both obvious, both defensible.
5. **Community posts link to backchannel.page.** The GitHub repo link goes in the
   body or the first comment, not in the submission URL -- except the Show HN,
   where the submission URL is the site itself and the repo is in the first
   comment.
6. **Every article states its access dates** and carries the same "as of July
   2026, check current pricing" caveat the comparison pages use. Any article that
   quotes a competitor price also names the source page.
7. **`site/llms.txt` gets a `## Writing` section** listing each article with a
   one-line description, mirroring `## Compare`. That file is the canonical
   machine-readable summary and it is how AI answer engines learn what we
   publish; an article that is not in it effectively does not exist to them.
8. **`sitemap.xml` and `llms.txt` update in the same change as the article.**
   Never as a follow-up.

## E. Blockers

**1. There is no article surface on backchannel.page. This blocks everything in
section A.**

`site/` today contains a landing page (`index.html`), twelve comparison pages,
the release pages, `admin/`, `downloads/`, plus `sitemap.xml`, `llms.txt`, and
`robots.txt`. There is no `/blog/`, no article template, and no `Article` JSON-LD
anywhere in the tree. Prerequisites, owned by whoever owns `site/`, not by this
plan:

- a `/blog/` index page and per-article directories following the existing
  `site/<slug>/index.html` convention;
- an article template with `Article` and `BreadcrumbList` JSON-LD, matching the
  `FAQPage` pattern already in use;
- `sitemap.xml` entries with `lastmod`;
- a `## Writing` section in `site/llms.txt`;
- a nav or footer entry so articles are reachable without the sitemap.

Until this lands, phases 1 through 4 in section C cannot start, and publishing to
dev.to first "to get moving" would recreate exactly the mistake this plan exists
to correct.

**2. r/LocalLLaMA is blocked on ALP-137 (configurable LLM endpoint for Ollama and
LM Studio).**

Verified 2026-07-24: `backend/app/services/llm.py:24` hardcodes
`OPENAI_BASE_URL = "https://api.openai.com/v1"` with no override, and the local
model entries in `backend/app/config.py` carry `"supports_text": False`, so
Privacy First mode gives local transcription and diarization and disables every
LLM agent. Meetily CE, Anarlog, and Vibe all summarize fully offline through
Ollama ([LFO]). r/LocalLLaMA is the single audience most certain to find and
punish "our differentiating feature needs a cloud API key", and the one most
likely to reward the fix. Do not post there before ALP-137 ships. When it does,
that is its own article and its own submission.

**3. Search demand is unmeasured -- ALP-138.**

No keyword-volume tool was available in any of the five research passes. Every
demand and priority ranking in those documents is qualitative, inferred from SERP
composition, G2 review counts, and competitor content density, and the research
says so explicitly ([MN]). Before allocating build hours against the article
list, run the gsc MCP against backchannel.page for existing impressions on these
terms, and a volume API if one becomes available. The article ordering in section
A is defensible on evidence and decay; it is not validated on demand.

**4. Verification debt gating specific articles.**

| Gate | Blocks | Action |
| --- | --- | --- |
| Otter Live Assist release not fetched directly (search summary only) | Article 1 | Fetch Businesswire 20260721446216 in a browser, or publish the Zoom half alone |
| Anarlog Pro price ($15/mo, $150/yr) -- `/pricing/` 404'd | Article 4 | Verify in a browser or write "a paid tier" |
| Microsoft MC1269223 (EU flex routing) not fetched | Article 5 | Omit unless verified. Do not soften it into an insinuation |
| tl;dv paid pricing | Any hub-table refresh | Vendor page returns metadata only; publish free-tier limits instead |

**5. Product-truth debt.** `CLAUDE.md` still describes four agents and 15s/5s
intervals and omits `strategic_signals` and the three briefing lenses. Three
separate research passes flagged it. `docs/agents.md` and
`backend/app/services/seed_agents.py` are authoritative. Reconciling `CLAUDE.md`
is a separate task, but until it happens, anyone drafting from it will reproduce
the exact error this plan was written to fix.

**6. Assets do not exist.** The 90-second demo needs a real recorded session with
redactable content, and the articles need at least one image each for social
cards. Neither exists today. This gates Product Hunt entirely.

## What we kept and what we discarded from the earlier Launch Kit

**Kept, deliberately.**

- The four-artifact structure: Show HN, r/selfhosted, a dev.to build log, and a
  90-second demo. It is the right set for this audience mix.
- The maker voice. First person, one person, no press-release adjectives.
- The honest-caveats discipline. Every post carries a caveat block in the body,
  not a disclaimer at the bottom. These audiences punish spin harder than they
  punish rough edges, and the twelve comparison pages already set this standard.
- Steering self-hosters to the free `docker compose` path rather than the
  account-gated desktop downloads -- **and saying openly why**. This was the
  original's best instinct and it is preserved verbatim in intent.
- The 90-second length for the demo.

**Discarded or corrected.**

- **"Four agents" is gone.** We ship nine. `backend/app/services/seed_agents.py`
  is the source of truth. The same error was live on
  `/fireflies-alternative/` and in `site/llms.txt`, which is why it also appears
  in article 6 as a correction to ourselves.
- **dev.to is no longer the canonical.** It was treated as "the one you own",
  which is backwards -- dev.to ranks on dev.to's domain. The canonical is
  backchannel.page; dev.to, Hashnode, and Medium are syndication with
  `canonical_url` pointing home; Hacker News and Reddit link to the
  backchannel.page URL.
- **"No bot" as the lead differentiator is demoted.** Fathom shipped bot-free
  capture 2026-04-15, Avoma sells bot-less native recording, and Plaud Desktop
  has been free on every plan since January 2026. Bot-free is table stakes and
  leading with it now makes us look like a follower ([MN] audit item 5).
- **Any implication that live in-call assistance is unique is gone.** Otter Live
  Assist (2026-07-21) and Zoom Sales Assist (2026-07-22) both went GA between the
  original draft and this plan, and Amurex did it in open source years earlier.
- **Any implication of fully-offline end-to-end operation is gone**, and replaced
  with an explicit statement of where the boundary is.
- **Cross-platform coverage is no longer framed as exclusively ours** -- Google
  crossed that boundary on 2026-04-22.
- The original had no competitive research behind it at all, so every specific
  competitor claim in the refreshed posts is new and traces to a claim-verification
  row in one of the five research documents.
