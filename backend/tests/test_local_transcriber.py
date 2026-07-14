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
