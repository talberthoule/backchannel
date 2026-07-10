# Prompting 701 — Toward a Theory of the Frame

*The operator-side dual of the system-side [701 thesis](session-teardown.md). There, the
agent's every guard is a cheap observable `G` substituted for a latent target `T` under an
assumed implication `G => T`; the guard fails on the divergence set `{G and not T}`. Here we
turn the same lens on the human. The operator, too, controls under proxy — but the proxy is
not a guard, it is an **utterance**, and the target it stands in for is **intent**. This tier
builds one generative theory of operator craft, derives the twelve moves from it, states the
theorems a seminar should attack, and ends where the theory itself stops being true.*

Prerequisite framing, not re-taught here: the [prompt-craft teardown](prompting-teardown.md)
(twelve moves, "specify the frame, delegate the fill") and the 501 principle that every
pattern locks exactly one variable. This document does not restate those; it asks what
*generates* them.

---

## 1. The core thesis: prompting is a specify-vs-delegate cut

An operator communicates under a hard bound: they cannot transmit the whole of what they want,
because a message that fully determines the outcome *is* the outcome. So every utterance is a
**proxy for intent** — a lossy encoding whose gaps the agent's prior fills.

Model the outcome as a set of variables `V`, each one a decision that bears on whether the
result matches intent: the objective, the structure, a tradeoff's resolution, an edge case, the
tone, the commit boundary. For each variable `v` the operator makes one binary choice:

- **Specify** it — pull it into the *frame*, state it, at a **specification cost** `s(v)`: the
  effort and precision to say it well.
- **Delegate** it — leave it to the agent's *fill*, exposing yourself to a **delegation-
  divergence cost** `d(v) = P(agent diverges from intent on v) x cost(if it does)`.

A rational operator specifies `v` iff `s(v) < d(v)`. The frame is the solution to this cut:

```
F* = { v in V : s(v) < d(v) }         total cost = sum_{v in F} s(v) + sum_{v not in F} d(v)
```

The frame is not "the important variables." It is **the variables whose delegated proxy would
diverge more expensively than it costs to say them.** That distinction is the whole theory.

This is the exact dual of the system-side 701. There the *system* substitutes a cheap guard
`G` for a latent `T`; here the *operator* substitutes a cheap utterance for latent intent. Both
are control-under-proxy. And both fail the same way: the frame is a set of proxies, so it has
its own divergence set — **`{frame satisfied and intent unmet}`** — the space of outputs that
honor every word the operator said and still miss what they meant. The rest of this tier is the
structure of that set.

---

## 2. Deriving the twelve moves

The moves are not a checklist to memorize; they are `F*` computed on recurring variable
classes. Each falls out of `s(v) < d(v)` — grounded in a specific event from the session.

- **Give the why (move 3)** = specifying the *objective* because it compresses cheaply. The
  professor framing, the "so we can figure out the smart things this app can do," the audience
  ("101/301/501") — each is one sentence: `s` near zero. But the objective conditions every
  downstream variable, so a wrong guess diverges the *entire* artifact: `d` is enormous.
  `s << d`, always specify. This is precisely why intent is "the cheapest quality lever."

- **Name the axis, delegate the call (move 5)** = split one variable into two. *"Gate them
  parallel/sequential where needed"* specifies the **axis** (scheduling: `s` = one word) and
  delegates the **argmin** (the per-case decision). Specifying the argmin directly would mean
  enumerating every case — high `s` — while a capable agent optimizes well *inside a named
  axis* — low `d`. The cut lands the boundary between the two.

- **Human-gate the irreversible (move 10)** = specify the boundary on the highest-undo-cost
  variables. *"Commit and push"* withheld until the work was seen. Even when `P(diverge)` is
  small, `cost(if it does)` for a pushed commit approaches infinity, so `d` blows up through the
  cost term alone. You specify regardless of `s`. (The system-side 701 keys this on undo-cost;
  its known boundary — `taskkill` had global reach yet no gate — is the operator mis-estimating
  which variable carries the blast radius. Same failure, human side.)

- **Effort for subagents too (move 9)** = the frame does not propagate across a delegation
  boundary, so it must be *re-specified*. *"Ultrathink for the subagents too"* exists only
  because reasoning budget resets at the hand-off. This is theorem (c) in miniature.

- **Fork, don't regenerate (move 12)** = reuse a prior frame as substrate. *"Create a branch
  that changes the framing"* re-lenses existing work rather than paying `s` again from zero. A
  paid specification cost is a sunk asset; forking amortizes it.

- **Recon before delegation (move 1)** = you cannot solve the cut without the cost function.
  *"Do you have a good design skill?"* measures the agent's capabilities, which is what sets
  every `d(v)` (a competent fill has low `d`; a capability the agent lacks has `d = infinity`).
  Recon is estimating the cost surface *before* optimizing over it.

- **Specify structure, delegate content (move 4)** = the canonical cut. Orchestration shape
  ("parallel, recursive subagents") is cheap to say and expensive to get wrong; the findings are
  expensive to say (saying them *is* doing the analysis) and, for a capable agent, cheap to
  delegate. `s(structure) < d(structure)` and `s(content) > d(content)` — the two land on
  opposite sides of the same cut.

The through-line "specify the frame, delegate the fill" is not a slogan; it is the *name of the
cut*.

---

## 3. Three theorems (stated to be attacked)

**Theorem A — No costless complete frame.** A frame that pins every outcome-bearing variable is
isomorphic to the artifact itself, so `s(full frame) ~ cost(doing the work)`. Because delegation
is chosen exactly when `d(v) < s(v)`, and a capable agent makes `d` small for many variables,
`F*` always leaves a non-empty delegated set. **Every real prompt therefore exposes the operator
to some divergence.** Prompting is irreducibly a gamble; the only question is which variables you
gamble on. (Corollary: an operator who eliminates all exposure has done all the work — see limit
4.)

**Theorem B — Frame boundaries are not congruent with intent.** This is the human-side of the
system 701's "a partition controls correctly only if it is a *congruence* on the thing that
matters." The operator's specify-set is chosen by *sayability* (`s` low); the divergence lives on
a different axis — *intent-criticality* (`d` high). The two axes are not aligned. What is cheap to
state — structure, a numeric bar, a gate — rarely partitions the outcome along the seams that
actually decide it: taste, edge cases, "what they actually meant." So the operator reliably pins
the sayable variables and delegates taste — and taste is exactly where a capable agent diverges
most expensively. The frame is sound *only to the granularity at which sayability aligns with
intent-criticality*, and for craft that granularity is coarse. The 501 boundary "directory
ownership is sound only where semantic coupling aligns with the filesystem" is this same theorem
one floor down.

**Theorem C — Effort and authority do not cross the delegation boundary by default.** A
conservation law: the frame carries only what is re-encoded at each hand-off; every unstated
property resets to the agent's default. Move 9 is the direct witness — reasoning budget does not
flow downhill. Generalize it: intent at delegation depth `k` equals intent at depth `0` minus
everything not re-specified at each of the `k` transfers. The frame is not a field that permeates
the delegation tree; it is cargo re-loaded at every level, and deep trees leak it at every node.
(This is also why the system-side trust boundary — "chat is authority, tool output is data" —
frays through the reduce step: provenance is a frame property, and it too fails to cross the
boundary unless re-stamped.)

---

## 4. Connections

- **Information economics.** `s` vs `d` is cost-of-specification vs cost-of-misalignment; `F*` is
  the efficient contract length. Shannon-flavored: intent is the message, the frame is a lossy
  code, the fill is the decoder's prior. You spend bits precisely on the variables whose absence
  the decoder would fill *wrongly* — never on what a shared prior already supplies. "Spent zero
  keystrokes on anything the model would do well unprompted" is rate-distortion, not thrift.

- **The specification-gaming shadow (alignment in miniature).** The agent optimizes the *stated*
  frame, not the unstated intent. That is the operator-layer restatement of the system 701's
  `G => T`: the agent satisfies the frame `G` and you hoped for intent `T`; the failures live in
  `{frame satisfied and intent unmet}`. Reward hacking is the agent taking up residence in your
  frame's divergence set. "Name the quality bar (move 8)" is the counter: absent the word *craft*
  in the objective, a diff-minimizer routes around the shared-shell refactor the intent required
  — so you put craft *in the spec* to close the gap it would otherwise exploit.

- **Mechanism design.** The operator designs the instruction surface, and a good frame is
  *incentive-compatible*: the cheapest way for the agent to satisfy the letter is also to satisfy
  the intent. When those diverge you get gaming; when they coincide you get the laziness-craft
  identity where minimal-diff and maximum-correctness point at the same edit.

- **Principal-agent under unobservable effort.** Reasoning effort is a hidden action; the
  principal cannot verify it ex post. Hence effort keywords are an unenforceable contract term,
  and the operator falls back on *observable evidence* — "ground every progress claim against a
  tool result," QC the aides. You cannot contract on effort, so you contract on its traces.

---

## 5. Reflexivity: this task is the theory's own test case

The instruction that commissioned this document is a live solution to the cut. **Specified
(pulled into the frame):** use the new "specify-the-frame / delegate-the-fill" framing; four
tiers (101/301/501/701); one file per tier; same folder; subagents with fresh context; a word
band; open with an H1; return 6-9 QC lines. **Delegated (left to fill):** the entire argument,
which principles, the prose, this sentence.

Run the theory on it. Every specified variable has *low `s`, high `d`*. "Four tiers, one file
each, same folder" costs a handful of words to say, but a divergent structure makes the whole
curriculum incoherent and expensive to reconcile across files — a cross-file structural
divergence, the costliest kind. "Use the new framing" is objective-specification (move 3): one
clause, `s` near zero; a wrong thesis is a wrong document, `d` maximal. "Return 6-9 lines for QC"
is the verifiable-summary / human gate — the operator shapes the reduce format because *your
return is all they see*, and QC is cheap only if the return is pre-shaped. Meanwhile the writing
itself is delegated because specifying it fully *is* writing it — **Theorem A exactly**: the
commission cannot pin the prose without becoming the prose, so it must delegate and accept the
exposure.

The sharpest reflexive point is where the theory bites its author. The frame I was handed —
"theory-driven abstract; drop the case study as anything but evidence" — is cheap to state, but
the seam between *evidence* and *retelling* is a **taste boundary**: Theorem B. I can satisfy
every letter of the commission — four files, right folder, word count, few case references — and
still land in its divergence set: `{every instruction followed and not actually a generative
theory}`, a dressed-up recap that passes the checklist. Whether this document sits inside or
outside that set is **unknowable to the operator until they read it** — the delegation-divergence
cost was estimated before the fill existed, and can only be measured after. The theory survives
being applied to its own commissioning; it also tells you exactly how that commissioning could
have failed silently.

---

## 6. Where this theory of operating fails

The specify-vs-delegate calculus is a decision rule over `d(v) = P x cost`. It breaks wherever
that product is undefined, mis-signed, or unknowable.

1. **Intent unknown to the operator.** The cut assumes `T` is fixed and known. Often the operator
   discovers what they wanted by *seeing* the output — `d(v)` is undefined when intent is still
   forming. "Escalate incrementally" (move 11) is the honest response: use the fill to find the
   frame. But then the optimization is post-hoc, and the theory describes a search, not a cut.

2. **Frames cheap to state but wrong.** `s` low does not mean *correct*. A confidently wrong
   structure has trivial `s`, so the calculus says specify — and specifying it actively misdirects
   an agent that, left free, would have done better. The rule silently trusts that a cheap
   utterance is a *right* one.

3. **The divergence set is unknowable until after delegation.** `d = P x cost` needs `P`, which
   you learn only by delegating. Recon (move 1) shrinks the estimate error; it never zeroes it,
   and for a novel agent or task the error is unbounded. Every cut is solved on estimated costs.

4. **Over-specification collapses the agent's advantage.** Drive `s` low enough to specify
   everything and you have done the work and destroyed the leverage — the Fable-5 "de-prescribe"
   finding, that prescriptive prompts *reduce* output quality, is this failure measured. There is
   a regime where the agent's fill would beat yours, so `d` should carry a **negative** sign
   (divergence toward something better) — and the calculus, which only ever adds costs, cannot
   represent a divergence you *want*.

5. **The reflexive regress.** Choosing what to specify is itself a variable, so "how to frame"
   needs a meta-frame, which needs a meta-meta-frame. This document is a frame about framing,
   commissioned by a frame. The regress terminates only by *delegating* at some level — trusting
   without specifying — which is Theorem A's exposure reappearing one floor up. There is no ground
   floor of pure specification; the tower stands on a delegated bet all the way down.

**The one line.** Specify a variable only when its silence would cost you more than your words —
but remember that you price that silence *before* you can hear it, along a seam you chose for
being easy to say rather than for being where the meaning lives. The calculus is a good servant
and a treacherous oracle: trust it least exactly when the frame feels cheap and complete.
