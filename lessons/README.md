# Lessons — teaching teardowns of real agentic coding sessions

This folder distills real Claude Code working sessions into course-style lessons. Two
**sessions** are covered, each read through two **lenses**, each lens laddered across course
levels (101 foundations -> 301 patterns/plays -> 501 judgment/theory -> 701 abstract theory).

## The two sessions

- **Design-review / ui-craft session** (files with **no prefix**). A session that installed a
  design-review skill system, ran two automated design reviews via background subagents, fixed
  findings across four surfaces, and redesigned an exported HTML document for craft.
- **Product-showcase session** (files prefixed **`showcase-`**). A multi-day session that
  installed a screenshot skill, seeded privacy-safe demo data, built a redesign-surviving
  capture pipeline, captured an unrepeatable live event, and curated assets for a downstream
  agent.

## The two lenses

- **Agent-behavior lens** — *what the model did well.* Combined teardown across altitudes.
- **Operator / prompt-craft lens** — *what the human said, and in what order, to get there.*
  A combined teardown plus a 101/301/501/701 ladder.

## File map

| Session | Lens | File(s) |
| --- | --- | --- |
| Design-review | Agent | [`session-teardown.md`](session-teardown.md) |
| Design-review | Operator | [`prompting-teardown.md`](prompting-teardown.md) (overview) + [`prompting-101-foundations.md`](prompting-101-foundations.md) / [`-301-practice.md`](prompting-301-practice.md) / [`-501-theory.md`](prompting-501-theory.md) / [`-701-abstract.md`](prompting-701-abstract.md) |
| Product-showcase | Agent | [`showcase-session-teardown.md`](showcase-session-teardown.md) (synthesis + 101/301/501/701) |
| Product-showcase | Operator | [`showcase-prompting-teardown.md`](showcase-prompting-teardown.md) (overview) + [`showcase-prompting-101-foundations.md`](showcase-prompting-101-foundations.md) / [`-301-practice.md`](showcase-prompting-301-practice.md) / [`-501-theory.md`](showcase-prompting-501-theory.md) / [`-701-abstract.md`](showcase-prompting-701-abstract.md) |

## Why two sessions of the same curriculum

The operator principles (specify the frame, delegate the fill; effort does not inherit;
gate the irreversible; escalate in rungs) recur across both sessions with *different evidence*.
Reading the two side by side separates the transferable principle from the incidental detail:
if a move shows up in a design review and in a screenshot pipeline, it is the technique, not
the task. The showcase session additionally surfaces moves the design session did not stress —
the "safe to use" verify-or-comply probe, just-in-time constraint injection under real
data-privacy risk, and operating during a live leak at an unrepeatable event.

## A note on models

Both sessions ran on **Opus 4.8 (1M context)**. Each operator-lens file closes with what
changes when the same playbook runs on **Claude Fable 5** (de-prescribe further, delegate
asynchronously, tune effort per phase rather than maxing it, and require evidence for progress
claims on long unattended runs).
