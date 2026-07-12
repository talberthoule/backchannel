import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = (ROOT / "desktop" / "backchannel.spec").read_text()
WORKFLOW = (ROOT / ".github" / "workflows" / "desktop-release.yml").read_text()
MIGRATION_PATH = ROOT / "scripts" / "migrate_releases_to_r2.ps1"
MIGRATION = MIGRATION_PATH.read_text() if MIGRATION_PATH.exists() else ""


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

    def test_permissions_and_publish_gate_are_minimal(self):
        top, publish = WORKFLOW.split("  publish:", 1)
        self.assertIn("permissions:\n  contents: read", top)
        self.assertIn("needs: build", publish)
        self.assertIn("runs-on: ubuntu-latest", publish)
        self.assertIn("environment: production", publish)
        self.assertIn("permissions:\n      contents: write", publish)
        self.assertIn(
            "if: github.event_name == 'push' && startsWith(github.ref, 'refs/tags/v')",
            publish,
        )

    def test_build_matrix_remains_packaging_only(self):
        build, publish = WORKFLOW.split("  publish:", 1)
        self.assertIn("strategy:", build)
        self.assertIn("Smoke test bundle", build)
        self.assertIn("actions/upload-artifact@v4", build)
        self.assertNotIn("Attach to release", build)
        self.assertNotIn("files:", WORKFLOW)
        self.assertIn("softprops/action-gh-release@v2", publish)
        self.assertIn(
            "body_path: .github/release-notes/${{ github.ref_name }}.md", publish
        )

    def test_publish_is_globally_serialized_and_downloads_all_assets(self):
        publish = WORKFLOW.split("  publish:", 1)[1]
        self.assertIn("group: backchannel-r2-publish", publish)
        self.assertIn("cancel-in-progress: false", publish)
        self.assertIn("actions/download-artifact@v4", publish)
        self.assertIn("pattern: Backchannel-*", publish)
        self.assertIn("merge-multiple: true", publish)
        self.assertIn("path: release-assets", publish)

    def test_publish_uses_separate_r2_configuration(self):
        publish = WORKFLOW.split("  publish:", 1)[1]
        for value in (
            "secrets.CLOUDFLARE_ACCOUNT_ID",
            "secrets.R2_ACCESS_KEY_ID",
            "secrets.R2_SECRET_ACCESS_KEY",
            "vars.R2_RELEASES_BUCKET",
            "AWS_DEFAULT_REGION: auto",
        ):
            with self.subTest(value=value):
                self.assertIn(value, publish)
        self.assertNotIn("D1", publish)

    def test_publish_calls_manifest_helper_without_legacy_mode(self):
        publish = WORKFLOW.split("  publish:", 1)[1]
        helper = publish.split("name: Build release manifest", 1)[1].split(
            "      - name:", 1
        )[0]
        self.assertIn("python desktop/scripts/build_release_manifest.py", helper)
        for flag in (
            "--asset-dir release-assets",
            "--tag \"${{ github.ref_name }}\"",
            "--commit \"${{ github.sha }}\"",
            "--published-at",
            "--manifest-out release-metadata/manifest.json",
            "--latest-out release-metadata/latest.json",
        ):
            with self.subTest(flag=flag):
                self.assertIn(flag, helper)
        self.assertNotIn("--allow-legacy-partial", helper)

    def test_publish_order_is_fail_closed_and_latest_is_last_r2_write(self):
        publish = WORKFLOW.split("  publish:", 1)[1]
        steps = (
            "name: Check immutable version",
            "name: Fetch current Latest",
            "name: Build release manifest",
            "name: Upload release assets",
            "name: Verify release asset sizes",
            "name: Create immutable manifest",
            "name: Verify immutable manifest",
            "name: Update Latest",
            "name: Publish GitHub release notes",
        )
        positions = [publish.index(step) for step in steps]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("head-object", publish)
        self.assertIn("ContentLength", publish)
        self.assertIn("--if-none-match '*'", publish)
        self.assertIn("cmp", publish)
        latest = publish.split("name: Update Latest", 1)[1].split(
            "name: Publish GitHub release notes", 1
        )[0]
        self.assertIn("--if-match", latest)
        self.assertIn("--if-none-match '*'", latest)
        self.assertIn("412", latest)
        self.assertIn("retry", latest.lower())
        self.assertIn("--current-latest", latest)

    def test_owner_migration_is_validated_and_opt_in_for_latest(self):
        for value in (
            "SupportsShouldProcess",
            "Mandatory = $true",
            "$Version",
            "$Commit",
            "$PublishedAt",
            "$AssetDirectory",
            "$SetLatest",
            "R2_ACCESS_KEY_ID",
            "R2_SECRET_ACCESS_KEY",
            "CLOUDFLARE_ACCOUNT_ID",
            "R2_RELEASES_BUCKET",
            "--allow-legacy-partial",
            "--if-none-match",
            "ContentLength",
        ):
            with self.subTest(value=value):
                self.assertIn(value, MIGRATION)
        self.assertNotIn("Remove-S3Object", MIGRATION)
        self.assertNotIn("delete-object", MIGRATION)
        self.assertNotIn("D1", MIGRATION)

    def test_owner_migration_writes_manifest_before_optional_latest(self):
        manifest = MIGRATION.index("releases/$Version/manifest.json")
        latest_guard = MIGRATION.index("if ($SetLatest)")
        self.assertLess(manifest, latest_guard)
        self.assertIn("ShouldProcess", MIGRATION[:manifest])

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
