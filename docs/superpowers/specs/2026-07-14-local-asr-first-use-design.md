# Local ASR First-Use Cache Design

## Goal

Make both key-free local transcription choices download successfully on their
first use in Docker and desktop builds without adding a downloader, dependency,
or provider-specific path:

- `local-whisper-base` -> `whisper-base`;
- `local-parakeet-tdt-0.6b` -> `nemo-parakeet-tdt-0.6b-v2`.

This is tracked separately from speaker coherence because it has an independent
cause, implementation seam, and verification path.

## Root Cause

`backend/app/services/local_transcriber.py` currently creates the exact model
directory before calling `onnx_asr.load_model(name, path)`. In `onnx-asr 0.11`,
an existing `local_dir` selects offline resolution. A fresh empty directory is
therefore interpreted as an installed model cache, and the resolver fails before
its built-in Hugging Face download fallback can run.

Both configured model names already exist in the library's repository mapping.
The application does not need to reproduce that mapping or call a second
download API.

## Design

Create only the shared `asr-models` parent directory. Before loading a model:

1. derive the child path for the selected `onnx-asr` model name;
2. if that child exists and is empty, remove it;
3. pass the child path to `onnx_asr.load_model()` whether it exists or not.

The library then sees a missing child on first use and performs its existing
online download. A populated child remains untouched and loads offline.

The existing process-level `_load_lock` continues to serialize model loads in
the Docker and desktop single-server runtime. No new lock or cache abstraction
is added.

## Recovery Boundary

A populated but incomplete cache remains an offline failure in `onnx-asr 0.11`.
Automatic repair would require validating model-specific file sets, staging a
download, publishing atomically across Windows, macOS, and Linux, and handling
cross-process locking. That complexity is not justified by the current
single-process product and is deferred explicitly. Recovery is to delete the
affected model directory and retry.

Permission failures, symlinks or junctions, and external processes racing over
the same cache may still raise. Those errors remain inside the existing local
transcription error boundary, so one failed model load does not crash the audio
WebSocket.

## Compatibility

The change uses only `pathlib` operations and the installed `onnx-asr` loader.
An empty directory contains no model data, so removing it is safe. Hidden files
make a directory populated and therefore prevent removal. No configuration,
database, caller, installer manifest, or dependency file changes are required.

## Verification

A network-free unit test will replace `onnx_asr` with a fake loader and exercise
both configured models in three states:

- absent child: the parent exists and the child remains absent when handed to
  the loader;
- empty child: it is removed before the loader is called;
- populated child: its marker file remains unchanged and the existing path is
  handed to the loader.

The test clears the process cache between cases and asserts the exact model name
and path for every call. The full backend suite must remain green.

After the unit gate, Docker first-use validation will select a local model with
an absent cache directory, observe download progress and successful
transcription, restart the backend, and confirm the populated cache is reused
without another download. Whisper is the primary smoke test; Parakeet receives
the same unit coverage and a first-use smoke test when network and disk budget
permit. Installer packaging waits for the Docker gate.
