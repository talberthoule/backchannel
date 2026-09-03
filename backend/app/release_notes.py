"""Application version and in-app release notes.

Single source of truth for the running application's version. It lives in the
`app` package so every delivery path (Docker image, desktop bundle, local dev)
ships it automatically. Update it as part of every release (see
docs/releasing.md): bump APP_VERSION and prepend a matching entry to
RELEASE_NOTES.

Bodies are GitHub-flavored markdown rendered in the Admin -> About tab. Keep
them user-facing summaries (no download links or repo internals) and ASCII.
"""

APP_VERSION = "0.6.1"

# Newest first; the first entry's version must equal APP_VERSION.
RELEASE_NOTES: list[dict] = [
    {
        "version": "0.6.1",
        "date": "2026-09-03",
        "title": "Updating no longer asks you to sign in for a public download",
        "body": """Checking for an update worked, but pressing Download update
opened a window asking you to sign in to an account, for a file the download
portal hands to anyone who asks. There was no account to sign in with, so the
update could not be taken from inside the app at all.

- The update download is now anonymous, like every other download this
  project publishes. Press Download update and it downloads. There is no
  authorization window, no account, and no sign-in anywhere on the path.
- Installs already running v0.6.0 are fixed too, without reinstalling. The
  portal side of the old handshake stopped requiring an account at the same
  time, so a v0.6.0 install that checks for updates can now fetch v0.6.1 on
  its own. If you already gave up and downloaded a build by hand, nothing is
  lost; updates from here are in-app again.
- If a download is interrupted it still resumes from where it stopped, and
  the panel now says the download was interrupted rather than blaming an
  expired authorization it no longer uses.

Two smaller things:

- The meeting picker in post-call Chat searches by date, the way the session
  sidebar's find box already did. Typing October, oct 8, 8, 10/8 or
  2026-10-08 finds the meetings from that day, so the two boxes finally
  behave the same way.
- Clicking into either of those search boxes now says that searching by date
  works, which was previously something you had to already know.
- In dark mode, the Privacy First review panel was unreadable. The panel that
  lists what stops working and what keeps working kept a light background in
  both themes while the feature names took the dark theme's light text, so
  the names disappeared into the panel just as you were deciding whether to
  turn the switch on. The panel now follows the theme.
""",
    },
    {
        "version": "0.6.0",
        "date": "2026-09-02",
        "title": "The PII Shield: no model, local or cloud, reads a name it does not need",
        "body": """This release adds a privacy layer that keeps personal data out of
every model prompt and out of the database itself, and makes a new session
faster to set up.

- A PII Shield, in Admin -> Privacy. With it on, people's names, company
  names, email addresses, phone numbers, card and national-id numbers, IP
  addresses and street addresses are replaced with tokens such as [PERSON_1]
  the moment a transcript line, directive, document excerpt, session name or
  speaker name is written. Every agent, the briefing, chat and Ask then work
  from tokenized text, whether the model is on this machine or in the cloud,
  and the database holds only tokens. The real values live in a vault
  encrypted under the same master key that protects your provider keys, and
  are put back only on the screen in front of you. Tokens stay consistent
  within a session so the models can follow who said what; nothing links a
  person across sessions.
- Detection runs entirely on this machine: pattern checks for structured
  identifiers, the session's own speaker roster and a protected-terms list
  you maintain (client companies, code names), and a small on-device
  name-recognition model that downloads once. No detection ever involves a
  cloud call. The Privacy tab has a scratch box to see exactly what a model
  would receive for any sentence.
- Audio never leaves while the shield is on. Audio cannot be tokenized, so
  the shield holds transcription to a local model and switches off cloud
  live captions, the way Privacy First does but for audio alone; cloud text
  models stay available because they receive tokens only. The Privacy tab
  shows each path, including a cloud caption gateway that is configured but
  paused, and the live call says "Live captions off: PII Shield" rather
  than going quiet. Uploaded documents are read on this machine and never
  sent as files.
- A Transcript Refiner agent, off by default, closes the quality gap of
  local-only transcription. It sends the tokenized transcript to any text
  model, local or cloud, to fix punctuation, casing, sentence boundaries and
  obvious mishearings, live every 45 seconds, at call end, and before
  post-import analysis. A rewrite is kept only if it carries exactly the
  original tokens, and the transcriber's own wording is kept alongside.
- You can watch it work. "Record outbound prompts" on the Privacy tab keeps
  a log of every prompt exactly as it left for a model, badged "tokens only"
  or "blocked", so the claim that no name reaches a model is something you
  check rather than trust. Independently, while the shield is on a prompt
  that still carries a vault value is refused before it is sent.
- Local Whisper's noise artifacts, a phrase looping a dozen times or a line
  of bracketed non-words, no longer reach the transcript.
- Exports carry tokens unless you tick "Include personal data" in the Export
  menu; every reveal, on screen or in a file, is counted in an audit trail
  the Privacy tab summarizes. A completed session shows how many values it
  holds shielded. Sessions recorded before the shield was on keep what they
  hold until you protect them (POST /api/sessions/{id}/pii/protect).
- Setting up a session is shorter. The Start Call and Process Transcript
  buttons now sit at the top of the pre-call screen and stay there while you
  scroll. Context is open; documents, imports, directives, participants and
  agent choices are collapsed cards whose headers say what they hold, and
  the recording notice is one line with the detail behind it.
- Gemini 3.8 Flash, released the day of this build, is in the model list
  and is now the recommended Google model for every text agent and Live
  Ask, at the same price as 3.7 Flash. Gemini 3.7 Flash stays selectable;
  an agent already set to it keeps running on it until you change it.
- The session sidebar's find box also understands dates. Typing October,
  oct 8, 8, 08, 8-, 8/, 10/8, 10-08 or 2026-10-08 finds the sessions created
  or started on that day, with nothing to add to the session name.
""",
    },
    {
        "version": "0.5.4",
        "date": "2026-09-02",
        "title": "A post-call Overview that opens first, a sidebar you can find things in, and truer cost numbers",
        "body": """This release reworks the post-call review and the session
sidebar, and closes two audits: one on token spend, one on how provider keys
are kept.

- A completed session now opens on an Overview. It leads with the briefing's
  top outcome, then a row of counts - commitments, open loops, opportunities,
  risks and estimated spend - a two-column digest of those lists with owners
  and status, who spoke how much, and when in the call the insights arrived
  (a resumed call is drawn as call time, with a seam at each resume). Every
  count links to the tab that holds the rows behind it; when a briefing
  exists the counts follow it, and the live insight totals are stated
  alongside. The Insights tab is unchanged and remains the raw record.
- The Insights tab no longer shows two groups both called "Action Cue". Every
  strategic signal carries its section badge (Signal, Risk, Next Question,
  Opportunity, Action Cue), and the group headings were borrowing the most
  common badge. They now read "Strategic Signals" and "Signal History"; the
  badges on the cards and the live-call chips are as they were.
- The session sidebar was rebuilt. Sessions come first, the tools moved to a
  compact footer, the whole list scrolls as one, and with six or more
  sessions a find box filters by session or group name. Each row shows its
  state as a small dot, the active session is marked, and a quiet menu on
  each row covers Rename, Move to a group and Delete. Collapsing to the icon
  rail is smooth and remembers your choice, and the sidebar now opens
  expanded by default. Everything works by keyboard and on touch screens.
- The Briefing tab reads like a one-page brief: numbered top outcomes, plain
  section headings with counts, the action plan beside the risks, and each
  item's reasoning behind a single "Why this matters" toggle. Empty sections
  are left out and named once at the foot of the page.
- Token totals for the live audio gateway were far too low. Each usage report
  from the live model was treated as a running total and only the increase
  was kept, which on a talking call dropped most of what was billed. Usage is
  now recorded once per turn. Audio tokens and cached prompt tokens are priced
  at their own published rates rather than the text rate, and the Tokens tab
  shows cached and audio columns when a session has them. New sessions will
  show higher, truer live totals; sessions recorded before this release keep
  the figures they had.
- Provider keys are harder to reach. The local API now refuses requests from
  other websites and from hostnames it does not recognize, so a page open in
  your browser cannot read transcripts or spend your provider budget through
  it. Provider error messages and logs are scrubbed of anything key-shaped,
  and a saved key is shown as its last four characters only. On Windows the
  desktop app now protects its key file with your Windows account, so a
  copied data folder cannot be read elsewhere; an administrator-forced
  password reset means re-entering provider keys once. If you run the Docker
  stack and reach it by a DNS hostname rather than an IP address or
  localhost, list that name in BACKCHANNEL_ALLOWED_HOSTS; the database and API
  ports are also bound to the local machine only.
- Smaller things: the post-call Export menu and tab strip work by keyboard,
  the completion banners and the logo read correctly in dark mode, and small
  teal text meets the contrast bar in both themes.
""",
    },
    {
        "version": "0.5.3",
        "date": "2026-08-25",
        "title": "The quieter call screen arrives, and strategic signals become insights",
        "body": """The v0.5.2 desktop bundles were built before the quieter call
screen landed, so this is the first release to carry it, together with the
follow-on work that turns strategic signals into insights you can act on.

- The live call screen is quieter. It had grown five strategic signal panels
  across the top, a conversation-type dropdown and a copy of the meeting context
  you typed during setup, a Debug button whose readout unfolded into the bar and
  pushed everything sideways, a separate signal History container, and the word
  "Listening" three times over. The panel now shows three signals, the setup
  information is gone from the bar, and Debug is a small icon whose readout
  opens over the page instead of rearranging it.
- The model chooses which three signals you see. The panel used to fill its
  slots in a fixed order - signal, then risk, then next question - so the same
  two kinds always won and an opportunity or action cue only appeared when an
  earlier slot was empty. The analysis now ranks everything it produces by what
  you can act on right now, and the top three take the panel.
- Every strategic signal is an insight. Each signal now appears in the insight
  list as a card of its own, so you can star it, vote on it, dismiss it and
  export it like any other insight, and a dismissed signal stays dismissed even
  if the analysis raises it again. The Strategic filter is the whole strategic
  picture: the three signals on the panel, everything else the current cycle
  produced, and the three most recently retired signals, which also stay under
  the History filter. Filter chips with nothing behind them no longer render.
- The analyst stops repeating itself. Each analysis pass now sees a compact
  list of everything already on the board - not just the open questions - and
  is told to add only what is new, so an observation raised at minute 12 no
  longer comes back at minute 40 in fresh words.
- The live transcription column folds away. Collapse it to a narrow rail when
  you want the insights to have the screen, and open it again in one click.
  Starting a call also collapses the session sidebar, so the call view opens at
  full width.
- The live transcript is searchable. A quiet magnifier in the transcription
  column's header - or Ctrl+F while the transcript is focused - opens an
  inline search: matches highlight in place, Enter and Shift+Enter step
  through them, and Esc returns to the live tail. While a search is open the
  view holds its place instead of following new speech.
- The desktop updater introduces itself. Update checks were being turned away
  at the download portal's edge because the request carried a generic Python
  browser signature rather than the application's name, and the check gave up
  after five seconds on a slow connection. From this version the updater
  identifies itself as Backchannel and waits ten seconds. An install on v0.5.2
  or earlier cannot see this release from inside the app, so fetch it from the
  download portal once; updates after that are in-app again.
""",
    },
    {
        "version": "0.5.2",
        "date": "2026-08-16",
        "title": "Everything in 0.5.1, plus a briefing that reads properly",
        "body": """v0.5.1 was tagged but never distributed, so if you are coming
from v0.5.0 this release carries all of its changes as well as the fix below.
See the v0.5.1 notes underneath for the rest.

- Briefing headings get the width of their card. In the post-call briefing, an
  item's title shared a line with its status and speaker labels. In the
  three-across cards at the bottom - objectives, opportunities, open questions -
  those labels took most of the width and left a five-word heading wrapping over
  five lines beside a mostly empty card. The labels now drop to their own line
  when there is no room for them, so headings read as headings.
""",
    },
    {
        "version": "0.5.1",
        "date": "2026-08-15",
        "title": "Tells you what a call cost, and stops writing everything down twice",
        "body": """This release is about the two things a long call was quietly
wasting: your money and your transcript.

- The Tokens tab is a cost report now. It opens with what the call cost rather
  than a token count, and every agent carries its own dollar figure so you can
  see which one is expensive. The live audio bridge is billed by the minute
  instead of by tokens, so it used to show nothing at all; it now appears with
  the rest. On a measured 35-minute call that was about a fifth of the bill,
  invisible.
- Calls stop transcribing the same sentence twice. When a call captures both
  your microphone and system audio, close to half the transcript was the same
  speech saved twice under two different speaker names, which is also why a
  two-person call could show up as four participants. The duplicates are
  suppressed as they happen, so the transcript reads properly, the export is
  not half padding, and every analysis agent stops re-reading the same words.
- Runaway answers are capped. One analysis call in an earlier session produced
  sixty-three thousand tokens in a single reply, most of it discarded. Replies
  are now bounded and reasoning is budgeted, and a reply that legitimately
  needs more room gets it on a second attempt instead of being truncated.
- The app is lighter while a call is running. Live speaker detection uses
  substantially less processor time, and the call screen no longer redraws
  itself sixty times a second to animate the audio meter, so the machine stays
  responsive during long meetings.
- New models and corrected prices. GPT Live Transcribe and Gemini 3.7 Flash are
  selectable, and the Gemini Flash rates shown in the pricing table were too
  high by half and are now correct.
- Insights stop quietly disappearing. An insight could be deleted by being
  merged into itself; that can no longer happen. Sales-opportunity scouting is
  also switched off entirely on meeting types that do not use it, instead of
  running and discarding the result.
- The meeting-audio option explains itself. The pre-call checkbox now says
  plainly that your microphone is always recorded and that this option adds a
  second track for the meeting's own audio, which is what lets speaker labels
  tell local from remote voices definitively. Turning it off shows what that
  costs: with headphones on, the far end cannot be heard or transcribed. The
  consent notice is also readable in dark mode instead of gray-on-gray.
""",
    },
    {
        "version": "0.5.0",
        "date": "2026-08-02",
        "title": "Asks which provider you use, and stops losing things",
        "body": """Setup stops assuming which provider you use, the call
surfaces stop losing things, and the post-call record stops showing you raw
identifiers.

- First-run setup asks instead of assuming. A fresh install no longer seeds a
  cloud model behind your back. Every enabled agent starts unselected and says
  so, models are grouped by Google, OpenAI, and local, and one role-appropriate
  recommendation is marked in each provider you actually have available.
  Connecting only an OpenAI key no longer tells you Google is required, and a
  keyless local setup can find the paths that work with no cloud account.
- Strategic signals persist. Signals raised during a call are kept and stay
  readable both live and after the call instead of scrolling away. Briefing
  context built from them is deduplicated, so the same observation stops
  arriving several times in different words.
- Documents feed the live conversation. Uploaded document summaries are stored
  once and reused, so asking about a document mid-call draws on the summary
  rather than re-reading the file. Under Privacy First the excerpt path keeps
  that working without sending the document anywhere.
- The briefing names people, not identifiers. Owners and attribution resolve to
  speaker names at read time, including in exported HTML. The raw owner chip is
  gone and the rationale sits directly under the summary it explains.
- Insights say which model produced them. Enhance Insights shows the model you
  asked for alongside the one that actually ran, so a fallback is visible
  rather than silent. Insight type labels are legible words on badges and
  section headers, and the Excel export is a single enriched file instead of a
  choice between two partial ones.
- Ask questions without leaving the call. A new in-call ask bar answers from the
  conversation as it happens, so you can check what was said earlier without
  stopping the recording or waiting for the post-call briefing.
- The live insight surface was redesigned. Insights arriving during a call are
  laid out to be read at a glance while you are still talking, so the list can
  be scanned mid-conversation rather than studied afterwards.
- Steadier in the places that used to slip. Activity chips separate blocked
  work from failed work and report a current failure count rather than a
  running total. Batch readiness stops calling a blank or unrecognized model id
  ready. Oversized briefing context items are retained rather than dropped. The
  live ask bar no longer starves the transcript it depends on.
- Sixteen known vulnerabilities were cleared from the web-facing dependency
  stack. The four ways this project builds its frontend now agree, so the app
  you install is built from the exact dependency tree that was tested, and
  Windows executables carry proper product and version metadata.

Existing installations keep the models they have selected; the unselected
first-run state applies only to genuinely fresh databases.""",
    },
    {
        "version": "0.4.0",
        "date": "2026-07-28",
        "title": "Updates itself, and knows what your machine can run",
        "body": """Backchannel now updates itself, measures whether your
hardware can keep up before a call starts, and keeps working through the
failures that used to end a call quietly.

- Desktop builds update in place. The app checks for a new version, verifies
  its signature before touching anything, applies it with a rollback path if
  the swap fails, and waits for recording and post-processing to finish before
  restarting.
- Privacy First is a working mode, not a warning. With a self-hosted model
  configured, the analysis agents, post-import Analyze, Enhance Insights, and
  the call briefing all keep running with the switch on. When a model is
  refused, the message now names the agent and the model to change instead of
  only saying no.
- Find out before the call whether your machine can keep up. The Local Model
  Fit Test times each self-hosted model against the real agent prompts and
  scores it per role, with per-model cycle budgets, an adjustable contention
  slider, and coverage for transcription and the briefing. Call-start capacity
  admission adds up diarization, transcription, captions, and agents against
  the machine's actual headroom.
- Measurements expire honestly. A benchmark taken on different hardware or
  against an older standard is marked out of date rather than shown as
  current, and a stale one is left out of the capacity verdict and named as
  unmeasured instead of quietly counting as a pass.
- Live interim captions can run on-device. Point the audio bridge at the local
  captioner and captions work with no cloud call, including under Privacy
  First. It is CPU-heavy, so check the fit test first.
- Long calls survive slow models. A diarizer that falls behind sheds audio
  instead of exhausting memory, self-hosted requests get room to finish
  instead of timing out mid-briefing, and agent replies are validated against
  a schema so a local model's output is no longer silently dropped. If a cloud
  model hits its quota mid-run, insight revalidation continues on a
  self-hosted one.
- Ending a call tells the truth. Stopping the browser share stops the system
  track at that moment rather than surfacing a stray speaker minutes later,
  End Call names any analysis stage that failed instead of finishing silently,
  the summary is saved with the call so a dropped connection cannot lose it,
  and a long post-processing run no longer looks like a lost connection.
- When nothing is happening, the app says why. A runtime diagnosis surface
  reports what is running, what is blocked, and what to change, and editing a
  self-hosted endpoint no longer silently orphans the agents pointing at it.
- The post-call Briefing reads like a briefing. An at-a-glance strip sums up
  the meeting in five seconds, the top outcomes lead the page, and every
  section carries its own color and icon so risks, actions, and open
  questions can be found by scanning instead of reading. Owners and status
  show as chips, supporting rationale tucks behind a toggle, and strategic
  signals from the call now appear in the briefing.""",
    },
    {
        "version": "0.3.8",
        "date": "2026-07-25",
        "title": "Self-hosted models become first-class",
        "body": """Self-hosted models now stand on their own: every model an
endpoint serves shows by its own name in the pickers, you can add more than
one endpoint, and Privacy First keeps on-prem agents running.

- Add any number of OpenAI-compatible servers -- Ollama, LM Studio, vLLM,
  LiteLLM -- from the new Self-Hosted Models card in Admin -> API Keys.
  Connect to one and it lists the models it serves; each appears by name in
  every agent picker instead of hiding behind a single placeholder.
- Privacy First now judges the destination, not the vendor. With an endpoint
  on your own machine or LAN, the analysis agents keep running while Privacy
  First is on; only cloud providers stay blocked. A fully local setup --
  local ONNX transcription plus a self-hosted model -- now runs with the
  switch on. Only interim live captions remain cloud-only.
- Enhanced Sortformer diarization now unlocks only after three sustained
  windows prove enough throughput for both live audio tracks plus
  transcription load. Diagnostics show the measured margin and retain the
  model's peak memory footprint for whole-call capacity planning. Earlier
  passes below the new requirement return to Lightweight and show the
  measured shortfall.
- If you configured the earlier single OpenAI-compatible endpoint, it is
  migrated automatically into a named endpoint on first launch. Nothing to
  redo, and env-var-only installs keep working unchanged.""",
    },
    {
        "version": "0.3.7",
        "date": "2026-07-25",
        "title": "Run the agents on your own machine",
        "body": """The analysis agents can now use a self-hosted
OpenAI-compatible server instead of a cloud provider.

- Point the agents at Ollama, LM Studio, vLLM, or LiteLLM by setting a
  base URL and model id in Admin -> API Keys, then pick the
  OpenAI-Compatible model for any agent. Paired with local ONNX
  transcription, the whole pipeline runs on your hardware with no API
  key from anyone.
- Local endpoints usually need no credential, so none is required and
  no authorization header is sent. Set one only if your server expects
  it.
- Nothing changes unless you configure it. With no base URL set, every
  existing setup behaves exactly as before.

One thing to know: the Privacy First switch still turns the analysis
agents off, because it recognizes only the local transcription models.
A fully local setup is configured through the endpoint rather than
through that switch.""",
    },
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
