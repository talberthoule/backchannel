import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = (ROOT / "desktop" / "backchannel.spec").read_text()
WORKFLOW = (ROOT / ".github" / "workflows" / "desktop-release.yml").read_text()
MIGRATION_PATH = ROOT / "scripts" / "migrate_releases_to_r2.ps1"
MIGRATION = MIGRATION_PATH.read_text() if MIGRATION_PATH.exists() else ""


class ReleaseContractTests(unittest.TestCase):
    def test_workflow_is_dispatch_only_macos_handoff(self):
        self.assertIn("workflow_dispatch:", WORKFLOW)
        self.assertNotIn("tags:", WORKFLOW)
        self.assertIn("release_ref:", WORKFLOW)
        self.assertIn("expected_commit:", WORKFLOW)
        self.assertIn("runs-on: macos-latest", WORKFLOW)
        self.assertNotIn("windows-latest", WORKFLOW)
        self.assertNotIn("ubuntu-latest\n            asset:", WORKFLOW)
        self.assertIn("retention-days: 1", WORKFLOW)

    def test_macos_build_is_credential_free_and_publish_is_separate(self):
        build, publish = WORKFLOW.split("  publish-macos:", 1)
        for name in (
            "CLOUDFLARE_ACCOUNT_ID",
            "R2_ACCESS_KEY_ID",
            "R2_SECRET_ACCESS_KEY",
        ):
            with self.subTest(name=name):
                self.assertNotIn(name, build)
                self.assertIn(name, publish)
        self.assertIn("environment: production", publish)
        self.assertIn("actions: write", publish)
        self.assertIn("group: backchannel-r2-publish", publish)
        self.assertIn("cancel-in-progress: false", publish)
        self.assertIn("publish_release_platform.ps1", publish)
        self.assertLess(
            publish.index("publish_release_platform.ps1"),
            publish.index("--method DELETE"),
        )

    def test_macos_build_is_tag_pinned_smoked_and_exactly_packaged(self):
        build, publish = WORKFLOW.split("  publish-macos:", 1)
        for value in (
            "path: controller",
            "path: source",
            "ref: ${{ inputs.release_ref }}",
            "git cat-file -t",
            "git rev-parse",
            "${{ inputs.expected_commit }}",
            "taggerdate:iso-strict",
            "node-version: 24",
            "npm ci",
            "npm run build",
            "download_models.py",
            "download_pg.py",
            "pyinstaller desktop/backchannel.spec",
            "desktop/scripts/smoke_test.py",
            "Backchannel-macos-arm64.zip",
            "actions/upload-artifact@v4",
        ):
            with self.subTest(value=value):
                self.assertIn(value, build)
        self.assertNotIn("softprops/action-gh-release", WORKFLOW)
        self.assertNotIn("files:", WORKFLOW)
        self.assertIn("actions/download-artifact@v4", publish)
        self.assertIn("name: Backchannel-macos-arm64.zip", publish)

    def test_macos_cleanup_targets_only_this_runs_exact_artifact(self):
        publish = WORKFLOW.split("  publish-macos:", 1)[1]
        self.assertIn("actions/runs/$GITHUB_RUN_ID/artifacts", publish)
        self.assertIn(
            'select(.name == "Backchannel-macos-arm64.zip")', publish
        )
        self.assertIn("actions/artifacts/$artifact_id", publish)
        self.assertIn("--method DELETE", publish)

    def test_linux_bundle_collects_the_xorg_tray_backend(self):
        self.assertIn('hidden.append("pystray._xorg")', SPEC)


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
            "scripts/r2-object.mjs",
            "--allow-legacy-partial",
            "--if-none-match",
            "contentLength",
        ):
            with self.subTest(value=value):
                self.assertIn(value, MIGRATION)
        self.assertNotIn("Remove-S3Object", MIGRATION)
        self.assertNotIn("delete-object", MIGRATION)
        self.assertNotIn("D1", MIGRATION)

    def test_owner_migration_has_no_aws_cli_or_credential_aliases(self):
        self.assertNotRegex(MIGRATION, re.compile(r"(?i)(?:^|[&|;\s])aws(?:\s|$)"))
        migration_lower = MIGRATION.lower()
        for value in (
            "AWS_DEFAULT_REGION",
            "AWS_ACCESS_KEY_ID",
            "Invoke-Aws",
            '"s3", "cp"',
            '"s3api"',
        ):
            with self.subTest(value=value):
                self.assertNotIn(value.lower(), migration_lower)

    def test_owner_migration_writes_manifest_before_optional_latest(self):
        manifest = MIGRATION.index("releases/$Version/manifest.json")
        remote_check = MIGRATION.index("$existing = Invoke-R2", manifest)
        latest_guard = MIGRATION.index("if ($SetLatest)")
        should_process = MIGRATION.index("$PSCmdlet.ShouldProcess")
        first_upload = MIGRATION.index("foreach ($asset in $manifest.assets)")
        self.assertLess(remote_check, should_process)
        self.assertLess(latest_guard, should_process)
        self.assertLess(should_process, first_upload)
        self.assertNotIn('"put"', MIGRATION[:should_process])
        self.assertIn("recovery", MIGRATION.lower())

    def test_spec_bundles_brand_icons(self):
        self.assertIn('"assets"', SPEC)
        self.assertIn("icon.ico", SPEC)
        self.assertIn("icon.icns", SPEC)


if __name__ == "__main__":
    unittest.main()
