# Aggregate Local Resource Budget Design

**Date:** 2026-07-27

**Status:** Draft (design-first; agreement required before implementation)

**Issue:** ALP-156

**Author:** Fable/Opus lane (pane w2:pB)

## Goal

Give the app a single owner of the machine's compute budget for a live call, so
that a user cannot be walked through a series of green lights into a
configuration that cannot run. Replace per-component boolean gates, each
validated alone on an idle machine, with one admission decision that reasons
over the whole selected configuration and reports measured headroom, backed by a
runtime controller that degrades the call by a deliberate priority order when
demand still exceeds supply.

## The failure this addresses

On 2026-07-27 the user assembled a configuration in which every component passed
its own gate and the assembled system could not run:

- Sortformer streaming diarization, cleared by the Sortformer benchmark.
- `local-parakeet-live` on-device live captions, cleared (advisorily) by the
  live-caption fit test.
- `local-parakeet-tdt-0.6b` batch ASR, cleared by transcription readiness.
- `qwen3.5-4b` for every text agent, cleared by the model picker and Privacy
  First.

The live call then ran one diarizer per track against mic plus system audio,
required roughly twice realtime for diarization alone, while batch ASR and the
on-device captioner competed for the same in-process thread pool and CPU, and
the 4B text model ran the agents. The diarization backlog climbed from 2 to 1602
frames in 95 seconds and the container was OOM-killed (ALP-153); only 12 segments
transcribed. Separately the same 4B model could not finish a briefing inside the
then-120s request timeout and truncated its JSON (ALP-154).

No component was individually misconfigured. The aggregate was impossible, and
nothing in the system was responsible for noticing. That gap - not either
individual bug - is what this design closes.

### Why each gate said yes

Each gate answered a narrower question than the call actually poses. The
concrete gates as built (verified against the current tree):

- **Sortformer benchmark** (`POST /api/diagnostics/diarization/sortformer/benchmark`,
  handler `backend/app/routers/diagnostics.py:243`, service
  `backend/app/services/diarization_diagnostics.py:178`). It times exactly one
  `model.diarize()` call over a single 15-20s mono clip at `batch_size=1`
  (`diarization_diagnostics.py:201-203`, `_run_diarization` at `:267`), on the
  otherwise-idle machine, and passes iff real-time factor
  `<= SORTFORMER_RTF_THRESHOLD = 0.70` (`diarization_diagnostics.py:14,157-163`).
  One track, one pass, no contention, GPU memory probed but excluded from the
  verdict. A passing result is persisted as a boolean unlock
  (`diarization.sortformer.benchmark_status`, `diarizer_runtime.py:109-120`) that
  survives reload and is required to select Enhanced
  (`diarizer_selection.py:16-20`, `diarizer_runtime.py:98-102`). The call demanded
  two tracks, sustained for the whole call, contended against ASR, captioner, and
  text agents.
- **Live-caption fit test** (`local_fit.py:750`, `classify_live_feasibility`
  against `ASR_LIVE_FEASIBLE_RTF=0.33` / `ASR_LIVE_MARGINAL_RTF=0.66` on a 3s
  window). It projects the captioner running by itself; it does apply a single
  contention multiplier (default 1.5x, clamp 1.0-3.0, `local_fit.py:59-61,854`),
  but it is **advisory only - there is no hard gate**: selecting
  `local-parakeet-live` instantiates the captioner regardless
  (`orchestrator.py:227-228`), and the verdict is not persisted
  (`local_fit.py:603-635`).
- **Transcription readiness** (`GET /api/diagnostics/transcription/readiness`,
  `transcription_readiness.py:44-83`) confirms only that the ONNX runtime is
  importable (`local_asr_available()` at `:40`) - a *presence* check, not that
  weights are warmed and not that any CPU remains. It blocks call start in
  `frontend/src/App.tsx:635-640` on a pure boolean.
- **Model picker / Privacy First** (`frontend/src/lib/modelOptions.ts:27-58`,
  backend `privacy.py`). Privacy First locks every non-local option
  (`optionState`, `runsLocally`) and admits the 4B model because it runs locally.
  Privacy reasons about *where* computation happens
  (`custom_endpoints.py:is_on_prem` at `:125-154`), never about whether the
  machine can *afford* it, and it was silent on speed.

Every one of these is a correct answer to its own question. The missing question
is the aggregate one: does this machine have the sustained throughput and the
memory to run all of these at once, for a whole call, at the configured track
count? Notably the Local Model Fit card
(`frontend/src/components/LocalModelFitCard.tsx`) already comes closest to the
right shape - it shows measured latency/RTF margins and a live contention slider
rather than a checkmark - but it evaluates each component in isolation, persists
nothing, is not track-count aware, and renders no aggregate verdict.

## The resource model

The design introduces one shared budget with two dimensions, because the two
observed failures were of two different kinds - one throughput (diarization
falling behind), one memory (the OOM kill) - and ALP-155 correctly notes a
latency-only model would have missed the memory failure entirely.

Before the arithmetic, one distinction the current code makes that the model
must respect:

- **In-process consumers** contend for the single backend process: its default
  `ThreadPoolExecutor`, the GIL, its memory, and the container limit. These are
  the diarization worker (one task draining a queue, `feed_audio` via
  `asyncio.to_thread`, `audio_runtime.py:248-296`), batch ASR (up to 3
  concurrent `asyncio.to_thread(model.recognize)`, semaphore in
  `ordered_transcription.py:33`), and the `local-parakeet-live` captioner
  (in-process ONNX, single-flight, `local_live_captioner.py:98-116`). This is the
  set that shares one thread pool and is what OOM-killed the container.
- **Out-of-process, same-machine consumers** contend for the physical CPU/GPU but
  not the backend's event loop, GIL, or thread pool. A loopback text endpoint
  (LM Studio, Ollama, vLLM) is reached over async HTTP (`llm.py:_call_openai` at
  `:158`), so an agent call is prompt-building plus an `await` on a socket. Its
  inference still burns the same physical cores as the audio pipeline, but it
  cannot exhaust the backend process itself.

The budget therefore tracks a *machine* dimension (physical CPU + memory, which
every same-machine consumer draws on) and is careful about which consumers also
load the *backend process* specifically.

### Dimension 1: sustained CPU throughput

Express every component's demand in a single currency: CPU-seconds consumed per
wall-clock second of call (equivalently, cores kept busy). The machine budget is
usable cores minus a reserve for the event loop, WebSocket I/O, database, and OS.

Per-component demand:

- **Diarization:** `track_count * diar_rt_factor`, where `diar_rt_factor` is the
  CPU-seconds to diarize one second of one track on this machine. `track_count`
  is 1 for mic-only and 2 once system audio is captured (the default when
  tab/system audio is on); the system diarizer is built lazily on the first
  track-1 frame (`audio_runtime.py:263-265`), and both tracks are serialized
  through one worker, so the required *throughput* the single worker must sustain
  is `track_count x realtime`. This is the dominant, sustained load and the one
  that failed. The factor must be measured per track and multiplied by track
  count, and measured under representative load or discounted - which is exactly
  ALP-155's remit.
- **Batch ASR:** `speech_fraction * asr_rt_factor`, in-process, bounded at 3
  concurrent segments. Batch ASR runs only on diarized speech, so its average
  load is the ASR realtime factor scaled by the fraction of wall-clock that is
  speech (VAD already yields this). Bursty; the budget reasons about the
  sustained average and the controller absorbs bursts.
- **Live captioner:** `cap_rt_factor`, in-process, continuous on the mixed track
  when `local-parakeet-live` is the gateway; zero for a cloud Live/Realtime
  gateway or when disabled.
- **Text agents:** for a self-hosted endpoint the inference is out-of-process
  (see above), costing physical CPU
  `sum_over_agents(tokens_per_call / tokens_per_sec) / interval_seconds` but no
  backend-process thread-pool time. For a LAN or remote endpoint the compute is
  off-box entirely (zero local CPU, but a latency term - below). For a cloud
  model, zero.

Admission compares the sum of demands to the budget and reports the margin:
`headroom = budget - sum(demands)`. A configuration is comfortable when headroom
is positive with a safety factor, thin when barely positive, and
refused-with-override when negative. Track count is a literal multiplier on the
diarization term; concurrency is represented by summing every active component
against one budget rather than checking each against the whole machine.

### Dimension 2: peak resident memory

Sum the resident footprint of every model loaded at once - diarizer instances
(one per track), the batch ASR model, the captioner (which shares cached
`local-parakeet-tdt-0.6b` weights with a Parakeet batch model,
`local_live_captioner.py`), and the local text model only if it is served
in-process - plus the bounded audio buffers (the diarization backlog is capped
near 2 MB, `audio_runtime.py:208-209`; the captioner's `_pending` at 30s,
`local_live_captioner.py:40`) and process overhead. Compare against the container
memory limit (Docker) or a machine-memory reserve (desktop). A loopback text
endpoint's model memory lives in *its* process, not the backend's, and counts
against the machine reserve but not the container limit. This dimension is what
actually killed the call and is projected independently of throughput.

### The latency term for remote endpoints

A LAN or remote text endpoint costs no local CPU but can still make a
configuration unworkable, as ALP-154 showed: a 4B model that could not answer a
briefing within the request budget. ALP-154 has already raised the ceilings
in-tree - `LLM_SELF_HOSTED_TIMEOUT_SECONDS = 900` and
`LLM_SELF_HOSTED_MAX_TOKENS = 8192` (`config.py:22-27`), applied per
self-hosted call (`llm.py:67-83`), with truncation surfaced as `LLMReplyTruncated`
(`llm.py:86-88,360-363`) - so the planner's latency term consumes those exact
per-endpoint limits: expected tokens-per-second against the largest contracted
output (the briefing arbiter) versus the endpoint's timeout, warning when a
single call would exceed it. This keeps the throughput budget about the machine
and the latency budget about the slow-model case without conflating them.

## Where the decision lives

The issue frames three options: a single admission check at call start; per
component budgets negotiated against a shared pool; or an adaptive controller
that degrades by priority under load. This design takes the first and third
together and rejects the second as the primary mechanism.

- **A single admission owner (predictive).** One service - the local capacity
  planner - reasons over the entire selected configuration at call start and
  produces the headroom numbers above. The existing gates stop rendering their
  own verdicts in isolation; they become measurement providers that feed the
  planner (the diarizer's realtime factor and memory footprint from the
  ALP-155 benchmark, the captioner and ASR factors from the fit test, the text
  model's tokens/sec and per-endpoint timeout). The planner renders the one
  combined verdict. It has the inputs today - the fit card already computes
  latency and RTF with a contention multiplier; what is missing is summation,
  track-count, memory, and persistence.
- **A runtime controller (reactive).** Prediction on a contended machine is never
  exact - models warm up, the machine is never perfectly idle, GC pauses
  happen - so a predictive check alone would still occasionally admit a
  configuration that drifts under load. Three independent per-component relief
  valves already exist (ALP-153's diarization shed, `audio_runtime.py:212`; the
  captioner's `MAX_PENDING_SECONDS` drop, `local_live_captioner.py:88-96`; the
  batch-ASR semaphore and timeouts, `ordered_transcription.py:33-98`), but each
  fires on its own when its own queue overflows - "whichever overflows first
  wins," which is precisely the issue's complaint. The controller coordinates
  these existing valves under one priority order and one view of which budget is
  breached.
- **Per-component static budgets are rejected as the primary mechanism.**
  Contention does not divide cleanly, and a fixed split of the machine is either
  wasteful when one component is idle or wrong when one spikes. The shared-pool
  arithmetic lives in the planner (dimension 1 is literally a shared pool), but
  it is computed globally, not pre-partitioned per component.

## What degrades first

When live demand exceeds the budget, the controller first identifies *which*
budget is breached - the in-process throughput/memory of the backend (the OOM
axis) or the physical-CPU/endpoint-latency axis - then applies the
highest-in-value-order lever that relieves *that* budget. The value order, first
sacrificed to last, is a product decision stated so it can be ratified
deliberately rather than decided by whichever queue overflows first:

1. **Live interim captions** (shed, then disable the local captioner). Lowest
   durable value - the content is reconstructed by batch ASR moments later - and
   dropping it relieves the in-process pool immediately, the exact axis that
   OOM'd. Doubly justified as first.
2. **Text-agent cadence** (widen intervals, then reduce the active agent set to
   the highest-value agents). Insights tolerate latency: a 40s analyst becoming
   80s is graceful, and the final pass still runs at call end. This is the lever
   that relieves the physical-CPU/endpoint axis.
3. **Diarization detail** (shed oldest audio -> coarser speaker attribution).
   The ALP-153 behavior. The transcript text survives; only speaker labels
   degrade. Relieves the in-process pool but costs more than captions, so it
   comes after them.
4. **Batch transcript text is protected.** The durable record everyone reads
   after the call; it degrades only if 1-3 were insufficient, and then by
   widening segmentation, not dropping content.
5. **Call liveness is never sacrificed.** The process must not die; keeping the
   call recorded and endable outranks everything. This is the floor ALP-153
   established.

### Relationship of this order to ALP-153

ALP-153 currently makes diarization the *first* thing to shed, because the
diarization queue is the one that overflowed. Under this design, captions and
text-agent cadence should give way *before* diarization detail, so diarization
shedding becomes a later resort rather than the first casualty of any overload.
This does not contradict ALP-153 and does not want it reverted: its shed-oldest
bound remains the correct floor that guarantees the call never OOM-dies. The
change is that the controller should relieve pressure through steps 1 and 2
first, so step 3 (ALP-153's mechanism) fires less often and later. Stated plainly
per the issue's instruction: keep ALP-153; add the earlier relief valves ahead
of it, and give the three existing valves one coordinator instead of three
independent triggers.

## What the user is told

A boolean pass is what misled the user, so every surface that today shows
supported/not-supported changes to show measured margin:

- **Per-component measurement** becomes a margin, not a checkmark: "Runs at 1.2x
  realtime; a dual-track call needs 2.0x - 40% short on this machine" instead of
  "Supported". The fit card already renders margins this way; the diarization
  card's persisted boolean unlock (`DiarizationCapabilityCard.tsx:262`) is the
  main surface that must change from pass/fail to margin.
- **Call-start admission** shows the aggregate: "Projected load about 2.3x this
  machine's sustained capacity, and peak memory near the container limit," with
  concrete, ranked reductions (capture a single track; choose a lighter
  diarizer; turn off live captions; move the text model to a LAN GPU box). This
  is a new surface; today `App.tsx:635-640` only blocks on the boolean
  transcription-readiness check.
- **Proceed-anyway is allowed with an honest warning** rather than blocked,
  naming what will degrade first (per the order above) so the choice is informed.
  A thin-margin start says what the controller will do; a negative-margin start
  says the call will run degraded from the outset.
- **Privacy First stays a hard, separate gate.** Privacy is binary and about
  destination; capacity is a measured, independent axis shown alongside it. A
  configuration can be private and over budget; the user sees both facts, not one
  collapsed into the other.

### What the 2026-07-27 configuration would have done instead

The planner would have summed diarization (2 tracks x the Sortformer factor,
which passed at RTF 0.70 for a single idle track and is therefore about 1.4x
realtime for two contended tracks before ASR and captioner load) + batch ASR +
the continuous captioner + the 4B text agents, projected sustained CPU well above
the machine budget and peak memory near the container limit, and returned
negative headroom. Instead of four green lights it would have shown one honest
verdict - "this configuration needs about 2.3x your machine" - with ranked
reductions. Had the user proceeded anyway, the runtime controller would have
dropped live captions and widened agent intervals before touching diarization,
and ALP-153's floor would have kept the call alive rather than letting it OOM.

## Relationship to the in-flight lanes

All four related issues are corner treatments of this same gap; this design is
the frame they sit inside, and each remains independently useful.

- **ALP-153 (fixed).** Keep as the controller's floor (never OOM). Generalized
  here so captions and agent cadence shed before diarization detail, and so the
  three independent relief valves gain one coordinator.
- **ALP-155 (benchmark honesty, codex w2:pH).** Becomes the measurement provider
  for the diarization term: it must output a per-track sustained realtime factor
  and a memory footprint under representative load, not a boolean unlock at RTF
  0.70. This design consumes those numbers; the benchmark's honesty is a
  precondition for the planner's numbers to mean anything.
- **ALP-154 (llm.py limits, claude w2:pJ; largely landed in-tree).** Provides
  the per-endpoint timeout (900s) and explicit max_tokens (8192) the latency
  term consumes, and its arbiter-trimming idea directly shrinks the text-agent
  cost term. Complementary and upstream of the planner's text-model inputs.
- **ALP-129 (cloud quota -> local fallback, claude-2 w2:pG).** The planner's
  headroom function is exactly the "does local have capacity to accept this work"
  query ALP-129 must ask before failing a cloud batch over to a local model.
  ALP-129 becomes a consumer of the planner.

## Non-goals

This design deliberately does not cover:

- GPU scheduling and contention modeling beyond treating a GPU-served model as
  off-CPU local load. ROCm/CUDA queue contention is out of scope.
- The measurement methodology of any individual benchmark beyond requiring
  per-track sustained-under-load numbers; that is ALP-155's work, consumed here.
- Cloud provider rate limits and spend caps themselves (ALP-129 owns detecting
  them); only the local-headroom half of the fallback decision is in scope.
- Monetary/token cost budgets. This is a compute budget, not a spend budget.
- Making the ALP-153 backlog constants operator-tunable (they are compile-time
  constants at `audio_runtime.py:208-209`); revisit only if the controller needs
  to vary them.
- Re-tuning the individual audio-pipeline constants (VAD threshold, segment
  bounds); the design consumes them as given.
- The desktop bundle's embedded PostgreSQL footprint beyond a fixed overhead
  constant.

## Known loose end surfaced during design

`LocalModelFitCard.tsx:373-374` still tells the user "Live interim captions have
no local option today (they need a cloud streaming model)," which contradicts the
now-local `local-parakeet-live` path. Not part of this design, but worth fixing
alongside the capacity work since the fit card is where captioner capacity will
be shown.

## Open questions for agreement

1. Is the degradation order (captions -> agent cadence -> diarization detail ->
   protect transcript -> never the call) the right product ranking? This is the
   one genuinely subjective call in the design.
2. Should a negative-margin configuration be refusable-with-override (proposed)
   or hard-blocked? The proposal favors an informed override.
3. Where should the planner physically live - a new service invoked at call start
   by the WebSocket handler, versus folding it into session start-up? (Deferred
   until the model is agreed.)
4. Is a first increment that only (a) sums the existing fit-card measurements plus
   track count into one call-start headroom verdict and (b) coordinates the three
   existing runtime valves under the priority order acceptable, with memory
   projection and per-endpoint latency to follow? Sequencing to be set with the
   lane owners.
