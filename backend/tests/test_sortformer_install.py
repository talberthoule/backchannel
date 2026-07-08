import unittest
from unittest.mock import patch

from scripts.install_sortformer import should_install_sortformer, use_rocm_windows_wheels


class SortformerInstallTests(unittest.TestCase):
    def test_sortformer_install_defaults_to_enabled(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertTrue(should_install_sortformer())

    def test_sortformer_install_can_be_disabled(self):
        with patch.dict("os.environ", {"INSTALL_SORTFORMER": "false"}, clear=True):
            self.assertFalse(should_install_sortformer())

    def test_explicit_index_url_skips_rocm_windows_wheels(self):
        self.assertFalse(use_rocm_windows_wheels("cu130"))
        self.assertFalse(use_rocm_windows_wheels("https://example.com/whl"))

    def test_rocm_windows_wheels_require_windows_amd_and_python_312(self):
        with patch("scripts.install_sortformer.sys") as fake_sys, \
                patch("scripts.install_sortformer.nvidia_gpu_present", return_value=False), \
                patch("scripts.install_sortformer.amd_gpu_present", return_value=True):
            fake_sys.platform = "win32"
            fake_sys.version_info = (3, 12, 4)
            self.assertTrue(use_rocm_windows_wheels("auto"))

            fake_sys.version_info = (3, 14, 0)
            self.assertFalse(use_rocm_windows_wheels("auto"))

            fake_sys.version_info = (3, 12, 4)
            fake_sys.platform = "linux"
            self.assertFalse(use_rocm_windows_wheels("auto"))


if __name__ == "__main__":
    unittest.main()
