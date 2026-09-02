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
UPDATE_SMOKE = ROOT / "desktop" / "scripts" / "smoke_update_archive.py"

# Steps every native (PyInstaller-on-the-runner) build job must run itself.
# The Linux build runs the same steps inside Dockerfile.release-linux, which
# test_linux_release_container_builds_smokes_and_exports_one_tarball covers.
NATIVE_BUILD_STEPS = (
    "node-version: 24",
    "npm ci",
    "npm run build",
    "download_models.py",
    "download_pg.py",
    "pyinstaller desktop/backchannel.spec",
    "desktop/scripts/smoke_test.py",
)

# Every desktop platform the workflow can build and publish from GitHub. Each
# owns a build / publish / cleanup job triple, and the workflow tests below
# hold every triple to the same contract instead of the macOS one alone.
PLATFORMS = {
    "macos": {
        "id": "macos-arm64",
        "archive": "Backchannel-macos-arm64.zip",
        "runner": "macos-latest",
        "digest_check": "shasum -a 256 -c -",
        "package": "ditto -c -k --keepParent",
        "build_steps": NATIVE_BUILD_STEPS,
    },
    "windows": {
        "id": "windows-x64",
        "archive": "Backchannel-windows-x64.zip",
        "runner": "windows-latest",
        "digest_check": "sha256sum -c -",
        "package": "Compress-Archive",
        "build_steps": NATIVE_BUILD_STEPS + ("download_ffmpeg.py",),
    },
    "linux": {
        "id": "linux-x64",
        "archive": "Backchannel-linux-x64.tar.gz",
        "runner": "ubuntu-latest",
        "digest_check": "sha256sum -c -",
        "package": "docker build",
        "build_steps": (
            "--file controller/desktop/Dockerfile.release-linux",
            "--build-context controller=controller/desktop/scripts",
            "--target export",
            "[[ ${#files[@]} -eq 1 ]]",
            '[[ "${files[0]}" == "linux-output/Backchannel-linux-x64.tar.gz" ]]',
        ),
    },
}
NATIVE_PLATFORMS = ("macos", "windows")
JOB_ROLES = ("build", "publish", "cleanup")

# Names that may only ever appear inside a protected publish job.
PRODUCTION_SECRET_NAMES = (
    "CLOUDFLARE_ACCOUNT_ID",
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "R2_RELEASES_BUCKET",
    "BACKCHANNEL_RELEASE_SIGNING_URL",
    "CLOUDFLARE_ACCESS_CLIENT_ID",
    "CLOUDFLARE_ACCESS_CLIENT_SECRET",
)
# The local signing key never reaches GitHub in any job.
LOCAL_SIGNING_KEY = "BACKCHANNEL_RELEASE_SIGNING_PRIVATE_KEY"

# Only these first-party actions may run, and only at a full commit SHA.
ALLOWED_ACTIONS = {
    "actions/checkout",
    "actions/setup-node",
    "actions/setup-python",
    "actions/cache/save",
    "actions/cache/restore",
}


def _blocks(text, indent):
    """Split one level of a YAML mapping into {key: block text}, in file order.

    A block runs from its key line to the line before the next key at the same
    indentation, so a job block holds that whole job and nothing else.
    """
    header = re.compile(
        r"^" + " " * indent + r"([A-Za-z0-9_-]+):[ \t]*$", re.MULTILINE
    )
    matches = list(header.finditer(text))
    blocks = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        blocks[match.group(1)] = text[match.start() : end]
    return blocks


def _jobs():
    return _blocks(WORKFLOW.split("\njobs:\n", 1)[1], indent=2)


def _job(role, platform):
    return _jobs()["%s-%s" % (role, platform)]


def _triggers_and_inputs():
    triggers = WORKFLOW.split("\non:\n", 1)[1].split("\npermissions:\n", 1)[0]
    inputs = _blocks(triggers.split("    inputs:\n", 1)[1], indent=6)
    return triggers, inputs


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

    def test_workflow_is_dispatch_only_with_one_gated_triple_per_platform(self):
        triggers, inputs = _triggers_and_inputs()
        self.assertEqual(
            re.findall(r"^  ([A-Za-z_]+):", triggers, re.MULTILINE),
            ["workflow_dispatch"],
        )
        for trigger in ("push", "pull_request", "schedule", "tags", "branches"):
            with self.subTest(trigger=trigger):
                self.assertNotIn(trigger + ":", WORKFLOW)
        self.assertIn("run-name: Desktop release", WORKFLOW)
        self.assertEqual(
            list(inputs),
            ["release_ref", "expected_commit", "correlation_id", "platforms"],
        )
        for name in ("release_ref", "expected_commit", "correlation_id"):
            with self.subTest(input=name):
                self.assertIn("required: true", inputs[name])
        # The coordinator dispatches without a platforms value while it builds
        # Windows and Linux locally, so the default has to stay macOS-only or
        # one coordinator run would publish those platforms from both paths.
        self.assertIn("required: false", inputs["platforms"])
        self.assertIn("\n        default: macos-arm64\n", inputs["platforms"])
        self.assertNotIn("platforms=", COORDINATOR)

        jobs = _jobs()
        expected = sorted(
            "%s-%s" % (role, platform) for platform in PLATFORMS for role in JOB_ROLES
        )
        self.assertEqual(sorted(jobs), expected)
        order = list(jobs)
        for platform, spec in PLATFORMS.items():
            with self.subTest(platform=platform):
                build, publish, cleanup = (
                    jobs["%s-%s" % (role, platform)] for role in JOB_ROLES
                )
                self.assertLess(
                    order.index("build-" + platform), order.index("publish-" + platform)
                )
                self.assertLess(
                    order.index("publish-" + platform),
                    order.index("cleanup-" + platform),
                )
                self.assertIn(
                    "if: ${{ contains(inputs.platforms, '%s') }}" % spec["id"], build
                )
                self.assertIn("needs: build-%s\n" % platform, publish)
                self.assertIn("needs: [build-%s, publish-%s]" % (platform, platform), cleanup)
                self.assertIn(
                    "if: ${{ always() && needs.build-%s.result == 'success' }}"
                    % platform,
                    cleanup,
                )
                self.assertIn("runs-on: %s\n" % spec["runner"], build)
                self.assertIn("runs-on: %s\n" % spec["runner"], publish)
                self.assertIn("runs-on: ubuntu-latest\n", cleanup)
        self.assertNotIn("contents: write", WORKFLOW)
        self.assertNotIn("retention-days:", WORKFLOW)
        self.assertNotIn("actions/upload-artifact", WORKFLOW)
        self.assertNotIn("actions/download-artifact", WORKFLOW)

    def test_every_build_is_credential_free_and_only_publish_holds_production(self):
        self.assertNotIn(LOCAL_SIGNING_KEY, WORKFLOW)
        jobs = _jobs()
        publish_jobs = sorted("publish-" + platform for platform in PLATFORMS)
        self.assertEqual(
            sorted(name for name, body in jobs.items() if "environment:" in body),
            publish_jobs,
        )
        self.assertEqual(
            sorted(name for name, body in jobs.items() if "secrets." in body),
            publish_jobs,
        )
        self.assertEqual(
            sorted(name for name, body in jobs.items() if "vars." in body),
            publish_jobs,
        )
        for platform, spec in PLATFORMS.items():
            build = _job("build", platform)
            publish = _job("publish", platform)
            with self.subTest(platform=platform):
                self.assertNotIn("environment:", build)
                self.assertNotIn("secrets.", build)
                self.assertNotIn("vars.", build)
                for name in PRODUCTION_SECRET_NAMES:
                    self.assertNotIn(name, build)
                    self.assertIn(name, publish)
                self.assertIn("environment: production", publish)
                self.assertNotIn("actions: write", publish)
                self.assertIn("group: backchannel-r2-publish", publish)
                self.assertIn("cancel-in-progress: false", publish)
                self.assertIn("ref: ${{ inputs.release_ref }}", publish)
                self.assertIn('pip install "cryptography>=41.0.0"', publish)
                self.assertEqual(publish.count("publish_release_platform.ps1"), 1)
                self.assertIn("-SigningMode Remote", publish)
                self.assertIn("-PlatformId %s " % spec["id"], publish)
                self.assertIn(
                    "-AssetPath ../controller/release-assets/%s " % spec["archive"],
                    publish,
                )

    def test_release_actions_are_pinned_to_immutable_commits(self):
        uses = re.findall(r"^\s*-?\s*uses:\s*(\S+)", WORKFLOW, re.MULTILINE)
        self.assertEqual(len(uses), WORKFLOW.count("uses:"))
        self.assertGreater(len(uses), 0)
        for reference in uses:
            with self.subTest(uses=reference):
                action, _, ref = reference.partition("@")
                self.assertIn(action, ALLOWED_ACTIONS)
                self.assertIsNotNone(re.fullmatch(r"[0-9a-f]{40}", ref))

    def test_every_cleanup_is_separate_from_production_credentials(self):
        for platform in PLATFORMS:
            publish = _job("publish", platform)
            cleanup = _job("cleanup", platform)
            with self.subTest(platform=platform):
                self.assertNotIn("actions: write", publish)
                self.assertIn("actions: write", cleanup)
                self.assertNotIn("environment:", cleanup)
                self.assertNotIn("secrets.", cleanup)
                self.assertNotIn("vars.", cleanup)
                for name in PRODUCTION_SECRET_NAMES + (LOCAL_SIGNING_KEY,):
                    self.assertNotIn(name, cleanup)
                self.assertIn("GH_TOKEN: ${{ github.token }}", cleanup)
                # Nothing but the job's own script runs with actions: write.
                self.assertNotIn("uses:", cleanup)
                self.assertIn("needs: [build-%s, publish-%s]" % (platform, platform), cleanup)
                self.assertIn("always()", cleanup)

    def test_every_build_is_tag_pinned_smoked_and_exactly_handed_off(self):
        self.assertNotIn("softprops/action-gh-release", WORKFLOW)
        self.assertNotIn("files:", WORKFLOW)
        for platform, spec in PLATFORMS.items():
            build = _job("build", platform)
            publish = _job("publish", platform)
            cleanup = _job("cleanup", platform)
            with self.subTest(platform=platform):
                for value in (
                    "path: controller",
                    "path: source",
                    "ref: ${{ inputs.release_ref }}",
                    "fetch-depth: 0",
                    "${{ inputs.expected_commit }}",
                    "${{ inputs.correlation_id }}",
                    '[[ "$EXPECTED_COMMIT" =~ ^[0-9a-f]{40}$ ]]',
                    '[[ "$(git cat-file -t "refs/tags/$RELEASE_REF")" == tag ]]',
                    'actual_commit="$(git rev-parse "refs/tags/$RELEASE_REF^{commit}")"',
                    '[[ "$actual_commit" == "$EXPECTED_COMMIT" ]]',
                    "taggerdate:iso-strict",
                    'echo "published_at=$published_at" >> "$GITHUB_OUTPUT"',
                    "published_at: ${{ steps.release.outputs.published_at }}",
                    "cache_key: ${{ steps.handoff.outputs.cache_key }}",
                    "bundle_sha256: ${{ steps.handoff.outputs.bundle_sha256 }}",
                    'cache_key="backchannel-%s-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}'
                    '-${EXPECTED_COMMIT}-${bundle_sha256}"' % platform,
                    "path: controller/release-assets/%s" % spec["archive"],
                    "key: ${{ steps.handoff.outputs.cache_key }}",
                ) + spec["build_steps"]:
                    with self.subTest(value=value):
                        self.assertIn(value, build)
                self.assertEqual(build.count("uses: actions/checkout@"), 2)
                self.assertEqual(build.count("uses: actions/cache/save@"), 1)
                self.assertNotIn("actions/cache/restore@", build)

                self.assertEqual(publish.count("uses: actions/checkout@"), 2)
                self.assertEqual(publish.count("uses: actions/cache/restore@"), 1)
                self.assertNotIn("actions/cache/save@", publish)
                self.assertIn(
                    "path: controller/release-assets/%s" % spec["archive"], publish
                )
                self.assertIn(
                    "key: ${{ needs.build-%s.outputs.cache_key }}" % platform, publish
                )
                self.assertIn("fail-on-cache-miss: true", publish)
                self.assertNotIn("restore-keys:", publish)
                self.assertIn(
                    "BUNDLE_SHA256: ${{ needs.build-%s.outputs.bundle_sha256 }}"
                    % platform,
                    publish,
                )
                self.assertIn(
                    "PUBLISHED_AT: ${{ needs.build-%s.outputs.published_at }}"
                    % platform,
                    publish,
                )
                digest_check = 'echo "$BUNDLE_SHA256  release-assets/%s" | %s' % (
                    spec["archive"],
                    spec["digest_check"],
                )
                self.assertLess(
                    publish.index(digest_check),
                    publish.index("publish_release_platform.ps1"),
                )

                # A triple only ever reads its own build's outputs and archive.
                for other, other_spec in PLATFORMS.items():
                    if other == platform:
                        continue
                    for body in (build, publish, cleanup):
                        self.assertNotIn("build-" + other, body)
                        self.assertNotIn(other_spec["archive"], body)

    def test_every_cleanup_deletes_only_the_exact_cache_by_id(self):
        for platform in PLATFORMS:
            cleanup = _job("cleanup", platform)
            with self.subTest(platform=platform):
                self.assertIn("always()", cleanup)
                self.assertIn("actions/caches", cleanup)
                self.assertIn(
                    "CACHE_KEY: ${{ needs.build-%s.outputs.cache_key }}" % platform,
                    cleanup,
                )
                self.assertIn("actions/caches/$cache_id", cleanup)
                self.assertIn('-f key="$CACHE_KEY" -f ref="$GITHUB_REF"', cleanup)
                self.assertIn('if [[ "$returned_key" == "$CACHE_KEY"', cleanup)
                self.assertIn('&& "$returned_ref" == "$GITHUB_REF" ]]', cleanup)
                self.assertIn("matches=$((matches + 1))", cleanup)
                self.assertIn('[[ "$matches" -eq 1 ]]', cleanup)
                self.assertEqual(cleanup.count("--method DELETE"), 1)

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
            'ValidateSet("Remote", "Local")',
            'SigningMode = "Remote"',
            "ValidateRange(1, 300)",
            "SigningTimeoutSeconds = 30",
            "BACKCHANNEL_RELEASE_SIGNING_URL",
            "CF-Access-Client-Id",
            "CF-Access-Client-Secret",
            "--signing-request-out",
            "--detached-key-id",
            "--detached-signature",
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

    def test_every_native_archive_runs_the_production_update_smoke(self):
        self.assertTrue(UPDATE_SMOKE.is_file())
        windows_zip = COORDINATOR.index("Compress-Archive")
        windows_smoke = COORDINATOR.index("smoke_update_archive.py")
        self.assertLess(windows_zip, windows_smoke)
        self.assertIn("--platform windows-x64 --archive $AssetPath", COORDINATOR)

        linux_archive = LINUX_DOCKERFILE.index(
            'tar -C dist -czf "/out/Backchannel-linux-x64.tar.gz" Backchannel'
        )
        linux_smoke = LINUX_DOCKERFILE.index("smoke_update_archive.py")
        self.assertLess(linux_archive, linux_smoke)
        self.assertIn("--platform linux-x64", LINUX_DOCKERFILE)
        self.assertIn(
            "--archive /out/Backchannel-linux-x64.tar.gz",
            LINUX_DOCKERFILE,
        )

        # In the workflow every natively packaged archive is smoked after it is
        # zipped and before it is handed off; the Linux build delegates both the
        # packaging and the smoke to Dockerfile.release-linux (asserted above).
        for platform in NATIVE_PLATFORMS:
            spec = PLATFORMS[platform]
            build = _job("build", platform)
            with self.subTest(platform=platform):
                archive = build.index(spec["package"])
                smoke = build.index("smoke_update_archive.py")
                handoff = build.index("id: handoff")
                self.assertLess(archive, smoke)
                self.assertLess(smoke, handoff)
                self.assertIn(
                    "smoke_update_archive.py --platform %s --archive "
                    "../controller/release-assets/%s" % (spec["id"], spec["archive"]),
                    build,
                )
        linux_build = _job("build", "linux")
        self.assertNotIn("smoke_update_archive.py", linux_build)
        self.assertLess(
            linux_build.index("--file controller/desktop/Dockerfile.release-linux"),
            linux_build.index("id: handoff"),
        )


if __name__ == "__main__":
    unittest.main()
