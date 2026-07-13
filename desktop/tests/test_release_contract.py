import re
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

    def test_publish_uses_only_the_checked_in_cloudflare_client(self):
        publish = WORKFLOW.split("  publish:", 1)[1]
        self.assertRegex(
            publish,
            re.compile(
                r"steps:\s*\n\s*- uses: actions/checkout@v4\s*\n\s*"
                r"- uses: actions/setup-node@v4\s*\n\s*with:\s*\n"
                r"\s*node-version: 24"
            ),
        )
        for operation in ("head", "get", "put"):
            with self.subTest(operation=operation):
                self.assertIn(f"node scripts/r2-object.mjs {operation}", publish)
        self.assertNotRegex(publish, re.compile(r"(?i)(?:^|[&|;\s])aws(?:\s|$)"))
        for value in (
            "AWS_DEFAULT_REGION",
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
            "R2_ENDPOINT",
            "Invoke-Aws",
            "@aws-sdk",
        ):
            with self.subTest(value=value):
                self.assertNotIn(value, publish)

    def test_publish_scopes_cloudflare_credentials_to_r2_steps(self):
        publish = WORKFLOW.split("  publish:", 1)[1]
        self.assertIn("R2_BUCKET: ${{ vars.R2_RELEASES_BUCKET }}", publish)
        self.assertNotIn("D1", publish)
        header, steps = publish.split("    steps:", 1)
        release_notes = steps.split("name: Publish GitHub release notes", 1)[1]
        self.assertNotIn("CLOUDFLARE_ACCOUNT_ID", header)
        self.assertNotIn("R2_ACCESS_KEY_ID", header)
        self.assertNotIn("R2_SECRET_ACCESS_KEY", header)
        self.assertNotIn("CLOUDFLARE_ACCOUNT_ID", release_notes)
        self.assertNotIn("R2_ACCESS_KEY_ID", release_notes)
        self.assertNotIn("R2_SECRET_ACCESS_KEY", release_notes)
        for step in steps.split("      - name:"):
            if "node scripts/r2-object.mjs" in step:
                with self.subTest(step=step.splitlines()[0]):
                    self.assertEqual(
                        set(re.findall(r"^\s{10}([A-Z][A-Z0-9_]+):", step, re.M)),
                        {
                            "CLOUDFLARE_ACCOUNT_ID",
                            "R2_ACCESS_KEY_ID",
                            "R2_SECRET_ACCESS_KEY",
                        },
                    )

    def test_publish_resolves_annotated_tag_to_checked_out_commit(self):
        publish = WORKFLOW.split("  publish:", 1)[1]
        self.assertIn("name: Resolve release commit", publish)
        self.assertIn("git rev-parse 'HEAD^{commit}'", publish)
        self.assertIn("RELEASE_COMMIT=", publish)
        self.assertEqual(publish.count('--commit "$RELEASE_COMMIT"'), 2)
        self.assertNotIn("github.sha", publish)

    def test_publish_calls_manifest_helper_without_legacy_mode(self):
        publish = WORKFLOW.split("  publish:", 1)[1]
        self.assertEqual(
            publish.count("python desktop/scripts/build_release_manifest.py"), 2
        )
        helper = publish.split("name: Build release manifest", 1)[1].split(
            "      - name:", 1
        )[0]
        self.assertIn("python desktop/scripts/build_release_manifest.py", helper)
        for flag in (
            "--asset-dir release-assets",
            "--tag \"${{ github.ref_name }}\"",
            "--commit \"$RELEASE_COMMIT\"",
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
        self.assertIn("json.load(sys.stdin)", publish)
        self.assertIn('["contentLength"]', publish)
        self.assertIn("--if-none-match '*'", publish)
        self.assertIn('--content-disposition "attachment; filename=\\"$filename\\""', publish)
        self.assertGreaterEqual(publish.count("--cache-control no-store"), 2)
        self.assertIn("cmp", publish)
        self.assertGreaterEqual(
            len(re.findall(r"(?:-eq|==)\s+44", publish)), 3
        )
        for value in ("NoSuchKey", "NotFound", "PreconditionFailed", "grep -E", "412"):
            with self.subTest(value=value):
                self.assertNotIn(value, publish)
        latest = publish.split("name: Update Latest", 1)[1].split(
            "name: Publish GitHub release notes", 1
        )[0]
        self.assertIn('["etag"]', latest)
        self.assertIn("--if-match", latest)
        self.assertIn("--if-none-match '*'", latest)
        self.assertRegex(latest, re.compile(r"(?:-eq|==)\s+42"))
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
