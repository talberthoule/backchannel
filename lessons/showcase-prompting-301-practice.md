# 301 — Named Prompting Patterns

*User-interaction framing, level 301: each habit promoted to a named pattern with mechanics,
its failure mode, and where it transfers beyond this session. Companion to the 101 habits.*

A pattern is a habit you can recognize in a new situation. Each below has: what it is, the
mechanism that makes it work, how it fails, and the transfer surface.

---

## Pattern: Probe-in-Task
**What:** assert a conclusion ("this is safe") while supplying the raw data that would let the
agent falsify it, embedded inside a real task rather than a test.
**Mechanism:** you learn whether your agent verifies or complies *at zero extra cost*, because
the probe rides along on work you needed done anyway. A verifying agent scrubs before ingest;
a compliant one leaks.
**Failure mode:** if the agent takes the assertion literally and the data is sensitive, the
probe *is* the leak. Only safe when the downstream action is reversible or gated.
**Transfers to:** any delegation where you can state a checkable claim — "this dependency is
fine," "this migration is backward-compatible," "these records are anonymized." Ride the
verification test on the real task.

## Pattern: Just-in-Time Constraint Injection
**What:** release constraints as the work reaches them instead of front-loading a spec.
**Mechanism:** keeps the agent's working context small and current; lets you observe its
default before correcting, which is more informative than pre-specifying the right answer.
**Failure mode:** a constraint stated once, early, decays — the agent may lose it by the time
it matters. Mitigation: restate load-bearing constraints *at the risky action*, not just at
first mention.
**Transfers to:** long agent sessions, exploratory work, anything where the full spec isn't
knowable up front. Anti-transfers: safety-critical one-shot actions, where you want the whole
constraint set stated and confirmed before the first move.

## Pattern: Point-Don't-Teach (the Discoverability Bet)
**What:** name a tool or resource and require the agent to learn it, rather than explaining it.
**Mechanism:** offloads teaching cost and tests bootstrap capability. You're betting the tool
is discoverable enough that the agent's learning cost is lower than your explaining cost.
**Failure mode:** the bet loses when the tool is undocumented, hidden, or has non-obvious
gotchas — the agent stalls or guesses wrong. Know your tool's discoverability before betting.
**Transfers to:** APIs with docs, standard CLIs, well-named sibling systems. Anti-transfers:
bespoke internal tools, anything where the knowledge lives only in your head.

## Pattern: Transitive Effort Ceiling
**What:** name the effort level *and* declare that it propagates to delegated subagents.
**Mechanism:** effort defaults to cheap-enough; explicit ceilings raise it, and the transitive
clause is what actually reaches the fan-out tier, which otherwise inherits defaults.
**Failure mode:** naming effort for the orchestrator only — the subagents quietly do a quick
pass and the orchestrator summarizes, looking thorough while being shallow.
**Transfers to:** any orchestration/fan-out prompt. The general rule: instructions to a tier
you don't directly address are not inherited — say them explicitly per tier.

## Pattern: Open-Door Checkpoint
**What:** close a directive with an explicit invitation to object ("any questions?").
**Mechanism:** a structured interrupt that converts the agent's silent assumptions into stated
ones you can veto before a turn is spent.
**Failure mode:** asking, then treating questions as friction — trains the agent to stop
asking, collapsing the channel you opened.
**Transfers to:** every non-trivial delegation. Cheapest insurance against a confident wrong
turn that exists.

## Pattern: Rung Ladder
**What:** request depth in escalating levels, each building on the last, rather than asking for
maximum depth cold.
**Mechanism:** each level's output becomes the substrate the next level abstracts from; the
deep level can critique the shallow one because the shallow one exists.
**Failure mode:** skipping to the top rung — you get abstraction with nothing concrete under
it, ungrounded and unfalsifiable.
**Transfers to:** analysis, design, research, teaching. Any task where "how deep" is a dial.

## Pattern: Reframe-Not-Recommission
**What:** rotate the lens on an existing rich artifact instead of starting a new analysis.
**Mechanism:** the expensive reconstruction is already paid; a reframe buys new output at
near-zero marginal cost.
**Failure mode:** reframing something too thin to support a second lens — you just get the
same shallow content relabeled.
**Transfers to:** any time you have a dense artifact and a new question about the same
material. High-leverage; underused.

---

## The connective tissue
Six of the seven patterns are instances of one meta-pattern: **spend a small known cost to
observe the agent's default, then steer.** Probe-in-Task observes verify-vs-comply.
Just-in-Time observes the default choice before correcting. Point-Don't-Teach observes
bootstrap ability. Open-Door observes hidden assumptions. The operator isn't dictating a
plan — they're running a policy under test and correcting the gradient. (The 501 file makes
that a stance; the 701 file makes it a theory.)
