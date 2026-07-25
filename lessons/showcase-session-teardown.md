# The Product-Showcase Session — Agent-Behavior Teardown

*One agentic coding session read through the lens of **what the model did well**, at four
altitudes (101 foundations, 301 patterns, 501 judgment, 701 theory) plus a synthesis. The
session: a multi-day Claude Code run that installed a screenshot skill, seeded privacy-safe
demo data, built a redesign-surviving capture pipeline, captured an unrepeatable live event,
and curated assets for a downstream agent.*

*This is the **product-showcase session**. Its sibling, the **design-review / ui-craft
session**, is torn down in [session-teardown.md](session-teardown.md) (agent lens) and
[prompting-teardown.md](prompting-teardown.md) (operator lens). For this session's operator
lens, see [showcase-prompting-teardown.md](showcase-prompting-teardown.md) and the
`showcase-prompting-*` ladder. See [README.md](README.md) for the full map.*

---

# The Backchannel Showcase Session — Professor's Synthesis

*Model-behavior framing. The spine that runs through the 101/301/501/701 handouts. Derived
from a real multi-day Claude Code session that installed a screenshot skill, seeded
privacy-safe demo data, built a capture pipeline, survived a UI redesign, captured a live
event, and curated assets for a downstream agent.*

## One Spine, Multiple Resolutions

The handouts were written independently but describe the same organism at different scales.
There is a single spine running through every consequential decision in this session:

> **Match the force of an action to how hard it is to undo — and place what you learn where
> the next actor will already be standing when they need it.**

It resolves differently at each level:

- **101 sees habits.** *Run it once before you say it works. Read before you touch a live
  system. Never trust "it's safe" with real data.* Concrete, imperative, anchored to a
  moment you can point at.
- **301 sees patterns.** The same instincts, named and made transferable: *Provable Scrub at
  the Gate. Prove Read-Only, Stage the Writes. Semantic Anchors, Not Incidental Ones.* They
  carry across domains — the scrub-with-assertion works the same on a customer DB dump as on
  a meeting transcript.
- **501 sees system properties.** The patterns dissolve into forces: *irreversibility
  gradients, knowledge-placement locality, contamination semantics that outlive the
  conversation.* The question is no longer "what should the agent do" but "what does the
  agent's action leave behind in the graph, and which edges transmit damage."
- **701 sees formal objects.** The forces become theorems and impossibility results: the
  session as a sampled trajectory of a policy on persistent shared state; preserved
  optionality as the unifying safety objective; non-interference, weakest-precondition proof
  obligations, capability boundaries.

The second half of the spine — knowledge placement — is the quiet star and the least
intuitive. The agent put four lessons in four different homes: a shell gotcha into the
installed skill file, a wait-condition fix into the capture script, cross-session mechanics
into a memory file, a data-safety rule into the deliverable README. Not one went into a
central "notes" doc, because **nobody consults documentation they have to know exists; they
consult what is already in front of them at the moment of need.** Placement turns knowledge
from a pull system that fails silently into a push system that fires exactly when relevant.

The spine has a deliberate exception, visible at all levels: **minimalism governs artifacts,
never verification.** The agent refused a speculative wrapper skill, reused caches, deleted
its own superseded work — but still ran an immediate smoke test, still read frontend source
for durable selectors, still closed the scrub script with an assertion that can fail.
Laziness about what you *build*; never laziness about what you *check*. Where the two
collide, checking wins — which is why a two-minute smoke test in week one prevented a broken
pipeline from detonating during an unrepeatable live event weeks later.


---

# 101 — Foundations Handout

*Model-behavior framing. Working with AI Coding Agents. For students who have never driven an
agent, or are in their first weeks of hands-on technical work. These lessons are about
habits, not clever code — the small, boring disciplines that separate work that holds up from
work that quietly breaks.*

## The Eight Lessons

### 1. Run it once before you say it works
**What happened:** Right after installing the screenshot skill, the agent tested it against
the live site. It failed — run from Git Bash, the argument `--pages /` got silently rewritten
into a Windows path, producing a broken 0-byte file. Re-run from PowerShell, it worked.
**The habit to build:** After every install, script, or fix, run it once for real and look at
the output before declaring it done.
**How beginners get it wrong:** They see "installation complete" and stop — the 0-byte file
only shows up if you actually look.

### 2. Look at what's really there — don't assume the standard layout
**What happened:** Before installing, the agent checked the source repo's actual file layout
and found the helper scripts lived at the repo root, not inside the skill folder. A normal
install would have silently missed them.
**The habit to build:** Before copying, installing, or depending on anything, spend two
minutes looking at what actually exists.
**How beginners get it wrong:** They assume things are organized the way things "usually" are,
and discover the missing piece only when it fails later.

### 3. Check advice against your actual project before following it
**What happened:** The user pasted a 7-step workflow from another AI (mobile shots, dark-mode
variants, route-based capture). The agent searched the codebase: no mobile layout, no dark
mode, no routes existed. Two of seven steps would have showcased features the product didn't
have.
**The habit to build:** When you receive a plan — from an AI, a tutorial, a checklist — verify
each step against your real project before executing any of it.
**How beginners get it wrong:** They treat confident, well-formatted advice as correct and
burn hours on steps that don't apply.

### 4. Never trust "it's safe" with real data — check it yourself
**What happened:** The user handed over a transcript and said it was "safe." The agent read
the whole file first and found a real employer, a real client, and five real people. It
scrubbed every name to a fictional one *before* the data touched the app — and ended the scrub
script with an automatic check that fails if any real name survives.
**The habit to build:** Read any real-world data fully before feeding it into a tool, and
verify your cleanup with a check that can fail — not just your eyes.
**How beginners get it wrong:** They take "it's fine" at face value, paste customer data into
a system, and discover the leak when it shows up in a screenshot or a public page.

### 5. Read before you touch a live system
**What happened:** Before opening a second browser tab on a live call, the agent read the
frontend code to confirm that viewing was read-only — a second tab would not hijack the call.
Only then did it proceed.
**The habit to build:** When your action could affect something running, read the relevant
code or docs first to confirm what your action actually does.
**How beginners get it wrong:** They "just try it" on the live thing, because trying is faster
than reading — until the one time it isn't.

### 6. Fix the script, not just the run
**What happened:** The capture script hit three failures (a button that exists in only one
sidebar mode, a screenshot fired mid-"Thinking...", a send button that no-ops before a
dropdown loads). Each fix was written *into the script*. After a full UI redesign months
later, it still worked — because it targeted meaningful labels and text, not fragile styling.
**The habit to build:** When you fix a problem, put the fix somewhere permanent — the script,
the config, the docs — not just in the one run in front of you.
**How beginners get it wrong:** They fix it by hand, get their output, and lose the knowledge
— so the same failure costs the same hour next time.

### 7. Use cheap checks before expensive ones
**What happened:** The agent spotted a bad screenshot without opening it: the file was 86KB
when a populated chat view should be ~130KB. The mismatch triggered a visual check, which
confirmed the shot fired too early.
**The habit to build:** After producing an output, glance at the cheap signals first — file
size, line count, exit code, row count — and inspect deeply only when one looks wrong.
**How beginners get it wrong:** They either check nothing or exhaustively inspect everything —
both waste the information sitting in a simple `ls`.

### 8. When the moment can't be repeated, capture generously and curate after
**What happened:** During a time-limited live call, the agent took 20 burst screenshots every
25-30 seconds — because a live moment can't be re-captured, but bad frames can always be
deleted. Afterward it kept 2, cropped one to exclude leaked names, and deleted its own shots
when the user's were better.
**The habit to build:** For anything unrepeatable, over-collect first and be ruthless in
cleanup afterward — including deleting your own work when something better exists.
**How beginners get it wrong:** They try to take the one perfect capture live, miss it, and
can never get it back.

## Guardrails for Your First Month

1. **Don't feed real names or customer data into any tool without scrubbing first** — even
   when told it's fine. A leak in a demo is nearly impossible to un-publish.
2. **Don't declare anything "done" that you haven't run end-to-end at least once.** "It should
   work" and "it works" are different claims.
3. **Don't build a reusable tool the first time you do a task.** The agent declined to build a
   wrapper because it would only "standardize one saved command line." Do it by hand twice;
   automate on the third time, when you know what varies.
4. **Don't execute a multi-step plan without checking every step against your project.**
5. **Don't experiment directly on anything live or shared.** Until reading-the-code-first is a
   habit, assume your action does more than you think.

## Seminar Discussion Questions
1. The user said the transcript was "safe," and the agent verified anyway — and found five
   real names. When is double-checking someone's assurance good judgment, and when does it
   become wasted effort or distrust?
2. The agent caught a bad screenshot from its file size before looking at the image. What
   "cheap signals" exist in work you already do, and what would you need to know in advance for
   them to be useful?
3. The capture script survived a redesign because it targeted *meaning* (labels, text) rather
   than *appearance* (styling, positions). Where else does anchoring to meaning rather than
   appearance make your work survive change?


---

# 301 — Pattern Catalog

*Model-behavior framing. Agentic Engineering Patterns. For practitioners who use agents daily
but haven't systematized. Named, transferable patterns — not one-off tips.*

## Pattern 1: Pit-of-Success Patching
**Problem:** Environment traps found during install get re-debugged by every future session
unless the fix lives where the next reader will look.
**Mechanics:** (1) Smoke-test in the real environment, not the one the docs assume. (2)
Diagnose the trap fully once. (3) Encode the fix *into the installed artifact* — skill file,
script header, config — not into chat. (4) Include the exact working invocation, not just a
warning. (5) Duplicate durable facts into memory as an index only.
**Session instance:** Git Bash's MSYS layer mangled `--pages /` into a 0-byte file; after
confirming PowerShell worked, the agent edited the installed SKILL.md to add the shell
requirement and exact paths, so any future session inherits the fix at the point of use.
**Failure modes:** Editing an artifact that syncs from upstream gets your patch clobbered on
update. Padding artifacts with every micro-observation buries the one note that matters.
**Transfers to:** A Makefile needing `gmake` on macOS (note in the header). A flaky test
needing a warm cache (encode in the fixture). A deploy script failing behind a proxy (proxy
var in the usage text).

## Pattern 2: Reality-Grounded Plan Triage
**Problem:** Plausible generic plans contain steps assuming capabilities your system lacks;
adopting them wholesale wastes effort.
**Mechanics:** (1) Treat each step as a *claim about your system*, not an instruction. (2) For
each claim, find the cheapest falsifier: a grep, a config check, a file read. (3) Render a
per-step verdict — adopt / adapt / skip — with evidence. (4) Ask what the plan *omits*: the
hard problems specific to your context. (5) Apply a deferral test to proposed abstractions —
if it would standardize "one saved command line," defer.
**Session instance:** Handed a 7-step showcase workflow, the agent grepped: no react-router,
zero `@media`, no `prefers-color-scheme`. It adopted the output contract, skipped the
ungrounded steps, named the two hard problems the template missed (demo data, explaining an
invisible-value product), and declined the premature wrapper skill.
**Failure modes:** On greenfield work there's nothing to grep — triage becomes stalling.
Rejecting a step because a capability is *currently* absent misfires when the plan is meant to
drive what gets built (dark mode arrived later; a skipped step became live).
**Transfers to:** A compliance checklist applied to a system with no user accounts. A
microservices playbook applied to a 3-user monolith. A CI/CD template assuming containers in a
repo that ships a desktop binary.

## Pattern 3: Provable Scrub at the Gate
**Problem:** Sensitive data that enters a system even once contaminates everything downstream,
so sanitization must happen *before* ingestion and be provable.
**Mechanics:** (1) Never accept "it's safe" as a property of the data — establish it by reading
in full. (2) Map every sensitive token to a fictional replacement; fix garbles in the same
pass so the output is *better*, not just safer. (3) End with an *executable assertion* that
greps for every original token and fails loudly if any survive. (4) Ingest through the
product's real APIs so the data acquires genuine derived state. (5) Where contamination
already exists, attach a standing rule to the source.
**Session instance:** The user declared a transcript "safe"; the agent found a real employer,
client, and five people, wrote a scrub script mapping each real token to a fictional stand-in
(plus STT fixes) ending in an assert-grep, then seeded via the app's REST APIs. The mapping
itself is deliberately not reproduced here -- publishing "real -> pseudonym" pairs in a public
repo re-identifies every screenshot the pseudonyms were meant to protect, which is the same
failure one layer up.
**Failure modes:** The assert only proves absence of the names you *enumerated* — useless
against sensitive content you didn't spot (figures, codenames, addresses). Scrubbing after
ingestion is theater; the raw data already lives in logs and backups.
**Transfers to:** Loading a prod DB dump into staging. Turning a real postmortem into training
material. Building an eval set from real support tickets.

## Pattern 4: Semantic Anchors, Not Incidental Ones
**Problem:** Automation keyed to incidental properties (CSS classes, coordinates, timing)
breaks silently on every redesign; automation keyed to meaning survives.
**Mechanics:** (1) Read the source and inventory *semantic* handles: aria-labels, roles,
placeholder text, visible copy, state indicators. (2) Anchor every action to one; treat a
styling selector as a defect even if it works today. (3) Wait on *state semantics*, not time —
"'Thinking...' appeared then disappeared" beats a 3-second sleep. (4) Verify silently-enforced
preconditions (a handler that no-ops without a loaded model) by waiting on the precondition.
(5) Encode corrected assumptions into the script.
**Session instance:** Three failures — an aria-label only in the collapsed sidebar, a
utility-class wait firing mid-"Thinking..." post-redesign, an Enter that no-op'd before the
model dropdown loaded — each pushed toward semantics. Payoff: the script survived a full
redesign unchanged, needing only a dark-mode extension.
**Failure modes:** Apps with no accessibility affordances offer nothing to anchor to — the fix
is adding aria-labels (which improves the app), not regressing to coordinates. Visible-text
anchors break under localization; prefer role+name when both exist.
**Transfers to:** API tests asserting on *fields* not byte order. Log alerts keyed to event
*names* not phrasing. Pipeline checks keyed to schema *contracts* not column order.

## Pattern 5: Cheap Invariant Tripwires
**Problem:** Expensive verification doesn't scale across a pipeline's runs; failures need a
cheap first-line detector that points at where to look.
**Mechanics:** (1) For each output, find a near-free proxy correlated with correctness: size,
line/record count, duration, exit code. (2) Calibrate an expected range from known-good runs.
(3) Check the proxy first; escalate to expensive verification only when out of band. (4) Treat
the tripwire as a *pointer*, never a verdict.
**Session instance:** The agent caught the mid-"Thinking..." screenshot by noticing 86KB vs an
expected ~130KB, then verified visually and root-caused the wait bug.
**Failure modes:** Trusting the proxy as proof inverts the pattern — an in-range file can still
show the wrong screen, and calibration rots when the product legitimately changes. No baseline
exists on run one.
**Transfers to:** ETL asserting row counts before human review. Builds flagging a binary 40%
smaller than yesterday. Report generators checking rendered page counts.

## Pattern 6: Checkpoint-and-Park, Re-Scout on Resume
**Problem:** Work interrupted across sessions gets redone from scratch or resumed against stale
assumptions — the fix is a two-sided protocol: record state at the pause, distrust it at the
resume.
**Mechanics:** (1) At an interruption, write a state ledger: done / seeded / exact resume steps
/ *why*. (2) Store it in durable memory, not context. (3) On resume, treat it as a map of
*intent*, not *current reality*. (4) Re-scout before replaying: check service state, take one
cheap probe, diff against the ledger. (5) Fold deltas into the plan before executing parked
steps.
**Session instance:** At the redesign pause, the agent recorded exact state. Days later it
didn't replay blindly: it noticed containers "Up Less than a second," waited, peeked,
discovered the redesign had *added* dark mode, and extended the run to light+dark.
**Failure modes:** Trusting the checkpoint verbatim ships stale assumptions. Checkpoint *rot*
scales with pause length — a two-month pause may invalidate the ledger entirely. Checkpoint at
state transitions, not continuously.
**Transfers to:** Pausing a DB migration over a weekend. Handing infra work across timezones.
Resuming a dependency-upgrade branch after main moved.

## Pattern 7: Asymmetric-Cost Capture (Overcapture, Curate Late)
**Problem:** Non-replayable events have brutally asymmetric error costs — a missed capture is
gone forever, a bad capture costs one delete — so capture and judgment must be separated in
time.
**Mechanics:** (1) Before the event, walk a pre-ranked fallback ladder for *how* to observe and
settle on the highest rung that works — don't debug the ideal rung mid-event. (2) During,
capture greedily on a fixed cadence; don't stop to evaluate. (3) When a risk surfaces
mid-capture, flag it immediately *but keep capturing*. (4) Afterward, curate ruthlessly: keep
the few that earn it, salvage compromised ones surgically (verified crops), delete the rest.
(5) Deletion over addition across sources.
**Session instance:** With viewer, tab-group, and beacon paths exhausted, the agent fell back
to native screen capture and burst-shot 20 frames at 25-30s through the live call. When real
names surfaced it flagged immediately without stopping, kept 2 of 20 (one a crop excluding the
leak), and deleted its own frames when the user's proved better.
**Failure modes:** When the *capture itself* is the irreversible harm (regulated data to a
third party, recordings that shouldn't exist), "capture everything" is the violation.
Overcapture without a real curation pass just relocates the problem into a folder of 200
unreviewed frames.
**Transfers to:** Verbose logging during a one-shot incident, pruned into the postmortem.
Recording every take of a conference demo. Snapshotting distributed state on every heartbeat
while a Heisenbug is live.

## Pattern 8: Prove Read-Only, Stage the Writes
**Problem:** Acting near live systems mixes safe observations with potentially destructive
mutations — prove an action is read-only before taking it, and stage anything that isn't behind
a human gate.
**Mechanics:** (1) Before observing a live system, verify from source that observation doesn't
mutate. (2) Classify every action as read / reversible write / irreversible write — the class
picks the safeguard. (3) On another agent's or person's surface, prefer primitives that
*prepare without committing* (type don't Enter; open a PR don't merge). (4) When targeting is
ambiguous, disambiguate with a cheap self-marker, not a guess at someone else's resources. (5)
When a staged action misses its audience, reproduce it verbatim.
**Session instance:** Before a viewer tab, the agent confirmed from code that `connect()` only
fires in start/resume — viewing was provably read-only. Facing three "Claude" tab groups, it
navigated *its own* tab to example.com as a beacon. At handoff it used send-text (types without
submitting) so the human reviewed before execution.
**Failure modes:** Staging everything buries the human in approval fatigue until they
rubber-stamp the one write that mattered. The read-only proof is only as good as the code you
read — one that misses a side channel is confidence without safety.
**Transfers to:** `EXPLAIN` before a query on a prod replica, `UPDATE`s in a reviewed
migration. `terraform plan` staged, `apply` human-gated. Drafting the incident email in the
ticket rather than sending.

## Constraints & Boundary Conditions
1. **Closed-vocabulary limits (P3, P8):** Assert-grep scrubs and code-read proofs only cover
   what you enumerated / what the code you read does. Open-ended PII, side channels, and stale
   source defeat them.
2. **No baseline, no pattern (P2, P5):** Triage needs a codebase to grep; tripwires need
   known-good runs. On greenfield/first-run work, fall back to direct verification.
3. **Artifact ownership (P1):** Patching installed artifacts assumes you own the copy.
   Upstream-synced files clobber your patch — put the note in a layer you control.
4. **Checkpoint rot scales with pause length (P6):** Re-scout is proportional work; know when
   to declare a checkpoint dead.
5. **Irreversible capture inverts P7:** Overcapture assumes bad frames are deletable. Where
   capture creates the liability, greedy capture is the failure mode.
6. **Semantic anchors need a semantic app (P4):** No accessibility affordances / localized copy
   means nothing stable to anchor to. The fix is improving the app, which needs write access
   you may not have.

## Integrative Exercise — "The Friday Demo"
You're the agent-driving engineer at a healthtech startup. Sales has a *recorded, one-take*
customer demo Monday 9am against staging. On your desk: (a) a CSV of real patient-adjacent
scheduling data with a PM's note *"legal already looked at this, it's fine to load into
staging"*; (b) a 10-step "demo environment playbook" from another AI including direct-SQL
seeding, a mobile walkthrough, and building a reusable "demo-prep CLI"; (c) the platform team
ships a staging redesign *Sunday night*; (d) you're off Saturday and Sunday. Deliverable: a
screenshot folder for the deck, plus whatever it takes for Monday's one-take to survive review
before external sharing.

Write the plan, combining **at least three patterns**, answering:
1. What do you do with the CSV and the assurance, and what artifact *proves* it? (P3)
2. Which playbook steps do you adopt/adapt/skip — with the falsifier for each — and what's your
   ruling on the CLI tool? (P2)
3. How do you build capture so Sunday's redesign doesn't destroy it, and what's your cheapest
   wrong-output detector? (P4, P5)
4. What do you write down Friday 5pm, and what's the *first* thing you do Monday 7am, before
   trusting anything you wrote Friday? (P6)
5. How do you run the one-take, and what happens if real data appears on screen mid-take? (P7,
   P8)

*Full credit requires: (1) an executable check; (4) a concrete re-scout probe; (5) a statement
of why you don't stop the take — in terms of error-cost asymmetry, not vibes.*


---

# 501 — Seminar Brief

*Model-behavior framing. Agentic Systems: Judgment, Risk, and Coordination. For senior
engineers and researchers who design multi-agent workflows. Note: this session was one node in
a larger topology — the user runs concurrent Claude sessions in herdr tabs; a sibling session's
design review triggered the redesign; a third session consumes this session's outputs.*

## 1. Thesis
This session is fundamentally a case study of an agent operating as one **stateful node in a
distributed, partially observable human-agent system**, where the governing competence is not
planning or tool skill but the management of *irreversibility*. Across nine phases, every
consequential choice — scrub before ingest, read code before touching a live UI,
type-but-don't-submit into a sibling session, capture liberally then curate ruthlessly, mark
contaminated state rather than delete it — instantiates one implicit policy: **index the
aggressiveness of an action to its reversibility, and index the placement of knowledge to
where the next actor will actually stand when they need it.** As agents move from
single-conversation tools to persistent nodes in multi-session topologies, the binding
constraint shifts from *what the agent can do* to *what the agent's actions leave behind* — in
databases, filesystems, sibling terminals, a human's half-typed prompt. Planning is a 301
skill; this session demonstrates the 501 skill of *consequence topology*: knowing which edges
in the system graph transmit damage, and in which direction.

## 2. Five Deep Analyses

### 2.1 Risk-Asymmetry Management: Aggressiveness Indexed to Reversibility
The session runs two opposite operating modes and switches between them by loss function, not
by phase. Where loss is asymmetric-cheap (a missed screenshot costs a re-run), the agent is
maximally liberal: 20 frames every 25-30s, knowing 18 will be discarded. Where loss is
asymmetric-expensive (PII into a database, audio into a live session, a keystroke into a
human's terminal), it becomes maximally conservative: scrub-with-assertion before any data
touches the app; read `connect()` semantics before attaching a viewer; type-without-Enter by
construction. These are not two dispositions but one — **the same expected-loss calculus
evaluated per-action.** "Capture liberally, curate ruthlessly" is the identical policy to
"verify before attach," applied to a recoverable failure versus an unrecoverable one.

The live-capture cascade deserves the strong reading: **lattice descent with invariant
preservation**, not mere fallback. Each degradation (extension-native capture ->
beacon-disambiguated tab targeting -> native OS screen capture with F11) surrenders fidelity
but never surrenders two invariants: the live session must not be perturbed, and the
unrepeatable event must be recorded. Note what the agent did *not* try: anything touching the
streaming tab. The search space was pre-pruned by irreversibility analysis done before the
event — the code-read proving a viewer is read-only, and the recognition that "Resume Audio"
would inject a fake mic. Graceful degradation is 301; degradation *with a proof obligation,
discharged in advance, about which moves are forbidden* is the 501 version.

The seminar position: this calculus was **implicit**, encoded nowhere but in behavior. That is
both the session's strength and its fragility. Nothing in the environment enforced "don't click
Resume Audio"; a marginally less careful agent clicks it. Risk-asymmetry management that lives
only in disposition does not compose across agents — which is why the knowledge-placement
behavior (2.2) is its necessary complement.

### 2.2 Knowledge Placement: The Nearest-Point-of-Future-Use Principle
The session performs a consistent and, I argue, correct theory of where a lesson should live:
**at the point where the next actor will already be standing when it becomes relevant.** The
MSYS gotcha went into the installed SKILL.md — the next agent to hit it is reading that skill.
The wait-for-"Thinking..." fix went into the capture script — the next failure occurs inside a
run of that script. The herdr mechanics went into a memory file — cross-session knowledge with
no code home. The "radioactive session" rule went into the deliverable README — the threat
model is a future *consumer of the assets*. Four lessons, four homes, zero centralized docs.

This beats centralized documentation for a structural reason: agents and humans do not consult
docs; they consult **whatever is in their working set at the moment of need.** A central
"gotchas.md" must be *found*, which requires already knowing a gotcha exists — the exact
knowledge it is meant to supply. Placement converts documentation from a pull system that fails
silently into a push system that fires when relevant. The cache-locality analogy is exact: the
value of stored knowledge is its hit rate, and hit rate is a function of placement, not content
quality. Editing the *installed* third-party SKILL.md rather than noting the caveat in chat is
the strongest instance — chat is the lowest-locality store in the system, garbage-collected at
session end.

The unresolved tension: placement *fragments* knowledge, and fragmented knowledge cannot be
audited, versioned, or invalidated as a set. The capture script's embedded lessons stayed valid
across the redesign only because they were semantic — a skilled choice, but had a placed lesson
gone stale (SKILL.md paths after a directory move), no mechanism would detect it.
Nearest-point-of-future-use is the right *write* policy; the field lacks the corresponding
*invalidation* policy.

### 2.3 Multi-Session Topology: The Session as a Node with Weak Identity
The session operated *knowingly* as one node among several. Three improvised primitives deserve
formalization. First, **identity resolution by observable side effect**: when herdr's pane list
and Chrome's tab groups offered no distinguishing labels (all "Claude"), the agent identified
itself by matching a session ID to its own scratchpad path, and disambiguated its browser tab
by navigating to example.com as a beacon — mutating its own observable state to become
findable. This is the agent re-deriving, from scratch, what distributed systems solved with
node IDs and heartbeats; that it *had* to is an indictment of agent-hosting UIs where n agents
share one label.

Second, the **non-executing handoff**: messaging the website session by typing into its prompt
*without submitting*. This converts inter-agent communication from command execution into a
*proposal requiring human ratification* — human-in-the-loop enforced by mechanism, not policy.
The agent could not inject an instruction into a sibling even if its message were malformed or
adversarially influenced, because the Enter key belongs to the human. Contrast the naive design
(agents invoking each other directly), which transitively extends every agent's blast radius to
every reachable agent's permissions.

Third, the **write-write race with the human**: the handoff landed while the user was
mid-composition in the same terminal — two writers, one buffer, no locking. The recovery
(reproduce verbatim in its own channel) was correct but reveals the deeper problem: the prompt
is being used simultaneously as a human input device and an inter-agent mailbox, and is fit for
neither under concurrency. The one boundary that held by construction was the Chrome tab-group
constraint the agent *couldn't* talk its way around — which is exactly what you want from an
isolation boundary.

### 2.4 The Economics of Minimalism as Risk Policy
The session's minimalism reads superficially as frugality; the stronger claim is that **in
agentic systems, minimalism is a safety mechanism, because every artifact an agent creates is
standing state that some future actor will trust.** The refused wrapper skill is the clean
case: its cost was not the twenty minutes to write it but that a skill file is a *durable
instruction to future agents*, and a wrapper standardizing "one saved command line" would
encode today's incidental parameters as tomorrow's authoritative interface. Deferring until a
repeated need materializes is an *eviction policy for speculative state*. Likewise
deletion-over-addition: removing its own inferior shots wasn't tidiness, it was preventing a
downstream consumer that cannot judge provenance from selecting a worse asset. In a topology
where other agents consume your outputs uncritically, *curation is access control*.

The session also shows where minimalism must yield, and the boundary is principled: **minimalism
governs artifacts, never verification.** The maximally lazy install still got an immediate
smoke test — which caught the MSYS mangling that would otherwise have detonated during the
unrepeatable live event. The lazy capture still spent effort reading source for semantic
selectors — which paid off when the redesign landed and the script survived. The scrub script's
closing assertion is the same shape: minimal artifact, plus one check that fails loudly if its
core promise breaks.

Where minimalism undershoots is exactly where this session got lucky: **one-shot events and
cross-agent contracts.** A pipeline validated only against the current UI is adequate for
repeatable capture and inadequate for the live call — the agent compensated by over-capturing
(buying redundancy in data because it had bought none in mechanism). And the "radioactive" rule
living only in a README is minimal but unenforced. The defensible rule: minimalism is the right
default for anything re-runnable, and the wrong default for anything you get one attempt at or
that another agent consumes without judgment.

### 2.5 Contamination Semantics: Provenance Outlives the Conversation
Phase 7 created a fact no session-level care can undo: a database session containing unscrubbed
real names, produced legitimately, from the user's own audio. The agent's response defines a
**taint protocol**: (1) *detected at ingress* — flagged the moment a real name surfaced in a
live insight; (2) *contained at egress* — 18 of 20 frames discarded, the survivor cropped to
exclude leaking cards, each crop visually re-verified; (3) *labeled, not destroyed* — the rule
written into the deliverable README; (4) *escalated* — deleting user data unilaterally
recognized as outside the agent's authority even when it was the privacy-maximal move. Detect,
contain, label, escalate — a complete protocol improvised in real time.

The deep point: **provenance is a property of state, and state outlives the conversation that
created it.** Within the session the taint was tracked in the agent's attention — it knew which
session was dirty, which frames leaked. The moment the session ends, all of that collapses into
one English sentence in a README. Every future export path — retranscribe, XLSX export, summary
HTML, chat-over-transcripts, a future agent told to "grab a screenshot of a session with lots
of insights" — will happily traverse the radioactive session, and none consults the README. The
contamination is durable; the warning is advisory; the enforcement is nonexistent.

The stance: this is correct behavior *given current infrastructure* and simultaneously the
clearest demonstration that the infrastructure is missing a layer. The agent moved the taint
label to the highest-locality location available — but taint that matters should be a property
the *storage layer* carries and *export paths* check, not a property of documentation. Compare
the scrub script's assertion (enforcement) with the README sentence (hope). That gap is the gap
between Phase 3's contamination, prevented mechanically, and Phase 7's, managed rhetorically —
the session's most important open wound.

## 3. Near-Miss Ledger

| # | Counterfactual | Damage class | Safeguard that prevented it |
|---|---|---|---|
| 1 | Agent clicks "Resume Audio" in its viewer tab, streaming a synthetic mic into the user's live session | Irreversible corruption of an unrepeatable recording + garbage insights in real data | Code-read *before* UI interaction: verified `connect()` semantics and viewer read-only status; recognized the button as a live-mutation path and refused it |
| 2 | Agent takes "safe to use" at face value and seeds the raw transcript | Real employer, client, five names into PostgreSQL -> screenshots -> public site, in a repo whose git history had *just* been scrubbed of that employer | Read-fully-before-ingest + a scrub script whose terminal assertion greps every real name and fails the run if any survive |
| 3 | Handoff uses `pane-run` (Enter) instead of `send-text` (types only) | Autonomous prompt execution in a sibling session — and, mid-human-composition, an interleaved Frankenstein prompt neither author wrote | Non-executing handoff by design; human keeps the Enter key. The write-write race that *did* occur was survivable because nothing executed |
| 4 | Agent deletes the contaminated DB session "to be safe" | Unilateral destruction of the user's real meeting data — the only record of the live event | Authority boundary: risk contained via curation + a standing README rule; the destroy/keep decision left with the data's owner |
| 5 | Skill install skips the smoke test; MSYS mangling ships latent | A silently broken capture pipeline (0-byte outputs, no error) discovered only mid-live-event, when there is no second take | Immediate smoke test *plus inspection of the output artifact* — the 0-byte file, not an exit code, revealed it; same anomaly-sensing later caught the 86KB frame |

## 4. Open Problems
1. **Taint tracking for agent-created persistent state.** The radioactive session is marked only
   in a README no export path consults. What makes provenance labels ("contains unscrubbed
   PII," "synthetic demo data") first-class properties of rows/files that survive across
   sessions and are *checked* by egress paths? Application schema, storage layer, or harness —
   and who writes the label when the agent that knew the provenance has ended?
2. **A real inter-agent handoff protocol.** send-text is a brilliant hack revealing the missing
   abstraction: agents messaging agents need addressed delivery, an ACK, human-ratification
   semantics, and freedom from write-write races on shared input surfaces. The failure ladder
   here (target unregistered -> pane-level addressing -> human missed it -> verbatim
   reproduction) is a protocol being discovered empirically. What mailbox-with-consent design
   makes each failure impossible rather than recoverable?
3. **Agent identity in shared UIs.** Self-identification via side effect (session-ID match,
   example.com beacon) is a symptom. Multi-agent workspaces need node identity: stable,
   human-legible, machine-queryable labels on panes/tabs/groups, so "which of these five
   'Claude' surfaces is me / safe to touch" is a lookup, not an experiment against production.
4. **An invalidation model for placed knowledge.** Nearest-point-of-future-use fragments lessons
   across skill files, scripts, memory, READMEs, with no index and no staleness detection. When
   the environment changes, which placed lessons silently die? Can placement be paired with
   cheap validity probes — the documentation analogue of the smoke test?
5. **Operating policy during a live leak at an unrepeatable event.** The agent flagged, *kept
   capturing*, and resolved the tension in curation — implicitly deciding a contained leak into
   its own scratchpad was cheaper than losing one-shot data. Right here, but a judgment call
   with no framework: under what formal conditions should an agent continue operating in the
   presence of a detected data-exposure, versus halt? The answer must weigh irrecoverability of
   the event, containment of the capture path, and downstream curation authority — none of which
   current agent policies represent explicitly.


---

# 701 — Agentic Systems: Formal Foundations

*Model-behavior framing. The session read as a single sampled trajectory from a policy's
rollout distribution; academic frames imported; conjectures, impossibility results, and a
reflexive n=1 critique. Builds on the 501 seminar brief.*

## What changes at 701

The lower courses treat the session as a *source of lessons*. A 701 does the opposite: it
treats the session as **a single sampled trajectory drawn from a policy's rollout
distribution**, and asks what formal structure that one trajectory reveals or constrains. The
unit of study is no longer "the agent did X, which teaches Y" (501) but "here is a formal
object; the session is one realization; here are its invariants, its conservation laws, its
impossibility results." What remains after abstraction is a policy acting on persistent,
shared, partially-observed state under incomplete self-knowledge of its own effects.

## The central thesis: many "best practices" are shadows of one objective — preserved optionality

Read the session's disparate disciplines as projections of a single quantity onto different
spaces:

| Behavior | Space | What it preserves |
|---|---|---|
| Reversibility-indexed aggression | action space | reachable future states |
| Overcapture, curate late | data space | recoverable observations of an unrepeatable event |
| Refusing the wrapper skill | artifact space | freedom from load-bearing commitments |
| Knowledge placement | future-agent space | the next actor's ability to act correctly |
| Read-before-touch | epistemic space | refusing to spend optionality you can't prove you can afford |

The formal candidate for "optionality" already exists: **empowerment** (Klyubin, Polani,
Nehaniv, ~2005) — the channel capacity between an agent's actions and its future observations, a
scalar measure of how much controllable influence it retains. The 701 thesis: **empowerment,
usually proposed as an intrinsic-motivation signal, is better read here as a safety objective —
and not only the agent's own, but the preserved empowerment of the human and of future
agents.** A trustworthy node maximizes progress per unit of optionality spent, for everyone
downstream. That reframing (from "keep my own options open" to "don't collapse anyone's
reachable set without proof it's worth it") is the organizing result, and every module is a
corollary.

This unifies two things the 501 kept separate: *minimalism* (artifact space) and
*irreversibility management* (action space) become the **same theorem viewed through real-
options theory** (Dixit & Pindyck): under irreversibility plus uncertainty, the option to defer
has strictly positive value. Building the wrapper is exercising an irreversible option early;
deferring it *is* the empowerment-preserving move. Minimalism and read-before-touch are not two
virtues — they are one inequality.

## The formal object, and why the obvious model is wrong

The obvious model is a **POMDP**. It fails on three axioms this session violates, and the
failures are the interesting part:

1. **Episodic reset fails.** The conversation ends, but the "radioactive" database session
   persists — state outlives the policy that created it, and a *different, amnesiac* agent
   inherits it. The right object is closer to a **partially observable stochastic game with
   persistent shared state and non-persistent, interchangeable, anonymous principals.** No clean
   name exists in the literature; that absence is itself a finding.
2. **Stationary environment fails.** Sibling herdr sessions mutate shared state concurrently.
   This is a Dec-POMDP / stochastic game (Shapley), but worse: the other players' policies are
   unobserved *and* the players are other instances of yourself whose identity you cannot even
   resolve (all tabs "Claude").
3. **Known action semantics fails.** The agent does not know a priori what "Resume Audio" does —
   it must *read the code to compute the effect*. The transition function is itself partially
   observed and must be discovered before it can be safely used.

Axiom 3 is where the deepest theory lives.

## Module A — Safe autonomy as proof-obligation discharge (and its unsoundness bound)
"Read `connect()` before attaching a viewer" is **computing a weakest precondition** (Dijkstra)
— discharging a Hoare-logic obligation that an action preserves an invariant (*the live session
is not perturbed*). The agent is doing lightweight formal verification against a model it
assembles by reading source.

The conjecture: **the soundness of an agent's safety proof is bounded above by the completeness
of its effect-model, which is bounded by what it observed.** The side-channel caveat (a
heartbeat the code-read missed) is not an edge case — it is the *general* failure mode, because
it is partial observability wearing a security costume. This connects to the **frame problem**
(McCarthy & Hayes): safe action requires reasoning about what an action does *not* change, and
the frame is exactly what a bounded reader cannot fully enumerate. You cannot verify what you
did not observe. The near-miss (refusing Resume Audio) was a *sound* proof; the danger is
structurally identical *unsound* proofs, and nothing in the agent's phenomenology distinguishes
the two.

## Module B — Information-flow theory and the two regimes of non-interference
The scrub-with-assert and the radioactive-session are textbook **information flow control**:
Denning's lattice (1976), non-interference (Goguen & Meseguer, 1982). Two regimes, and the gap
is the point:

- **Enforced non-interference** — the `assert`-grep is a *declassification guard*: data cannot
  leave the "raw" label until a check proves the sensitive tokens are gone.
- **Advisory non-interference** — the README rule is a *comment*. Every egress path traverses
  the tainted state without consulting it.

Sharpest claim: **advisory non-interference is not a security property — it is a documentation
property, and the two are categorically different.** This mirrors the classic result that
information-flow control cannot be soundly retrofitted; it must be end-to-end and carried by the
substrate — the **end-to-end argument** (Saltzer, Reed & Clark, 1984) generalized: a property
intermediate layers cannot completely enforce must live at the endpoints. An agent over a
substrate without label propagation can only ever achieve the advisory regime. Carefulness is
not a substitute for a type system.

## Module C — Knowledge placement as the end-to-end argument for epistemics; and a two-generals limit
Placement *is* the end-to-end argument applied to knowledge: a lesson in a central doc cannot be
guaranteed delivery (the reader must know it exists), so it must live at the endpoint that will
use it. Correct placement maximizes *delivery guarantee*.

The limit: you cannot achieve both delivery-guarantee and global auditability without an index
that itself must be maintained — a CAP-flavored tradeoff (analogy, not theorem). Fragmented
placed knowledge is deliverable but un-auditable and **un-invalidatable**: when the environment
shifts, no mechanism detects which placed lessons went stale.

The coordination piece — the non-executing handoff and the write-write race — is a **common-
knowledge** problem (Halpern & Moses, 1990): coordinated action requires common knowledge, which
is provably unattainable over an unreliable channel (coordinated-attack / two-generals). The
write-write race on the shared prompt is a two-generals instance in miniature. The
`send-text`-don't-`Enter` primitive *sidesteps the impossibility by refusing to require
agreement*: it converts a coordination problem into a unilateral proposal a human ratifies. You
cannot solve two-generals; you can decline to need it solved.

## Module D — Ratification as a capability boundary, not a behavioral norm
`send-text` vs `pane-run` is a **mechanism-design** result. It moves human-in-the-loop from a
*policy* the agent chooses to honor to a *capability* the agent structurally lacks — the
difference between incentive-compatibility-by-choice and **dominant-strategy-by-construction**,
mapping onto **capability security / POLA** (Dennis & Van Horn; Saltzer & Schroeder): the agent
cannot inject an executing instruction into a sibling because it does not hold the "commit"
capability — the Enter key belongs to the human.

Load-bearing claim: **behavioral norms do not compose across agents; capability boundaries do.**
"The agent will ask before committing" is a property of one well-behaved agent. "The agent
*cannot* commit" is a property of the *system* and holds for every agent behind that boundary.
Trust that scales must be encoded as capability, not disposition. This is also the answer to
Module A's unsoundness bound: where you cannot prove an action safe, put it behind a boundary
that makes committing it structurally impossible without a human.

## Impossibility results the course would conjecture
1. **No retrofit taint.** Enforced non-interference over agent-created persistent state is
   unachievable without a label-propagating substrate; carefulness yields only the advisory
   regime. (Module B)
2. **No verified frame.** An agent's safety proofs are unsound in exactly the measure of the
   effects it did not observe; complete safety requires complete observation, which partial
   observability forbids. (Module A)
3. **No free coordination.** Reliable inter-agent coordination over a channel shared with human
   input is impossible (two-generals); it can only be sidestepped by non-committing primitives.
   (Module C)
4. **No costless placement.** Placed knowledge cannot be simultaneously delivery-guaranteed and
   globally auditable/invalidatable without a maintained index. (Module C)
5. **The optionality-progress frontier.** There is a Pareto frontier between progress and
   preserved empowerment; every irreversible action spends optionality, and the "good agent"
   operates on the frontier rather than interior to it. (Thesis)

## The reflexive turn — the n=1 problem
Everything above is reverse-engineered from a single rollout — behavioral cloning from one
trajectory, with all its pathologies: non-identifiability (many policies produce this trace),
survivorship (we studied a success; the near-misses are counterfactual, never *observed*
failures), and the narrative fallacy (post-hoc coherence imposed on locally-greedy moves). The
honest framing: the casebook is a *maximum-likelihood policy fit to n=1*, and its claims are
only as good as their out-of-distribution predictions. The course's final demand: *state what
would falsify each conjecture, and design the trajectory that would.* A theory that cannot be
surprised by the next session is not a theory.

## Open theoretical problems (distinct from 501's engineering ones)
- Is there a **conservation law** for optionality — a Lyapunov-style potential the good policy
  provably descends slowly? (The Landauer/irreversibility-costs-erasure analogy is suggestive
  but *only* analogy.)
- What is the **complexity class** of computing a safe action under an incompletely-observed
  transition function? (Module A hints it inherits POMDP hardness.)
- Is there a **type theory of provenance** for agent-created state such that egress is a
  well-typedness check? (Module B's substrate.)
- What is the **identifiability** result for policies fit to k trajectories — how many rollouts
  before the extracted "principles" are the true policy rather than one consistent hypothesis
  among many?

## Reflexive coda — the theory governs the memory system that stores it
Module C's critique of placed knowledge *is* a critique of the agent's own memory system: a
`MEMORY.md`-plus-files store is exactly placed knowledge — deliverable but fragmented, with no
invalidation mechanism. The correct response is the discipline the theory prescribes: stamp
provenance and as-of dates (read memories as intent, not current truth); prefer enforced over
advisory (mark ephemeral scratchpad as ephemeral rather than pretend durability); treat recall
as a proof obligation (verify a recalled file/flag still exists before acting). The instinct the
session stumbled toward with the scrub-assert and the radioactive README, now stated as a
principle that turns back and governs the instinct. That is the 501->701 move: the instinct
becomes a theorem, and the theorem governs the instinct.


---

