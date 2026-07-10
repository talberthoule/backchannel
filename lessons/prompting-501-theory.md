# Prompting 501 — The Theory of Driving the Model

*The operator-side companion to the session's [501 reading](session-teardown.md#501-the-theory-underneath-the-session--and-where-it-breaks) and to the [prompt-craft teardown](prompting-teardown.md). The old 501 asked what the **agent's** patterns silently assume; its 701 generalized that to control under proxy. This one turns the lens on the **human**: the twelve operator moves are not tricks, they are instances of a single hard problem — **specifying intent under delegation you cannot fully observe**. For each principle: the move, the established theory it instantiates (outside theory is labeled as framing and tied back to a session event), the evidence, the boundary where it breaks, and the open question. The audience designs agent systems and wants to know **when each move is wrong.***

---

## 1. The frame/fill split is delegation across a principal-agent gap

**Principle.** Every move in the teardown reduces to one table: the operator *set* the structure, the axis, the checkpoint, the bar, the effort, the gate — and *delegated* the findings, the per-case call, the work between checkpoints. "Specify the frame, delegate the fill."

**Theory (framing).** This is the **principal-agent problem** (Jensen–Meckling). A principal hires an agent to act on partial, unobservable information; the agent's effort and reasoning are hidden, so the principal cannot contract on *actions*, only on a specified *frame* plus verification. Move 4 — *"specify the structure, delegate the content"* — is exactly a principal writing an incomplete contract: dictate the orchestration you can observe and check, leave the analysis you cannot.

**Evidence.** The teardown's clinching detail is move 8: *"if you want craft, say craft."* The operator refused to specify the findings (move 4) but *did* specify the quality bar — because a mediocre analysis was the failure he feared. What he made explicit tracks what he distrusted.

**Boundary.** That is also where the split fails. **What the operator refuses to make explicit is precisely what he most fears the agent getting wrong** — and the frame/fill contract offers no way to hedge a fear you won't name. Craft got named because it was feared; the *unnamed* fills are a silent bet that the agent's default is acceptable there. When that bet is wrong, the contract has no clause for it (moral hazard: the agent optimizes the observable frame, not the unstated worry).

**Open question.** Can an operator surface his own implicit fears before delegating — a "what would make this output useless?" pass — cheaply enough to be worth it, or is the fear only legible *after* a bad return?

---

## 2. Intent is a lossy compression of the objective

**Principle.** Move 3 — *"give the why, not just the what"* — works because a one-line statement of purpose lets the agent *reconstruct* the thousand decisions the operator never enumerated (audience "101/301/501," the professor framing).

**Theory (framing).** This is **underspecification** and the **rate-distortion** view of a spec. The full objective is high-entropy; intent is a short code the agent decompresses using a shared prior. A good "why" is the minimal message whose reconstruction is close to the true objective — the cheapest quality lever, as the move says, because it buys the most decisions per token.

**Evidence.** Move 2 — *"ground the model in fresh, authoritative sources"* — is the operator installing a better decompression codebook so the reconstruction doesn't run on stale priors.

**Boundary.** Decompression uses **the model's priors, not the operator's**. The gap gets filled with whatever the agent already believes purpose implies — sometimes the operator's intent, sometimes drift. The Fable-5 note sharpens this: Fable 5 *"connects the task to relevant information rather than inferring intent on its own,"* which is safer only because it defers to supplied context — but where context is thin, the prior still rules. Lossy compression is fine until the sender and receiver hold different codebooks.

**Open question.** How does an operator detect a codebook mismatch *before* the output — is there a "read back your understanding of the why" handshake that costs less than the wrong deliverable?

---

## 3. Framing is an optimization with two failure modes and an interior optimum

**Principle.** Over-frame (script the steps) and you destroy the agent's comparative advantage — you spend keystrokes on work it does better unprompted, and, per the Fable-5 guidance in the teardown, *"prompts written for prior models are often too prescriptive and reduce output quality."* Under-frame and you court ambiguity and misalignment (principle 1's unnamed fears). There is an interior optimum.

**Theory (framing).** This is a **bias/variance** tradeoff in specification. Over-specification is bias: you force the output toward your enumerated steps even when they're worse. Under-specification is variance: the output scatters across the agent's priors (principle 2). Move 5 — *"name the axis, delegate the call"* — is the interior point: fix the dimension (bias down the thing you care about), free the per-case decision (keep the variance where the agent beats you).

**Evidence.** Move 4 fixed only the execution shape and left the analysis free; move 8 added the bar without scripting how to reach it. Each is a deliberate placement on the frame axis, not a maximal spec.

**Boundary.** **The seam cannot be found a priori.** The operator does not know how much framing is too much until he sees a return that is either boxed-in or scattered — the same structure as the old 501's finding that the critical path is *"only discoverable after decomposition."* You locate the optimum by overshooting once and correcting, not by calculation.

**Open question / model-design consequence.** This is *why* "de-prescribe" is a Fable-5 design directive, not just operator advice: if the model reliably fills a light frame well, the interior optimum shifts toward less specification, and old scaffolding becomes pure bias. The open question is whether the seam is stable enough per task-type to learn, or whether it moves with every model release.

---

## 4. Checkpoints and gates are control under partial observability

**Principle.** Move 6 (*"once all reviews are back, proceed"*) and move 10 (*"commit and push"* only after human review) let long, unwatched work run and resume deterministically. The operator can't watch continuously, so he installs triggers.

**Theory (framing).** This is an **approval controller** over a partially observable process, and it maps onto **Type-1/Type-2 reversibility** exactly as the old 501 §6 argued: a working-tree edit is cheap to undo (Type-2), so it runs open-loop; a push leaves the local blast radius (Type-1), so it is gated. The checkpoint is control of *duration* without observation; the gate is control of *irreversibility*.

**Evidence.** Fixes sat in the working tree, reviewed, until the human said commit — the controller gating on undo-cost, not on quality.

**Boundary.** **A gate keyed on "irreversible/outward" misses high-blast-radius *local* actions.** The old 501's canonical case is `taskkill /F /IM node.exe`: local, ungated, yet it killed the user's unrelated processes. Reversibility and blast radius are different axes; the operator's gate guards the first and can wave through catastrophe on the second.

**Open question.** Should the operator's gate key on **blast radius** (how many entities an action can touch) rather than, or alongside, reversibility? A scoped push is outward with local reach; `taskkill` is local with global reach.

---

## 5. Effort is an explicitly allocated, non-inheriting resource

**Principle.** Move 9 — *"ultrathink... and ultrathink for the subagents too as I want them using max effort"* — reveals two facts at once: reasoning budget is a **resource the operator allocates**, and it **does not propagate through delegation by default**. The operator had to spend a clause pushing it downhill.

**Theory (framing).** This is **resource allocation** under compute-as-quality economics. Effort is a priced input; more of it buys (noisy) quality. The non-inheritance is the load-bearing insight: delegation resets the budget, so an unspecified subagent runs cheap.

**Evidence.** The teardown's Fable-5 upgrade to move 9 is *per-phase* effort — `low`/`medium` for mechanical fixes, `high`/`xhigh` for the 501/701 reasoning — because the fan-out already lets you set the dial per stage.

**Boundary.** **More is not monotonically better.** The Fable-5 guidance is explicit: *"higher isn't monotonically better,"* start around `high` and sweep; low effort on Fable 5 can beat a prior model's `xhigh`. The discipline is **allocation, not maximization** — spend the budget where marginal reasoning buys marginal quality and starve the stages where it doesn't. Maxing everything is the effort analog of over-framing (principle 3): paying for reasoning the task can't convert.

**Open question / model-design consequence.** "Tune effort" is a Fable-5 design directive for the same reason "de-prescribe" is: once effort is a first-class dial with a non-monotone response curve, the operator's job stops being *turn it up* and becomes *find the per-phase optimum* — and nobody yet knows that curve's shape a priori.

---

## 6. Progressive disclosure is sequential decision-making, not a plan

**Principle.** Move 11 — *"escalate incrementally; use the model's output as scaffolding"* (review → fix → commit → redesign → 101/301/501 → 701 → reframe) — is the operator running an **adaptive policy**: each turn conditions on the last turn's result rather than committing a full spec up front.

**Theory (framing).** This is **online / closed-loop sequential decision-making** versus open-loop planning. A monolithic spec is an open-loop controller (decide everything before observing); progressive disclosure is closed-loop (observe, then decide the next move). Closed-loop wins under uncertainty because it uses information the open-loop plan couldn't have had — the model's own output becomes the state you plan against.

**Evidence.** Move 12 — *"fork, don't regenerate"* — is the same policy exercising its escape hatch: rather than re-run from scratch, re-lens existing substrate.

**Boundary.** **Each step conditions on a possibly-flawed prior step.** A greedy adaptive policy that always takes the next local move can climb a wrong hill — it optimizes step-to-step and never revisits the global frame. If turn 3 quietly set the wrong direction, turns 4–8 build on it. Move 12 is the *only* move in the set that performs a global reframe, and it exists precisely because incremental escalation, left alone, locks in early turns.

**Open question.** When should an operator break the greedy chain and reframe globally — is there a signal (repeated small corrections, rising friction) that says "the substrate is wrong, stop building on it"?

---

## 7. The operator is the residual authority

**Principle.** Across all twelve moves the human keeps exactly the decisions whose misjudgment is costliest — structure, the quality bar, the gate, the intent — and delegates everything else.

**Theory (framing).** This is **residual rights of control** (Grossman–Hart–Moore incomplete-contracts theory): when a contract cannot specify every contingency, the party who holds *residual* authority is the one who decides the cases the contract left open. The operator writes an incomplete contract (principle 1) and reserves for himself the non-contractible variables — the ones no cheap proxy can adjudicate. He is the **oracle of last resort**, which ties directly to the old 501 §4 oracle problem: for defects with no available machine oracle (semantic staleness, "is this actually good"), *"the only remedy is a human oracle."* Structure, bar, gate, and intent are exactly those un-proxyable variables.

**Evidence.** The teardown's summary line — *"say what only you can decide; delegate the rest"* — is the residual-authority rule stated as craft. He spent zero keystrokes on anything the model does well unprompted, and all of them on the four things a proxy can't settle.

**Boundary.** Residual authority is only as good as the operator's judgment about *which* variables are non-contractible. Mis-classify a costly variable as delegable (fail to name craft, in principle 1's terms) and you've handed the oracle's decision to a proxy that can't make it.

**Open question.** Can the set of "only-I-can-decide" variables be made explicit per task-type, or is knowing which four things to keep itself the un-teachable residual skill?

---

## Where the operator's playbook fails

Five honest failure modes — the situations where a *good* operator move is the wrong move:

1. **Over-framing.** Scripting steps the agent would do better unprompted (principle 3) spends keystrokes to *lower* quality — the Fable-5 "too prescriptive" trap. The reflex to specify more is exactly backward on a model that fills a light frame well; **"de-prescribe" is the model-design answer to this operator failure.**

2. **Intent that encodes the wrong objective.** A crisp "why" (principle 2) that names the wrong purpose is *worse* than silence — the agent decompresses confidently in the wrong direction, and every downstream fill inherits the error. A lossy code that faithfully transmits the wrong message is high-fidelity failure.

3. **Gates on the wrong axis.** Approving the irreversible (principle 4) while an ungated local action (`taskkill`) does more damage. The gate feels like control and isn't, because it guards reversibility when blast radius was the variable that mattered.

4. **Effort mis-allocation.** Maxing every stage (principle 5) on a non-monotone response curve pays for reasoning the task can't convert, and starving a hard stage to fund an easy one is the same error inverted. **"Tune effort per phase" is the model-design answer** — the dial exists because maximization is a mistake.

5. **Progressive disclosure that locks in an early wrong turn.** Greedy escalation (principle 6) with no global-reframe checkpoint compounds a bad turn-3 decision through every later turn. Move 12 ("fork, don't regenerate") is the antidote, but only if the operator notices the substrate is wrong — and the same incrementalism that builds momentum is what hides the wrong turn.

**The through-line.** The old 501 said each *agent* pattern is a lock on one variable that fails when that variable diverges from the one that matters. The operator's playbook is the dual: **each operator move commits the human to deciding one variable and delegating the rest — and each fails exactly where the variable he chose to keep, or chose to release, diverges from the one that actually decided the outcome.** Knowing the moves is 301. Knowing which variable each move silently bets on — and when that bet is wrong — is 501.
