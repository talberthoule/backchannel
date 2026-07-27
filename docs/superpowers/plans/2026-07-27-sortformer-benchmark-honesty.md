# Sortformer Benchmark Honesty Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unlock Sortformer only when it sustains a dual-track call with load reserve, while reporting measured throughput and residual risk.

**Architecture:** Keep the existing upload endpoint and model adapter. Replay one live-size sample three times through one loaded model, classify aggregate RTF against a 3x realtime requirement, and make every selection check validate the stored RTF against the current threshold so old false passes are revoked. Reuse the existing diagnostics card's `selection_reason` surface instead of adding UI state.

**Tech Stack:** Python 3, stdlib `unittest`, FastAPI service layer, React/TypeScript existing diagnostics card.

## Global Constraints

- Work only in `C:/work/backchannel/alp-155` on `agent/alp-155-benchmark-honesty`.
- Do not modify `backend/app/services/llm.py` or the shared checkout.
- Use three benchmark windows, two live tracks, and a 1.5 contention reserve.
- Add no dependency, migration, background load generator, or new frontend state.

---

### Task 1: Prove the current verdict is unsafe

**Files:**
- Modify: `backend/tests/test_diarization_diagnostics.py`
- Modify: `backend/tests/test_diarizer_selection.py`

**Interfaces:**
- Consumes: `BenchmarkMeasurement`, `classify_benchmark`, `sortformer_is_selectable`
- Produces: failing tests for the dual-track threshold, user-facing margin, and stale stored passes

- [ ] **Step 1: Write the failing classification tests**

Add literal expectations:

```python
def test_classify_benchmark_rejects_old_single_track_false_pass(self):
    result = classify_benchmark(BenchmarkMeasurement(
        audio_seconds=60.0,
        processing_seconds=36.0,
        device="cpu",
        model_id="test-model",
    ))
    self.assertEqual("failed", result.status)
    self.assertIn("1.67x realtime", result.reason)
    self.assertIn("3.0x required", result.reason)

def test_classify_benchmark_warns_when_passing_margin_is_thin(self):
    result = classify_benchmark(BenchmarkMeasurement(
        audio_seconds=60.0,
        processing_seconds=19.0,
        device="cuda",
        model_id="test-model",
    ))
    self.assertEqual("passed", result.status)
    self.assertIn("thin", result.reason.lower())
```

- [ ] **Step 2: Write the failing stale-pass selection test**

```python
def test_old_pass_is_not_selectable_when_rtf_misses_current_requirement(self):
    self.assertFalse(sortformer_is_selectable(
        benchmark_status="passed",
        sortformer_available=True,
        benchmark_real_time_factor=0.60,
    ))
```

- [ ] **Step 3: Verify RED**

Run:

```powershell
python -m unittest tests.test_diarization_diagnostics tests.test_diarizer_selection -v
```

Expected: the 0.60 RTF still passes, the reason lacks measured headroom, and the selection helper does not accept an RTF argument.

### Task 2: Implement the sustained dual-track gate

**Files:**
- Modify: `backend/app/services/diarization_diagnostics.py`
- Modify: `backend/app/services/diarizer_selection.py`
- Modify: `backend/app/services/diarizer_runtime.py`
- Modify: `backend/tests/test_diarization_diagnostics.py`
- Modify: `backend/tests/test_diarizer_selection.py`
- Modify: `backend/tests/test_diarizer_runtime.py`

**Interfaces:**
- Consumes: stored benchmark status and RTF, one uploaded live-size audio sample
- Produces: `SORTFORMER_RTF_THRESHOLD`, `SORTFORMER_BENCHMARK_WINDOWS`, `describe_benchmark_headroom()`, and RTF-aware selection

- [ ] **Step 1: Add the requirement constants and margin description**

In `diarization_diagnostics.py`, set:

```python
SORTFORMER_LIVE_TRACKS = 2
SORTFORMER_CONTENTION_RESERVE = 1.5
SORTFORMER_BENCHMARK_WINDOWS = 3
SORTFORMER_RTF_THRESHOLD = 1 / (
    SORTFORMER_LIVE_TRACKS * SORTFORMER_CONTENTION_RESERVE
)
SORTFORMER_THIN_MARGIN = 0.25
```

Add `describe_benchmark_headroom(real_time_factor, threshold, passed)` that formats measured throughput (`1 / RTF`), required throughput (`1 / threshold`), percentage headroom, and the thin-margin warning. Call it from `classify_benchmark`.

- [ ] **Step 2: Replay three windows with one model**

After loading and preparing the model, call `_run_diarization` exactly three times. Sum elapsed processing time and classify it against `audio_seconds * SORTFORMER_BENCHMARK_WINDOWS`.

Add a test that patches `_audio_duration_seconds`, environment probing, model loading, preparation, `_run_diarization`, and `time.perf_counter`; assert three runs and aggregate audio/processing seconds.

- [ ] **Step 3: Make selection validate current RTF**

Change:

```python
sortformer_is_selectable(
    benchmark_status,
    sortformer_available,
    benchmark_real_time_factor,
)
```

to require a finite RTF at or below `SORTFORMER_RTF_THRESHOLD`. Thread the RTF through `resolve_effective_diarizer_mode`, `get_diarizer_runtime_config`, and `set_selected_diarizer`.

Add a runtime test with stored `status="passed"` and `rtf="0.32"` that asserts `selection_reason` includes measured throughput, the 3.0x requirement, and the thin-margin warning.

- [ ] **Step 4: Verify GREEN**

Run:

```powershell
python -m unittest tests.test_diarization_diagnostics tests.test_diarizer_selection tests.test_diarizer_runtime -v
```

Expected: all focused tests pass.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/services/diarization_diagnostics.py backend/app/services/diarizer_selection.py backend/app/services/diarizer_runtime.py backend/tests/test_diarization_diagnostics.py backend/tests/test_diarizer_selection.py backend/tests/test_diarizer_runtime.py
git commit -m "fix: make Sortformer benchmark reflect live load"
```

### Task 3: Document and verify the user-visible contract

**Files:**
- Modify: `docs/audio-pipeline.md`
- Modify: `backend/app/release_notes.py`

**Interfaces:**
- Consumes: the implemented three-window, 3x requirement
- Produces: operator documentation and release-note copy matching runtime behavior

- [ ] **Step 1: Update the benchmark documentation**

State that one 15-20 second input is replayed for three windows and that passing requires 3x measured throughput: two tracks plus the 1.5 load reserve.

- [ ] **Step 2: Add one release-note bullet**

Add a bullet to the current release describing that Enhanced diarization no longer unlocks from a single-track benchmark that cannot sustain mic plus system audio.

- [ ] **Step 3: Run complete verification**

```powershell
python -m unittest discover -s tests
cd ../frontend
npm run build
cd ..
sentrux check .
sentrux gate .
git diff --check
```

Expected: all tests/builds pass; Sentrux reports no unapproved structural regression; the worktree is clean after the final commit.

- [ ] **Step 4: Request independent review**

Send the frozen commit SHA and verification summary to `claude-comparison-1`, address any blocker, then send the reviewed SHA to the default-branch integrator. Do not merge or push from this lane.
