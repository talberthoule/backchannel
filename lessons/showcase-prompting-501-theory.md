# 501 — Operator Judgment: prompting as policy-under-test

*User-interaction framing, level 501: system-level judgment. Stances, tradeoffs, a near-miss
ledger, when NOT to use the patterns, and open problems. Builds on the 101 habits and 301
patterns; the 701 file formalizes what this argues.*

101 gives habits. 301 names patterns. 501 is where you decide *which pattern, when, and at
what risk* — and where you own the stances, not the hedges.

## The governing stance

The operator in this session was not writing instructions. He was **running the agent as a
policy under test and correcting the gradient.** Every prompt did double duty: it advanced the
task *and* it revealed a default he could then steer. "Safe to use" advanced the seeding *and*
tested verify-vs-comply. Just-in-time constraints advanced the work *and* exposed the agent's
default choice before correction. This is the through-line the 301 file pointed at, promoted to
a governing stance: **good prompting is dual-control — you exploit the agent to get work done
while you probe it to learn what it does unprompted, and you spend the second to improve the
first.**

If you internalize one thing at this level: stop trying to fully specify. Specification assumes
you know the agent's defaults. You usually don't. Probe first, cheaply, then steer.

## Tradeoffs you are actually making

- **Just-in-time vs. front-loaded spec.** JIT keeps context small and reveals defaults, but
  pays in occasional rework and constraint-decay. Front-loading prevents rework but blinds you
  to the agent's default and bloats context. *Stance:* JIT by default for exploratory work;
  front-load only the constraints whose violation is irreversible.
- **Point-don't-teach vs. explain.** Pointing tests bootstrap and saves your effort but risks a
  stall on a non-discoverable tool. *Stance:* point when you'd bet even money the tool is
  discoverable; explain the moment you'd hesitate on that bet.
- **Probe-in-task vs. clean test.** Riding the probe on real work is free but couples the test's
  failure to real consequences. *Stance:* only probe-in-task when the action is reversible or
  gated. For an irreversible action, run the probe on throwaway data first.
- **Effort ceilings.** Naming max effort costs latency and tokens. *Stance:* name it only for the
  tier that does the load-bearing thinking; let cheap mechanical tiers stay cheap.

## Near-miss ledger

- **"Safe to use" almost leaked.** The probe worked *because* the agent scrubbed before ingest.
  Had the agent complied literally, real employer/client/person names enter the demo DB. The
  near-miss is the whole reason Probe-in-Task carries the "reversible-or-gated only" rule.
- **The tab-identity gap.** "All the tabs say Claude — I need a better indicator." A
  just-in-time constraint that surfaced only when it bit; a front-loaded "label your tabs"
  would have prevented the detour. Cost was small, so JIT was still correct — but this is the
  exact shape where JIT loses.
- **Mid-stream redirect (full-summary -> website tab).** Real rework cost, accepted as the
  price of not over-specifying downstream consumption up front. Fine here; would not be fine if
  the redirect landed after expensive irreversible work.
- **Constraint decay risk.** "Don't export from the unscrubbed session" lives in a README, not
  in the operator's prompt at each risky moment. The advisory-not-enforced gap is a live hazard
  the operator is carrying, not one he's closed.

## When NOT to use these patterns

- Don't Probe-in-Task when the downstream action is irreversible and sensitive. The probe
  becomes the incident.
- Don't Just-in-Time a constraint whose late arrival can't be undone. Front-load it.
- Don't Point-Don't-Teach into undocumented territory. You're not testing bootstrap, you're
  buying a stall.
- Don't Open-Door if you'll ignore the answer. You'll train the channel shut.
- Don't Rung-Ladder when you genuinely need only the shallow answer. The ladder is for depth you
  intend to reach, not ceremony.

## Open problems (operator-side)

- **How do you *know* the agent verified rather than got lucky?** A scrub-before-ingest is
  consistent with both a verifying policy and a compliant policy that happened to hesitate.
  Finite probes can't fully distinguish them. (The 701 file makes this an impossibility claim.)
- **What's the right restatement cadence for load-bearing constraints?** Too rare and they
  decay; too frequent and you're back to front-loading. There's a cost-optimal reminder
  schedule and this session didn't find it — it relied on a README that the egress paths don't
  consult.
- **Can the probe's information value be measured?** "Safe to use" bought real information about
  the agent's policy. How much? Enough to justify the leak risk? The operator priced this by
  instinct; there's a real expected-value calculation underneath.
- **Does the dual-control stance survive a model swap?** The whole approach assumes a verifying
  counterpart. On a different model the same prompts could produce compliance. Portability of an
  operator's playbook across models is unsolved and unmeasured.
