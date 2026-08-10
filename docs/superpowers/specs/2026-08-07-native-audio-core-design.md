# Backchannel: Intent, Measured CPU Cost, and the Case for a Native Core

Requested by: Talbert Houle
Performed by: Claude (Opus 5), agent/alp-token-cost-all
Date: 2026-08-07
Scope: Read the architecture and logic gates until the design intent is legible;
then theory-craft a ground-up rebuild (Rust and otherwise) aimed at the CPU cost
of a live session. Analysis and measurement only - no production code changed.

---

## Part 1 - The intent, read out of the architecture

### 1.1 What the application is for

Backchannel is a cognitive prosthetic for the person carrying a live business
conversation. The premise encoded everywhere in the code is that a human cannot
simultaneously participate in a conversation and analyze it, so the machine runs
the analytical half in parallel and surfaces what you would have noticed if you
had not been busy talking.

Three structural choices make that reading unambiguous:

- The audio gateway is a **silent listener** by design
  (`gemini_live.py`, `orchestrator.py:696`). It is an entire subsystem whose only
  job is to relay interim captions. It performs no analysis. It exists so the
  human can see the system is alive. That is a trust decision expensive enough to
  get its own agent slot.
- Analysis never blocks the conversation. Every text agent is an interval or
  event loop reading a shared buffer, never a request/response in the speaking
  path.
- The post-call surface (briefing, insights, chat over transcripts) is a
  first-class product, not an export. The system assumes the conversation has a
  second life.

### 1.2 The organizing principle: insight has a shelf life

The single most revealing thing in the codebase is the *spread* of the seeded
intervals, because they are not a performance compromise - they are a claim about
how fast different kinds of insight decay.

| Agent | Cadence | Window | Implied claim |
| --- | --- | --- | --- |
| `objection_handler` | 10s | last 90s | An objection answered late is worthless |
| `consolidated_analyst` | 40s | full buffer | Questions and observations keep |
| `strategic_signals` | 45s | full buffer | Strategy is a slow variable |
| `opportunity_specialist` | 55s cooldown | event-driven | Enrichment can lag its trigger |
| `synthesizer` | 75s cooldown / 120s max | whole corpus | Reconciliation is never urgent |

Read top to bottom, cost per invocation rises and urgency falls. The objection
handler gets the cheapest model (`gemini-3.5-flash-lite`) and the shortest window;
the synthesizer gets the most expensive (`gemini-3.1-pro-preview`) and the whole
corpus. **The scheduler is a latency hierarchy keyed to the decay rate of each
insight type.** That is the core design idea of the application.

### 1.3 What the code actually spends its effort on: refusing

Cataloguing the logic gates in the live path produces a lopsided result. Almost
every gate is a *suppression* gate, not a production gate:

- `transcript_window == last_window` -> skip the cycle entirely
  (`orchestrator.py:816`, `:894`)
- Unchanged insight corpus -> skip the synthesizer call (ALP-283)
- `_texts_similar` inside `_DEDUP_WINDOW_SECONDS = 300` -> drop the insight
  (`orchestrator.py:723`)
- `_MAX_ACTIVE_QUESTIONS = 24` -> cap what is carried into the prompt
- `_suppressed_analyst_types` -> delete the opportunity lens from the prompt on
  meeting types where enrichment is off (ALP-286)
- `should_defer_new_speaker_segment` -> suppress a short one-off speaker
- `MIN_SEGMENT_MS`, `MIN_NEW_SPEAKER_MS`, phantom-phrase and single-word filters
- `_shed_diarization_backlog` -> discard the oldest audio when behind (ALP-153)

The comments attached to these constants are the best documentation in the
repository, and they cite measurements from real meetings: a 57-minute call where
the median gap between later-merged insights was 1.0 minute; an active-question
list that grew to 45 entries and never shrank; an opportunity lens that produced
57 of 199 insights on a measured call, every one with an empty match.

**The intent here is explicit: the hard problem is not generating insight, it is
not drowning the user in it.** Backchannel is a suppression engine wearing a
generation engine's clothes. Any rebuild that reproduces the generation and not
the suppression will feel like a downgrade regardless of how fast it is.

### 1.4 The cost pyramid, and the layer nobody optimized

Sorting the runtime by invocation frequency produces a clean pyramid:

| Layer | Runs | Where | Cost/call | Optimized? |
| --- | --- | --- | --- | --- |
| 1. VAD | 31.25x/s/track | your CPU | microseconds | **no** |
| 2. Speaker embedding | per segment | your CPU | ~100ms wall | **no** |
| 3. Batch transcription | per segment | network | ~1s | partly |
| 4. Text agents | every 10-45s | network | seconds + tokens | heavily |
| 5. Synthesizer / briefing | every 75s+ / at end | network | seconds + many tokens | heavily |

Cost per invocation rises roughly 100x per layer and frequency falls roughly 100x
per layer. It is a well-proportioned design.

The entire `agent/alp-token-cost-all` branch - prompt ordering for cache prefixes,
insight volume, agent loop windows, the synthesizer working set - operates on
layers 4 and 5. That work is real and it was correctly targeted at *dollars*.

**Layers 1 and 2 are the only ones that run on your machine, and they are the only
ones nobody has tuned.** The token-cost instinct was right; it was simply never
pointed at the layers that cost watts instead of dollars. That is the whole CPU
story, and Part 2 quantifies it.

---

## Part 2 - Where the CPU actually goes (measured, not assumed)

### 2.1 Method

Measurements taken on this machine (28 logical cores, onnxruntime 1.21.1,
`.release-venv`) against the checked-in models. The metric throughout is
**process CPU time** (`time.process_time()`, summed across threads), because that
is what "the app eats CPU" means. Wall time is reported alongside so the latency
trade-off stays visible. All figures are warm - model load excluded.

Scripts are in the session scratchpad (`ort_bench.py`, `pytax_bench.py`,
`discard_bench.py`) and are reproducible.

### 2.2 Finding 1: ONNX Runtime is running on defaults, and the defaults are wrong here

There is **no `SessionOptions` anywhere in application code**. Both models are
constructed as `ort.InferenceSession(path, providers=["CPUExecutionProvider"])`
(`speaker_diarizer.py:39`, `:55`). ORT therefore picks its own intra-op thread
count - on a 28-core box, a lot of threads - and its thread pool spin-waits
between operators.

Silero VAD, 10 seconds of one track (312 frames):

| Config | Wall | CPU | CPU/frame | Cores consumed |
| --- | --- | --- | --- | --- |
| **ORT defaults (as shipped)** | 44.9ms | **156.2ms** | 0.501ms | **3.48** |
| `intra_op=1` | 34.5ms | 31.2ms | 0.100ms | 0.91 |
| `intra_op=1`, spin off | 36.5ms | 31.2ms | 0.100ms | 0.86 |

The shipped configuration uses **5x the CPU and is 23% slower in wall time** than
a single thread. For a 2.3MB LSTM invoked 31 times a second there is nothing to
parallelize; the thread pool is pure overhead. This is a strict loss on both axes.

WeSpeaker ResNet152-LM, one 5-second segment embedding:

| Config | Wall | CPU | Cores | Parallel efficiency |
| --- | --- | --- | --- | --- |
| **ORT defaults (as shipped)** | 138ms | **2,631ms** | **19.07** | **23%** |
| `intra_op=4` | 225ms | 883ms | 3.92 | 69% |
| `intra_op=1`, spin off | 611ms | 607ms | 0.99 | - |

This is the headline. The shipped configuration spends **2.6 CPU-seconds to do
0.6 CPU-seconds of arithmetic**. It buys a 4.3x wall-clock speedup by consuming
19 cores: **77% of the CPU burned by the speaker-embedding model is thread-pool
overhead, not math.**

At `intra_op=4` the same work costs 3.0x less CPU and is still 2.7x faster than
single-threaded - comfortably real-time for a 5-second segment.

### 2.3 Finding 2: 57% of the VAD loop is Python, not inference

Running the real `SpeakerDiarizer.feed_audio` over 20 seconds of audio (625 frames)
against the raw ORT cost for the same frame count:

| | CPU | Per frame |
| --- | --- | --- |
| `feed_audio` (full path) | 546.9ms | 0.875ms |
| Raw ORT inference only | 234.4ms | 0.375ms |
| **Python / numpy overhead** | **312.5ms** | **0.500ms (57%)** |

Per frame the loop allocates a numpy array from bytes, divides by 32768,
concatenates the context window, reshapes, re-casts, builds an input dict, and
crosses the FFI boundary - 31.25 times per second per track. This is the one place
in the codebase where interpreter overhead genuinely dominates, and it is the
strongest argument for a native core (Part 3).

### 2.4 Finding 3: two pieces of dead cost in the frame loop

**The diagnostic RMS block** (`speaker_diarizer.py:386-405`) runs
`np.sqrt(np.mean(frame_float ** 2))` plus a `hasattr` check on **every frame** in
order to emit one log line every 312 frames. Measured at **5.7% of `feed_audio`**.
It is 99.7% waste by construction: track the running max only, or drop it.

**The pending-audio drain** (`speaker_diarizer.py:379`) uses
`self._pending_audio = self._pending_audio[frame_bytes:]`, which copies the whole
remaining buffer once per frame.

| Chunk size | Slice-rebind (as written) | `del buf[:n]` in place |
| --- | --- | --- |
| 100ms | 23.4us | ~0us |
| 1000ms | 109.4us | 15.6us |

Small in absolute terms, but it is a genuine O(n^2) pattern that gets worse
exactly when the system is already behind - which is when the backlog shedder
fires.

### 2.5 Finding 4: embeddings computed, then thrown away

`_finalize_segment` (`speaker_diarizer.py:456`) extracts the full ResNet152
embedding at line 471, *before* `match_or_create` gets to decide whether the
segment is usable. When `allow_create` is False (segment shorter than
`MIN_NEW_SPEAKER_MS` = 4000ms) and no fallback-eligible profile exists,
`match_or_create` returns `auto_unknown` and `assign_full` returns `[]` - the
segment is dropped after the embedding has already been paid for.

Verified directly:

| Registry state | `match_or_create(allow_create=False)` |
| --- | --- |
| Empty (start of every call) | `auto_unknown` -> segment dropped |
| Only the enrolled local voice profile | `auto_unknown` -> segment dropped |
| One ordinary profile | `auto_1` -> segment kept |

The enrolled local voice profile is registered with
`fallback_for_unmatched=False` (`audio_runtime.py:36`), and `_best_profile(
fallback_only=True)` filters on that flag - so **with voice enrollment on, every
0.75-4s segment that does not match the enrolled user burns a full 79MB forward
pass and produces nothing**, until some other speaker's >=4s segment establishes a
fallback-eligible profile. That is the opening minutes of every call.

The fix is ordering, not logic: decide `allow_create` and check for a
fallback-eligible profile *before* extracting the embedding.

### 2.6 Finding 5: the frontend re-renders the whole tree at 60fps

`useAudioCapture` runs a `requestAnimationFrame` loop calling `setAudioLevel` and
`setSystemAudioLevel` (`useAudioCapture.ts:251-269`). Those states live in
`App.tsx:196` - the root of the component tree - and there is **no `React.memo`
anywhere in `frontend/src`**. For the entire duration of a call, the transcript
list, the insight list, and every other child re-render 60 times a second to
animate one audio meter.

The PCM16 worklet also accumulates samples with `Array.prototype.push` per sample
and `splice` per chunk, on the audio thread. It works, but a preallocated
`Int16Array` with a write cursor is strictly better.

### 2.7 The budget, measured end to end on real call audio

An earlier draft of this section composed the warm component measurements against
an assumed 40% speech density and arrived at ~0.48 CPU-s per wall-second. **That
was wrong by roughly 5x.** The corrected figure below is a direct end-to-end
measurement: 600 seconds of real recorded audio from two actual sessions, run
through the pipeline pinned to the committed version of `speaker_diarizer.py`.

| Measured over 600s of real call audio | Value |
| --- | --- |
| Segments produced | 110 |
| Embedding calls | **172** |
| Audio actually embedded | **725s (121% of input)** |
| Total CPU | 751.9s |
| **CPU per audio-second, one track** | **1.25** |
| of which embedding | 665.6s (89%) |
| of which VAD | 86.3s (11%) |
| **Two-track projection** | **~2.5 CPU-s per wall-second** |

**About 2.5 cores saturated, sustained, for the whole call** - before
transcription, before agents, before the frontend.

Three reasons the earlier estimate was low, all of which matter:

1. **Real speech density is ~90%, not 40%.** People talk almost continuously on
   these calls. Nearly every second of audio reaches the embedding model.
2. **The coherence path re-embeds.** 172 embedding calls produced only 110
   segments. `_coherence_groups` (`speaker_diarizer.py:501`) splits an unmatched
   segment into 3-second windows and runs a full ResNet152 pass on each, on top
   of the full-segment embedding already computed. A 15s segment costs six
   forward passes. This is roughly a third of all embedding calls.
3. **The thread pool spin-waits between calls.** The 19-core pool does not sleep
   after an inference returns, so its cost bleeds into whatever runs next rather
   than staying inside the 138ms window. Measured VAD cost inflates from 0.027 to
   0.144 CPU-s per audio-second purely from having a warm embedding pool
   alongside it. The overhead is not confined to the inference.

Since roughly 77% of the embedding cost is thread-pool overhead, **the large
majority of Backchannel's sustained local CPU during a call is ONNX Runtime
scheduling overhead, not speaker recognition.**

This re-frames ALP-153 sharply. `_shed_diarization_backlog` and
`MAX_DIARIZATION_BACKLOG_SECONDS = 30` exist because the diarizer could not keep
up and the container was OOM-killed 95 seconds into a call. At 2.5 cores of
demand per two-track call, **a 4-core laptop cannot keep up and never could.**
The backlog shedder is a symptom, not a fix: speaker attribution is currently
being traded away for CPU headroom that is available for free.

Note the wall-clock picture hides all of this. The same 600 seconds of audio
processed in 41.9 seconds of wall time - about 14x faster than real time - which
is exactly why this was never caught. Wall time looks healthy while the machine
burns two and a half cores.

---

## Part 3 - Rebuild theory-craft

### 3.1 The honest decomposition: what Rust buys, and what it does not

Sorting the measured cost by what a language change would actually affect:

| Cost | Share of local CPU | Does Rust help? |
| --- | --- | --- |
| ONNX thread-pool overhead | ~65% | **No** - it is ORT's scheduler, same in any host language. Fixed by configuration. |
| ONNX inference arithmetic | ~20% | **No** - identical kernels via the `ort` crate. Fixed by a smaller or quantized model. |
| Python/numpy per-frame glue | ~12% | **Yes, almost entirely** |
| Buffer management, dead diagnostics | ~3% | Yes, but also free in Python |
| Layers 3-5 (transcription, agents) | ~0% local | **No** - these are network waits |

This is the finding that should shape the decision. **The dominant cost is not
Python. It is ONNX Runtime configuration, and it is free to fix.** A ground-up
Rust rebuild that kept the current models and let `ort` pick its own thread
defaults would reproduce most of the problem faithfully.

Rust's genuine win - the per-frame path - is real but is roughly 12% of today's
budget. It becomes the *dominant* remaining cost only after the free fixes land,
at which point it is worth doing for different reasons (predictable latency, no
GIL contention with the event loop, a clean embeddable core).

### 3.2 Tier 0 - free, no rewrite, do this first

| # | Change | Expected effect |
| --- | --- | --- |
| 1 | `SessionOptions(intra_op_num_threads=1)` + spin off for the VAD | 5x less VAD CPU, *and* 23% faster |
| 2 | `SessionOptions(intra_op_num_threads=4)` for the embedding model | 3.0x less CPU, still 2.7x faster than serial |
| 3 | Delete the per-frame diagnostic RMS block | -5.7% of `feed_audio` |
| 4 | `del self._pending_audio[:frame_bytes]` | removes an O(n^2) drain |
| 5 | Check `allow_create` + fallback profile *before* extracting the embedding | removes wasted forward passes in the opening minutes |
| 6 | Frontend: audio level via ref + direct style write, or `React.memo` the lists | removes a 60fps whole-tree re-render |
| 7 | Gate the coherence split harder (it re-embeds in 3s windows and can double segment cost) | bounded worst case |

Items 1 and 2 are roughly fifteen lines in `speaker_diarizer.py`. Make the thread
counts settings so the desktop bundle can scale them to the host core count -
`intra_op=4` is right for 8+ cores; on a 4-core laptop, 2 is likely better.

**Projected budget after Tier 0: ~0.18 CPU-s per wall-second, down from ~0.48 -
about a 2.7x reduction, without changing a single architectural decision.**

### 3.3 Tier 1 - the Rust audio core

After Tier 0, the remaining local cost is roughly 80% embedding inference and 20%
Python frame glue. A native core targets the second and makes the first
predictable.

Proposed shape - `backchannel-audio`, a Rust crate exposed to Python via PyO3 as a
compiled extension module:

```
bytes in (WebSocket) -> [ Rust ] -> speaker-attributed PCM segments out
                          |
                          +-- lock-free ring buffer, zero per-frame allocation
                          +-- energy/ZCR pre-gate (cheap)
                          +-- Silero VAD (only on ambiguous frames)
                          +-- segmentation state machine
                          +-- embedding via `ort` crate, bounded shared pool
                          +-- speaker registry (cosine match, profile limits)
```

Why PyO3 rather than a sidecar process: the desktop bundle already ships
PyInstaller, and adding a compiled `.pyd`/`.so` is far less operational surface
than a second process with an IPC contract. The orchestration layer stays exactly
where it is.

The design idea worth stealing from the application's own philosophy: **an energy
pre-gate.** In a typical meeting 50-70% of frames are unambiguously silence. A
zero-crossing + RMS gate is ~100x cheaper than the neural VAD and only needs to
escalate ambiguous frames. This is precisely the suppression logic from Part 1.3
applied to CPU instead of tokens, and it roughly halves VAD cost on its own -
worth prototyping in Python first, since the idea is language-independent.

**What Rust does NOT buy: anything in layers 3-5.** The agent orchestration is
prompt construction, JSON parsing, and awaiting network calls. Rust makes that no
faster and materially slower to change - and with 404 commits in the first month,
overwhelmingly in the agent and prompt layer, that is the part of the codebase you
least want to make expensive to edit. Recommendation: **leave the orchestrator in
Python permanently.**

### 3.4 Tier 2 - the model question, which is bigger than the language

After Tier 0 and Tier 1, essentially all remaining local CPU is one model:
WeSpeaker ResNet152-LM, 79MB, per segment.

This section originally posed two open questions. The first has since been
settled and the answer was no.

**SETTLED (ALP-292): ResNet152 stays.** The hypothesis that the larger model was
buying precision the 0.68 threshold already discards is wrong. Measured on real
Backchannel audio with a paired test over identical pair sets, ResNet152's
overlap rate - the probability a different-speaker pair scores at least as high
as a same-speaker pair - is 0.920% against ResNet34's 1.581% at 1.5s windows over
278 positives; difference +0.661%, 95% CI [+0.287, +1.096], P(152 better) 100%.
Equal error rate 3.61% against 5.37%. ResNet34 also over-segments concretely:
208 enrollments against 185 over the same ten recordings, and one extra phantom
speaker on two of them.

So the trade on offer was 1.7-1.9x more speaker confusion to save 3.3x CPU on a
component Tier 0 had already made ~4x cheaper. Declined. Full evidence and
method: `docs/superpowers/reviews/2026-08-07-alp-292-embedding-model-ab.md`.

Worth recording, because it cost the evaluation a redesign: **the per-track split
recordings are not usable as labels on this corpus.** Five of six two-sided
recordings carry speakerphone echo, and the two with a silent output track are
in-person meetings whose single mic holds the whole room. Anyone reaching for
that shortcut again should read section 3 of the ALP-292 report first.

**Still open: does INT8 dynamic quantization cost any accuracy?** ORT supports it
directly; for speaker embeddings the typical loss is negligible and CPU falls
2-3x. This is now the only remaining lever of that size, and the ALP-292 harness
can score it the same way - the comparison machinery already exists, so this is
a much cheaper question to answer than the first one was.

The framing still holds even though the answer changed: **the model is the cost;
the language is the glue.** It is simply that this particular model earns it.

### 3.5 Tier 3 - the architectural move: run the VAD in the browser

The most interesting option on the table is not a Rust option.

Move Silero VAD into the client, in a Web Worker fed from the existing
AudioWorklet via a `SharedArrayBuffer` ring, using onnxruntime-web with WASM SIMD.
This is a proven pattern. Then send only frames the VAD marked as speech.

Consequences:

- Layer 1 leaves the server **entirely**. The backend's per-frame path disappears.
- WebSocket traffic drops by the silence ratio - typically 50-70%.
- The diarization backlog problem largely dissolves; the server only ever sees
  speech.
- Privacy First gets *stronger*: silence never leaves the machine.
- The 2.3MB model ships to the browser once and caches.

Trade-offs to name honestly: VAD state moves per-client, the backend must trust
client-side segmentation (fine for a single-user desktop app; it is a compute
placement decision, not a security boundary), and mid-call reconnects need to
re-establish VAD state. It also means two VAD implementations if the server keeps
one for imported-audio paths.

### 3.6 What a true ground-up Rust rebuild would look like, and what it would cost

If the goal is one binary rather than incremental optimization:

| Component | Rust? | Rationale |
| --- | --- | --- |
| Audio ingest, ring buffers, VAD, segmentation | **Yes** | The only sustained-CPU path. Real win. |
| Speaker embedding + registry | **Yes** (via `ort`) | Same kernels; win is bounded pools and no marshalling |
| WebSocket + REST server | Yes (axum/tokio) | Clean, but this was never the bottleneck |
| Persistence | Yes (sqlx) | Straightforward |
| Agent orchestration, prompts, LLM calls | **No** | Network-bound; Rust taxes the fastest-changing code |
| Frontend | No change needed | It is fine once the re-render is fixed |

**The real risk of the rewrite is not the language - it is the loss of tuning
provenance.** The diarization and speaker-assignment logic carries a lot of
hard-won empirical calibration: coherence splitting, ghost filtering, profile
limits, fallback reuse, the 0.68 threshold, the 4000ms new-speaker floor. Those
numbers were earned against real meetings and most are undocumented outside code
comments. Porting them means re-validating every one.

Mitigation: treat `backend/scripts/diarizer_ab.py` plus the stored call audio as
the acceptance harness, and require the Rust core to match the Python core's
speaker attribution on real recorded calls before it is allowed to replace it.

### 3.7 Projected budget by tier

Two tracks, anchored to the **measured** 2.5 CPU-s/wall-second baseline from
section 2.7. Everything below the first row is a projection and should be
replaced with measurements as each tier lands.

Re-measured on v0.5.0. The original numbers were taken against a v0.3.8 base;
this work was later ported onto v0.5.0 (170 commits later) and the measurement
repeated on the same 600 seconds of real call audio, with the baseline pinned to
the v0.5.0 diarizer as committed.

| Stage | CPU-s per wall-second | vs baseline |
| --- | --- | --- |
| v0.5.0 as shipped (**measured**) | **2.27** | 1.0x |
| + Tier 0, session options + frame loop (**measured**) | **0.39** | **5.75x** |
| + Tier 3, VAD in the browser (projected) | ~0.38 | ~6x |
| + Tier 1, Rust audio core (projected) | ~0.37 | ~6x |
| + INT8 quantized embedding (projected, unevaluated) | ~0.12 | ~19x |

The first two rows are measured end to end, pinned to the committed diarizer
before and after. Everything below them is projection.

Output parity held across the port: both sides produced 110 identical segments
and 172 identical embedding calls. The VAD fell from 79.8 to 2.7 CPU-seconds, a
29x drop, and wall time was essentially unchanged this run (37.8s to 39.2s) - the
wall-time cost documented below is real but load-dependent, and did not
materialize on an uncontended machine.

Two rows changed meaning since the first draft, and both changes matter.

**Tier 0 delivered 4.7x, and it was configuration, not code.** The measured split
after the change is 98% embedding, 2% VAD - the VAD fell from 86.3s to 3.4s of
CPU over the same audio, a 25x drop from a change that mostly just set a thread
count. Most of that was never VAD cost at all: it was the embedding pool's
spin-wait bleeding into the frames that followed it. Measured directly, the
as-shipped configuration burns 894.5ms of CPU during a 300ms *idle* gap after an
inference returns; with spinning disabled, 0.0ms.

The deployment result is starker than the ratio suggests. Emulating a 2-CPU
container quota with an affinity mask - `os.cpu_count()` still reports the host's
28, which is exactly what ORT sees under a quota - the **old** configuration
processed audio at **134% of realtime**. It could not keep up with the
conversation, which is precisely the ALP-153 backlog-shed spiral. The same audio
under the bounded pool runs at 14.2%. Capping the pool is what makes ORT's
blindness to container CPU quotas stop mattering.

**Tier 2 is closed, not pending.** ResNet34 was evaluated and lost (section 3.4).
The coherence-split gating that appeared in an earlier version of this row was
also evaluated and declined: the windows partition the segment, so total embedded
audio is fixed and capping them saves nothing, and the splits are load-bearing -
each one prevents a spurious speaker enrollment. Both were plausible on paper and
neither survived measurement.

That leaves INT8 quantization as the only remaining lever of consequence, and it
is unevaluated. The ALP-292 harness can score it with the machinery already
built.

One structural caveat on all of this, from ALP-293: `MAX_SPEAKER_PROFILES_PER_TRACK`
is 4 and the application log shows that cap binding 350 times. On calls where it
binds, the registry has stopped discriminating regardless of which embedding model
is loaded - so past four voices, none of this section's trade-offs apply.

### 3.8 Recommended sequence

Steps 1 and 2 are **done**; the rest stands.

1. ~~Tier 0.~~ **Done (ALP-289, ALP-290).** Measured 4.0x on real call audio.
   Output provably unchanged: identical segment hashes and PCM at every emulated
   host size, embeddings bit-identical across thread configurations.
2. ~~Settle the model question.~~ **Done (ALP-292).** ResNet152 stays. The A/B
   also invalidated the labelling scheme this document originally proposed, and
   the harness now validates recordings instead of trusting them.
3. **Prototype the energy pre-gate in Python.** Unchanged and still worth doing.
   The idea is language-independent, so validate it before committing to Rust.
   Note it now targets the 3% of the budget that is VAD rather than the 11% it
   was before Tier 0, so its ceiling is lower than originally implied.
4. **Evaluate INT8 quantization of the embedding model.** This has moved up. It
   is the only remaining lever comparable in size to Tier 0, the harness to score
   it already exists, and it is an evaluation rather than an engineering project.
5. **Then decide on the native core**, with the real remaining budget in hand.

That budget is now known rather than assumed, and it argues against the rewrite
more strongly than the first draft did. After Tier 0, **97% of what remains is
ONNX inference inside one model** - arithmetic that Rust executes with the
identical kernels. The projected Rust win fell from "a few percent" to
approximately that, of a number already 4x smaller.

So: build the Rust core if you want a predictable, embeddable, GIL-free audio
engine, which is a legitimate goal on its own terms. Do not build it expecting it
to fix the CPU. The measurements said that was a configuration problem wearing a
language problem's clothes, and setting the configuration proved it.

---

## Open questions for the author

1. What is the actual target machine? Every number here is from a 28-core
   workstation. On a 4-core laptop the wall-clock picture inverts - the embedding
   model would be near or past real-time - and that changes the Tier 2 urgency
   substantially.
2. Was ResNet152 chosen deliberately over ResNet34, and against what evidence?
   The code comment documents the filename confusion but not the selection
   rationale.
3. Is the coherence-split path earning its cost in practice? It can double
   embedding cost on the segments that take it, and it only fires on unmatched
   speech.
4. Is one binary an actual goal (distribution, licensing, startup time), or is
   CPU the whole motivation? The answer decides whether Tier 1 is worth it after
   Tier 0 and Tier 2 land.
