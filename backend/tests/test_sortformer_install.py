import unittest
from unittest.mock import patch

from scripts.install_sortformer import should_install_sortformer


class SortformerInstallTests(unittest.TestCase):
    def test_sortformer_install_defaults_to_enabled(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertTrue(should_install_sortformer())

    def test_sortformer_install_can_be_disabled(self):
        with patch.dict("os.environ", {"INSTALL_SORTFORMER": "false"}, clear=True):
            self.assertFalse(should_install_sortformer())


if __name__ == "__main__":
    unittest.main()
