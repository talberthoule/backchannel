import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = (ROOT / "desktop" / "backchannel.spec").read_text()
WORKFLOW = (ROOT / ".github" / "workflows" / "desktop-release.yml").read_text()


class ReleaseContractTests(unittest.TestCase):
    def test_workflow_names_all_three_desktop_assets(self):
        for asset in (
            "Backchannel-windows-x64.zip",
            "Backchannel-macos-arm64.zip",
            "Backchannel-linux-x64.tar.gz",
        ):
            with self.subTest(asset=asset):
                self.assertIn(asset, WORKFLOW)

    def test_workflow_has_linux_matrix_and_tar_archive(self):
        self.assertIn("os: ubuntu-latest", WORKFLOW)
        self.assertIn("if: runner.os == 'Linux'", WORKFLOW)
        self.assertIn("tar -C dist -czf", WORKFLOW)

    def test_linux_bundle_collects_the_xorg_tray_backend(self):
        self.assertIn('hidden.append("pystray._xorg")', SPEC)

    def test_release_attachment_remains_tag_only(self):
        self.assertIn("if: startsWith(github.ref, 'refs/tags/')", WORKFLOW)

    def test_linux_tarball_is_created_inside_the_workspace(self):
        # tar resolves -f against the original working directory, so a
        # "../" prefix would drop the archive outside the workspace and
        # the upload and release-attach steps would silently miss it.
        self.assertNotIn('-czf "../', WORKFLOW)

    def test_spec_bundles_brand_icons(self):
        self.assertIn('"assets"', SPEC)
        self.assertIn("icon.ico", SPEC)
        self.assertIn("icon.icns", SPEC)


if __name__ == "__main__":
    unittest.main()
