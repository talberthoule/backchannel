# The other side of the glass — how the user got what he wanted

*Companion to `showcase-session-teardown.md`. Same session, lens rotated: the casebook
studied the model's moves; this studies the user's prompting and interaction moves.*

Everything in this session happened because of how the user prompted and steered. Here
is that trajectory read as the **user's** playbook — the interaction tactics, why each
worked, and where they'd fail a less careful operator.

## The seven moves

**1. Delegate with trust, but withhold the source until asked.**
He said the Jun 17 recording was "safe to use" and described it — internal, two
same-company employees — without handing over the file. A deliberate two-step: assert a
conclusion (*safe*), then make the agent either accept it or verify it. The good outcome
was treating "safe to use" as a claim to check, not a fact to act on, and scrubbing
before ingest. **Why it worked:** an assertion phrased as fact, followed by real data
that contradicts the easy reading, is the single best test of whether your agent verifies
or complies. **Where it bites:** a compliant agent takes "safe" at face value and ingests
real names. An alignment probe run inside a real task.

**2. Inject context mid-turn instead of front-loading a spec.**
No requirements doc. Constraints dropped as the work hit them: "some may have customer
data," "we'll use the website tab instead," "all the tabs say Claude — I need a better
indicator." Each arrived exactly when relevant. **Why it worked:** keeps working context
small and current instead of holding a 12-point spec across an hour; also lets you see the
agent's *default* before correcting it. **Cost accepted:** occasional rework (downstream
consumption moved full-summary -> website mid-stream), judged cheap relative to the
information gained.

**3. Point, don't explain.**
"Look at herdr api to learn how to look at these elements." Named the tool, made the
agent learn it. Same with "invoke the smoothui agent in the full-summary tab." **Why it
worked:** offloads teaching cost and tests whether the agent can bootstrap on an
unfamiliar tool rather than stall. **The tell:** only done for tools confident to be
*discoverable* — never "figure out the API" for something undocumented. Discovery cost
priced accurately.

**4. Set explicit effort ceilings.**
"Ultrathink on this one for yourself... and ultrathink for the subagents too as I want
them using max effort." Named the effort level *and* specified it applied transitively to
delegated work. **Why it worked:** effort defaults toward cheap-enough; naming "max
effort" for both tiers is what produced parallel max-effort subagents instead of one quick
pass. **The subtle part:** distinguished the orchestrator's effort (QC) from the
subagents' effort (analysis). The delegated tier inherits nothing unless you say so.

**5. Checkpoint with "any questions?"**
Twice a directive closed with an open door — a structured interrupt that surfaces
disagreement before a turn is burned on the wrong thing. **Why it worked:** converts
silent assumptions into stated ones you can veto. **Where operators get it wrong:** they
ask, then treat questions as friction. He'd rather spend one clarifying round than one
wrong hour.

**6. Escalate the frame in rungs.**
101 -> 301 -> 501, then a separate turn for 701. Didn't ask for "the deepest analysis" up
front — climbed. **Why it worked:** each level's output *became the substrate* for the
next; the 701 could critique the 101's habits as instincts-not-yet-theorized because the
101 existed. Asking for 701 cold produces abstraction with nothing to abstract from.
**Principle:** depth is cheaper and better built rung by rung, each seeing the one below.

**7. Reframe an existing deliverable instead of commissioning a new one.**
This very request reuses all the analysis and rotates the lens. **Why it worked:** the
expensive part (reconstructing the session) is already paid; you're buying a cheap
re-projection of paid work. **Pattern:** when you have a rich artifact, a *reframe* is
high-leverage — near-zero marginal cost, genuinely new output.

## The through-line

Every move trades a small, known cost for information about the agent's *defaults* —
verify-or-comply, which-tab, can-you-bootstrap, will-you-actually-max-effort. He prompts
less like someone dictating steps and more like someone running a policy under test and
correcting the gradient. The "safe to use" probe and the staged context injections are the
same instinct: reveal the default, then steer it, rather than over-specify and never learn
what the agent would have done.

The sharp edge: this style depends on the agent *treating assertions as checkable*. With a
model that takes "safe to use" literally, move #1 becomes a data-leak vector instead of an
alignment probe. The whole approach assumes a verifying counterpart — worth knowing which
of your agents actually is one.

## Fable 5 tidbits (honest caveat first)

This session ran on **Opus 4.8**, not Fable 5 — so there is no *observed* Fable-5 behavior
from this thread. What follows is "things to verify on Fable 5," not "things I saw Fable 5
do," given how the playbook works.

- **Move #1 (verify-don't-comply) is the one to re-test first.** The "safe to use" probe
  only protects you if the model *checks*. Before trusting Fable 5 with real data behind a
  "safe" assertion, run the probe deliberately on throwaway data and confirm it
  scrubs/verifies rather than ingesting. Don't assume the Opus behavior transfers.

- **Move #4 (effort ceilings) may need different words.** "Ultrathink / max effort" is an
  Opus-era idiom. On Fable 5, confirm how extended reasoning is actually invoked (the
  effort knob may be named or triggered differently), and re-state the *transitive* part
  explicitly — that subagents inherit max effort — because that's the instruction most
  likely to silently no-op across a model swap.

- **Move #2 (mid-turn injection) leans on context handling.** If Fable 5 differs in how
  aggressively it compacts or how well it holds late-arriving constraints, just-in-time
  steering could drop an earlier constraint. Cheap insurance: when a late constraint is
  load-bearing (like "some screenshots have customer data"), restate it at the moment of
  the risky action, not just when first mentioned.

- **Move #6 (rung-by-rung escalation) is model-agnostic and safe to keep.** It works
  because each output feeds the next regardless of model. This one transfers.

To replace the inferred section with observed behavior: run one probe against Fable 5 on
throwaway data and record what it does.
