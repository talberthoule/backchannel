import os
import socket
import unittest
from pathlib import Path
from unittest import mock

from bcdesktop.paths import app_data_dir, free_port, resource


class PathsTests(unittest.TestCase):
    def test_app_data_dir_env_override_wins(self):
        with mock.patch.dict(os.environ, {"BACKCHANNEL_DATA_DIR": "/somewhere/else"}):
            self.assertEqual(app_data_dir(), Path("/somewhere/else"))

    def test_app_data_dir_is_platform_specific(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("BACKCHANNEL_DATA_DIR", None)
            self.assertIn("backchannel", str(app_data_dir()).lower())

    def test_free_port_is_bindable(self):
        port = free_port()
        with socket.socket() as s:
            s.bind(("127.0.0.1", port))

    def test_resource_dev_fallback_points_into_repo(self):
        # No _MEIPASS in tests, so these resolve against the repo checkout.
        self.assertTrue(str(resource("frontend")).endswith("dist"))
        self.assertTrue(str(resource("models")).endswith("models"))
        self.assertTrue(str(resource("pgsql")).endswith("pgsql"))
        self.assertTrue(str(resource("assets")).endswith("assets"))
        self.assertTrue(str(resource("release_signing_keys.json")).endswith("release_signing_keys.json"))

    def test_brand_icons_are_committed(self):
        for name in ("icon.png", "icon.ico", "icon.icns"):
            with self.subTest(icon=name):
                self.assertTrue((resource("assets") / name).exists())

    def test_resource_rejects_unknown_name(self):
        with self.assertRaises(KeyError):
            resource("nonsense")


if __name__ == "__main__":
    unittest.main()
