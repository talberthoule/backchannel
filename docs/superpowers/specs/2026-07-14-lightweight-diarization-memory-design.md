# Lightweight Diarization Memory Design

## Goal

Remove optional Sortformer memory from lightweight live calls so local Whisper and lightweight diarization can run within ordinary Docker headroom.

## Evidence

- Docker Desktop has 15.45 GiB total memory, while unrelated containers currently consume about 11.665 GiB and swap is exhausted.
- The Backchannel startup wrapper retains a 731,576 KiB Python parent after checking Torch and NeMo, then launches Uvicorn as a child.
- A single read-only Sortformer environment probe raised the Uvicorn worker from 166,556 KiB RSS to 807,020 KiB RSS even though the selected and effective diarizer are both `lightweight`.
- The earlier accepted split-track replay peaked at 2.927 GiB. The two optional Sortformer costs are sufficient to explain the browser run crossing the global Docker boundary.
- The failed browser run still produced exactly Me, Remote A, and Remote B; Remote A=22, Remote B=2, Me=0; no duplicates or phantom speakers. The ALP-77 coherence changes are bounded and are not the GiB-scale source.

## Design

1. After the optional dependency check, the Docker startup wrapper will replace itself with Uvicorn via `os.execvp` instead of retaining a Python parent around `subprocess.run`.
2. `get_diarizer_runtime_config` will accept an internal `probe_sortformer` switch. Live calls and audio imports will pass `False`; when lightweight is selected, the function will use a cheap, explicit "not probed" environment. If Sortformer is selected, it will still probe and preserve fallback behavior.
3. Diagnostics and configuration endpoints keep their current default probe behavior and continue reporting real Torch, NeMo, GPU, benchmark, and availability data.

## Error Handling

- `os.execvp` failures propagate and fail container startup instead of leaving a half-started wrapper.
- Skipping the probe is allowed only when the selected mode is lightweight. A selected Sortformer mode always performs the existing availability probe.

## Verification

- Unit tests must fail first for retained subprocess startup and for a lightweight runtime call that invokes the Sortformer probe.
- Targeted tests then prove process replacement, reload flag preservation, lightweight probe avoidance, and selected-Sortformer probing.
- The full backend suite must remain green.
- A fresh Docker backend must show one server process, a substantially lower idle RSS, and no worker RSS jump when starting a lightweight call.
- The full Chrome/Recorder gate must complete without OOM, with exactly Me/Remote A/Remote B, no phantom or duplicate transcript, and a clean resume/end lifecycle.

## Non-goals

- Do not change the 0.68 speaker threshold, coherence window, ASR model, or transcript ordering.
- Do not stop unrelated projects as the product fix.
- Do not redesign transcription admission or Google client lifetimes unless a later isolated test proves they are independent blockers.
