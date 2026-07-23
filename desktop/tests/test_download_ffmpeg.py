import unittest
from unittest import mock

from scripts.download_ffmpeg import binary_name, build_url


class DownloadFfmpegTests(unittest.TestCase):
    def test_platform_urls_are_lgpl_static_builds(self):
        with mock.patch("scripts.download_ffmpeg.sys.platform", "win32"):
            url = build_url()
            self.assertIn("win64-lgpl", url)
            self.assertTrue(url.endswith(".zip"))
        with mock.patch("scripts.download_ffmpeg.sys.platform", "linux"):
            url = build_url()
            self.assertIn("linux64-lgpl", url)
            self.assertTrue(url.endswith(".tar.xz"))

    def test_macos_bundles_no_ffmpeg(self):
        with mock.patch("scripts.download_ffmpeg.sys.platform", "darwin"):
            self.assertIsNone(build_url())

    def test_binary_name_matches_platform(self):
        with mock.patch("scripts.download_ffmpeg.sys.platform", "win32"):
            self.assertEqual(binary_name(), "ffmpeg.exe")
        with mock.patch("scripts.download_ffmpeg.sys.platform", "linux"):
            self.assertEqual(binary_name(), "ffmpeg")


if __name__ == "__main__":
    unittest.main()
