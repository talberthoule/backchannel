"""Application version and in-app release notes.

Single source of truth for the running application's version. It lives in the
`app` package so every delivery path (Docker image, desktop bundle, local dev)
ships it automatically. Update it as part of every release (see
docs/releasing.md): bump APP_VERSION and prepend a matching entry to
RELEASE_NOTES.

Bodies are GitHub-flavored markdown rendered in the Admin -> About tab. Keep
them user-facing summaries (no download links or repo internals) and ASCII.
"""

APP_VERSION = "0.2.5"

# Newest first; the first entry's version must equal APP_VERSION.
RELEASE_NOTES: list[dict] = [
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
