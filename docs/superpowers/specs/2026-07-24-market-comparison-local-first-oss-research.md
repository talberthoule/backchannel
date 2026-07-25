# Local-first and open-source - competitive research (2026-07-24)

## Category summary

In this category "self-hosted and private" buys nothing. Every project here
runs transcription on-device, most are MIT, and several are further along on
polish, platform support, and community than Backchannel is. Repeating our
privacy line at these projects would read as noise at best and as
overclaiming at worst.

Three findings shape the whole category.

**1. The two leading open-source meeting notetakers both put automatic
speaker attribution behind a paid tier.** Meetily shipped speaker
diarization in Meetily **Pro 1.8.2** ("live as you record and on audio you
import or re-transcribe"), not in the MIT Community Edition. Anarlog's
documented free path is *manual* speaker-label assignment; automatic
speaker indexes arrive from the STT provider, and hosted "speaker
identification" is an Anarlog Pro feature. A local pyannote diarization PR
in the Anarlog repo (#3821) was closed **unmerged** on 2026-05-01. So the
honest, current, defensible line is not "we have diarization and they do
not" -- it is: **Backchannel gives automatic, live, local speaker
attribution away for free; the two biggest OSS notetakers charge for it.**

**2. No maintained open-source peer has shipped a live in-call agent
layer.** Anarlog's "agents" are a read-only MCP/CLI surface for *external*
coding agents to query stored meetings afterwards, explicitly scoped as
"All current Anarlog data operations are read-only." Meetily CE and Pro are
transcription plus post-meeting summaries. Buzz and Vibe are transcription
workstations. The only OSS project that ever marketed live in-meeting
suggestions, **Amurex** (AGPL-3.0, 2.9k stars), has had **no push since
2025-05-27** -- roughly 14 months. The live-agent lane is still open.

**3. The category leader renamed itself twice and dropped two platforms.**
Hyprnote became Char, then **Anarlog** (blog post 2026-05-03), relicensing
GPL to MIT and stating "We are not planning Linux or Windows support."
Its shipping artifacts are macOS `.dmg` only. Anarlog is extremely
healthy as a macOS product -- near-daily releases, three commits on
2026-07-24 alone -- but there is now a large, explicitly abandoned
Windows/Linux intent pool searching for "Hyprnote".

Where we are genuinely behind: **local LLM support**. Backchannel's agent
layer routes only to Google and OpenAI (verified by repo grep: zero
references to Ollama, LM Studio, or an OpenAI-compatible local endpoint
anywhere outside our own marketing copy). Meetily CE, Anarlog, and Vibe all
summarize fully offline via Ollama. In a category where privacy is table
stakes, "our differentiating feature needs a cloud API key" is the sharpest
attack available against us, and it is true.

## Per-competitor profiles

### Anarlog (formerly Hyprnote, briefly Char) -- primary target

**Positioning.** "AI notepad for private meetings." Bot-free, local-first
macOS notetaker; you type rough notes in a Memos pane while it listens, then
it merges your notes with the transcript into a structured summary.

**License.** MIT (relicensed from GPL in the 2026-05-03 rename post).
Repo: `github.com/fastrepl/anarlog`.

**Platforms.** macOS only. Release assets are
`hyprnote-macos-aarch64.dmg` and `hyprnote-macos-x86_64.dmg` (the filenames
still carry the old brand). The rename blog says "We are not planning Linux
or Windows support"; the docs separately say "Windows package-manager
distribution are forthcoming." Those two statements conflict; the shipped
artifacts are macOS only.

**Local processing reality.** Genuinely local by default: "Local
transcription runs on-device, so audio never leaves your machine." Full
offline operation requires downloading an on-device transcription model plus
LM Studio or Ollama for summaries and chat. Local models are Apple Silicon
only. Hosted models require Pro.

**Diarization.** This is the nuanced one. Docs describe manual assignment:
"In a transcript, select a speaker label to assign a participant and use
Apply to all when the same speaker appears again." The local pyannote-ONNX
diarization PR (#3821, "Diarize Speakers" button, 2/3/4/Auto up to 6
speakers) was **closed without merging** on 2026-05-01. A merged PR (#5834,
2026-07-01) handles the case where "the STT provider attaches diarization
speaker_index values" and pins DirectMic to the local user -- i.e.
automatic diarization is whatever the chosen STT provider supplies. Pro
lists hosted "speaker identification". Net: automatic local diarization is
not a documented free feature; live speaker labels exist but the automatic
attribution behind them is provider-dependent, and the hosted path is paid.

**Real-time vs post-call.** Live transcript with speaker labels and a live
notepad. Summaries, chat, and agent access are post-meeting. No live AI
suggestions during the call.

**Setup friction.** Best in category: download one `.dmg`, open it,
download an on-device model. Two steps, no terminal, no key required for the
local path.

**Project health.** Excellent and improving. 8,869 stars, only 10 open
issues, pushed 2026-07-24, three commits on 2026-07-24, releases
`desktop_v1.3.7` / `1.3.8` / `1.3.9` on three consecutive days
(2026-07-22/23/24). Changelog runs Jan 4 to Jul 25 2026 at near-daily
cadence. The one caveat is strategic, not technical: the founders'
primary product is now **Char**, a separate paid SaaS todo app, and the
rename post frames Anarlog as "community-maintained" with "patches,
security fixes, the occasional feature." The commit log does not currently
support a slowdown narrative -- do not claim one.

**Pricing contradiction to watch.** The 2026-05-03 post says Anarlog is
"free forever -- there is no paid tier." The current site sells **Anarlog
Pro at $15/month or $150/year** (cloud transcription, cloud LLM,
local-cloud sync, calendar, speaker identification). Treat the live site as
authoritative and do not quote the blog line.

**Genuine overlaps.** Bot-free capture of mic plus system audio; MIT;
local transcription; BYO key or local model; import audio/SRT/VTT; export;
chat over meeting content.

**What Backchannel has that they lack.** Live in-call insight agents;
Windows and Linux support at all; a multi-user server with a shared archive
and REST API; cross-session chat spanning up to 20 sessions; free automatic
live diarization with voice enrollment; split mic/system track identities;
re-transcription of stored audio through a different model.

**What they have that Backchannel lacks (ruthless).** A two-step install
with no account gate. A far better macOS story (we ship an unsigned macOS
bundle with no bundled ffmpeg and no Sortformer). Local LLM summaries via
Ollama/LM Studio -- we have none. Calendar integration. A notepad-merge
workflow that users specifically praise. 8,869 stars against our 1. Native
MCP server so external agents can query meetings. Near-daily release
cadence.

**Sharpest true differentiator.** Anarlog tells you what was said; it will
not tell you what to say next, and it will not run on Windows or Linux at
all.

**Sources.** `github.com/fastrepl/anarlog`, `api.github.com/repos/fastrepl/anarlog`,
`anarlog.so`, `anarlog.so/blog/char-is-now-anarlog/`, `anarlog.so/changelog/`,
`docs.anarlog.so/llms-full.txt`, `docs.anarlog.so/agents/overview`,
PRs #3821 and #5834.

### Meetily -- refresh target

**Positioning.** "Privacy first, AI meeting assistant ... 100% local
processing. no cloud required." Self-described "#1 self-hosted, open-source
AI meeting note taker for macOS and Windows."

**License.** MIT for the Community Edition. Repo:
`github.com/Zackriya-Solutions/meetily`. Open-core: Pro and Enterprise are
separate commercial products.

**Platforms.** Native `.exe`/`.msi` for Windows and `.dmg` for macOS.
Linux requires building from source; the downloads page lists Linux as "in
development" with a waitlist.

**Local processing reality.** Real. Local Whisper/Parakeet with GPU
acceleration, Ollama-first summarization, custom OpenAI-compatible endpoint
support. The fully-offline story remains stronger than ours.

**Diarization.** **Changed since our page was written.** Speaker
diarization shipped in **Meetily Pro 1.8.2**: "it has since shipped in
Meetily Pro (1.8.2) - live as you record and on audio you import or
re-transcribe." The downloads page lists "Speaker diarization (who said
what)" under Pro only; the MIT CE README still calls it "planned for PRO in
mid-June." It is live and it is paid.

**Real-time vs post-call.** Real-time transcription (claimed sub-2-second
latency) and, in Pro, real-time diarization. Analysis is still post-meeting
summaries. No live insight agents in either edition.

**Setup friction.** Download an installer, pick a model, optionally point
at Ollama. Clearly easier than our Docker path on Windows and macOS; harder
than ours on Linux, where Meetily requires a source build and we ship a
portable tarball.

**Project health.** Large but with an open-core divergence signal.
26,451 stars, 2,665 forks, **311 open issues**, last commit to the public
MIT repo **2026-06-05** (v0.4.0) -- about seven weeks quiet as of today.
Meanwhile the commercial Pro line is at **1.8.2**. Report this as a factual
observation about where development is happening, not as an accusation.
Site claims 369K+ users / 369.8K downloads and 25.9K stars.

**Pricing.** Community free. Pro $10/user/month billed annually ($120/year),
14-day trial. Enterprise custom.

**Genuine overlaps.** MIT core, bot-free system-audio capture, local
Whisper/Parakeet, real-time transcription, audio import and
re-transcription, works with any conferencing app, Windows support.

**What Backchannel has that they lack.** Free automatic diarization
(theirs is $120/year); five configurable live insight agents plus a
three-agent post-call briefing pass; per-agent model/prompt/trigger
configuration; cross-session chat (Pro-only for them); a multi-user server
with a REST API in the MIT codebase (their self-hosted deployment is a Pro
feature); voice enrollment; split mic/system track identities.

**What they have that Backchannel lacks (ruthless).** Fully-offline
summarization via Ollama -- our agents cannot run without a cloud key.
26,451 stars against our 1. Polished native installers on Windows and
macOS. GPU-accelerated local ASR tuning. A real content and community
operation. HIPAA/GDPR marketing posture we have not matched.

**Sharpest true differentiator.** Meetily makes you pay $120/year for
"who said what" and still will not tell you anything during the meeting.
Backchannel gives the first away and does the second.

**Sources.** `api.github.com/repos/Zackriya-Solutions/meetily`,
`meetily.ai`, `meetily.ai/downloads`,
`meetily.ai/blog/meetily-v0-3-0-import-audio-retranscribe`,
GitHub release v0.4.0.

### MacWhisper

**Positioning.** Polished Mac transcription and dictation app from
Goodsnooze. Not a meeting assistant in our sense; a transcription
workstation with meeting recording bolted on.

**License.** Proprietary. **Not open source.** Include it only in a
category roundup, never in an "open-source alternatives" frame.

**Platforms.** macOS only.

**Local processing reality.** Fully local Whisper and Parakeet models:
"Process sensitive content locally without data ever leaving your Mac."
Optional cloud AI services in Pro.

**Diarization.** **Automatic Speaker Recognition is in the FREE tier.**
This matters: it means "free local speaker recognition" is not a
Backchannel-exclusive claim on macOS. Reviewers describe accuracy as good
enough for 2-4 speaker interviews but below specialized cloud services.

**Real-time vs post-call.** File and recording oriented. Pro adds automatic
meeting recording for Zoom, Teams, Webex, Skype, Chime, Discord. AI
processing is prompt-driven and post-hoc.

**Setup friction.** One download, one model download. Trivial.

**Project health.** Actively maintained commercial product; independent,
no outside funding.

**Pricing.** Free tier; Pro EUR 64 one-time with lifetime updates on the
official site (a EUR 59 figure circulates from older third-party reviews).
App Store variant sells as a subscription.

**Overlaps.** Local transcription, local speaker recognition, system/meeting
audio capture, exports.

**What Backchannel has that they lack.** Everything meeting-shaped: live
agents, a meeting record model with directives and documents, multi-user
server, cross-session chat, Windows and Linux, open source.

**What they have that Backchannel lacks.** Free local speaker recognition
on macOS with zero setup, a genuinely polished Mac app, one-time pricing
with no subscription, deep integrations (Notion, Obsidian, Zapier), and a
CLI.

**Sharpest true differentiator.** MacWhisper produces a transcript.
Backchannel produces a meeting.

**Sources.** `macwhisper.com`, third-party pricing reviews (lower
confidence on the EUR 59 vs EUR 64 discrepancy).

### Superwhisper

**Positioning.** Local-first voice-to-text and dictation for macOS,
Windows, and iOS, with a Meeting mode added on top.

**License.** Proprietary. Not open source.

**Platforms.** macOS, Windows, iOS.

**Local processing reality.** On-device by default on Apple Silicon
(Whisper Tiny through Large V3 Turbo, Parakeet V2/V3); cloud models
optional via OpenAI, Anthropic, Deepgram, Groq. Intel Macs lean cloud.

**Diarization.** Documented: there is a dedicated
"Speaker-Separated Meetings" docs page -- "transcribe meetings with speaker
separation and process them with AI for enhanced insights."

**Real-time vs post-call.** Meeting mode "records audio from your meetings
and transcribes it into a clear summary with action items" -- post-call.
The real-time surface is dictation, not meeting analysis.

**Setup friction.** One download. Trivial.

**Project health.** Active commercial product.

**Pricing.** Free tier including meeting recording; Pro around
$8.49-$9.99/month, roughly $85/year, lifetime around $250. Prices vary
across sources; treat exact figures as medium confidence.

**Overlaps.** Local transcription, meeting recording, speaker separation,
BYO model provider.

**What Backchannel has that they lack.** Open source, self-hosting, live
agents, multi-user server, REST API, cross-session chat, exports as a
meeting record.

**What they have that Backchannel lacks.** System-wide dictation (a
different job we do not do), iOS, Windows-plus-macOS parity, and a
frictionless install.

**Sharpest true differentiator.** Superwhisper is a dictation tool that
also records meetings. Do not frame it as a meeting-assistant rival; frame
it as adjacent.

**Sources.** `superwhisper.com`, `superwhisper.com/docs/llms.txt`,
`superwhisper.com/docs/modes/speaker-separated-meetings.md`.

### Vibe

**Positioning.** "Transcribe on your own!" Cross-platform offline
transcription desktop app.

**License.** MIT. Repo `github.com/thewh1teagle/vibe`.

**Platforms.** macOS, Windows, Linux. The best OSS platform coverage in
this set alongside Buzz.

**Local processing reality.** "Ultimate privacy: fully offline
transcription, no data ever leaves your device." Whisper, Nemotron 3.5, and
Parakeet TDT v3; GPU acceleration across vendors.

**Diarization.** Yes, via the same author's `pyannote-rs`: segmentation-3.0
for speech activity plus **WeSpeaker embeddings** with cosine similarity on
onnxruntime. **This is essentially the same architecture as Backchannel's
diarizer.** We must never imply our VAD-plus-WeSpeaker approach is novel;
what is distinctive is that we run it *live, per segment, during the call*,
with voice enrollment and split-track identity, feeding agents. Vibe users
report speaker-switch instability (open issues #74, #279, #752).

**Real-time vs post-call.** File-first, with mic and system-audio capture
and a realtime preview. Not a meeting assistant: no meeting record, no
participants, no insights.

**Setup friction.** One download plus a model. Trivial.

**Project health.** Healthy. 6,885 stars, 458 forks, pushed 2026-07-17.
181 open issues is high relative to stars -- worth noting neutrally.

**Overlaps.** MIT, offline transcription, WeSpeaker-based diarization,
system-audio capture, Ollama summarization, CLI, exports.

**What Backchannel has that they lack.** Meeting semantics entirely: live
agents, participants and speakers as records, directives, documents,
insight lifecycle, server, API.

**What they have that Backchannel lacks.** Fully local summarization via
Ollama; a Claude API summarization path; broad export formats (SRT, VTT,
PDF, DOCX, HTML, JSON); YouTube/URL ingestion; stable-timestamps subtitle
mode; trivial install on all three platforms.

**Sharpest true differentiator.** Vibe transcribes files. Backchannel runs
a meeting.

**Sources.** `api.github.com/repos/thewh1teagle/vibe`, Vibe README,
`github.com/thewh1teagle/pyannote-rs`.

### Buzz

**Positioning.** Offline Whisper transcription workstation, the elder
statesman of the category (created 2022-09-24).

**License.** MIT. Repo `github.com/chidiwilliams/buzz`.

**Platforms.** macOS, Windows, Linux (Flatpak, Snap), plus PyPI.

**Local processing reality.** Fully offline, multiple Whisper backends and
Hugging Face Transformer model families.

**Diarization.** Yes: "Speaker identification in transcribed media," plus
"Speech separation before transcription for better accuracy on noisy
audio."

**Real-time vs post-call.** "Live realtime audio transcription from
microphone" with a presentation/caption overlay window. No meeting
analysis; AI summary exists only as a plugin.

**Setup friction.** One install (or `pip install buzz-captions`). Trivial.

**Project health.** Very healthy and unusually well-kept: 20,357 stars,
1,499 forks, only **27 open issues**, pushed 2026-07-24. The best
issue-hygiene signal in the entire set.

**Overlaps.** MIT, offline transcription, live mic transcription, speaker
identification, CLI, exports.

**What Backchannel has that they lack.** Meeting model, live agents,
server, multi-user, cross-session chat, insight lifecycle, participants.

**What they have that Backchannel lacks.** Four years of maturity, 20k
stars, Flatpak/Snap/PyPI distribution, a plugin system, watch folders, and
an install that takes one command.

**Sharpest true differentiator.** Buzz is captions and transcripts.
Backchannel is analysis during the call.

**Sources.** `api.github.com/repos/chidiwilliams/buzz`, Buzz README.

### Amurex -- the one addition (justified)

**Why include it.** It is the only open-source project that ever shipped a
live in-meeting copilot with real-time suggestions, which makes it the
single strongest counterexample to our central claim. Its current state is
therefore load-bearing evidence, and omitting it would look like we cherry
picked.

**Positioning.** "World's first AI meeting copilot." Chrome extension for
Google Meet and Microsoft Teams with live suggestions, transcripts,
summaries, and action items; self-hostable.

**License.** AGPL-3.0 (not MIT). The companion `amurex-web` repo has **no
license file at all**.

**Platforms.** Browser extension plus a self-hosted web app.

**Local processing reality.** Self-hostable, but it is a hosted-service
architecture with a cloud app at `app.amurex.ai`; it was never on-device
first.

**Diarization.** Not a documented feature.

**Real-time vs post-call.** Genuinely real-time -- live suggestions during
the meeting. This is the one real precedent for what Backchannel does.

**Project health.** Effectively dormant. Main repo last pushed
**2025-05-27**; `amurex-web` last pushed 2025-09-05. 2,858 stars, 61 open
issues on the main repo and 63 on the web repo, neither archived.

**Verdict.** The live-agent idea has been tried in OSS and abandoned. Our
claim must therefore be time-bounded and precise: *no actively maintained*
open-source meeting tool ships a live agent layer today.

**Sources.** `api.github.com/repos/thepersonalaicompany/amurex`,
`api.github.com/repos/thepersonalaicompany/amurex-web`, HN Show HN threads
42319601 and 42779378.

## Overlap and novelty matrix

| Dimension | Anarlog | Meetily | MacWhisper | Superwhisper | Vibe | Buzz | Amurex | Backchannel |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| License | MIT | MIT core, paid Pro | Proprietary | Proprietary | MIT | MIT | AGPL-3.0 | MIT, no paid tier |
| macOS | Yes | Yes | Yes | Yes | Yes | Yes | Browser | Yes (unsigned bundle) |
| Windows | No | Yes | No | Yes | Yes | Yes | Browser | Yes |
| Linux | No | Source build | No | No | Yes | Yes (Flatpak/Snap) | Self-host | Yes (tarball) |
| Local transcription | Yes (Apple Silicon) | Yes | Yes | Yes | Yes | Yes | No | Yes (ONNX Whisper/Parakeet) |
| Automatic diarization, free | Not documented; provider-dependent | No (Pro only) | Yes | Yes | Yes | Yes | No | Yes |
| Live diarization during call | Labels live; auto is provider-supplied | Pro only | No | No | No | No | No | Yes |
| Voice enrollment / known-speaker profile | No | No | Manual labels | No | No | No | No | Yes |
| Live in-call AI insights | No | No | No | No | No | No | Yes (dormant) | Yes |
| Configurable agents (model, prompt, trigger) | No | No | No | No | No | No | No | Yes |
| Post-call summary/briefing | Yes | Yes | Prompt-based | Yes | Ollama/Claude | Plugin | Yes | Yes (3-agent briefing) |
| Fully offline analysis (local LLM) | Yes (Ollama/LM Studio) | Yes (Ollama) | Local ASR, cloud AI | Partial | Yes (Ollama) | Plugin | No | **No** |
| Multi-user server + REST API | No | Pro only | No | No | No | No | Self-host web app | Yes |
| Cross-session chat | Post-hoc chat | Pro only | No | No | No | No | Yes | Yes (up to 20 sessions) |
| Bot-free capture | Yes | Yes | Yes (Pro) | Yes | Yes | Yes | Extension in-page | Yes |
| Setup steps to first meeting | ~2 | ~3 | ~2 | ~2 | ~2 | ~1-2 | Many | ~5-7 |
| GitHub stars | 8,869 | 26,451 | n/a | n/a | 6,885 | 20,357 | 2,858 | 1 |
| Last push | 2026-07-24 | 2026-06-05 | n/a | n/a | 2026-07-17 | 2026-07-24 | 2025-05-27 | 2026-07-24 |

## Positioning recommendation

**Page type.** Two head-to-head pages plus one category roundup.

1. `/vs-anarlog/` -- a head-to-head, but titled and optimized to also catch
   "Hyprnote alternative" traffic, because the product renamed twice in
   2026 and the old brand still owns the searches.
2. `/vs-meetily/` -- refresh in place; several claims are now false.
3. `/open-source-meeting-assistants/` -- an honest roundup covering
   Anarlog, Meetily, Buzz, Vibe, MacWhisper, Superwhisper, and Amurex, with
   the matrix above. This is the GEO play: a fair, sourced, dated
   comparison table is exactly the artifact LLM answer engines cite, and it
   is the only format where we can afford to say plainly that four of the
   seven beat us on install.

**Target keywords and intent.**

- `hyprnote alternative`, `anarlog alternative`, `hyprnote windows`,
  `hyprnote linux`, `anarlog windows` -- navigational and
  platform-frustration intent. This is the single best opening in the
  category: the vendor has publicly said it will not build Windows or
  Linux, and we ship both. High intent, low competition.
- `meetily alternative`, `meetily speaker diarization free`,
  `meetily pro price`, `free alternative to meetily pro` -- commercial
  intent from people who just hit the Pro paywall on "who said what."
- `open source meeting assistant with speaker diarization`,
  `free local speaker diarization meeting` -- the paywall wedge.
- `real time meeting assistant open source`,
  `ai meeting copilot during call open source`,
  `open source amurex alternative` -- our actual category, currently
  uncontested by any maintained project.
- `self hosted meeting assistant for teams`,
  `open source meeting notes multi user` -- the server angle, which no
  free peer offers.

**Sharpest true differentiator now that privacy is table stakes.**

> Every tool here keeps your audio local. Only Backchannel does anything
> with it before the meeting ends.

Concretely: five live agents -- consolidated analyst, objection handler,
synthesizer, opportunity specialist, and strategic signals -- each with its
own model, prompt, and trigger, pushing questions, objections,
opportunities, action items, risks, and next-question cues into the browser
while the call is still running, plus a three-agent post-call briefing pass.
No maintained open-source peer has this. The only one that ever did,
Amurex, has not been touched since May 2025.

**Secondary differentiator (nearly as strong, and newer).** Both leading
open-source notetakers charge for "who said what." Meetily's diarization is
Pro-only at $120/year. Anarlog's hosted speaker identification is Pro at
$15/month, and its free path is manual label assignment. Backchannel's
automatic, live, local diarization -- Silero VAD plus WeSpeaker ResNet152,
with voice enrollment and separate mic/system-track identities -- is in the
MIT repo with no tier above it.

**The honest concession we must make.** Two, stated plainly and up front:

1. **Setup.** Anarlog, MacWhisper, Superwhisper, Vibe, and Buzz are a
   download and a model file: about two steps and two minutes, no terminal,
   no account. Meetily is an installer plus a model. Backchannel is either
   Docker Compose (install Docker, clone, copy `.env`, `docker compose up
   --build` while it builds images and downloads ONNX models, open
   `localhost:3000`, paste an API key -- five to seven steps, and the first
   build is minutes not seconds), or a desktop bundle that requires an
   **approved Backchannel account** before you can download it. Every peer
   in this category is a direct download with no gate. That approval gate is
   a bigger friction delta than Docker is, and the comparison page should
   say so rather than let a reader discover it.
2. **Our agents need a cloud API key.** Backchannel transcription and
   diarization run fully offline, but the agent layer routes only to Google
   or OpenAI -- there is no Ollama, LM Studio, or OpenAI-compatible local
   endpoint in the codebase. Meetily CE, Anarlog, and Vibe all summarize
   with a fully local model. If air-gapped analysis is a hard requirement,
   we are the wrong tool today. Say it in the same paragraph as the agent
   pitch, not in a footnote.

**Product implication (report upward).** An OpenAI-compatible base-URL
option on the model registry would close the single largest competitive gap
in this category and would let us say "local agents" instead of "local
transcription, cloud agents." In a privacy-table-stakes category that is
worth more than any page on this list.

## Existing vs-meetily page audit

File: `site/vs-meetily/index.html`. Nine issues, three of them factually
wrong today.

| # | Location | Current claim | Status | Suggested correction |
| --- | --- | --- | --- | --- |
| 1 | Meta description, FAQ schema x2, table row, "Who said what" section | "speaker diarization is not in its free edition"; "Not shipped; planned, slated for Pro" | **Factually wrong** | "Shipped in Meetily Pro 1.8.2 -- live as you record and on imported or re-transcribed audio -- but not in the MIT Community Edition. Pro is $10/user/month billed annually ($120/year)." Update the meta description and both FAQ answers to match. |
| 2 | "In depth" -> "Notes after vs insights during" | "No open-source tool other than Backchannel ships this today." | **Overclaim -- highest reputational risk** | "No actively maintained open-source meeting tool ships this today. Amurex (AGPL-3.0) did, and it has had no commits since May 2025." Naming the precedent is what makes the claim credible to this audience. |
| 3 | Same section, and the FAQ | "four insight agents" | **Understated / stale** | "Five live agents -- consolidated analyst, objection handler, synthesizer, opportunity specialist, and strategic signals -- plus a three-agent post-call briefing pass." |
| 4 | Table row and FAQ | "21.6k+ GitHub stars" | Stale | "26.4k GitHub stars (2026-07-24)". |
| 5 | Table row and FAQ | "308,600+ claimed downloads" | Stale | "369K+ claimed users / 369.8K downloads (meetily.ai, 2026-07-24)". |
| 6 | Section subhead | "as of mid-2026 (Meetily v0.4.0 era)" | Incomplete | Keep v0.4.0 for the Community Edition (2026-06-05) but add that the commercial Pro line is separately at 1.8.2, so CE version numbers are not the product's version numbers. |
| 7 | "Maturity and community" | "polished releases, and an active content presence" with no counterweight | Unbalanced in Meetily's favour, but now missing a material fact | Keep the concession (they do win on community), and add one neutral sentence: "Development of the MIT Community Edition has been quiet since v0.4.0 on 2026-06-05, while the commercial Pro line has continued shipping." Present as an open-core observation, not a criticism. |
| 8 | Table row "Install experience" -> Backchannel | "Docker Compose; NVIDIA GPU optional, AMD-on-Windows script" | Incomplete and, once corrected, less flattering | "Docker Compose, or desktop bundles for Windows, macOS, and Linux -- the desktop downloads require an approved Backchannel account. Meetily's installers are ungated." Also update the "What getting started looks like" section, which still describes only the Docker path. |
| 9 | "Free vs open-core" | "Meetily's roadmap routes its best upcoming features ... toward a $10/user/mo Pro tier" | Tense is stale | "Meetily has routed its best features -- diarization, chat with meetings, self-hosted deployment, advanced exports -- into a $10/user/month Pro tier." Chat-with-meetings and self-hosted deployment being Pro strengthens our free-server point; add them. |
| 10 | JSON-LD `dateModified` | "2026-07-13" | Stale on edit | Update to the refresh date. |

Claims on the page that **remain accurate and should be kept**: both cores
MIT; Meetily is a Tauri/Rust desktop app and Backchannel is a
FastAPI+PostgreSQL server; bot-free capture on both sides; Meetily's
Ollama-first fully-offline analysis is better than ours; Backchannel's
insight agents currently need a Gemini or OpenAI key (verified: no local LLM
route exists in the repo); Backchannel has no paid tier; Meetily has no
real-time in-call insights.

## Page recommendation and priority

| Target | Decision | Rationale | Effort |
| --- | --- | --- | --- |
| Meetily | **Refresh existing `/vs-meetily/`** | Three claims are live on the site and wrong today, including a "no open-source tool other than Backchannel" overclaim that this audience will punish. Highest risk-adjusted value; fixing it also strengthens the page, since "they charge $120/year for diarization" beats "they do not have it." | 1-2 hours |
| Anarlog / Hyprnote | **Build new `/vs-anarlog/`** (title and H1 should carry "formerly Hyprnote") | 8,869 stars, near-daily releases, the strongest brand in local-first meeting notes, and a double rename that has left the "Hyprnote" search pool unowned. Their explicit refusal to support Windows or Linux is an unusually clean, non-adversarial wedge. Must concede install and macOS polish plainly. | 4-6 hours |
| MacWhisper | **Fold in** to the roundup | Proprietary, macOS-only, and a different job (transcription/dictation). A dedicated "vs" page would be a category error, and its free automatic speaker recognition weakens our diarization headline if we invite the comparison. | included below |
| Superwhisper | **Fold in** to the roundup | Same reasoning; it is a dictation tool with a meeting mode. Adjacent, not rival. | included below |
| Vibe | **Fold in** to the roundup | Excellent MIT tool, but file-transcription scope. Also note internally: it uses the same WeSpeaker embedding approach we do, so we must never call our diarizer architecture novel. | included below |
| Buzz | **Fold in** to the roundup | 20k stars, best issue hygiene in the set, but no meeting semantics. Useful as the "if you only need transcripts, use Buzz" honest recommendation, which buys credibility. | included below |
| Amurex | **Skip as a page; cite as evidence** | Dormant since May 2025 and AGPL. Its value is as the named precedent that makes our live-agent claim survive scrutiny. | n/a |
| Category roundup | **Build `/open-source-meeting-assistants/`** | One honest, dated, sourced matrix covering all seven. Best GEO/AI-citation asset in this category and the natural hub linking to both head-to-heads. Must openly recommend competitors for the jobs they do better. | 5-7 hours |

**Priority order.** (1) Refresh vs-meetily -- wrong claims are live now.
(2) Build vs-anarlog -- largest unowned intent pool.
(3) Build the roundup -- hub, GEO, and credibility.

## QA/QC pass

### Claim verification table

| Claim | Source URL | Access date | Verified | Confidence |
| --- | --- | --- | --- | --- |
| Hyprnote was renamed to Char, then to Anarlog | https://anarlog.so/blog/char-is-now-anarlog/ | 2026-07-24 | Yes | High |
| Anarlog relicensed from GPL to MIT | https://anarlog.so/blog/char-is-now-anarlog/ ; https://api.github.com/repos/fastrepl/anarlog | 2026-07-24 | Yes | High |
| Anarlog: 8,869 stars, 10 open issues, pushed 2026-07-24 | https://api.github.com/repos/fastrepl/anarlog | 2026-07-24 | Yes | High |
| Anarlog releases desktop_v1.3.7/1.3.8/1.3.9 on 2026-07-22/23/24, macOS dmg assets only | https://api.github.com/repos/fastrepl/anarlog/releases | 2026-07-24 | Yes | High |
| Anarlog states it is not planning Linux or Windows support | https://anarlog.so/blog/char-is-now-anarlog/ | 2026-07-24 | Yes | Medium (docs elsewhere say "Windows package-manager distribution are forthcoming" -- direct conflict; shipped assets are macOS only) |
| Anarlog Pro is $15/month or $150/year and includes speaker identification and cloud transcription | https://anarlog.so/ ; https://anarlog.so/pricing/ (via search snippet; direct fetch 404'd) | 2026-07-24 | Partly | Medium -- price seen on home page and search result; `/pricing/` did not resolve for direct fetch. Verify before publishing a price. |
| Anarlog blog says "free forever -- there is no paid tier" | https://anarlog.so/blog/char-is-now-anarlog/ | 2026-07-24 | Yes | High that it was said; **contradicted by the current site**. Do not quote. |
| Anarlog local pyannote diarization PR #3821 was closed unmerged on 2026-05-01 | https://api.github.com/repos/fastrepl/anarlog/pulls/3821 (`merged: false`) | 2026-07-24 | Yes | High |
| Anarlog automatic speaker indexes come from the STT provider | https://api.github.com/repos/fastrepl/anarlog/pulls/5834 (merged 2026-07-01) | 2026-07-24 | Yes | High |
| Anarlog docs describe manual speaker-label assignment | https://docs.anarlog.so/llms-full.txt | 2026-07-24 | Yes | Medium-High |
| Anarlog "agents" are read-only MCP/CLI for external agents, not in-call AI | https://docs.anarlog.so/agents/overview | 2026-07-24 | Yes | High |
| Anarlog offline mode needs an on-device model plus LM Studio or Ollama | https://docs.anarlog.so/llms-full.txt | 2026-07-24 | Yes | Medium-High |
| Meetily: 26,451 stars, 2,665 forks, 311 open issues, MIT | https://api.github.com/repos/Zackriya-Solutions/meetily | 2026-07-24 | Yes | High |
| Meetily public repo last commit 2026-06-05 (v0.4.0) | https://api.github.com/repos/Zackriya-Solutions/meetily/commits | 2026-07-24 | Yes | High |
| Meetily diarization shipped in Pro 1.8.2, live as you record and on imported audio | https://meetily.ai/blog/meetily-v0-3-0-import-audio-retranscribe (update note on a 2026-03-03 post) | 2026-07-24 | Yes | High |
| Meetily diarization is Pro-only, absent from Community Edition | https://meetily.ai/downloads ; https://meetily.ai/ ("Available in Pro") ; repo README | 2026-07-24 | Yes | High |
| Meetily Pro is $10/user/month billed annually at $120/year | https://meetily.ai/downloads ; https://meetily.ai/ | 2026-07-24 | Yes | High ($10 and $120); the struck-through $25 list price is Low |
| Meetily claims 369K+ users / 369.8K downloads and 25.9K stars | https://meetily.ai/ | 2026-07-24 | Yes (as a vendor claim) | High that it is claimed; Medium that it is accurate |
| Meetily Pro also gates chat-with-meetings and self-hosted deployment | https://meetily.ai/downloads ; repo README | 2026-07-24 | Yes | High |
| Meetily Linux requires a source build; Linux install is "in development" with a waitlist | https://meetily.ai/downloads ; v0.4.0 release notes | 2026-07-24 | Yes | High |
| Meetily has no real-time in-call AI assistance beyond transcription | repo README ; https://meetily.ai/downloads | 2026-07-24 | Yes (absence of evidence) | Medium-High |
| MacWhisper is proprietary, macOS only, Pro EUR 64 one-time | https://www.macwhisper.com/ | 2026-07-24 | Yes | High for proprietary/macOS; Medium for EUR 64 (third-party sources say EUR 59) |
| MacWhisper free tier includes Automatic Speaker Recognition | https://www.macwhisper.com/ | 2026-07-24 | Yes | Medium-High |
| MacWhisper Pro auto-records Zoom, Teams, Webex, Skype, Chime, Discord | https://www.macwhisper.com/ | 2026-07-24 | Yes | High |
| Superwhisper is proprietary; macOS, Windows, iOS | https://superwhisper.com/ | 2026-07-24 | Yes | High |
| Superwhisper has a Meeting mode and a Speaker-Separated Meetings mode | https://superwhisper.com/docs/llms.txt | 2026-07-24 | Yes | High |
| Superwhisper Pro pricing around $8.49-$9.99/month, about $250 lifetime | https://superwhisper.com/ plus third-party reviews | 2026-07-24 | Partly | **Low-Medium** -- sources disagree. Do not publish an exact price. |
| Vibe: MIT, 6,885 stars, 181 open issues, pushed 2026-07-17, macOS/Windows/Linux | https://api.github.com/repos/thewh1teagle/vibe | 2026-07-24 | Yes | High |
| Vibe supports speaker diarization, Ollama and Claude summaries, realtime preview | Vibe README (raw.githubusercontent.com) | 2026-07-24 | Yes | High |
| Vibe's diarization uses pyannote segmentation-3.0 plus WeSpeaker embeddings on onnxruntime | https://github.com/thewh1teagle/pyannote-rs | 2026-07-24 | Yes | Medium-High (pyannote-rs is by the same author; confirm Vibe links it before publishing) |
| Buzz: MIT, 20,357 stars, 27 open issues, pushed 2026-07-24, macOS/Windows/Linux | https://api.github.com/repos/chidiwilliams/buzz | 2026-07-24 | Yes | High |
| Buzz has live realtime mic transcription and speaker identification | Buzz README (raw.githubusercontent.com) | 2026-07-24 | Yes | High |
| Amurex is AGPL-3.0, 2,858 stars, last push 2025-05-27, not archived | https://api.github.com/repos/thepersonalaicompany/amurex | 2026-07-24 | Yes | High |
| amurex-web has no license and last push 2025-09-05 | https://api.github.com/repos/thepersonalaicompany/amurex-web | 2026-07-24 | Yes | High |
| Amurex offered live in-meeting suggestions | repo README ; HN 42319601 / 42779378 | 2026-07-24 | Yes | Medium-High |
| Backchannel repo: MIT, 1 star, created 2026-07-07, pushed 2026-07-24 | https://api.github.com/repos/talberthoule/backchannel | 2026-07-24 | Yes | High |
| Backchannel has five live agents plus three briefing agents | `docs/agents.md` ; `backend/app/services/agents/` | 2026-07-24 | Yes | High |
| Backchannel has no Ollama / local-LLM route for agents | repo-wide grep for `ollama\|lm_studio\|11434` -- only hit is our own `site/vs-meetily/index.html` marketing copy | 2026-07-24 | Yes | High |
| Backchannel cross-session chat accepts up to 20 sessions | `backend/app/routers/chat.py` (`session_ids: list[uuid.UUID] = Field(min_length=1, max_length=20)`) | 2026-07-24 | Yes | High |
| Backchannel desktop downloads require an approved account | `docs/quickstart.md` ; `site/llms.txt` | 2026-07-24 | Yes | High |
| Backchannel diarization is Silero VAD + WeSpeaker ResNet152 ONNX with optional Sortformer | `docs/audio-pipeline.md` ; `CLAUDE.md` | 2026-07-24 | Yes | High |

### Flagged and unverifiable claims

- **Anarlog Pro pricing ($15/mo, $150/yr).** Seen on the home page and in a
  search snippet, but `anarlog.so/pricing/` returned 404 to direct fetch.
  **Do not publish the number until re-verified in a browser.**
- **The Anarlog "free forever, no paid tier" statement.** Directly
  contradicted by the Pro tier now sold on the site. If we quote the blog we
  will look like we are misrepresenting them. Do not use it.
- **Anarlog Windows/Linux intent.** The rename post says never; the docs say
  Windows packaging is "forthcoming." Phrase our copy around shipped
  artifacts ("Anarlog ships macOS builds only") rather than around intent,
  so a future Windows release does not make our page wrong.
- **Superwhisper prices.** Sources give $8.49/mo, $9.99/mo, $84.99/yr, and
  $249.99 lifetime inconsistently. Publish "paid tiers from roughly $9/month"
  or omit.
- **MacWhisper Pro price.** Official site shows EUR 64; third-party reviews
  say EUR 59. Use the official figure or say "one-time purchase, no
  subscription."
- **Meetily's 369K download and 25.9K star claims.** These are vendor
  self-reports. Attribute them ("Meetily claims...") rather than asserting
  them. Our independently verified figure is 26,451 GitHub stars.
- **Meetily's $25 struck-through list price.** Seen once in a page render;
  low confidence. Publish only the effective $10/user/month and $120/year.
- **"Meetily has no real-time in-call AI assistance."** This is an
  absence-of-evidence conclusion from the README, downloads page, and
  release notes. It is well supported but we cannot inspect the closed Pro
  build. Phrase as "no in-call AI assistance is documented in either
  edition."
- **Anarlog's free-tier automatic diarization.** Our conclusion (manual
  labels free, automatic attribution provider-dependent or hosted) is built
  from docs plus an unmerged PR plus a merged PR's wording. It is the best
  reading available but it is inference, not a vendor statement. Phrase
  carefully: "Anarlog's documentation describes assigning speaker labels
  manually; automatic speaker indexes come from the transcription provider,
  and hosted speaker identification is a Pro feature." Avoid the flat
  sentence "Anarlog has no diarization" -- it would be unfair and probably
  wrong for provider-backed configurations.
- **Third-party review sites** (getvoibe, toolchase, spokenly, lumevoice,
  heymumble, brightcoding, aitoolsdigest) are SEO content of uneven quality
  and several are published by competing vendors. Nothing in this document
  rests on them alone; every load-bearing claim traces to a repo API, a
  vendor site, or the repo itself. Do not cite them on a public page.
- **Contradiction against Backchannel's shipped capabilities: none found.**
  The one claim in our existing marketing that this research pressure-tested
  and confirmed is the concession that our agents require a cloud key. The
  claims this research falsifies are all about Meetily, and they are listed
  in the audit section above.
