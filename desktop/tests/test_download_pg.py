import unittest
from unittest import mock

from scripts.download_pg import artifact_platform, jar_url


class DownloadPgTests(unittest.TestCase):
    def test_platform_names_match_zonky_artifacts(self):
        with mock.patch("scripts.download_pg.sys.platform", "win32"):
            self.assertEqual(artifact_platform(), "windows-amd64")
        with mock.patch("scripts.download_pg.sys.platform", "darwin"):
            with mock.patch("scripts.download_pg.platform.machine", return_value="arm64"):
                self.assertEqual(artifact_platform(), "darwin-arm64v8")
            with mock.patch("scripts.download_pg.platform.machine", return_value="x86_64"):
                self.assertEqual(artifact_platform(), "darwin-amd64")

    def test_jar_url_points_at_maven_central(self):
        url = jar_url("windows-amd64")
        self.assertTrue(url.startswith("https://repo1.maven.org/maven2/io/zonky/test/postgres/"))
        self.assertTrue(url.endswith(".jar"))
        self.assertIn("embedded-postgres-binaries-windows-amd64", url)


if __name__ == "__main__":
    unittest.main()
