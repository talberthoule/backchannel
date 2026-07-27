import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = (ROOT / "desktop" / "backchannel.spec").read_text()
WORKFLOW = (ROOT / ".github" / "workflows" / "desktop-release.yml").read_text()
MIGRATION_PATH = ROOT / "scripts" / "migrate_releases_to_r2.ps1"
MIGRATION = MIGRATION_PATH.read_text() if MIGRATION_PATH.exists() else ""
PLATFORM_PUBLISHER_PATH = ROOT / "scripts" / "publish_release_platform.ps1"
PLATFORM_PUBLISHER = (
    PLATFORM_PUBLISHER_PATH.read_text() if PLATFORM_PUBLISHER_PATH.exists() else ""
)
LINUX_DOCKERFILE = (ROOT / "desktop" / "Dockerfile.release-linux").read_text()
COORDINATOR = (ROOT / "scripts" / "release_desktop.ps1").read_text()


class ReleaseContractTests(unittest.TestCase):
    def test_local_coordinator_is_tag_pinned_progressive_and_failure_isolated(self):
        for value in (
            "SupportsShouldProcess", "worktree add --detach", "^{commit}",
            "taggerdate", "Get-ReleasePublicationState", "Remove-StaleMacArtifacts",
            "workflow run desktop-release.yml", "correlation_id", "displayTitle",
            "Build-WindowsRelease",
            "Build-LinuxRelease", "publish_release_platform.ps1",
            "Backchannel-windows-x64.zip", "Backchannel-linux-x64.tar.gz",
            "run watch", "release view", "$failures", "finally",
        ):
            self.assertIn(value, COORDINATOR)
        main = COORDINATOR[COORDINATOR.index("$localPending") :]
        self.assertLess(
            main.index("Build-WindowsRelease"), main.index("Build-LinuxRelease")
        )
        self.assertLess(main.index("Build-LinuxRelease"), main.index("run watch"))

    def test_linux_release_container_builds_smokes_and_exports_one_tarball(self):
        for value in (
            "FROM node:24", "npm ci", "npm run build", "FROM python:3.12",
            "binutils",
            "pip install", "download_models.py",
            "rm -rf desktop/pgsql && python desktop/scripts/download_pg.py",
            "pyinstaller desktop/backchannel.spec",
            "COPY --from=controller smoke_test.py",
            "USER nobody\nRUN python /tmp/backchannel-smoke-test.py",
            'tar -C dist -czf "/out/Backchannel-linux-x64.tar.gz" Backchannel',
            "FROM scratch AS export",
            "COPY --from=bundle /out/Backchannel-linux-x64.tar.gz /",
        ):
            self.assertIn(value, LINUX_DOCKERFILE)
        self.assertNotIn("ENTRYPOINT", LINUX_DOCKERFILE)
        self.assertNotIn("CMD", LINUX_DOCKERFILE)
        self.assertLess(
            LINUX_DOCKERFILE.index("pyinstaller desktop/backchannel.spec"),
            LINUX_DOCKERFILE.index("COPY --from=controller"),
        )
        self.assertIn('--build-context "controller=$ControllerScripts"', COORDINATOR)
        self.assertIn(
            '-ControllerScripts (Join-Path $repoRoot "desktop\\scripts")',
            COORDINATOR,
        )

    def test_workflow_is_dispatch_only_macos_handoff(self):
        self.assertIn("workflow_dispatch:", WORKFLOW)
        self.assertNotIn("tags:", WORKFLOW)
        self.assertIn("release_ref:", WORKFLOW)
        self.assertIn("expected_commit:", WORKFLOW)
        self.assertIn("correlation_id:", WORKFLOW)
        self.assertIn("run-name: Desktop release", WORKFLOW)
        self.assertIn("runs-on: macos-latest", WORKFLOW)
        self.assertNotIn("windows-latest", WORKFLOW)
        self.assertNotIn("ubuntu-latest\n            asset:", WORKFLOW)
        self.assertNotIn("retention-days:", WORKFLOW)
        self.assertNotIn("actions/upload-artifact", WORKFLOW)
        self.assertNotIn("actions/download-artifact", WORKFLOW)

    def test_macos_build_is_credential_free_and_publish_is_separate(self):
        build, remainder = WORKFLOW.split("  publish-macos:", 1)
        publish, cleanup = remainder.split("  cleanup-macos:", 1)
        for name in (
            "CLOUDFLARE_ACCOUNT_ID",
            "R2_ACCESS_KEY_ID",
            "R2_SECRET_ACCESS_KEY",
            "BACKCHANNEL_RELEASE_SIGNING_PRIVATE_KEY",
        ):
            with self.subTest(name=name):
                self.assertNotIn(name, build)
                self.assertIn(name, publish)
        self.assertIn("environment: production", publish)
        self.assertIn("runs-on: macos-latest", publish)
        self.assertNotIn("actions: write", publish)
        self.assertIn("actions: write", cleanup)
        self.assertIn("group: backchannel-r2-publish", publish)
        self.assertIn("cancel-in-progress: false", publish)
        self.assertIn("publish_release_platform.ps1", publish)
        self.assertIn("pip install \"cryptography>=41.0.0\"", publish)
        self.assertIn("ref: ${{ inputs.release_ref }}", publish)
        self.assertLess(
            WORKFLOW.index("publish_release_platform.ps1"),
            WORKFLOW.index("--method DELETE"),
        )

    def test_release_actions_are_pinned_to_immutable_commits(self):
        refs = re.findall(
            r"uses:\s+actions/(?:checkout|setup-node|setup-python|cache(?:/(?:save|restore))?)@([^\s#]+)",
            WORKFLOW,
        )
        self.assertEqual(len(refs), 10)
        self.assertTrue(all(re.fullmatch(r"[0-9a-f]{40}", ref) for ref in refs))

    def test_macos_cleanup_is_separate_from_production_credentials(self):
        self.assertIn("  cleanup-macos:", WORKFLOW)
        publish, cleanup = WORKFLOW.split("  publish-macos:", 1)[1].split(
            "  cleanup-macos:", 1
        )
        self.assertNotIn("actions: write", publish)
        self.assertIn("actions: write", cleanup)
        self.assertNotIn("environment: production", cleanup)
        for name in (
            "CLOUDFLARE_ACCOUNT_ID",
            "R2_ACCESS_KEY_ID",
            "R2_SECRET_ACCESS_KEY",
            "BACKCHANNEL_RELEASE_SIGNING_PRIVATE_KEY",
        ):
            self.assertNotIn(name, cleanup)
        self.assertIn("needs: [build-macos, publish-macos]", cleanup)
        self.assertIn("always()", cleanup)

    def test_macos_build_is_tag_pinned_smoked_and_exactly_packaged(self):
        build, remainder = WORKFLOW.split("  publish-macos:", 1)
        publish = remainder.split("  cleanup-macos:", 1)[0]
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
            "actions/cache/save@",
            "bundle_sha256",
            "cache_key",
        ):
            with self.subTest(value=value):
                self.assertIn(value, build)
        self.assertNotIn("softprops/action-gh-release", WORKFLOW)
        self.assertNotIn("files:", WORKFLOW)
        self.assertIn(
            'cache_key="backchannel-macos-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}-${EXPECTED_COMMIT}-${bundle_sha256}"',
            build,
        )
        self.assertIn(
            "path: controller/release-assets/Backchannel-macos-arm64.zip",
            build,
        )
        self.assertIn("actions/cache/restore@", publish)
        self.assertIn(
            "path: controller/release-assets/Backchannel-macos-arm64.zip",
            publish,
        )
        self.assertIn("fail-on-cache-miss: true", publish)
        self.assertNotIn("restore-keys:", publish)
        self.assertIn("needs.build-macos.outputs.cache_key", publish)
        self.assertIn("needs.build-macos.outputs.bundle_sha256", publish)
        self.assertLess(
            publish.index("shasum -a 256 -c"),
            publish.index("publish_release_platform.ps1"),
        )

    def test_macos_cleanup_deletes_only_the_exact_cache_by_id(self):
        cleanup = WORKFLOW.split("  cleanup-macos:", 1)[1]
        self.assertIn("always()", cleanup)
        self.assertIn("actions/caches", cleanup)
        self.assertIn("needs.build-macos.outputs.cache_key", cleanup)
        self.assertIn("actions/caches/$cache_id", cleanup)
        self.assertIn('-f key="$CACHE_KEY" -f ref="$GITHUB_REF"', cleanup)
        self.assertIn('if [[ "$returned_key" == "$CACHE_KEY"', cleanup)
        self.assertIn('&& "$returned_ref" == "$GITHUB_REF" ]]', cleanup)
        self.assertIn("matches=$((matches + 1))", cleanup)
        self.assertIn('[[ "$matches" -eq 1 ]]', cleanup)
        self.assertIn("--method DELETE", cleanup)

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

    def test_platform_publisher_is_conditional_verified_and_latest_last(self):
        for value in (
            "SupportsShouldProcess",
            "build_platform_manifest.py",
            "r2-release-common.ps1",
            "--if-none-match",
            "contentLength",
            "platforms/$PlatformId.json",
            "--if-match",
            "Updating Latest",
            "BACKCHANNEL_RELEASE_SIGNING_PRIVATE_KEY",
            "--keys-file",
            "--release-notes-file",
        ):
            with self.subTest(value=value):
                self.assertIn(value, PLATFORM_PUBLISHER)
        self.assertNotRegex(
            PLATFORM_PUBLISHER, re.compile(r"(?i)(?:^|[&|;\s])aws(?:\s|$)")
        )
        self.assertLess(
            PLATFORM_PUBLISHER.index("Creating immutable platform manifest"),
            PLATFORM_PUBLISHER.index("Updating Latest"),
        )
        self.assertNotIn("delete", PLATFORM_PUBLISHER.lower())
        self.assertNotIn('"--if-none-match", "*"', PLATFORM_PUBLISHER)
        self.assertIn('"--if-none-match", "create-only"', PLATFORM_PUBLISHER)

    def test_migration_uses_shell_safe_create_condition(self):
        self.assertNotIn('"--if-none-match", "*"', MIGRATION)
        self.assertIn('"--if-none-match", "create-only"', MIGRATION)

    def test_spec_bundles_brand_icons(self):
        self.assertIn('"assets"', SPEC)
        self.assertIn("icon.ico", SPEC)
        self.assertIn("icon.icns", SPEC)
        self.assertIn("release_signing_keys.json", SPEC)

    def test_spec_builds_and_collects_a_standalone_onefile_updater(self):
        self.assertIn('repo / "desktop" / "updater.py"', SPEC)
        self.assertIn('name="BackchannelUpdater"', SPEC)
        self.assertRegex(SPEC, r"updater_exe\s*=\s*EXE\(")
        updater_block = SPEC[SPEC.index("updater_exe = EXE("):SPEC.index("coll = COLLECT")]
        self.assertNotIn("exclude_binaries=True", updater_block)
        self.assertRegex(SPEC, r"COLLECT\(\s*exe,\s*updater_exe,")
        self.assertIn('release_signing_keys.json"), "."', SPEC)


if __name__ == "__main__":
    unittest.main()
