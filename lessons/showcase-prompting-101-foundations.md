# 101 — Prompting Habits: how to steer an agent to get what you want

*User-interaction framing, level 101: concrete, imperative habits. Do this; not that.
Derived from the Jun-2026 showcase session. Companion to `showcase-prompting-teardown.md`.*

These are the moves you can copy tomorrow without understanding why they work. The 301 file
names them; the 501 file argues when to break them; the 701 file proves what they are. Here,
just the habits.

## Habit 1 — State your conclusion AND hand over the raw data
Don't only say "this file is safe to use." Say it *and* give the agent the file. The claim
tells the agent your belief; the data lets it check you. If you withhold the data, a wrong
belief becomes a silent action.
- DO: "This recording is safe — internal, two coworkers. Here's the file."
- DON'T: "This is safe, go ahead and use it" with no way for the agent to verify.

## Habit 2 — Drop constraints when they become relevant
You don't need a requirements doc up front. State each constraint at the moment the work
reaches it. It keeps the agent's attention on what matters now and lets you see its default
before you correct it.
- DO: "Some of these screenshots have customer data — work around those" *as* you hand over
  the screenshots.
- BUT: restate a load-bearing constraint again at the risky moment. "Don't export from that
  session" said once, an hour ago, is easy to lose.

## Habit 3 — Name the tool, let the agent learn it
For anything discoverable (a documented API, an installed CLI, a sibling session), name it
and stop. Don't teach it.
- DO: "Look at the herdr API to learn how to read these elements."
- DON'T: paste three paragraphs explaining herdr. You'll be wrong about what it needs and
  slow to boot.
- EXCEPTION: if it's genuinely undocumented or hidden, teach it — the agent can't discover
  what isn't discoverable.

## Habit 4 — Say the effort level out loud, and say it covers subagents
Agents default to the cheapest answer that clears the bar. If you want maximum effort, name
it — and if the work fans out to subagents, say the effort applies to *them* too. They
inherit nothing unless you say so.
- DO: "Ultrathink on this. And ultrathink for the subagents too — I want max effort."
- DON'T: assume "be thorough" reaches the delegated tier.

## Habit 5 — End directives with an open door
Close a non-trivial instruction with "any questions?" It's a cheap interrupt that surfaces a
wrong assumption before the agent spends a turn on it.
- DO: "...take the new screenshots. Any questions?"
- THEN: actually treat the questions as useful, not as friction.

## Habit 6 — Ask for depth in rungs, not all at once
Don't open with "give me the deepest possible analysis." Ask for the shallow level first,
then build on it: 101, then 301, then 501, then 701. Each level gives the next something to
stand on.
- DO: "Break this into 101/301/501." Later: "Now what would a 701 say?"
- DON'T: "Write me the PhD-level version" cold — it has nothing to abstract from.

## Habit 7 — Reframe existing work instead of commissioning new work
When you already have a rich artifact, ask for the same material through a new lens rather
than starting over. The expensive part is already paid.
- DO: "Take what you did and reframe it around how I prompted."
- DON'T: "Now do a fresh analysis of my prompting" — it re-pays the reconstruction cost.

## The one-line summary
Every habit above trades a small known cost (a clarifying round, a bit of rework, handing
over the raw file) for information about what the agent does *by default* — so you can steer
it before it commits.
