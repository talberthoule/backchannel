# ALP-160: Fit-result staleness

- **Requested by:** shepherd lane w1:pP ("fable-root"), relaying the ALP-160 brief
- **Performed by:** Claude Opus 5 (1M context) via Claude Code, lane w1
- **Date:** 2026-07-28
- **Scope:** Design only. No code, schema, or git changes. Companion to
  [ALP-166 endpoint identity](2026-07-27-alp-166-endpoint-identity.md).

> **Provenance.** The ALP-160 assignment comment was not read directly - Linear is
> denied in this session - but the shepherd relayed the brief in full, so the five
> validity dimensions, the three response modes, and the two presentation surfaces
> below are the ones asked for. One gap is flagged rather than guessed: I could
> not locate an ALP-156 "capacity verdict" module in the tree (no `capacity`
> symbol in `backend/app` or `frontend/src`). Section 5.2 therefore designs to its
> *contract* as a consumer, not to its internals. Reconcile before implementing.

Sources read: `backend/app/services/local_fit.py`,
`backend/app/services/diarization_diagnostics.py`,
`backend/app/services/diarizer_runtime.py`,
`backend/app/services/diarizer_selection.py`,
`backend/app/routers/diagnostics.py`,
`frontend/src/components/LocalModelFitCard.tsx`.

## 1. The thesis

There are two stored fit results in the tree and they fail in opposite
directions, but for one shared reason: **each stores a mixture of raw
measurements and derived judgments, with no record of the conditions the
measurement was taken under.**

- A *measurement* (latency, real-time factor, peak memory) is a fact about a
  machine at a moment. It expires when the machine or the subject changes.
- A *judgment* (green/yellow/red, "passed", a recommended interval) is a pure
  function of a measurement plus current thresholds, budgets, and the contention
  slider. It expires the instant any of those change - which is constantly.

Persisting judgments is what makes staleness hard. The fix is to stop:

> **Persist the measurement with its provenance. Recompute the judgment on read.**

That single rule dissolves most of the problem, and the codebase already half
believes it - see F1.

## 2. Findings

### F1 - The local fit blob persists verdicts the UI has already stopped trusting

`store_local_fit_result` (`local_fit.py:650`) writes the whole run payload to one
app setting, `diagnostics.local_fit.last_result`, including every `RoleFit`'s
`verdict`, `recommended_interval_seconds`, and `changed`.

The card does not use them. `LocalModelFitCard.tsx:18-20` carries an explicit
"Scoring mirror of backend app/services/local_fit.py" and recomputes
`classifyLatency` / `recommendInterval` / `classifyRtf` client-side from raw
latency and the live contention slider, because the slider must re-derive
verdicts without re-benchmarking.

So the stored verdicts are already vestigial for display, yet they persist, and
they silently disagree with the screen as soon as the user moves the slider or an
agent's interval changes. `RoleFit.latency_seconds` even documents the split -
"raw measured latency; the UI applies contention live" - which is the right
instinct applied to only one of the fields.

Severity: low on its own (nothing reads them), but it is the shape that makes the
Sortformer case dangerous, where an equivalent frozen verdict *is* load-bearing.

### F2 - The Sortformer record is four loose scalars with no provenance

`record_sortformer_benchmark` (`diarizer_runtime.py:153`) writes four independent
app settings:

```
diarization.sortformer.benchmark_status
diarization.sortformer.real_time_factor
diarization.sortformer.contention_adjusted_real_time_factor   # added by ALP-155
diarization.sortformer.peak_memory_mb                         # added by ALP-155
```

Nothing binds them into a record. There is no timestamp, no schema version, no
`device`, no `gpu_name`, no `model_id` - even though `BenchmarkResult` measured
`device` and `model_id` and simply discards them at persist time.

Consequence: a stored result cannot answer "when, on what hardware, for which
model, under which code version?" - which is the entire input set staleness needs.

### F3 - The live case: a pre-ALP-155 record still unlocks Enhanced

This is F1 and F2 combined, and it is the reason ALP-160 exists.

A benchmark taken before ALP-155 wrote only `benchmark_status="passed"` and a
`real_time_factor`. The two ALP-155 keys were never written, so they read `""`,
and `_parse_float("")` returns `None`.

The gate is `sortformer_is_selectable` (`diarizer_selection.py:19-30`):

```python
sortformer_available
and benchmark_status == "passed"
and benchmark_real_time_factor is not None
and math.isfinite(...) and 0 < rtf <= SORTFORMER_RTF_THRESHOLD
```

It consults `status` and `rtf` only. The contention-adjusted factor and the peak
memory that ALP-155 added - the two fields that exist precisely because raw RTF
was judged insufficient evidence - are **not consulted at all**. A record missing
both therefore passes the gate exactly as if it were complete, and
`_selection_reason` renders `describe_benchmark_headroom(rtf, passed=True)`,
narrating confident headroom for a measurement that never tested the thing
ALP-155 was added to test.

The record is not merely stale. It is *structurally incapable* of satisfying the
current standard, and it is reported as passed.

Severity: highest in this spec. It silently unlocks a live-call diarization path
on evidence the codebase itself has already declared inadequate.

### F4 - Peak memory is a high-water mark carried across machines

`record_sortformer_benchmark:170-185` deliberately keeps the larger of the stored
and the new value:

```python
peak_memory_mb = max(peak_candidates) if peak_candidates else None
```

Within one machine that is defensible - peak memory is bursty and under-sampling
is the common error. Across a hardware change it is wrong: swap the GPU, re-run,
and the old machine's peak survives forever with no way to clear it short of
editing the database. It is the one field that never gets fresher.

Severity: moderate, and it is a staleness bug that survives a re-run, which makes
it worse than the others.

### F5 - `status` is frozen while `rtf` is re-judged, so they can disagree

`SORTFORMER_RTF_THRESHOLD` is derived at import from `SORTFORMER_LIVE_TRACKS *
SORTFORMER_CONTENTION_RESERVE` (`diarization_diagnostics.py:20`). Because
`sortformer_is_selectable` re-applies the *current* threshold to the stored rtf,
tightening those constants correctly re-locks a previously passing machine - good,
and worth preserving.

But the stored `status` string is a frozen judgment from the old threshold, and
the gate ANDs the two. So:

- threshold tightened: `status="passed"` but rtf now fails -> correctly locked,
  though the stored status is a lie that `to_dict` still reports to the UI.
- threshold loosened: `status="failed"` pins the lock shut even though the
  machine now qualifies. Only a manual re-run clears it.

Half the record is live, half is frozen. F5 is the argument for not storing
`status` at all.

### F6 - Local fit has a timestamp nobody reads; Sortformer has none

`store_local_fit_result` stamps `completed_at` (`local_fit.py:660`) and
`summarize_local_fit` returns the blob verbatim as `last_result`. No consumer
compares it to anything; the card restores the report and the contention slider
and renders it as though it were current. The Sortformer path has no timestamp at
all, so age is not even expressible there.

### F7 - Text-model fit results are keyed by an id whose meaning can change

The stored blob's `text_models[].model_id` values are `endpoint:<slug>:<wire>`
ids. Per ALP-166 F2, a deleted-then-recreated endpoint reissues its slug, so a
stored fit result can silently describe a *different server* under an unchanged
id - different hardware, different quantization, different privacy class.

**ALP-160's correctness depends on ALP-166's tombstone.** Without non-recycled
ids there is no reliable way to ask "is this measurement still about the same
thing?", because identity itself is ambiguous. With tombstones, a vanished
endpoint is detectable as gone rather than indistinguishable from a live one.

## 3. What makes a stored measurement invalid

Five inputs, collapsed into three consequences. The collapse is the point: five
independent staleness flags would need five UI treatments and five test matrices.

| Input | Detected by | Class |
| --- | --- | --- |
| Benchmark schema changed (the ALP-155 case) | `schema_version < MIN_SUPPORTED_SCHEMA`, or a field required at the current version is absent | **Incompatible** |
| Subject identity changed (model gone, endpoint re-pointed, endpoint tombstoned) | recorded `model_id` no longer resolves, or the recorded endpoint fingerprint differs from the live one | **Superseded** |
| Hardware changed | recorded `device` / `gpu_name` / `gpu_backend` differ from a live probe | **Superseded** |
| Age | `measured_at` older than `FIT_RESULT_SOFT_AGE_DAYS` | **Aged** |
| Thresholds, budgets, contention changed | not a validity input at all - see 4.1 | *(none)* |

### 3.1 The provenance stamp

Every stored fit record - text, ASR, and Sortformer alike - carries the same
header. It is small on purpose; anything not needed to answer a validity question
stays out.

```
schema_version   int     bumped whenever a measured field is added or its meaning changes
measured_at      ISO8601 UTC
subject          { model_id, endpoint_fingerprint | null }
host             { device, gpu_name, gpu_backend, gpu_memory_gb }
```

`endpoint_fingerprint` is the endpoint's normalized `base_url` plus its `on_prem`
verdict at measurement time. Comparing it to the live endpoint answers "same
server?" for the F7 case; the ALP-166 tombstone is what makes the `model_id` half
of the comparison trustworthy.

ALP-155 would have been a `schema_version` bump. That is the whole fix for F3:
the old record declares an older version, and an older version is not gradeable
against the current standard.

### 3.2 Why "thresholds changed" is deliberately not a validity input

Because judgments are recomputed on read (section 4.1), a changed threshold,
budget, or contention factor simply produces a different verdict from the same
valid measurement. Treating those as invalidation would force a re-benchmark for
a change that costs nothing to recompute - the expensive fix for the cheap
problem. F5 exists only because a judgment was frozen; unfreezing it removes the
question.

## 4. What the system does with an invalid result

### 4.1 First, stop storing judgments

Persist raw measurements and the provenance stamp. Drop `verdict`,
`recommended_interval_seconds`, and `changed` from the stored local-fit payload,
and drop `status` from the Sortformer record. Recompute all of them on read from
current thresholds, current budgets, and the current contention setting.

This is a net deletion. The card already recomputes them (F1); the backend gains
one scoring call on read and loses a class of disagreement. F5 disappears
entirely, and the good half of the existing behaviour - re-judging stored rtf
against the current threshold - becomes the uniform rule rather than an accident.

### 4.2 Then, three responses - and never a fourth

| Class | Stored numbers | Gating | User sees |
| --- | --- | --- | --- |
| **Incompatible** | not shown | closed | empty state: "This machine has not been measured against the current benchmark." + Run button |
| **Superseded** | shown, de-emphasized | closed | "Measured on different hardware" / "...on a different server", naming what changed, + Re-run |
| **Aged** | shown normally | open | quiet "Measured 94 days ago" note |

**Incompatible reads as absent**, not as a warning. A record that cannot be
graded against the current standard has no verdict to soften - showing it with a
caveat invites the reader to trust the number anyway, which is exactly what F3
does today.

**Superseded still shows its numbers**, because they are true about something and
the operator may want them ("it did 0.28 on the old box"). It must not gate.

**Aged only informs.** Age alone is weak evidence about a machine that has not
otherwise changed, so it never locks anything. `FIT_RESULT_SOFT_AGE_DAYS` starts
at 90 and is a tuning knob, not a law - real machines drift on their own schedule
(thermal paste, driver updates, a background indexer), and no constant chosen here
will fit every box.

**Never auto-rerun.** A Sortformer benchmark loads a NeMo model and runs
`SORTFORMER_BENCHMARK_WINDOWS` passes; a local fit test runs two LLM calls per
on-prem model plus every bundled ASR model. Both hold real resources for minutes.
A page load that starts one is a worse surprise than a stale number, especially
mid-call. Invalidation makes the gate close and offers the button; the human
presses it.

### 4.3 The gate that fixes F3

`sortformer_is_selectable` gains one precondition: the record must be
**Incompatible-free and not Superseded**. Concretely, it must carry the current
`schema_version` and every measurement the current version requires - which, since
ALP-155, includes the contention-adjusted factor.

That single condition closes the live case. A pre-ALP-155 record declares an older
version, is classified Incompatible, and cannot unlock Enhanced no matter what its
`status` string says. The operator is told the benchmark predates the current
standard and is offered a re-run.

### 4.4 Consolidating the Sortformer record (fixes F2, F4)

Store one JSON app setting, `diarization.sortformer.last_result`, shaped like the
local-fit blob, replacing the four scalars. Read the legacy keys once at startup
if present, wrap them as `schema_version = 0`, and let the normal Incompatible
path handle them - so the migration needs no special-case UI.

Peak-memory carry-forward (F4) then becomes trivially correct: keep the
high-water mark only when the incoming record's `host` fingerprint matches the
stored one, and reset it otherwise. Same two lines, scoped by provenance.

## 5. Presentation

### 5.1 Agents tab (`LocalModelFitCard`)

One banner at the card head describing the report as a whole, since a run covers
several models at once:

- Incompatible / no record: the existing pre-run empty state, with the reason.
- Superseded: banner naming the specific mismatch ("Measured on NVIDIA RTX 4080;
  this machine now reports Radeon RX 7900"). Rows render greyed. Apply-intervals
  stays enabled - budgets are the user's choice, not a benchmark output - but the
  recommendation column is suppressed, because a recommendation derived from a
  superseded measurement is the one output that would mislead.
- Aged: a single line under the header.

Per-model rows carry their own badge when only some models are superseded - the
common case, since one endpoint can be re-pointed while others are untouched.
That is the one place a per-row treatment earns its keep.

### 5.2 ALP-156 capacity verdict

*Assumption, flagged: treated here as a consumer of fit records defined by its
contract, since no capacity module was found in the tree.*

The capacity verdict aggregates several fit inputs into one answer, which makes
it the surface where a silently-stale input does the most damage - the verdict
looks whole while resting on a measurement that no longer applies.

Two rules:

1. **An invalid input is missing, not passing.** Incompatible and Superseded
   records are excluded from the aggregate. The verdict reports itself as
   incomplete and names which input is unmeasured. It must never round a missing
   input up to a favorable one, which is the general form of the F3 bug.
2. **The verdict inherits the worst validity class of its inputs**, and says
   which input contributed it. "Capacity unknown: the diarization benchmark
   predates the current standard" is actionable; a bare degraded verdict is not.

Aged inputs do not degrade the verdict; they annotate it, consistent with 4.2.

## 6. Out of scope

- Re-running benchmarks automatically on any trigger. Explicitly rejected in 4.2.
- Any change to what the benchmarks measure, or to `SORTFORMER_RTF_THRESHOLD` and
  the contention constants. This spec governs the lifecycle of a stored result,
  not its content.
- The duplicated scoring math between `local_fit.py` and `LocalModelFitCard.tsx`.
  Real drift risk, and 4.1 makes the backend authoritative on read, but unifying
  the two is its own issue.
- Retention or history of past fit results. One current record per subject is
  enough for every question here.

## 7. Open questions

1. Does ALP-156's verdict have a "degraded but usable" state that an Aged input
   should feed, or is it strictly complete/incomplete? Section 5.2 assumes the
   latter.
2. Should a Superseded local-fit record keep its applied per-model intervals?
   This spec keeps them - they are stored on `AgentConfig.model_intervals` and are
   the user's setting, not a benchmark artifact - but it is a judgment call worth
   confirming.
3. Is the legacy four-key Sortformer read (4.4) worth keeping past one release,
   or should it be dropped after a version with a note in the release notes?
