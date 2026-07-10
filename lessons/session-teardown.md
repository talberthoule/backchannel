# One Session, Three Altitudes

*A teaching teardown of a single agentic coding session — read at three course levels.*

A person and an AI coding assistant spent one session installing a design-review
skill system, running two automated design reviews via background subagents,
fixing every finding across four surfaces with three parallel sub-teams, and then
redesigning an exported HTML document for craft. This document teaches that
session at three altitudes:

- **101 — Foundations.** The vocabulary and the always-safe moves. If you are new
  to working with an agentic assistant, start here.
- **301 — Applied Practice.** The reusable orchestration and verification *plays*,
  each with its tradeoffs and failure modes. For practitioners doing multi-agent work.
- **501 — Theory & Meta.** The principles each play instantiates, the established
  theory behind them, and — the part that sharpens judgment — the boundary where
  each one breaks. For people who design agent systems.

The same events recur at each level; what changes is the depth of *why*. A single
thread runs top to bottom: **check the result, not the claim** shows up in 101 as a
rule of thumb ("'no error' is not 'it worked'"), in 301 as the *Review → Fix →
Independently-Verify* pipeline, and in 501 as the *test-oracle problem*.

> **Method note (this document eats its own cooking).** This teardown was itself
> produced by the method it describes: a lead ("the professor") wrote a single
> ground-truth case file, dispatched three subagents in parallel — one per course
> level, each with a sharply bounded remit so the tiers wouldn't overlap — then did
> quality-control on the returns (checking for fabricated facts, level-bleed, and
> missing patterns) before synthesizing. The capstone's unifying thesis came from
> the 501 aide; the cross-tier connective tissue is the professor's.

---
# Working With an Agentic Coding Assistant — 101 Foundations

Welcome. This lesson uses one real working session between a person ("the user")
and an AI coding assistant ("the agent") to teach you the basic vocabulary and
the safe, repeatable moves. You do not need to code to follow along. Every claim
here comes from that session.

---

## The four words you need first

**Skill** — a ready-made bundle of instructions and rules the agent can load and
follow, like an expansion pack of expertise. In this session the user asked the
agent to install a skill system called `ui-craft` from GitHub. It arrived as 14
skills: `ui-craft` (design "don't make it look generic" rules), `audit`
(accessibility/performance checks), `heuristic` (scores a screen 0–100), and
`finalize` (a final "is it ready to ship?" gate). The agent didn't guess how to
design — it loaded tools built for it.

**Subagent** — a helper the main agent hands a chunk of work to. The helper does
the work on its own and hands back a short written **summary** (not everything it
did). Here, the main agent dispatched two subagents to review the design: one for
the app, one for the website and docs. The main agent then combined their
summaries. Think "the agent delegating to teammates and reading their reports."

**Design review** — checking a finished thing against known standards *before*
you change it, so you fix the right problems. The two review subagents scored the
app **58 out of 100 (an F)** and the landing page **73 (a C)**, then listed
specific issues. Nobody changed a line of code until the reviews were in.

**Verification** — proving something actually worked by *looking at the real
result*, not by assuming. After the fixes, the agent re-ran the app's build
itself (74 modules, passed) instead of trusting the helpers' "it's green" claims.

---

## The beginner-safe loop this session demonstrates

1. **Understand the task** — the user asked; the agent restated and explored.
2. **Pick the right *existing* tool** — it listed the design skills it already
   had rather than inventing an approach.
3. **Confirm it actually worked** — it checked results, not just exit messages.
4. **Review before you change** — reviews first, fixes second.
5. **Let the human commit** — it never saved changes permanently until asked.

Master this loop and you are already doing the job well.

---

## A small worked example (why step 3 matters)

The agent ran a command to install `ui-craft`, but piped the output through
`head -60` (a command that shows only the first 60 lines). `head` stopped reading
early, which abruptly killed the installer mid-write. **The command *looked*
successful — no error appeared — but the files were never written.** The agent
noticed the target folder was empty, realized the pipe had cut the installer off,
and re-ran the command *without* piping. This time all 14 skills landed. Lesson:
"no error" is not the same as "it worked."

---

## 8 rules of thumb you can reuse everywhere

**1. "No error" is not "it worked" — check the result.**
Why: commands can fail silently and still look fine. How: after any action, look
for the real artifact (the file, the folder, the output). *Session moment:* the
`head`-piped installer that quietly wrote nothing.

**2. Know your tools before you act.**
Why: reaching for what you already have beats guessing. How: ask "what tools/
skills do I already have for this?" first. *Session moment:* asked "do you have a
good design skill?", the agent listed its existing ones instead of winging it.

**3. Actually invoke the skill — don't work from memory.**
Why: a skill carries steps and rules you will otherwise forget. How: load and run
the tool, don't paraphrase it. *Session moment:* for the export-page redesign the
agent *invoked* the `ui-craft` skill and ran its built-in Discovery checklist.

**4. A tool flagging something is not proof it's real — verify each flag.**
Why: automated scanners produce false alarms. How: check each flag against the
actual code before acting. *Session moment:* of 10 "missing confirmation" hits, 4
were false positives (the confirmation was already there); only 6 were fixed.

**5. Review before you change.**
Why: reviewing first tells you *what* to fix and how big the job is. How: run a
check/review pass before editing. *Session moment:* two full design reviews ran
before any fix was attempted.

**6. Fix the root cause once, not every symptom.**
Why: one fix at the source is smaller and also fixes problems you didn't list.
How: find the shared origin instead of patching each spot. *Session moment:* a
single global focus-outline rule cleared about 93 separate findings.

**7. Verify by looking at real output, not by reading the plan.**
Why: a claim of "done" can still be wrong. How: re-run the build yourself; render
the real thing and look at it. *Session moment:* the agent re-ran the build and
even rendered the redesigned export page in light and dark mode to confirm.

**8. Say what you couldn't check — flag limits, don't hide them.**
Why: honest gaps are trustworthy; silent gaps mislead. How: write the caveat into
your report. *Session moment:* the browser tool only rendered one screen width, so
the reviews openly said mobile was judged from source code, not a live view.

---

## Let the human commit

Some actions are hard to undo or reach the outside world — saving changes
permanently ("commit"), publishing them ("push"), deleting things. Throughout the
session the agent left its edits sitting in the working files and **waited for the
user to ask before committing**. When asked, it committed carefully. New rule to
internalize: *irreversible or outward-facing actions wait for a human's go-ahead.*

---

## Mini glossary

- **Agent:** the AI assistant doing the work for you.
- **Subagent:** a helper the agent delegates a task to; returns a short summary.
- **Skill:** a loadable bundle of instructions/rules the agent can follow.
- **Build:** the step that assembles the code and fails if something is broken —
  a quick "does it still work?" check.
- **Commit / push:** save changes permanently / publish them; treat as
  irreversible, so a human approves.
- **False positive:** a tool flags a problem that isn't actually a problem.
- **Detector / heuristic score:** an automatic checker vs. a judged 0–100 rating —
  two different instruments, both fallible.

---

*One step beyond 101:* the session also decided which helpers could safely run at
the same time based on which files each one owned, and it treated its instructions
to subagents as a strict "contract." That's real, but it's **301/501 material** —
you'll get there once these fundamentals are second nature.
# 301 — Applied Practice: Orchestrating a Multi-Agent Design Overhaul

**Audience:** You already know what skills and subagents are. This tier hands you the reusable *plays* — the ones that survive contact with a real repo — each with its tradeoffs, its failure mode, and how to lift it off this session onto your own work.

Everything below traces to one session: an agent redesigning a real app across four surfaces (`frontend/`, `site/`, `docs-site/`+`docs/`, plus an export-HTML generator in `backend/`), using review skills, background subagents, and browser automation. 301 shows you the play; 501 shows why it's principled (locking theory, Amdahl, epistemology) — we reference that in a line and move on.

---

## The seven patterns

### 1. Partition-by-ownership concurrency
**When to use:** You have N units of work and can draw a clean line so each writer owns a disjoint set of files/directories. **When NOT to:** Two units must edit the same file — then parallel writers are *last-writer-wins corruption, not a merge*; the second agent overwrites the first with no conflict marker to warn you.

**Failure it prevents:** Silent file clobbering. There is no git merge between two agents writing the same working tree at the same time — the filesystem just keeps whatever landed last.

**This session:** The three fix surfaces lived in disjoint trees (`frontend/`, `site/`, `docs-site/`). The agent's explicit rule — *file/directory ownership dictates the concurrency boundary* — let three lead agents run fully in parallel with zero collision risk. Where files *were* shared (the site's `style.css` across comparison pages; overlapping `.tsx` in the app), the lead kept sole ownership of the shared file and only spawned children on disjoint file sets.

**Apply it elsewhere:** Before dispatching, list the files each task will touch. Disjoint sets → parallelize. Overlap → either (a) serialize the overlapping work under one owner, or (b) worktree-isolate each and merge. The agent here judged worktree-and-merge *too costly* for tangled TSX and serialized instead — a legitimate call. Isolation has a merge tax; pay it only when the parallelism buys back more than it costs.

### 2. Foundational-first sequencing
**When to use:** Some outputs are *referenced by* others — tokens before the components that consume them, a schema before its callers, an API before its client. Build the referenced thing first. **When NOT to:** Units are truly independent (no shared vocabulary) — sequencing them just adds latency for nothing.

**Failure it prevents:** Half-built references. If dark mode, palette, and focus rings all point at design tokens that don't exist yet, every downstream fix either breaks or hardcodes a value you'll rip out later.

**This session:** *Across* surfaces there was no dependency, so site and docs ran parallel and finished sooner. *Inside* the app surface there was a hard dependency chain, so the app lead ran a **sequential pipeline**: (1) build the 3-layer semantic token spine (light+dark) + self-host the font, (2) then global `:focus-visible` + the `outline-none` sweep, (3) collapse the insight-row hues to one accent, (4) `ConfirmProvider`, (5) mobile drawer + responsive tables, (6) dark-mode toggle sweeping `bg-white` → token. Tokens are step 1 because steps 2, 3, and 6 all reference them. This made the app track the **long pole** (critical path); the other two finished early and idle.

**Apply it elsewhere:** Draw the dependency arrows first. Parallelize *across* independent branches; serialize *within* a branch in reference order. Your critical path is the longest dependency chain — staff it first and don't let a shorter parallel track's completion fool you into thinking you're done.

### 3. Review → Fix → Independently-Verify pipeline
**When to use:** Any time a subagent reports "done" or "build green" on work you can't see. **When NOT to:** Never skip it on anything that ships — but keep verification proportional; you re-run the build, you don't re-derive the whole review.

**Failure it prevents:** Trusting an unobserved claim. A subagent returns a summary, not a transcript — you didn't watch it work, so "it's green" is a claim, not a fact.

**This session:** Leads returned self-contained summaries; the agent acted as **reducer/synthesizer** over them. Then it *independently verified*: re-ran the frontend build itself (74 modules, passed), and used `git` to confirm each lead stayed inside its own tree AND that the pre-existing `backend/` changes were untouched — i.e., no cross-contamination.

**Apply it elsewhere:** Reviews return summaries; you synthesize the through-line (see pattern 5). Then re-run the objective check *yourself* — build, tests, lint — and use `git status`/`git diff --stat` to confirm scope: did each agent stay in its lane, and did anything leak into files nobody was assigned? The scope check catches what a passing build can't.

### 4. Deterministic detector vs judged score — and triage
**When to use:** Whenever a static tool flags findings. Treat the flag as a *hypothesis*, not a verdict. **When NOT to conflate:** A tool firing is never proof the thing is real; a judged score (an LLM-rated 0–100) is a different instrument with different failure modes. Keep them separate in your head and your report.

**Failure it prevents:** Acting on false positives — burning effort "fixing" things that were already correct, or worse, breaking working code to satisfy a linter.

**This session:** The deterministic `ui-craft-detect` scanner and the judged `heuristic` UsabilityScore were used side by side. The scanner flagged 10 "destructive-action-with-no-confirm" hits; triage found **4 were false positives** (the confirm already lived in the onClick handler) and 6 were genuine. The fix — a `ConfirmProvider` — was applied to the **6 real** ones and *deliberately not* the 4. Same discipline on the site: the detector went 12→11, and the 11 residuals were confirmed false positives because *the detector reads each HTML file in isolation and can't see shared CSS*.

**Apply it elsewhere:** For each detector finding ask: does this reproduce when I look at the actual behavior/context the tool can't see? Fix the confirmed ones; annotate the false positives with *why* (so the next run doesn't re-litigate them). Never let a count of findings become a to-do list without triage first.

### 5. Root-cause over symptom
**When to use:** When many findings share one upstream cause. **When NOT to:** Findings are genuinely independent — then there's no single lever and you fix them individually.

**Failure it prevents:** N patches for one bug, which is a bigger diff *and* leaves every sibling the ticket never named still broken.

**This session:** The app had `outline-none` on ~93 interactive elements and `focus-visible` used **zero** times app-wide. One global `:focus-visible` rule cleared ~93 findings — a far smaller diff than guarding 93 call sites, and it fixed siblings no ticket enumerated. The same defect (no `:focus-visible` anywhere) turned out to span *both* the app and the site — a cross-surface through-line the synthesizer surfaced.

**Apply it elsewhere:** When a report lists many similar findings, grep for the shared upstream cause before writing any patch. One guard in the shared path beats one guard per caller. Bonus: the root-cause fix generalizes to instances the audit missed.

### 6. The subagent prompt as a contract
**When to use:** Every dispatch. The prompt is the *entire* interface — the agent can't ask a clarifying question mid-run and have you notice in time, and **its return text is all you will ever see** of its work.

**Failure it prevents:** An agent that read the wrong source, fought another agent over a shared resource, drifted out of its lane, or returned an unusable blob.

**This session:** Every lead was told to (a) read the ui-craft skill files **by absolute path**, (b) run the detector, (c) capture screenshots in its **own dedicated browser tab** (so two agents don't fight one browser), (d) apply the audit + heuristic lenses, (e) write a report and **return a self-contained summary**. Fix leads additionally got an explicit ownership boundary and ordered stages.

**Reusable contract checklist:**
- [ ] **Ground-truth source**, named by absolute path — not "the design guide," *the file*.
- [ ] **Exact tool-load steps** — which skills to read, which CLI to run, in order.
- [ ] **Ownership boundary** — the files/dirs this agent (and only this agent) may write; may it spawn children, and only on disjoint sets?
- [ ] **Ordered steps** — the sequence, with any internal dependencies called out.
- [ ] **Output format** — what the return must contain to be usable by the reducer.
- [ ] **"Your return text is all I see"** — state it explicitly so the agent front-loads conclusions, not process.

### 7. Commit hygiene / human-gated irreversible acts
**When to use:** Any outward or irreversible action — commit, push, destructive delete. **When NOT to:** Reversible in-tree edits don't need a gate; that's the working tree's whole job.

**Failure it prevents:** Un-revertible mistakes and contaminated history — a feature commit that also swept in unrelated dirty files is a pain to unwind.

**This session:** Fixes were left in the working tree for human review — **no commits** until the user asked. On request, the agent branched off `master` (default-branch safety), made **three per-surface commits** (app / site / docs) for clean revertability, and **deliberately excluded** the pre-existing dirty `backend/` files and the skill tooling / local settings — not part of this task, not its to commit. Then added the required co-author + session trailers and pushed.

**Apply it elsewhere:** Branch before you commit on a default branch. One commit per logical surface, so any one reverts cleanly. Stage *only* the files your task owns — `git add -p` or explicit paths, never `git add -A` over a dirty tree. Keep irreversible acts behind an explicit human ask.

---

## Constraints & Gotchas (each with the fix)

- **`head`/pipe SIGPIPE kills a side-effecting writer.** `npx skills add … | head -60` — `head` closed the pipe, SIGPIPE-killed the installer mid-write, and the command still *looked* successful while the files never landed. **Fix:** never pipe a command that *writes as a side effect* into `head`/`grep`/anything that closes early; run it un-piped and inspect output after. Verify the artifact (the target dir) exists, don't trust the exit appearance.
- **Chrome MCP quirks.** It blocks `file://` (so you can't screenshot a local HTML file directly), renders at a **fixed ~1568px regardless of resize**, **won't persist some screenshot files**, and **dialogs block the session**. **Fix:** serve local output over HTTP before screenshotting; judge narrow-viewport/mobile from source and *say so* (see honest-limitation flagging); give each parallel agent its own tab so they don't collide.
- **`taskkill /F /IM node.exe` has a wide blast radius.** Used to stop a dev server it had started, it killed **every** node process on the machine — including the user's unrelated ones. **Fix:** kill by PID (the one you started), not by image name. Track the PID when you spawn the server.
- **Cross-surface asset coupling.** The site's new hero used **real screenshots of the app UI that the same session had just redesigned** — so the shots were stale the moment they landed. **Fix:** when a redesign touches surface A, flag every other surface that embeds A's rendered output as needing a refresh. Coupling through *assets* is invisible to a per-directory scope check.
- **Verify by rendering real output, not by reading the diff.** For the export HTML, the agent wrote a scratch script that called the *actual* render functions with stub domain objects and a fake async DB (to exercise the async legacy path), served the real HTML over HTTP, and screenshotted light + dark. **Fix:** exercise the flow end-to-end and *observe* it; a diff that reads correct can still render broken.

---

## One-page decision rule: parallel vs serial

> **Parallelize two units of work if and only if their write-sets are disjoint AND neither references an output the other hasn't produced yet. If write-sets overlap → serialize under one owner (or worktree-isolate and merge, only when the parallelism outweighs the merge tax). If one references the other → sequence them, foundational thing first. Everything else runs in parallel, and your critical path is the longest such dependency chain — staff it first.**

Checklist per candidate pair: (1) Do their file/dir write-sets intersect? (2) Does either consume the other's not-yet-built output? (3) Is there a shared external resource (one browser, one dev server, one DB) they'd contend over? Any "yes" pushes toward serialize-or-isolate; all "no" → parallel.
# 501: The Theory Underneath the Session — And Where It Breaks

This is a 501-level reading of one agentic design-overhaul session. The audience designs
agent systems. You already know the vocabulary (subagent, orchestrator, detector) and the
patterns (fan-out, gated dispatch, verify-before-done). The job here is to name the deeper
principle each pattern instantiates, connect it to established theory, and — the part that
actually sharpens judgment — locate the boundary where the principle stops being true. Every
claim is anchored to a specific event in the case file.

---

## 1. Ownership-as-concurrency-control

**Principle.** When the agent decided how to parallelize the fixes, it did not reason about
tasks; it reasoned about *files*. "File/directory ownership dictates the concurrency
boundary." The three surfaces (`frontend/`, `site/`, `docs-site/`) live in disjoint trees, so
three leads ran fully in parallel; inside the app lead, token-consuming edits that shared
component files were forced *sequential*.

**Theory it instantiates.** This is textbook concurrency control, and the session actually
spans both regimes. Directory partitioning is a **coarse-grained pessimistic lock**: acquire
the subtree, exclude all other writers, no conflict is even possible. The case file names the
alternative explicitly — "isolate in a worktree and merge" — which is **optimistic concurrency
control**: let writers proceed independently, detect conflicts at merge time, pay a
reconciliation cost when they collide. The agent's rule that "parallel writers to the SAME
working tree are last-writer-wins corruption, not a merge" is precisely the statement that a
shared mutable filesystem provides *no* transactional isolation — there is no MVCC underneath,
so you must supply isolation yourself, either by locking (partition) or by snapshotting
(worktree).

**Session evidence for the tradeoff being made consciously.** For the overlapping TSX
component files, the agent *considered* worktree-isolate-and-merge and rejected it: the merge
cost on overlapping TSX was judged higher than the throughput lost to serializing. That is the
classic pessimistic-vs-optimistic decision rule — optimism wins only when contention is low.
Here contention was high (tokens, dark-mode, focus all touch the same components), so
pessimism (serialize) was correct.

**The boundary.** Static partitioning assumes coupling is *visible in the directory tree.* It
is not always. The site lead put real screenshots of the app into the hero at the same time
the app lead was redesigning that app. Two disjoint subtrees, zero file collision, clean
parallel run — and yet a genuine data dependency: the screenshots were now of stale UI. This
is a **hidden write-write conflict across an artifact boundary the lock manager cannot see.**
Directory ownership is sound only to the granularity at which semantic coupling aligns with
filesystem structure. When an asset in tree A *depicts* the state of tree B, the tree is the
wrong lock domain.

**Open question.** Can coupling be made a first-class, declarable input to the scheduler —
"site/hero depends-on frontend/ui" as an explicit edge — without the declaration cost
exceeding the value? Coupling you must hand-annotate is coupling you will forget to annotate.

---

## 2. Critical-path / fan-out economics

**Principle.** "The app track was the long pole; site+docs finished sooner." The app lead was
a six-stage sequential pipeline (tokens -> focus -> palette -> confirms -> responsive ->
dark-mode); the other two leads were shallow.

**Theory.** Amdahl's law, and more precisely **critical-path scheduling.** Wall-clock is
bounded below by the *longest dependency chain*, not by total work. Fanning out shortens only
the parallelizable fraction; it cannot compress a serial chain. The app lead's internal
ordering (tokens must exist before anything references them) is an irreducible serial segment,
and no amount of additional agents shortens it. Speedup is capped at `1 / (serial fraction)`;
once site and docs finish, every remaining minute is pure critical path.

**When fanning out is NOT worth it.** Three conditions, all visible in this session's shape:
(a) When the serial fraction dominates — spawning a fourth agent to help the app lead would
have done nothing, because its stages are chained. (b) When per-agent fixed cost (spawn,
context-load, summarize-back) exceeds the work saved — a two-file fix does not amortize a
subagent. (c) When coordination overhead grows super-linearly — every parallel writer you add
raises the probability of the hidden-coupling conflict from §1. The economically correct
degree of fan-out is where marginal wall-clock saved equals marginal coordination cost, and
for a deep pipeline that optimum is *one* worker.

**Open question.** The lead cannot see the critical path *a priori* — it discovers the app is
the long pole only after decomposition. Good scheduling needs a depth estimate before
dispatch, but depth is exactly what is hardest to estimate without doing the work.

---

## 3. Context economy: the lead as a lossy reducer

**Principle.** "Subagents return SUMMARIES, not transcripts. The lead is a
reducer/synthesizer." The dispatch contract stated it bluntly: "your return text is all I
see."

**Theory.** This is **map-reduce** with a hard **information bottleneck** at the reduce step.
Each subagent maps a large private context (screenshots, detector output, file reads) to a
small message; the lead reduces those messages to a decision. The bottleneck is not
incidental — it is *why* the pattern scales (the lead never holds N full transcripts) and
simultaneously *where* it fails (compression is lossy, and the loss is chosen by the
compressor, not the consumer).

**The risk.** Lossy summarization can hide defects. A subagent that reports "build green" has
compressed away everything that would let the lead audit that claim. The session's
counter-move is exactly the anti-bottleneck discipline: "read the journal, don't assume," and
"re-run the build yourself." The lead did *not* trust the leads' green claims — it re-ran the
frontend build (74 modules) and used git to confirm each lead stayed in its subtree. This is
the recognition that a summary is a *claim*, not *evidence*, and that a reducer which cannot
reconstruct the evidence cannot verify the claim.

**The boundary.** You cannot re-derive everything — if you re-ran every subagent's full work
you would have gained nothing from fanning out. So the reduce step is irreducibly a *trust*
decision: verify the cheap, high-leverage claims yourself (build, scope), accept the rest.
The blind spot is any defect that is (a) not surfaced in the summary and (b) too expensive to
independently re-derive. The stale-screenshot risk lived precisely there — no single
subagent's summary contained it, because it was an *emergent* property of two summaries the
lead had to hold at once.

**Open question.** What is the minimal *verifiable* summary — a return format where the key
claims carry cheap, independently-checkable evidence (a build hash, a git diff stat) rather
than an assertion? The session gestures at this with "check scope with git"; it is not yet a
protocol.

---

## 4. Epistemics of verification: two instruments, one oracle problem

**Principle.** The session ran two *different* measuring instruments and refused to blend them.
The deterministic `ui-craft-detect` produced 137 findings, 100 "Critical." The judged
`heuristic` lens produced a 58/F UsabilityScore. These are not two readings of one quantity;
they are non-composable instruments, and the case file's rule is "never conflate 'a tool
flagged it' with 'it's real.'"

**Theory.** This is the **test-oracle problem.** A test needs an oracle — a source of truth
about correct output. The detector is a **high-recall, low-precision candidate generator**: it
flags `destructive-no-confirm` structurally and produced *false positives* (4 of 10 confirms
already lived in the onClick handler; 6 were real). Recall is near-total, precision is poor.
The judged score is a **different oracle entirely** — subjective, holistic, not reducible to a
count of findings. Averaging a precision-poor count with a holistic judgment produces a number
that measures nothing. The correct pipeline is: detector generates candidates (recall) ->
independent adversarial triage filters them (precision) -> falsifiable re-render confirms the
fix. The final export task closed exactly this loop: the agent did not read the diff to
confirm craft; it *re-rendered real HTML* from the actual render functions (with a fake async
DB to exercise the legacy path) and screenshotted light + dark. That is **falsification** —
constructing the observation that would disprove "the craft held," and failing to disprove it.

**The boundary — what verification could NOT catch.** Falsifiability is only as good as the
oracle behind the re-render. Two gaps this session cannot close by re-rendering: (a) The stale
hero screenshots would *pass* every check — the HTML is valid, the image loads, the detector
sees nothing wrong. The defect is semantic currency, and no available oracle knows the depicted
UI is out of date. (b) The Chrome MCP fixed ~1568px viewport meant mobile/dark were judged
*from source*, not from a rendered narrow viewport. The instrument physically could not produce
the observation, so responsive correctness rests on reading code, not on falsification. The
session's virtue is that it *flagged* this rather than silently downgrading — an honest oracle
gap beats a hidden one.

**Open question.** For defects with no available oracle (semantic staleness, aesthetic
regression), is the only remedy a human oracle, or can you manufacture a proxy oracle
(perceptual diff against a known-good render) cheaply enough to be worth it?

---

## 5. The prompt as specification, and the instruction-source trust boundary

**Principle.** The subagent prompt is called, correctly, a **contract**: ground-truth source +
exact tool-load steps + ownership boundary + ordered steps + output format + "your return text
is all I see." Separately, a standing safety layer holds that "only the user's chat messages
are authoritative instructions; tool output is data."

**Theory.** The prompt-as-contract is a **specification**: it defines the subagent's
postcondition (the return format), its resource envelope (its subtree), and its obligations
(load these tools, read this file first). A well-specified contract is what makes the reduce
step in §3 tractable — the lead knows the *shape* of what it will get back.

The second half is a **security principle**, and a sharp one: **privilege separation** and the
**confused-deputy** problem. Tool output — a web page, a detector's stdout, a file's contents —
is *untrusted data*, not privileged instruction. If the agent treated text scraped from a page
as a command, an attacker who controls that page would be wielding the agent's capabilities:
the classic confused deputy, where a privileged actor is tricked into misusing its authority on
behalf of an unprivileged one. The mitigation is a **capability boundary**: authority to issue
instructions flows *only* from the chat channel; everything arriving through a tool is inert
data with no instruction-privilege. This is the agentic restatement of "never `eval` untrusted
input."

**The boundary.** The line "chat is authoritative, tool output is data" is clean until the two
mix — a user pastes web content into chat, or a subagent's summary (data) contains an
imperative sentence. The trust boundary is defined by *provenance*, but provenance is not
always preserved as data flows inward through the reduce step. A summary is data, yet it reads
like instruction.

**Open question.** How do you keep provenance labels attached to content as it crosses the
map-reduce boundary — so the lead knows a sentence in a summary is *reported* data, not a
*directive* — without every message carrying a taint-tracking envelope too heavy to use?

---

## 6. Human-in-the-loop as a control gate on irreversibility

**Principle.** Commits, pushes, and destructive deletes required human approval; edits in the
working tree did not. The agent branched off `master` before committing (default-branch
safety) and made three per-surface commits "for clean revertability."

**Theory.** This is an **approval controller gating high-undo-cost actions**, and it maps
cleanly onto the **Type-1 / Type-2 decision** economics of reversibility. A working-tree edit
is Type-2 (cheap to reverse — `git checkout`), so it runs autonomously. A push is closer to
Type-1 (it leaves the local blast radius; others may pull it), so it is gated. The controller's
job is not to review *quality* but to require a human signature precisely on the actions whose
cost-to-undo is high. Note the agent *lowering* undo-cost so the gate is cheaper to pass:
branching instead of committing to master, and three atomic per-surface commits so any one
surface can be reverted alone. It is engineering reversibility *into* the irreversible step.

**The boundary — reversibility is not always where the approval gate is.** The `taskkill /F /IM
node.exe` was *not* gated — it is a local process action, not an outward one — yet it had a wide
blast radius, killing the user's *other* node processes. The undo-cost model keyed the gate on
"outward/irreversible acts like push," but blast radius and reversibility are different axes: an
ungated local action can be more damaging than a gated commit. The controller guarded the wrong
variable.

**Open question.** Should the approval gate key on *blast radius* (how many entities an action
can affect) rather than, or in addition to, *reversibility* (undo-cost)? `taskkill` is a local
action with global reach; a scoped push is an outward action with local reach.

---

## 7. The laziness–craft dialectic as an optimization objective

**Principle.** "Laziness shortens the SOLUTION, never the COMPREHENSION; craftsmanship is NOT
optional when explicitly requested." The clearest instance: one global `:focus-visible` rule
cleared ~93 findings, a *smaller* diff than guarding 93 call sites — and it fixed sibling
elements the ticket never named.

**Theory.** Minimal-diff-at-root-cause is where the lazy objective and the correct objective
*coincide*, and this is not luck — it is what "root cause" means. A symptom fix scales with the
number of call sites (N guards); a root-cause fix is O(1) at the shared chokepoint. The
minimum-description-length solution and the maximum-correctness solution point at the *same*
edit because both are minimized by locating the single point through which all callers route.
Fixing the shared function is simultaneously the smallest diff and the only fix that catches
the siblings.

**Where they genuinely conflict.** The coincidence is not universal. Craft sometimes demands
work that a pure diff-minimizer would skip: the export-HTML task *refactored a shared document
shell* (`_DOC_STYLE`, `_document`, `_masthead`, `_stat_strip`) — strictly *more* code and a
bigger diff than patching two render functions in place. A lazy objective alone would not build
that abstraction. What resolves the conflict is the case file's own escape clause: **"explicitly
requested."** The user asked for craft ("redesign it using the proper design skills"), which
*changes the objective function* — craft is now part of the spec, not gold-plating. Note the
self-correction that proves the discipline is about comprehension, not diff size: the agent's
first export edit introduced a sloppy `.replace()` hack and a duplicate CSS line, and it *went
back and cleaned it up* so the code would "read honestly" — accepting a larger diff to raise
comprehension. Laziness that lowers comprehension is not the lazy virtue; it is the dangerous
counterfeit.

**Open question.** "Explicitly requested" is a clean switch when the user speaks. What is the
default craft level for work the user *didn't* specify — where does an agent set the objective
between minimal-that-works and maximal-that-delights, absent a request?

---

## Where this playbook fails

Five honest failure modes of the whole approach — the situations in which a designer should
*not* reach for these patterns:

1. **Non-partitionable work.** The playbook's engine is disjoint ownership. Work that is
   irreducibly entangled — a cross-cutting refactor touching every component, a schema change
   rippling through frontend and backend — has no clean partition. Fan-out degrades to
   serialize-everything, and the orchestration overhead becomes pure loss.

2. **Invisible coupling.** Static partitioning is blind to dependencies that don't align with
   the directory tree. The stale hero screenshots are the canonical case: two clean subtrees, a
   real cross-artifact dependency, no lock manager on earth would catch it. The more surfaces
   you parallelize, the more of these latent edges you accumulate unseen.

3. **Lossy-summary blind spots.** The reduce step hides any defect that a subagent didn't
   surface and the lead can't cheaply re-derive — especially *emergent* defects visible only
   when two summaries are held together. Independent verification catches the cheap claims
   (build, scope); it structurally cannot catch what no summary reported.

4. **Verification oracle gaps.** Falsification is only as strong as the available oracle.
   Semantic staleness passes every check; the fixed-viewport instrument couldn't render mobile
   at all. Where no oracle exists, "verified" quietly means "read the code and hoped."

5. **Over-orchestration overhead.** Every subagent costs spawn, context-load, and
   summarize-back. Below a work threshold — a two-file fix, a deep serial pipeline — a single
   worker beats a fleet. The playbook's own economics (§2) say the correct fan-out for a
   critical-path-dominated task is one. Reaching for orchestration by reflex, rather than when
   the parallelizable fraction justifies it, spends coordination cost to buy nothing.

The unifying lesson for designers: each pattern is a *lock on one variable* — ownership locks
files, approval locks irreversibility, the trust boundary locks provenance, verification locks
correctness. Every one of them fails at the boundary where the variable it guards diverges from
the variable that actually matters (semantic coupling, blast radius, provenance-through-reduce,
oracle-availability). Knowing the pattern is 301. Knowing which variable it silently assumes is
the same as the one you care about — that is 501.
---

# Capstone: The Unifying Thesis

Read across all three altitudes, the session's patterns are not a grab-bag. They
are all the same *shape*: **each pattern is a lock that guards exactly one
variable — and each one fails precisely where the variable it guards diverges from
the variable that actually matters.**

| Pattern | Variable it locks | Silently assumes | Breaks when... |
| --- | --- | --- | --- |
| Partition-by-ownership | files / directories | coupling is visible in the tree | an asset in tree A *depicts* tree B (stale hero screenshots) |
| Foundational-first / critical path | dependency order | the long pole is knowable up front | depth is only discoverable after decomposition |
| Context economy (summaries) | context size | the summary carries the defect | a defect is *emergent* across two summaries the lead holds at once |
| Detector vs judged score | finding validity | a flag equals a fact | the tool can't see the context (confirm-in-onClick; shared CSS) |
| Prompt-as-contract / trust boundary | provenance | data stays labeled as data | a summary (data) reads like a directive after the reduce step |
| Human-in-the-loop gate | undo-cost (reversibility) | blast radius tracks reversibility | a local, ungated action has global reach (`taskkill /F /IM node.exe`) |
| Laziness ↔ craft | diff size ↔ comprehension | minimal == correct | craft requires *more* code (the refactored shell) — resolved by "explicitly requested" |

**Knowing the pattern is 301. Knowing which variable it silently assumes is the
same as the one you care about — that is 501.**

---

## One lesson, three altitudes

| Lesson | 101 (rule) | 301 (play) | 501 (principle) |
| --- | --- | --- | --- |
| Don't trust claims | "'No error' isn't 'it worked' — check the result" | Review → Fix → **Independently-Verify** | The test-oracle problem; summary is a *claim*, not *evidence* |
| Fix once, at the source | "Fix the root cause, not every symptom" | Root-cause over symptom | MDL == max-correctness at the shared chokepoint |
| Who runs at once | *(deferred up)* | Partition-by-ownership + parallel-vs-serial rule | Ownership as a coarse pessimistic lock; worktrees as optimistic concurrency |
| Say what you couldn't check | "Flag limits, don't hide them" | Honest-limitation flagging in the report | Oracle gaps: "verified" can quietly mean "read the code and hoped" |
| Let a human decide the risky move | "Let the human commit" | Commit hygiene / human-gated acts | Approval controller on Type-1 (high-undo-cost) actions |

---

## The pocket cheat-sheet

**Parallel-vs-serial, in one line.** Parallelize two units *iff* their write-sets
are disjoint **and** neither consumes an output the other hasn't produced yet.
Overlap → serialize under one owner (or worktree-isolate + merge, only when the
parallelism outweighs the merge tax). Reference dependency → sequence,
foundational thing first. Your critical path is the longest dependency chain —
staff it first.

**The subagent-prompt contract (6 items).**
1. Ground-truth source, by **absolute path** — the file, not "the guide."
2. Exact tool-load steps — which skills/CLIs, in order.
3. Ownership boundary — the files it (and only it) may write; may it spawn children, on disjoint sets only.
4. Ordered steps — with internal dependencies called out.
5. Output format — what the return must contain to be usable by the reducer.
6. "Your return text is all I see" — so it front-loads conclusions, not process.

**Constraints catalog (each with its fix).**
- **Pipe into `head`/`grep` can SIGPIPE-kill a side-effecting writer.** → Never pipe a command that *writes* into something that closes early; run un-piped, then verify the artifact exists.
- **Browser automation quirks** (blocks `file://`; fixed viewport; won't persist some screenshots; dialogs block). → Serve local output over HTTP; judge narrow viewports from source and *say so*; one tab per parallel agent.
- **`taskkill /F /IM node.exe` kills *every* node process.** → Kill by the PID you started, not by image name.
- **Cross-surface asset coupling.** → When a redesign touches surface A, flag every other surface that embeds A's rendered output; per-directory scope checks can't see it.
- **Verify by rendering real output, not by reading the diff.** → Exercise the flow end-to-end (real functions, stub data) and *observe* it.
- **Commit hygiene.** → Branch off the default branch; one commit per logical surface; stage only files your task owns; never `git add -A` over a pre-existing dirty tree.

---

## Professor's QC note (transparency)

What I checked before shipping this: (1) **fabrication** — every number is traceable
to the case file; the aides invented nothing. (2) **Level-bleed** — 101 stays
foundational and points up; 301 stays practical; 501 stays principled and doesn't
re-teach the plays. (3) **Coverage** — the highest-value ideas (ownership-as-
concurrency-boundary, the SIGPIPE install failure, detector-vs-judged triage, the
root-cause focus fix) each land at the altitude that fits them. What I'd still
watch: the economics tier (critical path, fan-out cost) is argued *structurally*
because the case file carried no wall-clock timings — treat those claims as
directional, not measured.
