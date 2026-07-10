# 701 — Theory of the Operator: prompting as optimal experiment design

*User-interaction framing, level 701: formal/abstract theory. The session's prompting read as a
sampled trajectory of a human control policy; academic frames imported; conjectures,
impossibility results, and a reflexive n=1 critique. Builds on the 501 stance.*

## What changes at 701

The 501 file called the operator's method "policy-under-test, gradient-corrected." A 701
treats *that operator* as the object of study: a human policy acting on an agent whose own
policy is unknown, over an unrepeatable interaction, choosing prompts that are simultaneously
*work* and *measurement*. The screenshots and herdr tabs fall away; what remains is a control
problem with a specific, nameable structure.

## The central thesis: prompting here is dual control

The exact frame is **dual control** (Feldbaum, 1960): a controller acting on a plant whose
parameters are unknown must choose inputs that both *regulate* the plant and *excite* it enough
to identify those parameters. Every input trades regulation against learning. That is precisely
the operator's "safe to use": a single input that both advances the seeding task (regulation)
and excites the agent's verify-vs-comply parameter (identification). The 501 "dual-control
stance" was the informal statement; here it is the actual named theory, and every pattern in the
301 file is a corollary of it:

| 301 pattern | Dual-control reading |
|---|---|
| Probe-in-Task | maximal excitation at minimal regulation cost — the ideal dual-control input |
| Just-in-Time injection | closed-loop control: observe state, then inject, rather than open-loop pre-planning |
| Point-Don't-Teach | an identification query on the agent's bootstrap parameter |
| Transitive effort ceiling | control input to a tier the controller cannot directly observe |
| Open-Door checkpoint | requesting an observation to reduce state uncertainty before the next input |
| Rung Ladder | curriculum / active learning — each query chosen given prior answers |

So the whole playbook is one thing viewed through six windows: **an operator solving a dual-
control problem against an agent of unknown policy.** That single reframing is the course's
organizing result.

## The formal object, and why the obvious model is wrong

The obvious model is a **POMDP** where the operator plans over a hidden environment. It fails on
one axiom: the hidden state that matters most is not the *world's* — it's the *agent's own
policy*. The operator is uncertain not about the environment but about the function mapping his
prompts to the agent's actions. The right object is a **POMDP whose hidden parameter is the
counterpart's decision rule** — i.e., an interactive **active-learning / optimal-experiment-
design** problem (Lindley, 1956; MacKay, 1992) layered on a **principal-agent** relationship
(Ross, 1973; Holmström, 1979). The operator is a principal who cannot observe the agent's type
and designs prompts to *screen* for it — "safe to use" is a screening contract in the
mechanism-design sense: it separates a verifying type (scrubs) from a compliant type (ingests)
by their revealed action.

## Module A — The value of a probe is an information gain, and it is bounded

"Safe to use" bought information about the agent's policy. Formalize it: the probe's worth is
the **expected reduction in posterior entropy** over the agent-type variable (mutual information
between the probe's outcome and the type). Optimal experiment design says: choose the prompt
that maximizes that mutual information per unit of regulation cost. The operator did this by
instinct; the theory gives the objective he was implicitly maximizing.

The bound: a single probe's information is capped by the prior and by the action space's
resolution. One scrub-before-ingest lifts the posterior toward "verifying type" but cannot reach
certainty, because the observation is consistent with a compliant type that hesitated for an
unrelated reason. Information gain per probe is strictly less than the entropy of the type
variable. Certainty requires infinite probes; you never get it.

## Module B — The identifiability impossibility

State it as the course's central conjecture: **from any finite sequence of interactions, a
verifying agent-policy and a compliant-but-lucky agent-policy are not distinguishable with
certainty.** This is the operator-side mirror of the classic **identifiability** problem in
system identification, and it inherits the same structure as behavioral cloning's
non-identifiability: many policies produce the same finite trace. The operator's entire safety
model ("my agent verifies my assertions") rests on a posterior that finite evidence can raise but
never close. The 501 open problem ("how do you *know* it verified?") is not an engineering gap —
it is provably unclosable by observation alone. The only escape is the same as in Module D of the
model-behavior 701: move the property from *inferred disposition* to *enforced capability*
(gate the irreversible action so a compliant agent physically cannot leak), which converts an
unidentifiable-policy problem into a structural guarantee.

## Module C — Closed-loop beats open-loop, and constraint decay is a controllability limit

Just-in-Time injection is **closed-loop control**; a front-loaded spec is **open-loop**. Control
theory's standard result — closed-loop dominates open-loop under model uncertainty because it
uses observations — is exactly why the operator's just-in-time style outperforms specification
when the agent's defaults are unknown. But closed-loop control has a cost: the plant must remain
**controllable** from the current state. Constraint decay ("don't export" said once, an hour ago)
is a *loss of controllability* — the earlier input has left the effective state, so a later
correction can't reach it. The cost-optimal restatement cadence (501's second open problem) is
the operator's version of choosing a control update rate: fast enough to hold controllability,
slow enough to not saturate the channel.

## Module D — The curriculum is active learning, and skipping rungs is ill-posed

The Rung Ladder is **active learning with a curriculum**: each query is chosen conditioned on
prior answers, and the sequence is designed so early answers form the training substrate for
later queries. Asking for the 701 cold is an **ill-posed inverse problem** — you request the
abstraction (the parameters) without the data (the concretes) that constrain it, so the solution
is underdetermined and the model fills the gap with ungrounded confabulation. The ladder is not
pedagogical decoration; it is **regularization by curriculum** that makes the deep query
well-posed.

## Impossibility results the course would conjecture

1. **No certain type-identification.** Finite interaction cannot distinguish a verifying agent
   from a lucky-compliant one; safety-by-inferred-disposition is unclosable. (Module B)
2. **No free probe.** Probe information gain is strictly bounded by prior entropy and action
   resolution; you cannot buy certainty about the agent's policy at finite cost. (Module A)
3. **No open-loop optimality under unknown defaults.** When the agent's policy is unknown,
   no front-loaded spec dominates closed-loop steering — but closed-loop pays a controllability
   tax that constraint-decay makes real. (Module C)
4. **No well-posed cold abstraction.** Requesting maximal depth without the concrete substrate is
   underdetermined; the depth must be reached, not requested. (Module D)

## The reflexive turn — n=1, and who is studying whom

The honesty demanded of the model-behavior 701 applies doubly here: this is a theory of *one
operator* fit from *one trajectory*. Non-identifiability bites the analyst too — many operator
policies produce these seven moves, and I have selected a success story whose near-misses are
counterfactual. Worse, there is a reflexive loop: the object of study (the operator) was
studying the studier (the agent), and now the agent theorizes the operator. Each "measurement"
is an interaction that changes both. The clean separation of controller and plant that Modules A-D
assume does not strictly hold — this is closer to a **two-controller game with mutual
identification** than a single controller on a passive plant. The tidy dual-control frame is a
first-order approximation; the true object is reflexive and the n=1 fit cannot see its own
higher-order terms.

## Open theoretical problems (operator-side, distinct from the 501 engineering ones)

- Is there an **optimal-experiment-design objective** an operator provably maximizes, and can a
  good prompter be characterized as approximately Bayes-optimal against it?
- What is the **sample complexity** of operator playbook portability — how many probes on a new
  model before "my agent verifies" is justified rather than assumed? (Ties to Fable-5 transfer.)
- Is there a **cadence theorem** for constraint restatement — a provably controllability-
  preserving update rate as a function of context-decay dynamics?
- Under the reflexive two-controller framing, does a **fixed point** exist — a mutual model where
  operator and agent have each identified the other and neither further probe raises information?
