# Prompting 301 - The Operator's Plays

*Applied practice for the human who drives an agentic coding assistant. This tier
takes the twelve operator moves from [prompting-teardown.md](prompting-teardown.md)
and sharpens them into named PLAYS you can lift onto your own work. You already
own the 101 vocabulary - frame vs fill, delegation, gate, effort - so we skip
straight to technique.*

The whole craft compresses to one sentence: **specify the frame, delegate the
fill.** Say only what you alone can decide; hand the model everything it would do
well unprompted. Every play below is that sentence applied to a different lever.

---

## The plays

Each play: when to use, when NOT to, the failure it prevents, the session moment
(quoting the operator), and how to lift it elsewhere.

### Play 0 - Recon, ground, then give the why

**Use when** you are about to assign real work and haven't confirmed the model's
toolset or fed it fresh ground truth. **Don't when** you have already grounded it
this session - re-probing wastes a turn. **Prevents** delegating to a capability
that isn't there, and instructions built on the model's stale priors instead of
the actual source. **Session:** the operator opened with *"do you have a good
design skill?"* (a probe, not a command), then *"install [ui-craft], then read
[the docs] so we can figure out the smart things this app can do"* - external
ground truth plus the intent behind it. **Elsewhere:** ask what the model *has*
before you tell it what to do; point at the file/URL/tool by name; and attach the
*why* ("this feeds a 301 course, the audience is practitioners") to every ask.
Intent is the cheapest quality lever you own.

### Play 1 - Specify structure, delegate content

**Use when** you care how the work is orchestrated - parallel jobs, recursive
sub-agents, a pipeline shape. **Don't when** you find yourself dictating the
*findings* - the moment you pre-write the answer you've stopped delegating.
**Prevents** a monolithic single-threaded grind when the work wanted fan-out, and
a scripted-to-death prompt that suppresses the model's judgment. **Session:**
*"two design review jobs... complete each with subagents, and if those subagents
need to spawn their own, enable that."* He set the execution shape and left the
analysis entirely open. **Elsewhere:** state the orchestration (how many workers,
who may spawn children) as constraints; never state the conclusions. Dictate the
container, not the contents.

### Play 2 - Name the axis, delegate the call

**Use when** there's a real tradeoff (scheduling, batching, ordering) but the
right choice is case-by-case and the model is closer to the cases than you are.
**Don't when** the axis has a fixed correct answer you already know - then just
say it. **Prevents** both over-specifying ("run these three in parallel" when two
of them collide) and under-specifying (no guidance, so it never considers
serializing at all). **Session:** *"gate them parallel/sequential where needed
when needed"* - he named the dimension (scheduling) and handed over the per-case
judgment. **Elsewhere:** identify the dial that matters, then say "you decide, on
this axis." You supply the axis; the model supplies the reading.

### Play 3 - Checkpoint gating

**Use when** a long fan-out needs to run unattended and resume deterministically.
**Don't when** the condition is vague ("when it's ready") - a checkpoint with no
stated trigger is just hope. **Prevents** babysitting a multi-minute run, and the
opposite failure of the model charging past a synchronization point into work
that depended on results not yet in. **Session:** *"once all the reviews are back,
proceed."* One conditional trigger let the whole review fan-out run without a
human watching. **Elsewhere:** gate multi-step work on a *stated, checkable*
condition ("once the tests pass," "after all three summaries return"). That is how
you delegate *duration* - the span between checkpoints - without hovering.

### Play 4 - Role plus process plus self-review, in one prompt

**Use when** you want a disciplined pipeline out of a single turn, not a one-shot
answer. **Don't when** the task is trivial - a role-and-QC frame is overhead on a
two-line fix. **Prevents** an eager unreviewed dump: work that was never dispatched
cleanly and never checked before it reached you. **Session:** *"act as if you are
a professor... work with your lead student aids... review for quality control and
revisions."* One instruction carried a role (professor), a method (dispatch aides,
synthesize), and a self-check (QC before shipping). **Elsewhere:** bundle
who-you-are + how-you-work + check-your-own-work in the same prompt. The role sets
standards, the method sets structure, the self-review catches the model's own
misses before you have to.

### Play 5 - Name the quality bar AND invoke the skill by name

**Use when** you want craft, and a real skill for it exists. **Don't when** no such
skill is installed - then "use the skill" points at nothing (see gotchas).
**Prevents** two distinct failures: shipping a minimal version because "good
enough" was never contradicted, and the model *paraphrasing* a skill from memory
instead of loading its actual steps. **Session:** *"add some craftsmanship to
this... use the proper design skills"* - two moves fused. "Craftsmanship" put
quality in the spec; "the proper skills" made the model *load* the design skill
rather than wing it. **Elsewhere:** if you want craft, say "craft" so it enters the
objective function - and if a skill exists, tell the model to *invoke* it, not
recall it. A named skill loaded is steps and rules you'd otherwise lose.

### Play 6 - Push effort down to the delegates

**Use when** you raise the reasoning budget on work that will fan out to
sub-agents. **Don't when** the delegated work is mechanical - maxing effort on a
find-and-replace burns budget for nothing (see the Fable 5 note). **Prevents** the
sharpest, quietest failure in this whole tier: **effort does not flow downhill.**
You set a high budget on the orchestrator, it spawns children at the *default*, and
your "deep" analysis was actually done shallow by the workers who did the looking.
**Session:** *"ultrathink... and ultrathink for the subagents too as I want them
using max effort."* He raised the dial *and explicitly propagated it*.
**Elsewhere:** whenever you set effort and then delegate, state the effort for the
delegates too, in the same breath. Assume nothing inherits.

### Play 7 - Human-gate the irreversible

**Use when** an action is outward-facing or hard to undo - commit, push,
destructive delete, anything that leaves the local blast radius. **Don't when** the
work is a reversible in-tree edit; gating those defeats the working tree's purpose
and turns you into a bottleneck. **Prevents** un-revertible mistakes and
contaminated history - a push you can't take back, a commit that swept in unrelated
files. **Session:** fixes sat in the working tree for review; *"commit and push"*
came only after he'd seen the result. **Elsewhere:** let reversible work run
autonomously - that's the whole point of delegation - and hold the outward,
hard-to-undo step behind an explicit human word. Trust the model to do the work;
keep the irreversible act behind your "go."

### Play 8 - Escalate incrementally; use output as scaffolding

**Use when** the end state is fuzzy or large and each step's result would sharpen
the next ask. **Don't when** you already have a crisp, complete spec - then
front-loading it is faster than a slow climb. **Prevents** the monolith failure: a
giant up-front spec that locks in wrong assumptions before you've seen a single
result. **Session:** review -> fix -> commit -> export redesign -> teach it
(101/301/501) -> 701 -> reframe. Each turn stood on the last turn's output; he
never front-loaded a giant plan, he *climbed*. **Elsewhere:** disclose
progressively. Let the model's own output become the substrate for your next
instruction - you steer with far more information at turn five than you had at turn
one, so spend the cheap early turns buying that information.

### Play 9 - Fork, don't regenerate

**Use when** you have good substrate and want a *different cut* of it - a reframe,
a re-lens, a new audience. **Don't when** the substrate doesn't actually exist yet,
or is wrong at the root - forking bad ground just propagates the flaw (see
gotchas). **Prevents** paying full price to rebuild work you already have.
**Session:** this very lesson - *"create a branch... that changes the framing"* -
re-lensed an existing teardown rather than re-running it from scratch.
**Elsewhere:** when the bones are good and only the angle should change, branch and
reframe. Regeneration is for when the substrate itself is wrong.

---

## One-page decision heuristic: specify the frame, delegate the fill

Every play is the same split. The operator sets the left column and never the
right:

| You always SET (the frame) | You always DELEGATE (the fill) |
| --- | --- |
| the structure - parallel/recursive workers | the content - the actual findings |
| the axis to optimize (parallel-vs-serial) | the per-case call along it |
| the checkpoint condition ("once reviews are back") | the work between checkpoints |
| the role + method + self-check | how the pipeline executes |
| the quality bar ("craftsmanship") + which skill | how the craft is reached |
| the effort - and that it propagates to delegates | where the budget gets spent |
| the human gate on irreversible acts | everything reversible before it |
| the intent (the *why*) | how the model connects task to purpose |

**How much to frame - find the seam.** Over-framing (scripting every step, dictating
the answer) wastes the model's judgment and, on newer models, actively lowers output
quality. Under-framing (no axis, no checkpoint, no ownership boundary) courts
ambiguity and drift. The seam: **frame the decisions only you can make - intent,
irreversibility, the tradeoff axes, the quality bar - and delegate every decision
the model is equally or better placed to make.** If you're typing something the model
would have done right unprompted, delete it. If you're leaving out something only you
know (which surfaces matter, what "done" means, what must not be touched), add it.

---

## Operator gotchas

- **Effort does not propagate.** Setting a high budget on the orchestrator does not
  raise it for the sub-agents it spawns; they start at the default. Say "ultrathink
  for the subagents too" or your deep pass was done shallow by the workers.
- **A named skill must be invoked, not recalled.** "Use good design sense" gets you
  the model's memory of design. "Invoke the ui-craft skill" gets you the skill's
  actual loaded steps. Name it so it *loads*.
- **A checkpoint needs a stated condition.** "When it's ready" is not a gate. "Once
  all three reviews return" is. A trigger the model can't test is one it will guess
  at.
- **Forking needs the substrate to actually exist.** Re-lensing assumes there is good
  ground to re-lens. Confirm the substrate is there and sound before you branch off
  it - forking a draft that was never written just regenerates with extra steps.

---

## Fable 5 practice note

Run these plays on `claude-fable-5` and the technique shifts in four concrete ways.
The instinct that made them work on Opus 4.8 is, on Fable 5, close to the prescribed
style - so lean in harder:

- **De-prescribe further (Plays 1, 2).** Fable 5 guidance is explicit that prompts
  written for older models are *too prescriptive* and lose quality. State the goal
  and constraints; do not enumerate steps. If you still carry step-by-step
  scaffolding from a prior model, strip it and A/B the result.
- **Delegate asynchronously (Plays 1, 3).** Async sub-agents beat spawn-and-block:
  long-lived agents keep their own context and the orchestrator never bottlenecks on
  the slowest one. "Enable the subagents to spawn their own" becomes "delegate
  independent subtasks, keep working, intervene only if one drifts."
- **Tune effort per phase, don't max everywhere (Play 6).** Effort is
  `output_config.effort` (low/medium/high/xhigh/max). Use low/medium for mechanical
  work (the find-and-replace fixes) and high/xhigh for hard reasoning (the analysis,
  the synthesis). The fan-out already lets you set effort per stage - "ultrathink
  everywhere" is the blunt version of a dial you can now aim.
- **Audit progress claims against tool results.** Fable 5 will happily work
  unattended for many minutes; make "point to evidence (a build result, a git stat)
  for every claim of done" an explicit line. Play 4's QC gave you this for free by
  asking for it; on Fable 5, require it in writing - it nearly eliminates fabricated
  status on long runs.

*Why these hold and where they break - async coordination limits, effort economics,
the verification-oracle problem - is 501/701 material; this tier just runs the plays.*

---

## The one line

**Specify the frame, delegate the fill, gate the irreversible, give the why - and
push the effort downhill yourself, because it won't go on its own.**
