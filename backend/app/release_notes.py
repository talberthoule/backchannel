"""Application version and in-app release notes.

Single source of truth for the running application's version. It lives in the
`app` package so every delivery path (Docker image, desktop bundle, local dev)
ships it automatically. Update it as part of every release (see
docs/releasing.md): bump APP_VERSION and prepend a matching entry to
RELEASE_NOTES.

Bodies are GitHub-flavored markdown rendered in the Admin -> About tab. Keep
them user-facing summaries (no download links or repo internals) and ASCII.
"""

APP_VERSION = "0.3.6"

# Newest first; the first entry's version must equal APP_VERSION.
RELEASE_NOTES: list[dict] = [
    {
        "version": "0.3.6",
        "date": "2026-07-23",
        "title": "OpenAI models work everywhere",
        "body": """This hotfix completes OpenAI support across every agent and adds
OpenAI batch transcription options.

- The Briefing (Meeting Lens, Discovery Lens, Arbiter) and Strategic
  Signals agents now work with OpenAI models. Previously they always
  called Gemini, so selecting an OpenAI model failed with a "model not
  found" error after the call.
- When a briefing does fail, the error now explains what happened and
  how to fix it instead of showing a raw error dump.
- Batch transcription gains OpenAI options: GPT Audio 1.5 and the
  cost-efficient GPT Audio Mini. These are OpenAI's audio-capable chat
  models; OpenAI's GPT-5.6 text models cannot accept audio, so they
  are not batch transcription options. Both new models are priced in
  Admin -> About and appear once a working OpenAI key is added.""",
    },
    {
        "version": "0.3.5",
        "date": "2026-07-23",
        "title": "Clear provider errors, current OpenAI models, cost visibility",
        "body": """This release makes provider failures actionable, refreshes the
OpenAI lineup, and shows what calls cost.

- Chat and Enhance Insights no longer fail with a bare server error
  when a provider hits its quota or rejects a key. They now explain
  what happened and how to fix it, and failed Enhance runs offer a
  one-click "Retry failed batches".
- The post-call summary banner now reads like "Final analysis pass:
  3 new insights, 7 insights updated - 23 insights total for this
  session" instead of unexplained counts.
- Every confirmation and notice now uses the app's own themed dialogs
  instead of raw browser popups.
- The OpenAI model lineup is current, including the GPT-5.6 family,
  and OpenAI transcription models (gpt-4o-transcribe and
  gpt-4o-mini-transcribe) can be selected as the batch transcription
  model once a working OpenAI API key is added.
- Admin -> About gains a Models & Pricing table, and the post-call
  Tokens tab shows an estimated cost per model and for the session,
  at standard text rates as of July 23, 2026.""",
    },
    {
        "version": "0.3.4",
        "date": "2026-07-23",
        "title": "Hotfix: starting a new call works again",
        "body": """This hotfix repairs starting a call, which was broken in
versions 0.3.1 through 0.3.3.

- Pressing Start Call on a new session failed silently: the server
  rejected the request that marks the session active, so the call never
  began. The underlying server error is fixed and starting a call works
  again for new and existing sessions.
- No data was affected. Sessions created while the bug was present work
  normally after upgrading.""",
    },
    {
        "version": "0.3.3",
        "date": "2026-07-23",
        "title": "Live strategic signals, post-call briefings",
        "body": """This release separates the lightweight live strategic-signal cycle
from the full post-call briefing pipeline and fixes a diagnostics-card failure.

- Strategic Signals is now a standalone Administration agent with its own
  enable switch, model, prompt, and cycle interval. It uses one model call per
  live cycle (45 seconds by default) while preserving evidence links and the
  existing automatic insight upvotes.
- The Meeting Lens, Discovery Lens, and Brief Arbiter now run only after a
  normal End Call or when Generate Briefing is selected. They no longer run
  every 45 seconds during a call.
- Administration and the public agent guide now show the complete current
  crew and the triggers shipped by the application.
- Invalid non-finite diarization benchmark values can no longer be saved and
  break the Diagnostics card on later visits.""",
    },
    {
        "version": "0.3.2",
        "date": "2026-07-23",
        "title": "Voice calibration works out of the box",
        "body": """This release makes voice calibration and audio imports work out of
the box on the Windows and Linux desktop bundles and clears up two confusing
Administration labels.

- The Windows and Linux desktop bundles now include ffmpeg, so recording
  your voice profile, running a mic benchmark, and importing MP3, M4A, or
  WebM audio need no separate install. The macOS bundle still uses a
  system ffmpeg.
- When ffmpeg is unavailable or cannot read a file, the app now explains
  what is missing and how to fix it instead of showing a raw system error.
- The Diarization Capability card no longer shows a status tag that could
  read as "diarization is unavailable" when only the optional Enhanced
  mode was locked behind a benchmark.
- First-run setup now describes the Cloud AI path accurately for both
  providers: a Google or OpenAI key powers the analysis agents and live
  captions, while saved transcripts come from Gemini or the built-in local
  transcription models.""",
    },
    {
        "version": "0.3.1",
        "date": "2026-07-23",
        "title": "Guided provider setup, default-browser app window, and tidier sessions",
        "body": """This release makes the first run genuinely guided, honors your default
browser for the desktop app window, lets you clean up session groups safely,
and makes speaker revalidation progress visible and retryable.

- First launch now offers a guided provider setup: pick Google Gemini,
  OpenAI, or Privacy First local mode, follow a step-by-step API key guide
  with direct "Get a key" links, and see real readiness checks. Setup no
  longer reads as complete while the agents' active models still lack a
  usable credential.
- On Windows, the dedicated app window now opens in your default browser
  instead of preferring specific browsers, with a plain browser tab as the
  fallback when no app-window-capable browser is available.
- Session groups can be deleted from the sidebar with an accessible,
  confirmed control. Sessions in a deleted group are preserved and simply
  become ungrouped.
- Re-running insight enhancement after speaker corrections now reports its
  batch progress honestly, records per-batch outcomes, and offers retry for
  only the failed batches.""",
    },
    {
        "version": "0.3.0",
        "date": "2026-07-23",
        "title": "Voice enrollment, flexible call endings, and cost visibility",
        "body": """This release adds local voice calibration for reliable mic-only
speaker identity, gives you control over end-of-call analysis spend, tracks
per-call token usage, and makes the app easier to start with and keep current.

- Enroll your voice once in Administration -> Transcription & Audio so
  mic-only calls reliably map your speech to you. Only an encrypted voice
  fingerprint is stored; the calibration recording itself is never saved.
- End Call is now a split button: the primary action keeps the full
  briefing pipeline, while "End without briefing" skips briefing synthesis
  and opportunity matching for a faster, cheaper wrap-up.
- Unintentional disconnects (closed tab, network drop) now finalize the
  session with no analysis spend at all, and post-call review offers a
  one-click "Generate Briefing" whenever a briefing is missing.
- A new Tokens view shows per-call token usage with a breakdown by agent,
  transcription path, and model, persisted for every past session.
- Calls now refuse to start with a clear, actionable message when the
  selected transcription model has no usable credential, and runtime
  transcription failures are surfaced instead of ending in a silently
  empty transcript.
- Split-track calls now store per-track audio provenance so retranscription
  preserves who said what, including local/remote identity, across segments.
- The post-call Speakers tab shows full names with accessible controls, and
  re-running insight enhancement after speaker corrections reports partial
  or failed briefing work honestly with a retry path.
- Administration gains an About tab with the app version and release notes,
  first launch gets a guided setup checklist, and upgrades show a what's-new
  notice with unread release badges.""",
    },
    {
        "version": "0.2.5",
        "date": "2026-07-22",
        "title": "Desktop app window and new Gemini defaults",
        "body": """This release gives Backchannel a dedicated desktop-app window when a
supported Chromium browser is installed and updates the default Gemini models
used for meeting analysis and batch transcription.

- Open Backchannel in a dedicated app window with its own taskbar or Dock
  presence when Chrome, Edge, or Chromium is installed; otherwise use the
  default browser.
- Reserve a stable local port and verify each running instance before launch
  so shortcuts and app-window behavior remain reliable.
- Advertise an installable web-app manifest with purpose-specific icons.
- Add Gemini 3.6 Flash and Gemini 3.5 Flash-Lite as selectable models.
- Default consolidated analysis, opportunity analysis, and the three briefing
  lenses to Gemini 3.6 Flash; default objection handling and batch
  transcription to Gemini 3.5 Flash-Lite.
- Apply the new defaults once to existing installations while preserving any
  choices made after upgrading.""",
    },
    {
        "version": "0.2.4",
        "date": "2026-07-15",
        "title": "Better two-speaker diarization and local ASR first use",
        "body": """This release improves two-speaker diarization, local transcription first
use, and the memory profile of the default lightweight audio path.

- Split internally mixed long turns with short coherence windows while keeping
  the established speaker-similarity threshold unchanged.
- Keep coherence-group assignment non-enrolling so an ambiguous transition
  cannot create extra speaker profiles or consume registered remote slots.
- Allow Whisper and Parakeet local ASR models to download on first use without
  an API key, then reuse the cached models offline.
- Skip optional Sortformer probing for normal live calls and audio imports
  that use lightweight diarization, reducing model and process overhead.

On a live split-track call, the sole configured local user is assigned only to
the physical microphone; every voice arriving through shared system audio is
diarized normally as a remote participant.""",
    },
    {
        "version": "0.2.3",
        "date": "2026-07-13",
        "title": "Stable live audio startup and split-track attribution",
        "body": """This release stabilizes live audio startup and speaker attribution for
calls with one local microphone user and remote participants on system audio.

- Prevent duplicate capture pipelines and call segments during rapid Start,
  Resume, End, or delayed browser permission prompts.
- Bind split-track microphone speech to the sole configured local user without
  consuming remote speaker slots; system-audio participants retain normal
  diarization.
- Preserve the capture topology for queued, reconnect-flushed, and final
  audio, and return to normal mic-only diarization when system sharing ends.""",
    },
    {
        "version": "0.2.2",
        "date": "2026-07-13",
        "title": "Authenticated desktop download portal",
        "body": """This release moves desktop delivery to Backchannel's authenticated
download portal and strengthens the access controls around private installers.

- Deliver Windows, macOS, and Linux bundles through recipient accounts,
  version grants, sessions, and immediate revocation.
- Save downloads with the release version in the local filename and announce
  download starts accessibly.
- Separate operator workflows for early-access decisions, user security, and
  release authorization, with stricter mutation and recovery handling.""",
    },
    {
        "version": "0.2.1",
        "date": "2026-07-11",
        "title": "Desktop brand icon and upgrade-safe database",
        "body": """This release gives the desktop app its brand icon, protects the shared
database during version handoffs, and restores the Linux tarball to the
automated release pipeline.

- Show the Backchannel waveform mark in the system tray and on the Windows
  executable and macOS app bundle.
- Quitting a lingering older instance no longer stops the database that a
  newer instance started on the shared data directory, which previously made
  the session list appear empty after an upgrade.
- Build the Linux tarball inside CI so releases attach it automatically.""",
    },
    {
        "version": "0.2.0",
        "date": "2026-07-11",
        "title": "Early-access administration and richer meeting chat",
        "body": """This release adds private early-access administration, richer meeting
chat context, and a portable Linux desktop bundle.

- Capture early-access requests and review them through a protected operator
  page.
- Ground meeting chat in briefings, saved insights, speaker-attributed
  transcripts, and recent follow-up context.
- Clarify interest-request failures and harden chat-context construction.
- Ship Linux x64 beside the existing Windows x64 and macOS arm64 bundles.""",
    },
    {
        "version": "0.1.1",
        "date": "2026-07-11",
        "title": "Call continuity and diarization stability",
        "body": """This release focuses on call continuity, readable analysis, more stable
speaker attribution, and a quieter desktop launch experience.

- Increase light-mode surface contrast and repair low-contrast status tags in
  dark-mode Administration views.
- Render meeting-chat replies as Markdown with bounded per-session follow-up
  history and a Reset chat control.
- Preserve the active call timer, WebSocket ownership, audio capture, and
  input meters while navigating to other sessions and back.
- Reduce runaway speaker creation with longer evidence requirements, bounded
  profile counts, tuned similarity matching, and echo/noise suppression when
  system audio is captured.""",
    },
    {
        "version": "0.1.0",
        "date": "2026-07-10",
        "title": "First desktop release",
        "body": """The first packaged release of Backchannel: real-time meeting analysis
with live transcription, speaker diarization, insight agents, and post-call
briefings, delivered as Windows x64 and macOS arm64 desktop bundles alongside
the Docker Compose stack.""",
    },
]
