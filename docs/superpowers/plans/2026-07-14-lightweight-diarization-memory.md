# Lightweight Diarization Memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove duplicated optional Sortformer memory from lightweight live calls without changing diarization behavior.

**Architecture:** Replace the dependency-checking startup wrapper with Uvicorn in the same process, then make Sortformer environment probing opt-out for internal lightweight execution paths. Diagnostics and selected-Sortformer paths retain the full probe.

**Tech Stack:** Python 3.12, FastAPI, asyncio, unittest, Docker Compose

## Global Constraints

- Keep the live speaker similarity threshold at 0.68.
- Preserve lightweight and selected-Sortformer fallback behavior.
- Diagnostics endpoints must continue to report the real Sortformer environment.
- Add no dependencies or new services.

---

### Task 1: Replace the startup wrapper process

**Files:**
- Create: `backend/tests/test_start_backend.py`
- Modify: `backend/scripts/start_backend.py`

**Interfaces:**
- Consumes: `ensure_sortformer_installed(required=False)` and `BACKEND_RELOAD`.
- Produces: `main()` replacing its process with the exact Uvicorn argv.

- [ ] **Step 1: Write the failing test**

Load `backend/scripts/start_backend.py` by file path, mock `ensure_sortformer_installed` and `os.execvp`, call `main()` with reload disabled, and assert:

```python
execvp.assert_called_once_with(
    "uvicorn",
    ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"],
)
```

Add a second assertion with reload enabled that the argv ends in `--reload`.

- [ ] **Step 2: Run the test to verify RED**

Run: `python -m unittest tests.test_start_backend -v`

Expected: FAIL because `main()` calls `subprocess.run` and never calls `os.execvp`.

- [ ] **Step 3: Implement the minimal process replacement**

Remove the unused `subprocess` import, import `os`, preserve the existing command construction, and replace:

```python
return subprocess.run(command).returncode
```

with:

```python
os.execvp(command[0], command)
return 0
```

- [ ] **Step 4: Run the test to verify GREEN**

Run: `python -m unittest tests.test_start_backend -v`

Expected: both tests PASS.

### Task 2: Skip the Sortformer probe for lightweight execution

**Files:**
- Modify: `backend/app/services/diarizer_runtime.py`
- Modify: `backend/app/ws/audio_handler.py`
- Modify: `backend/app/routers/imports.py`
- Modify: `backend/tests/test_diarizer_runtime.py`

**Interfaces:**
- Consumes: selected diarizer setting and optional `SortformerEnvironment`.
- Produces: `get_diarizer_runtime_config(db, environment=None, probe_sortformer=True)`.

- [ ] **Step 1: Write the failing tests**

Add one test that patches `probe_sortformer_environment` to raise, selects `lightweight`, calls:

```python
runtime = asyncio.run(get_diarizer_runtime_config(db, probe_sortformer=False))
```

and asserts the effective mode is lightweight. Add one test selecting Sortformer and assert the probe is still called when `probe_sortformer=False`.

- [ ] **Step 2: Run the tests to verify RED**

Run: `python -m unittest tests.test_diarizer_runtime -v`

Expected: FAIL because `probe_sortformer` is not accepted and the probe is unconditional.

- [ ] **Step 3: Implement the minimal lazy probe**

Read the selected mode before resolving the environment. When `probe_sortformer=False` and selected mode is lightweight, construct a non-available `SortformerEnvironment` with reason `Lightweight diarization is active; Enhanced availability was not probed for this request.` Otherwise call the existing probe. Pass `probe_sortformer=False` only from live WebSocket and audio-import execution.

- [ ] **Step 4: Run targeted and full tests**

Run:

```text
python -m unittest tests.test_start_backend tests.test_diarizer_runtime tests.test_audio_handler -v
python -m unittest discover -s tests -v
```

Expected: targeted tests PASS and the full backend suite PASS.

### Task 3: Verify the real Docker and browser behavior

**Files:**
- No production files.

**Interfaces:**
- Consumes: feature Docker stack and Google Recorder fixture.
- Produces: measured Docker/browser acceptance evidence.

- [ ] **Step 1: Recreate the feature backend with reload disabled**

Run the existing `r2-master-rollout` Compose project with `BACKEND_RELOAD=false`, no rebuild, and the feature worktree bind mount.

- [ ] **Step 2: Verify process and idle memory**

Run `docker top` and confirm one Uvicorn process rather than a retained startup parent plus child. Record idle RSS and cgroup memory.

- [ ] **Step 3: Run the full Recorder gate**

Use exactly Me, Remote A, and Remote B; share the Recorder tab with audio; complete the 28:13 playback; then perform one short Resume and End.

- [ ] **Step 4: Verify acceptance**

Confirm the backend was not OOM-killed, the session completed, there are exactly three speakers, both remotes have transcripts, Me contains only actual microphone speech, there are no consecutive duplicate transcripts, and the two-call lifecycle has two closed segments with one resume marker.

- [ ] **Step 5: Update ALP-77 and run the integration gate**

Record measured memory and browser evidence in Linear. Then run branch verification, merge, recreate Docker from master, smoke-test, and only afterward package installers.
