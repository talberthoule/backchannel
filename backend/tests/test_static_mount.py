import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI


class MountFrontendTests(unittest.TestCase):
    def test_noop_when_dist_unset(self):
        from app.main import mount_frontend

        app = FastAPI()
        before = len(app.routes)
        mount_frontend(app, "")
        self.assertEqual(len(app.routes), before)

    def test_mounts_static_files_when_dist_set(self):
        from app.main import mount_frontend

        app = FastAPI()
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "index.html").write_text("<html></html>")
            mount_frontend(app, tmp)
            self.assertTrue(
                any(getattr(r, "name", "") == "frontend" for r in app.routes)
            )


if __name__ == "__main__":
    unittest.main()
