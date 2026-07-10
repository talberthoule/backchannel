# Prompting 101 — Foundations of Driving the Model

*Companion to [prompting-teardown.md](prompting-teardown.md), pitched for beginners. That
teardown reads one real working session as twelve "operator moves." This lesson distills the
most foundational ones into a handful of habits you can use on your very first day driving an
agentic coding assistant. The focus is not on what the model did well — it's on what the
**person** said, and in what order, to steer it.*

You do not need to code to follow along. Every example is a real thing the operator typed.

---

## The five words you need first

An **agent** is the AI assistant doing the work. You are the **operator** — the human deciding
what it works on and when. Your whole job comes down to five ideas:

- **Frame vs. fill.** The **frame** is the part only *you* can decide: what the work is for,
  which sources are trustworthy, how good it has to be, what must not happen. The **fill** is
  the actual work — the analysis, the code, the findings — which the agent produces once the
  frame is set. The one habit under everything below: *set the frame, delegate the fill.*
- **Delegation.** Handing a chunk of work to the agent (or to its helper **subagents**) and
  letting it run, instead of dictating every step.
- **Checkpoint / gate.** A stated condition that says "stop here until X is true" — a way to
  hand off a long job without watching it the whole time.
- **Effort keyword.** A word like *ultrathink* that tells the agent how hard to think before
  answering. You turn the dial up for hard work, down for mechanical work.
- **The human gate.** Irreversible acts — saving changes permanently, publishing them,
  deleting things — wait for your explicit "go." Everything easy to undo can run on its own.

---

## The beginner-safe operator loop

Six steps, in order. Master these and you are already driving well.

1. **Probe first.** Ask what the tool can already do before you tell it what to do.
2. **Point it at real sources.** Name the file, URL, or tool it should read — don't lean on
   what it "already knows."
3. **Say what the output is for.** Give the purpose, not just the task.
4. **Name the quality bar.** If you want craft, say "craft"; if a skill exists, tell it to use
   the skill.
5. **Escalate one step at a time.** Let each result inform your next ask instead of front-
   loading one giant instruction.
6. **Keep the irreversible step behind your "go."** Let reversible work run; gate commits,
   pushes, and deletes on a human word.

---

## 8 prompting rules of thumb

Each rule: what it is, why it works, how to do it, and the exact moment in the session it came
from.

**1. Probe before you delegate.**
Why: you can't hand work to a capability you haven't confirmed exists. How: ask "what do you
have for this?" before issuing the first command. *Session moment:* he opened with *"do you
have a good design skill?"* — a question, not an order — and mapped the toolset before
assigning anything.

**2. Point at the source; don't trust its memory.**
Why: a named source is ground truth the model actually read; its priors are guesses. How: give
the file, URL, or tool by name. *Session moment:* *"install [ui-craft], then read [the docs] so
we can figure out..."* — every later instruction stood on something it had really read.

**3. Say the *why*, not just the *what*.**
Why: intent is the cheapest quality lever you have — it lets the model connect the task to the
right context instead of guessing. How: state what the output is *for*. *Session moment:* he
framed the work as building *"101/301/501 courses"*, so the model knew the audience and aimed
at it.

**4. Specify the structure, delegate the content.**
Why: dictate the shape you care about, and the findings improve when the model owns them. How:
prescribe *how* the work runs; never prescribe the answer. *Session moment:* *"two design
review jobs... complete each with subagents, and if those subagents need to spawn their own,
enable that"* — he set the execution shape and left every finding to the model.

**5. If a skill exists, tell it to use the skill — don't ask it to remember.**
Why: a skill carries steps and rules the model will otherwise wing from memory and get wrong.
How: name the bar *and* name the tool. *Session moment:* *"add some craftsmanship to this...
use the proper design skills"* — "craftsmanship" put quality in the spec, and "the proper
skills" made it load the design skill instead of paraphrasing it.

**6. Set the effort dial — and push it down to the helpers.**
Why: reasoning depth is something you choose, and helpers don't inherit it automatically. How:
raise effort explicitly, and say it applies to subagents too. *Session moment:* *"ultrathink...
and ultrathink for the subagents too as I want them using max effort."*

**7. Gate long work on a stated condition.**
Why: a checkpoint lets a long, fanned-out job run unattended and resume predictably — you
delegate *duration* without babysitting. How: state the trigger that says "now proceed."
*Session moment:* *"once all the reviews are back, proceed."*

**8. Let reversible work run; gate the irreversible.**
Why: edits sitting in working files are cheap to undo; a publish reaches the outside world and
isn't. How: trust the model on reversible work, hold the outward step for your word. *Session
moment:* fixes sat unsaved for review, and *"commit and push"* came only after he'd seen the
result.

---

## A small worked example: labeling frame vs. fill

Take one real exchange — the design review dispatch:

> *"two design review jobs... complete each with subagents, and if those subagents need to
> spawn their own, enable that. gate them parallel/sequential where needed when needed. once
> all the reviews are back, proceed."*

Watch how much of this is **frame** (the operator's job) and how little is **fill** (handed
off):

| The **frame** he set | The **fill** he delegated |
| --- | --- |
| *how many* jobs — two | *what* each review actually found |
| *who* does them — subagents, allowed to spawn their own | *which* screens and issues to flag |
| *the axis to optimize* — parallel vs. sequential scheduling | *when* to serialize each specific case |
| *the checkpoint* — "once all the reviews are back" | all the work between now and that checkpoint |

He spent every word on things only he could decide — the count, the helpers, the scheduling
axis, the stop condition — and zero words telling the model what the reviews should say. The
reviews came back scored (one screen got 58/100, an F; a page got 73, a C), and *nobody
changed a line until they were in.* That is the whole technique in one exchange: **say what
only you can decide; delegate the rest.**

---

## Mini glossary

- **Agent:** the AI assistant doing the work.
- **Operator:** you — the human steering it.
- **Subagent:** a helper the agent hands a chunk of work to; it returns a short written summary.
- **Skill:** a loadable bundle of instructions and rules the agent can follow (this session
  used one called `ui-craft`).
- **Frame:** the part only you can decide — purpose, sources, quality bar, what's off-limits.
- **Fill:** the actual work the agent produces once the frame is set.
- **Checkpoint / gate:** a stated condition that pauses work until it's met.
- **Effort keyword:** a word (e.g. *ultrathink*) that sets how hard the model thinks.
- **Commit / push:** save changes permanently / publish them — treat as irreversible, so a
  human approves.

---

## One line about newer models

Newer models like **Claude Fable 5** reward this style even more: say the goal and the
constraints and let the model fill in the steps, rather than scripting each step yourself.

*One step beyond 101:* this session also decided *which* helpers could safely run at the same
time, tuned effort per phase, and treated its instructions to subagents as a strict contract.
That's real — but it's **301/501/701 material**, and you'll meet it once these fundamentals are
second nature.
