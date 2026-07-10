# Driving the Model — A Prompt-Craft Teardown

*The same session as [session-teardown.md](session-teardown.md), read through a different
lens. That teardown asked "what did the model do well?" This one asks the operator's
question: **what did the human say, and in what order, to get there?** The subject is not
the agent's competence — it's the person's prompting and interaction technique.*

The session ran on **Opus 4.8 (1M context)**. A closing section covers what changes if you
run this same playbook on **Claude Fable 5**.

---

## The operator's moves

Each move: what the user actually did → why it worked → the reusable rule.

### Framing the work

**1. Recon before delegation.**
Opened with *"do you have a good design skill?"* — a capability probe, not a command. He
mapped the toolset before assigning work, so the first real instruction landed on ground he
knew existed. **Rule:** ask what the model *has* before telling it what to do; you can't
delegate to a capability you haven't confirmed.

**2. Ground the model in fresh, authoritative sources.**
*"install [ui-craft], then read [the docs] so we can figure out..."* — he supplied external
ground truth instead of trusting the model's priors. Every later instruction stood on a
source the model had actually read. **Rule:** point at the file/URL/tool; don't rely on
what the model already "knows."

**3. Give the *why*, not just the *what*.**
The professor framing, *"so we can figure out the smart things this app can do,"* the
audience ("101/301/501 courses") — each request carried its intent. The model connected the
task to the right context instead of guessing at purpose. **Rule:** state what the output is
*for*; intent is the cheapest quality lever you have.

### Delegating well

**4. Specify the *structure*, delegate the *content*.**
*"two design review jobs... complete each with subagents, and if those subagents need to
spawn their own, enable that."* He prescribed the **execution shape** (parallel jobs,
recursive delegation) and left the actual analysis entirely to the model. **Rule:** dictate
the orchestration when you care about it; never dictate the findings.

**5. Name the axis, delegate the call.**
*"gate them parallel/sequential where needed when needed."* He named the dimension to
optimize — scheduling — and handed the model the judgment of *when* to serialize. He didn't
say "run these three in parallel"; he said "you decide, on this axis." **Rule:** name the
tradeoff; let the model make the per-case decision inside it.

**6. Set an explicit checkpoint.**
*"once all the reviews are back, proceed."* A conditional trigger that let a long fan-out
run unattended and resume deterministically. **Rule:** gate multi-step work on a stated
condition; it's how you delegate *duration* without babysitting.

**7. Assign role + process + self-review in one prompt.**
*"act as if you are a professor... work with your lead student aids... review for quality
control and revisions."* One instruction carried a **role** (professor), a **method**
(dispatch aides, synthesize), and a **self-check** (QC the aides before shipping). **Rule:**
bundle who-you-are, how-you-work, and check-your-own-work; you get a disciplined pipeline
from a single turn.

### Controlling quality and effort

**8. Name the quality bar — and invoke the method by name.**
*"add some craftsmanship to this... use the proper design skills."* Two moves in one:
naming the bar ("craftsmanship") put quality *in the spec* so the model didn't ship a
minimal version; naming "the proper skills" made it actually **load** the design skill
rather than wing it from memory. **Rule:** if you want craft, say "craft" — and if a skill
exists, tell it to invoke the skill, not recall it.

**9. Effort keywords — pushed down to the delegates.**
*"ultrathink... and ultrathink for the subagents too as I want them using max effort."* He
raised the reasoning budget explicitly and — crucially — **propagated it to delegated
work**, which doesn't inherit it automatically. **Rule:** effort is a dial you set, and it
doesn't flow downhill to subagents unless you say so.

### Controlling risk and momentum

**10. Hold irreversible acts at a human gate.**
Fixes were reviewed while sitting in the working tree; *"commit and push"* came only after
he'd seen the result. Trust the model to do the work; keep the outward, hard-to-undo step
behind your own "go." **Rule:** let reversible work run autonomously; gate the irreversible
on a human word.

**11. Escalate incrementally; use the model's output as scaffolding.**
review → fix → commit → export redesign → teach it (101/301/501) → 701 → reframe. Each turn
stood on the last turn's output. He never front-loaded a giant spec; he **climbed**, letting
each result inform the next ask. **Rule:** progressive disclosure beats a monolith — the
model's own output is the substrate for your next instruction.

**12. Fork, don't regenerate.**
This very turn: *"create a branch... that changes the framing."* Rather than re-running the
teardown from scratch, he asked to **re-lens existing work**. **Rule:** when you have good
substrate and want a different cut, reframe it — don't pay to regenerate.

---

## What every move has in common

One pattern runs through all twelve: **the operator specified the *frame* and delegated the
*fill*.**

| He always set... | He always delegated... |
| --- | --- |
| the structure (parallel/recursive subagents) | the content (the findings) |
| the axis (parallel-vs-serial) | the per-case call |
| the checkpoint ("once reviews are back") | the work between checkpoints |
| the role + method + self-check | the execution |
| the quality bar ("craftsmanship") | how to reach it |
| the effort ("ultrathink") | where to spend it |
| the gate (human "commit and push") | everything reversible before it |

He steered with **constraints, checkpoints, and intent** — not step-by-step scripts — and
spent zero keystrokes on anything the model would do well unprompted. That is the whole
technique: **say what only you can decide; delegate the rest.**

---

## Running this playbook on Claude Fable 5

This session used Opus 4.8. If you run the same operator moves on **Claude Fable 5**
(`claude-fable-5` — Anthropic's most capable widely released model, built for the most
demanding reasoning and long-horizon agentic work), the striking thing is that these habits
aren't merely *compatible* with Fable 5 — they are close to what Anthropic's own Fable 5
guidance tells you to do. The operator got there by instinct; on Fable 5 it's the
prescribed style.

- **De-prescribe — which he already did (moves 4, 5).** Fable 5 guidance is explicit:
  *prompts written for prior models are often too prescriptive and reduce output quality.*
  State the goal and constraints; don't enumerate steps. His "specify the structure, delegate
  the content" is exactly this. On a prior model you might have scripted the steps; on Fable 5,
  don't — and A/B-test with old scaffolding removed.

- **Give the reason (move 3).** Fable 5 *connects the task to relevant information rather
  than inferring intent on its own* — so the "why" he attached to every request matters even
  more. Lead long-running agents with *"I'm doing X for Y; they need Z; with that in mind…"*

- **Let it delegate — asynchronously (move 4).** On Fable 5, parallel sub-agents are
  dependable, and **async delegation outperforms spawn-and-block** (long-lived agents keep
  their context; the orchestrator isn't bottlenecked on the slowest one). His "let the
  subagents spawn their own" becomes the sharper *"delegate independent subtasks and keep
  working; intervene only if one goes off track."*

- **Effort is a dial to *tune*, not a constant to max (move 9).** Fable 5's thinking is
  always on; you control depth with `output_config.effort` (`low`/`medium`/`high`/`xhigh`/
  `max`). Guidance: **start around `high` and sweep** — lower effort on Fable 5 often beats a
  prior model's `xhigh`, and higher isn't monotonically better. The upgrade to his single
  "ultrathink" is *per-phase* effort: `low`/`medium` for the mechanical fixes, `high`/`xhigh`
  for the 501/701 reasoning — the fan-out patterns already let you set effort per stage.

- **Plan for long turns behind your gates (moves 6, 10).** Single Fable 5 requests on hard
  tasks can run **many minutes**; structure the work as async check-ins rather than blocking
  calls. His checkpoints and human gates ("once reviews are back," "commit and push") aren't
  just tidy here — on Fable 5 they're how you stay in control of a model that will happily
  work for fifteen minutes unattended.

- **Ground progress claims (came free from move 7's QC).** Fable 5 guidance recommends
  requiring the model to **audit each progress claim against a tool result** (it nearly
  eliminates fabricated status on long runs). He got verification by *asking for QC*; on
  Fable 5, make "point to evidence for every claim" an explicit line in the prompt.

**One caveat to wire in before productionizing.** Fable 5 runs safety classifiers and can
return a `refusal` stop reason (HTTP 200, empty or partial content) on benign-but-adjacent
security/bio-flavored requests. For an autonomous fleet, opt into a server-side fallback to
Opus 4.8 (`fallbacks: [{"model": "claude-opus-4-8"}]` + the `server-side-fallback-2026-06-01`
beta) so a false-positive decline is re-served instead of silently stopping. Not exercised in
this session; relevant the moment this playbook drives unattended Fable 5 runs.

---

## The one line

**Specify the frame, delegate the fill, gate the irreversible, and give the *why* — the
model supplies the rest.** On Fable 5, that isn't just good operating; it's the manual.
