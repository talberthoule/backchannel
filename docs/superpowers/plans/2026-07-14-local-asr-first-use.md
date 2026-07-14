# Local ASR First-Use Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let both configured `onnx-asr 0.11` local models download on first use while preserving populated caches and the existing data directory.

**Architecture:** Create only the shared cache parent, remove an empty legacy model child, and pass the child path to the already-installed `onnx_asr.load_model()` resolver. Keep the current in-process lock and error boundary; add no downloader or cache abstraction.

**Tech Stack:** Python 3.12, stdlib `unittest`, `pathlib`, installed `onnx-asr 0.11`, Docker.

## Global Constraints

- Preserve `DATA_DIR/asr-models/<onnx-asr-model-name>` for Whisper and Parakeet.
- An absent or empty child must be absent when passed to `onnx_asr.load_model()` so its built-in first-use download runs.
- A populated child must remain byte-for-byte untouched and load offline.
- Keep `_load_lock`; current Docker and desktop servers are single process.
- A populated partial cache remains a documented manual-deletion recovery boundary.
- Add no dependency, downloader, repository mapping, validation manifest, cross-process lock, configuration, database, caller, or installer change.

---

### Task 1: Stop Empty Cache Directories from Forcing Offline Resolution

**Files:**
- Create: `backend/tests/test_local_transcriber.py`
- Modify: `backend/app/services/local_transcriber.py:24-36`

**Interfaces:**
- Consumes: `LOCAL_MODEL_MAP`, `data_dir() -> pathlib.Path`, and `onnx_asr.load_model(name, path)`.
- Produces: `_load_model(model_id)` with absent/empty/populated cache semantics for both local model IDs.

- [ ] **Step 1: Write the failing network-free cache test**

Create `backend/tests/test_local_transcriber.py`:

```python
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.services import local_transcriber


class LocalModelCacheTests(unittest.TestCase):
    def tearDown(self):
        local_transcriber._loaded.clear()

    def test_prepares_cache_path_without_touching_populated_caches(self):
        models = (
            ("local-whisper-base", "whisper-base"),
            ("local-parakeet-tdt-0.6b", "nemo-parakeet-tdt-0.6b-v2"),
        )

        for model_id, name in models:
            for state in ("absent", "empty", "populated"):
                with self.subTest(model_id=model_id, state=state), tempfile.TemporaryDirectory() as tmp:
                    local_transcriber._loaded.clear()
                    root = Path(tmp)
                    path = root / "asr-models" / name
                    marker = path / ".partial"

                    if state != "absent":
                        path.mkdir(parents=True)
                    if state == "populated":
                        marker.write_text("keep", encoding="utf-8")

                    sentinel = object()

                    def fake_load_model(actual_name, actual_path):
                        self.assertEqual(name, actual_name)
                        self.assertEqual(path, actual_path)
                        self.assertTrue(path.parent.is_dir())
                        self.assertEqual(state == "populated", path.exists())
                        if state == "populated":
                            self.assertEqual("keep", marker.read_text(encoding="utf-8"))
                        return sentinel

                    fake_onnx_asr = SimpleNamespace(
                        load_model=Mock(side_effect=fake_load_model)
                    )
                    with (
                        patch.object(local_transcriber, "data_dir", return_value=root),
                        patch.dict(sys.modules, {"onnx_asr": fake_onnx_asr}),
                    ):
                        self.assertIs(sentinel, local_transcriber._load_model(model_id))

                    fake_onnx_asr.load_model.assert_called_once_with(name, path)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
docker run --rm -e PYTHONDONTWRITEBYTECODE=1 `
  -v "${PWD}\backend\app:/app/app" `
  -v "${PWD}\backend\tests:/app/tests" `
  -w /app r2-master-rollout-backend:latest `
  python -m unittest tests.test_local_transcriber
```

Expected: FAIL for absent and empty states because `_load_model()` creates the child before the fake loader observes it.

- [ ] **Step 3: Implement the minimal cache-path correction**

Replace the path setup in `_load_model()` with:

```python
            name = LOCAL_MODEL_MAP[model_id]
            models_dir = data_dir() / "asr-models"
            models_dir.mkdir(parents=True, exist_ok=True)
            path = models_dir / name
            # onnx-asr 0.11 treats any existing local_dir as offline.
            # ponytail: populated partial caches need manual deletion; add staged downloads if recovery matters.
            if path.is_dir() and not any(path.iterdir()):
                path.rmdir()
            logger.info(f"Loading local ASR model {name} (downloads on first use)")
            _loaded[model_id] = onnx_asr.load_model(name, path)
```

- [ ] **Step 4: Run focused and complete backend tests**

Run:

```powershell
docker run --rm -e PYTHONDONTWRITEBYTECODE=1 `
  -v "${PWD}\backend\app:/app/app" `
  -v "${PWD}\backend\tests:/app/tests" `
  -w /app r2-master-rollout-backend:latest `
  python -m unittest tests.test_local_transcriber

docker run --rm -e PYTHONDONTWRITEBYTECODE=1 `
  -v "${PWD}\backend\app:/app/app" `
  -v "${PWD}\backend\tests:/app/tests" `
  -v "${PWD}\frontend:/frontend:ro" `
  -w /app r2-master-rollout-backend:latest `
  python -m unittest discover -s tests
```

Expected: focused test PASS and every backend test PASS.

- [ ] **Step 5: Commit the verified first-use fix**

```powershell
git add -- backend/app/services/local_transcriber.py backend/tests/test_local_transcriber.py
git diff --cached --check
git commit -m "fix: allow local ASR first-use downloads"
```

Expected: one production file and one test file committed; no dependency, caller, configuration, or installer changes.
