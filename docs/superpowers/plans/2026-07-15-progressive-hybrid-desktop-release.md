# Progressive Hybrid Desktop Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and publish Windows, Linux, and macOS desktop bundles independently so each appears in the authenticated portal immediately after its own native smoke test succeeds.

**Architecture:** New releases use one immutable `release.json` identity plus one immutable manifest per completed platform. A local PowerShell coordinator builds and publishes Windows and Linux from an exact tag; a three-job GitHub workflow builds macOS without credentials, passes its checksum-pinned bundle through a run-unique Actions cache, publishes it from a fresh protected macOS job, and deletes the cache by exact ID from a secret-free cleanup job. The portal merges valid platform manifests into its existing release shape while continuing to support historical aggregate manifests.

> **2026-07-22 amendment:** The cache handoff above supersedes Task 5's artifact upload/download and artifact-retention details, plus the artifact-specific acceptance checks below. The trust boundary, exact tag provenance, SHA-256 validation, protected publication, and bounded cleanup requirements remain unchanged. Existing coordinator cleanup remains only for legacy artifact handoffs.

**Tech Stack:** Python 3.12 stdlib, PowerShell 7/Windows PowerShell 5.1, Node 24 stdlib, Cloudflare R2, Cloudflare Workers/D1, GitHub Actions, Docker BuildKit, PyInstaller, React/Vite.

## Global Constraints

- Never move or replace the annotated `v0.2.4` tag; every bundle must use peeled commit `8a55c52f942396dd5626407a66e8a56050fadfbe`.
- Keep `scripts/r2-object.mjs` as the sole R2 transport; add no AWS CLI, SDK, storage service, or upload service.
- Keep R2 credentials out of native build jobs and logs. Scope them to platform-publication steps only.
- Publish per platform in this order: asset, remote-size check, immutable platform manifest, readback validation, conditional Latest.
- A platform is visible only after its immutable platform manifest validates. Never expose pending objects or arbitrary R2 keys.
- Keep historical `releases/{version}/manifest.json` behavior unchanged.
- Create `release.json` and `platforms/{id}.json` with `If-None-Match: *`; never overwrite them.
- Build Windows and Linux on this Windows x64 workstation; Linux uses its Linux x64 Docker engine; GitHub builds only macOS arm64.
- Delete the run-unique macOS cache by exact ID after verified publication; automatic cache eviction is the cancellation fallback.
- GitHub releases contain source notes only, with no executable attachments.
- Add no dependency for validation, hashing, JSON, orchestration, cleanup, or R2 transport.

---

### Task 0: Establish the required Python runtime

**Machine state:**
- Current `python.exe` entries are Windows Store aliases, not a working interpreter.
- The implementation and release contract require Python 3.12.

- [ ] **Step 1: Confirm the prerequisite is still missing**

```powershell
Get-Command python -All
python --version
```

Expected before installation: no runnable Python 3.12 interpreter. If Python 3.12 is already present when execution begins, skip installation and record its resolved path.

- [ ] **Step 2: Install Python 3.12 for the current user**

After obtaining the execution-time approval for this external installation, run:

```powershell
winget install --exact --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
```

Open a fresh noninteractive PowerShell process so the user PATH is reloaded. Do not install repository dependencies globally.

- [ ] **Step 3: Verify the exact runtime and create the implementation environment**

```powershell
python --version
python -c "import sys; assert sys.version_info[:2] == (3, 12); print(sys.executable)"
$ImplementationVenv = Join-Path $env:TEMP "backchannel-progressive-release-venv"
python -m venv $ImplementationVenv
$Python = Join-Path $ImplementationVenv "Scripts\python.exe"
& $Python -m pip install --upgrade pip
& $Python -m pip install -r backend/requirements.txt -r desktop/requirements.txt
```

Expected: Python reports 3.12.x, the interpreter path is user-scoped, and the temp venv installs outside the repository. In each later PowerShell block, `$Python` means `Join-Path $env:TEMP "backchannel-progressive-release-venv\Scripts\python.exe"`; the release coordinator creates its own disposable release venv.

---

### Task 1: Progressive release metadata primitives

**Files:**
- Modify: `desktop/scripts/build_release_manifest.py:1-151`
- Create: `desktop/scripts/build_platform_manifest.py`
- Create: `desktop/tests/test_platform_release_manifest.py`
- Test: `desktop/tests/test_release_manifest.py`

**Interfaces:**
- Consumes: existing `ASSETS`, `_version()`, `_timestamp()`, `_hash()`, and `_json_bytes()`.
- Produces: `build_release_identity(tag: str, commit: str, published_at: str) -> dict`.
- Produces: `build_platform_manifest(asset_path: Path, tag: str, commit: str, platform_id: str) -> dict`.
- Produces CLI: `python desktop/scripts/build_platform_manifest.py --asset ... --platform-id ... --tag ... --commit ... --published-at ... --release-out ... --platform-out ...`.

- [ ] **Step 1: Write failing metadata tests**

Create `desktop/tests/test_platform_release_manifest.py` with these core cases:

```python
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from desktop.scripts.build_release_manifest import (
    ASSETS,
    build_platform_manifest,
    build_release_identity,
)

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "desktop" / "scripts" / "build_platform_manifest.py"
TAG = "v1.2.3"
COMMIT = "a" * 40
PUBLISHED_AT = "2026-07-15T18:00:00Z"


class PlatformReleaseManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def asset(self, platform_id, payload=b"bundle"):
        filename = next(value[2] for value in ASSETS if value[0] == platform_id)
        path = self.root / filename
        path.write_bytes(payload)
        return path

    def test_release_identity_is_exact_and_normalizes_utc(self):
        self.assertEqual(
            build_release_identity(TAG, COMMIT, "2026-07-15T18:00:00+00:00"),
            {"version": TAG, "published_at": PUBLISHED_AT, "commit": COMMIT},
        )

    def test_each_platform_uses_only_its_trusted_tuple(self):
        for platform_id, platform, filename, content_type in ASSETS:
            with self.subTest(platform_id=platform_id):
                payload = platform_id.encode()
                path = self.asset(platform_id, payload)
                self.assertEqual(
                    build_platform_manifest(path, TAG, COMMIT, platform_id),
                    {
                        "version": TAG,
                        "commit": COMMIT,
                        "asset": {
                            "id": platform_id,
                            "platform": platform,
                            "filename": filename,
                            "key": f"releases/{TAG}/{filename}",
                            "size": len(payload),
                            "sha256": hashlib.sha256(payload).hexdigest(),
                            "content_type": content_type,
                        },
                    },
                )

    def test_rejects_unknown_id_wrong_name_symlink_and_empty_file(self):
        path = self.asset("windows-x64")
        with self.assertRaisesRegex(ValueError, "platform"):
            build_platform_manifest(path, TAG, COMMIT, "unknown")
        wrong = self.root / "wrong.zip"
        wrong.write_bytes(b"bundle")
        with self.assertRaisesRegex(ValueError, "filename"):
            build_platform_manifest(wrong, TAG, COMMIT, "windows-x64")
        with mock.patch.object(Path, "is_symlink", return_value=True):
            with self.assertRaisesRegex(ValueError, "symlink"):
                build_platform_manifest(path, TAG, COMMIT, "windows-x64")
        path.write_bytes(b"")
        with self.assertRaisesRegex(ValueError, "empty"):
            build_platform_manifest(path, TAG, COMMIT, "windows-x64")

    def test_cli_writes_compact_deterministic_metadata(self):
        asset = self.asset("linux-x64", b"linux")
        release_out = self.root / "metadata" / "release.json"
        platform_out = self.root / "metadata" / "linux-x64.json"
        result = subprocess.run(
            [
                sys.executable, str(CLI), "--asset", str(asset),
                "--platform-id", "linux-x64", "--tag", TAG,
                "--commit", COMMIT, "--published-at", PUBLISHED_AT,
                "--release-out", str(release_out),
                "--platform-out", str(platform_out),
            ], cwd=ROOT, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        expected_release = json.dumps(
            build_release_identity(TAG, COMMIT, PUBLISHED_AT),
            sort_keys=True, separators=(",", ":"),
        ).encode() + b"\n"
        expected_platform = json.dumps(
            build_platform_manifest(asset, TAG, COMMIT, "linux-x64"),
            sort_keys=True, separators=(",", ":"),
        ).encode() + b"\n"
        self.assertEqual(release_out.read_bytes(), expected_release)
        self.assertEqual(platform_out.read_bytes(), expected_platform)
```

- [ ] **Step 2: Run the test and verify the interfaces are missing**

Run:

```powershell
& "$env:TEMP\backchannel-progressive-release-venv\Scripts\python.exe" -m unittest desktop.tests.test_platform_release_manifest -v
```

Expected: import failure for `build_platform_manifest` or `build_release_identity`.

- [ ] **Step 3: Add minimal builders without changing aggregate behavior**

Add beside `build_manifest()` in `desktop/scripts/build_release_manifest.py`:

```python
ASSETS_BY_ID = {asset[0]: asset for asset in ASSETS}


def _commit(value: str) -> str:
    if not isinstance(value, str) or not COMMIT_RE.fullmatch(value):
        raise ValueError("commit must be lowercase 40-hex")
    return value


def build_release_identity(tag: str, commit: str, published_at: str) -> dict:
    _version(tag)
    return {
        "version": tag,
        "published_at": _timestamp(published_at),
        "commit": _commit(commit),
    }


def build_platform_manifest(
    asset_path: Path, tag: str, commit: str, platform_id: str
) -> dict:
    _version(tag)
    commit = _commit(commit)
    trusted = ASSETS_BY_ID.get(platform_id)
    if trusted is None:
        raise ValueError(f"invalid platform id: {platform_id!r}")
    asset_id, platform, filename, content_type = trusted
    path = Path(asset_path)
    if path.name != filename:
        raise ValueError(f"platform asset must use trusted filename: {filename}")
    if path.is_symlink():
        raise ValueError(f"release asset cannot be a symlink: {filename}")
    if not path.is_file():
        raise ValueError(f"release asset must be a regular file: {filename}")
    size = path.stat().st_size
    if size <= 0:
        raise ValueError(f"release asset cannot be empty: {filename}")
    return {
        "version": tag,
        "commit": commit,
        "asset": {
            "id": asset_id,
            "platform": platform,
            "filename": filename,
            "key": f"releases/{tag}/{filename}",
            "size": size,
            "sha256": _hash(path),
            "content_type": content_type,
        },
    }
```

Replace the duplicate commit validation in `build_manifest()` with `_commit(commit)` and leave every aggregate branch and flag intact.

- [ ] **Step 4: Add the narrow metadata CLI**

Create `desktop/scripts/build_platform_manifest.py`:

```python
"""Build deterministic identity and one immutable platform manifest."""

import argparse
from pathlib import Path

from desktop.scripts.build_release_manifest import (
    _json_bytes,
    build_platform_manifest,
    build_release_identity,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--asset", type=Path, required=True)
    parser.add_argument("--platform-id", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--published-at", required=True)
    parser.add_argument("--release-out", type=Path, required=True)
    parser.add_argument("--platform-out", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        release = build_release_identity(
            arguments.tag, arguments.commit, arguments.published_at
        )
        platform = build_platform_manifest(
            arguments.asset, arguments.tag, arguments.commit, arguments.platform_id
        )
    except ValueError as error:
        parser.error(str(error))
    arguments.release_out.parent.mkdir(parents=True, exist_ok=True)
    arguments.platform_out.parent.mkdir(parents=True, exist_ok=True)
    arguments.release_out.write_bytes(_json_bytes(release))
    arguments.platform_out.write_bytes(_json_bytes(platform))


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run progressive and aggregate metadata tests**

```powershell
& "$env:TEMP\backchannel-progressive-release-venv\Scripts\python.exe" -m unittest desktop.tests.test_platform_release_manifest desktop.tests.test_release_manifest -v
```

Expected: all tests pass, including exact-three and legacy-pair behavior.

- [ ] **Step 6: Commit**

```powershell
git add desktop/scripts/build_release_manifest.py desktop/scripts/build_platform_manifest.py desktop/tests/test_platform_release_manifest.py
git commit -m "feat: add progressive release metadata"
```

---

### Task 2: Progressive portal catalog compatibility

**Files:**
- Modify: `docs-site/release-access.js:12-286`
- Modify: `docs-site/release-access.test.js:1-405`
- Modify: `docs-site/worker.test.js:2012-2184`
- Test consumer: `docs-site/worker.js:817-1060` remains interface-compatible.

**Interfaces:**
- Produces: `parseReleaseIdentity(value, expectedVersion)`.
- Produces: `parsePlatformManifest(value, expectedVersion, expectedCommit, expectedPlatformId)`.
- Preserves: common manifest shape, `resolveEntitlements()`, `releaseSummary()`, and `handleReleaseDownload()`.

- [ ] **Step 1: Add failing strict parser tests**

Extend `docs-site/release-access.test.js` imports and add:

```javascript
const releaseIdentity = {
  version: 'v1.2.3',
  published_at: '2026-07-15T18:00:00Z',
  commit: 'b'.repeat(40),
};
const platformManifest = {
  version: 'v1.2.3',
  commit: releaseIdentity.commit,
  asset: baseAsset,
};

test('progressive metadata is exact and commit-pinned', () => {
  assert.deepEqual(parseReleaseIdentity(releaseIdentity, 'v1.2.3'), releaseIdentity);
  assert.deepEqual(
    parsePlatformManifest(platformManifest, 'v1.2.3', releaseIdentity.commit, 'windows-x64'),
    platformManifest,
  );
  assert.equal(parseReleaseIdentity({ ...releaseIdentity, extra: true }), null);
  assert.equal(parseReleaseIdentity({ ...releaseIdentity, version: 'v01.2.3' }), null);
  assert.equal(parsePlatformManifest(
    { ...platformManifest, commit: 'c'.repeat(40) },
    'v1.2.3', releaseIdentity.commit, 'windows-x64',
  ), null);
  assert.equal(parsePlatformManifest(
    { ...platformManifest, asset: { ...baseAsset, id: 'linux-x64' } },
    'v1.2.3', releaseIdentity.commit, 'windows-x64',
  ), null);
});
```

- [ ] **Step 2: Add failing catalog cases**

Add a `progressiveBucket({ platformIds, invalidId, includeLegacy })` fixture that lists `release.json`, selected `platforms/{id}.json`, and Latest. Add tests for:

```javascript
test('progressive catalog exposes one, two, or three completed platforms', async () => {
  for (const platformIds of [
    ['windows-x64'],
    ['windows-x64', 'linux-x64'],
    ['macos-arm64', 'linux-x64', 'windows-x64'],
  ]) {
    const catalog = await loadReleaseCatalog(progressiveBucket({ platformIds }));
    assert.equal(catalog.latestVersion, 'v1.2.3');
    assert.deepEqual(
      catalog.manifests.get('v1.2.3').assets.map(({ id }) => id).sort(),
      [...platformIds].sort(),
    );
  }
});

test('anchor alone is hidden and invalid sibling does not hide valid assets', async () => {
  const empty = await loadReleaseCatalog(progressiveBucket({ platformIds: [] }));
  assert.equal(empty.manifests.has('v1.2.3'), false);
  const partial = await loadReleaseCatalog(progressiveBucket({
    platformIds: ['windows-x64', 'linux-x64'], invalidId: 'linux-x64',
  }));
  assert.deepEqual(partial.manifests.get('v1.2.3').assets.map(({ id }) => id), ['windows-x64']);
  assert.ok(partial.diagnostics.includes('platform-invalid'));
});

test('legacy and progressive metadata conflict fails closed for the version', async () => {
  const catalog = await loadReleaseCatalog(progressiveBucket({
    platformIds: ['windows-x64'], includeLegacy: true,
  }));
  assert.equal(catalog.manifests.has('v1.2.3'), false);
  assert.ok(catalog.diagnostics.includes('manifest-conflict'));
});
```

- [ ] **Step 3: Run the focused suite and verify failure**

```powershell
Set-Location docs-site
npm run test:release-access
Set-Location ..
```

Expected: missing exports and unsupported progressive keys fail.

- [ ] **Step 4: Extract one trusted asset parser and add progressive parsers**

Extract the current asset checks into `parseAsset(asset, version)`. Keep duplicate-ID and duplicate-filename checks in `parseManifest()`. Add:

```javascript
export function parseReleaseIdentity(value, expectedVersion) {
  if (!value || typeof value !== 'object' || Array.isArray(value)
    || !exactKeys(value, ['version', 'published_at', 'commit'])
    || !VERSION_PATTERN.test(value.version)
    || (expectedVersion !== undefined && value.version !== expectedVersion)
    || !validUtcTimestamp(value.published_at)
    || !/^[0-9a-f]{40}$/.test(value.commit)) return null;
  return value;
}

export function parsePlatformManifest(value, version, commit, platformId) {
  if (!value || typeof value !== 'object' || Array.isArray(value)
    || !exactKeys(value, ['version', 'commit', 'asset'])
    || value.version !== version || value.commit !== commit) return null;
  const asset = parseAsset(value.asset, version);
  return asset?.id === platformId ? value : null;
}
```

- [ ] **Step 5: Merge legacy and progressive catalog keys deterministically**

Add exact `release.json` and `platforms/{trusted-id}.json` patterns. During pagination collect legacy, identity, and platform keys before fetching them. Keep legacy loading unchanged. For each progressive version without a legacy conflict, parse its identity, parse matching platforms against its commit and key ID, order valid assets by `ASSET_TUPLES`, and insert only a nonempty common shape:

```javascript
manifests.set(version, {
  version: identity.version,
  published_at: identity.published_at,
  commit: identity.commit,
  assets,
});
```

Use bounded diagnostics: `manifest-conflict`, `release-invalid`, `release-unavailable`, `platform-invalid`, and `platform-unavailable`. Preserve existing pagination and Latest validation.

- [ ] **Step 6: Add one Worker-level progressive authorization test**

In `docs-site/worker.test.js`, create a progressive fixture containing one Windows platform. Verify `/api/download/releases` lists only Windows without `key`, `content_type`, or `commit`; Windows downloads; Linux returns private `404` without an asset-object read.

- [ ] **Step 7: Run focused and aggregate portal suites**

```powershell
Set-Location docs-site
npm run test:release-access
npm run test:worker
node --test *.test.js
Set-Location ..
```

Expected: zero failures.

- [ ] **Step 8: Commit**

```powershell
git add docs-site/release-access.js docs-site/release-access.test.js docs-site/worker.test.js
git commit -m "feat: expose progressive platform releases"
```

---

### Task 3: Shared local R2 command seam

**Files:**
- Create: `scripts/r2-release-common.ps1`
- Modify: `scripts/migrate_releases_to_r2.ps1:18-78`
- Modify: `scripts/tests/test_migrate_releases_to_r2.ps1:1-177`
- Test: `scripts/tests/r2-object.test.mjs`

**Interfaces:**
- Produces: `Invoke-R2Object([string]$Client, [string[]]$Arguments)`, `Assert-R2Success($Result, $Action)`, and `Get-R2Latest($Destination, $Bucket, $Client)`.
- Preserves exit codes `42` for failed precondition and `44` for missing object.
- Preserves the historical migration CLI and behavior.

- [ ] **Step 1: Change the migration harness to require the shared seam**

Update `scripts/tests/test_migrate_releases_to_r2.ps1` to dot-source `scripts/r2-release-common.ps1`, call `Invoke-R2Object`, and retain every fake-node assertion for valid JSON, exit `44`, access denial, preference restoration, and redacted output. Require the migration script to contain:

```powershell
. (Join-Path $PSScriptRoot "r2-release-common.ps1")
```

- [ ] **Step 2: Run the harness and verify the missing common file fails**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/tests/test_migrate_releases_to_r2.ps1
```

Expected: failure because `scripts/r2-release-common.ps1` is absent.

- [ ] **Step 3: Move only proven native-command helpers into the common file**

Create `scripts/r2-release-common.ps1` with `Set-StrictMode -Version Latest`. Move the existing native preference preservation into `Invoke-R2Object`; its first argument is the checked-in client path and remaining arguments are passed to Node. Add the unchanged success assertion and:

```powershell
function Get-R2Latest {
    param(
        [Parameter(Mandatory = $true)][string]$Destination,
        [Parameter(Mandatory = $true)][string]$Bucket,
        [Parameter(Mandatory = $true)][string]$Client
    )
    if (Test-Path -LiteralPath $Destination) {
        Remove-Item -LiteralPath $Destination -Force
    }
    $result = Invoke-R2Object @(
        $Client, "get", "--bucket", $Bucket,
        "--key", "releases/latest.json", "--output", $Destination
    )
    if ($result.Code -eq 0) {
        return [pscustomobject]@{ Exists = $true; ETag = $result.Data.etag }
    }
    if ($result.Code -eq 44) {
        return [pscustomobject]@{ Exists = $false; ETag = $null }
    }
    throw "Reading Latest failed: $($result.Output)"
}
```

- [ ] **Step 4: Update historical migration without changing write order**

Dot-source the common file after the parameter block. Replace `Invoke-R2` with `Invoke-R2Object @($script:R2Client, ...)`, replace `Get-RemoteLatest` with `Get-R2Latest`, and delete only the moved functions. Preserve `SupportsShouldProcess`, exact asset validation, manifest-before-Latest order, recovery warning, and temporary cleanup.

- [ ] **Step 5: Run transport, migration, manifest, and contract regressions**

```powershell
node --test scripts/tests/r2-object.test.mjs
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/tests/test_migrate_releases_to_r2.ps1
Set-Location desktop
& "$env:TEMP\backchannel-progressive-release-venv\Scripts\python.exe" -m unittest tests.test_release_manifest tests.test_release_contract -v
Set-Location ..
```

Expected: all pass; the PowerShell harness prints `Windows PowerShell native R2 classification: OK`.

- [ ] **Step 6: Commit**

```powershell
git add scripts/r2-release-common.ps1 scripts/migrate_releases_to_r2.ps1 scripts/tests/test_migrate_releases_to_r2.ps1
git commit -m "refactor: share release R2 commands"
```

---

### Task 4: Immutable per-platform R2 publisher

**Files:**
- Create: `scripts/publish_release_platform.ps1`
- Create: `scripts/tests/test_publish_release_platform.ps1`
- Modify: `desktop/tests/test_release_contract.py:1-249`
- Uses: `desktop/scripts/build_platform_manifest.py`
- Uses: `scripts/r2-release-common.ps1`

**Interfaces:**
- CLI: `-Version`, `-Commit`, `-PublishedAt`, `-PlatformId`, `-AssetPath`, and PowerShell `-WhatIf`.
- Environment: `CLOUDFLARE_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_RELEASES_BUCKET`.
- Output: compact success metadata only; never credentials, signed headers, or object bodies.

- [ ] **Step 1: Write a fake-R2 publisher harness**

Create `scripts/tests/test_publish_release_platform.ps1`. Use a temporary `node.cmd` shim and operation log, following the migration harness. It must simulate `get`, `head`, and `put`, create requested output files, return `44` for missing objects, and return `42` for configured create races.

For a new Windows publication assert this exact operation/key order:

```text
get releases/v1.2.3/release.json
put releases/v1.2.3/release.json
get releases/v1.2.3/release.json
get releases/v1.2.3/platforms/windows-x64.json
put releases/v1.2.3/Backchannel-windows-x64.zip
head releases/v1.2.3/Backchannel-windows-x64.zip
put releases/v1.2.3/platforms/windows-x64.json
get releases/v1.2.3/platforms/windows-x64.json
get releases/latest.json
put releases/latest.json
```

Add cases for conflicting identity, identical platform success without asset re-upload, mismatched existing platform failure, remote size mismatch, one Latest `42` retry, Latest equality, and newer Latest non-regression.

- [ ] **Step 2: Run the harness and verify the publisher is absent**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/tests/test_publish_release_platform.ps1
```

Expected: failure because `scripts/publish_release_platform.ps1` is absent.

- [ ] **Step 3: Implement exact-byte immutable metadata handling**

Create `scripts/publish_release_platform.ps1` with `SupportsShouldProcess`, exact parameters, four credential presence checks, checked-in client/helper resolution, a regular asset check, and a unique temporary directory. Generate `release.json`, `platform.json`, and readback files through the Python CLI.

Add:

```powershell
function Assert-ExactBytes {
    param([string]$Expected, [string]$Actual, [string]$Label)
    if (-not (Test-Path -LiteralPath $Actual -PathType Leaf) -or
        [Convert]::ToBase64String([IO.File]::ReadAllBytes($Expected)) -cne
        [Convert]::ToBase64String([IO.File]::ReadAllBytes($Actual))) {
        throw "$Label readback did not match"
    }
}

function Read-R2Json {
    param([string]$Key, [string]$Destination)
    Invoke-R2Object @(
        $script:R2Client, "get", "--bucket", $script:Bucket,
        "--key", $Key, "--output", $Destination
    )
}
```

For absent identity, conditionally create it; on exit `42`, read and compare the winner. For existing platform, accept only exact bytes and skip asset upload. Otherwise upload the asset, require exact `contentLength`, conditionally create the platform manifest, and compare readback bytes.

- [ ] **Step 4: Implement monotonic Latest last**

Use `Get-R2Latest` and the existing version validation. If Latest is older or absent, write `latest.json` with `--if-match` or `--if-none-match '*'`; retry one exit `42`. If it equals the candidate, succeed without writing. If it is newer, keep it unchanged. No R2 call may occur after the Latest put.

- [ ] **Step 5: Add structural contract assertions**

Extend `desktop/tests/test_release_contract.py`:

```python
PLATFORM_PUBLISHER = (ROOT / "scripts" / "publish_release_platform.ps1").read_text()

def test_platform_publisher_is_conditional_verified_and_latest_last(self):
    for value in (
        "SupportsShouldProcess", "build_platform_manifest.py",
        "r2-release-common.ps1", "--if-none-match", "contentLength",
        "platforms/$PlatformId.json", "--if-match", "Updating Latest",
    ):
        self.assertIn(value, PLATFORM_PUBLISHER)
    self.assertNotRegex(
        PLATFORM_PUBLISHER, re.compile(r"(?i)(?:^|[&|;\s])aws(?:\s|$)")
    )
    self.assertLess(
        PLATFORM_PUBLISHER.index("Creating immutable platform manifest"),
        PLATFORM_PUBLISHER.index("Updating Latest"),
    )
    self.assertNotIn("delete", PLATFORM_PUBLISHER.lower())
```

- [ ] **Step 6: Run all publisher dependencies**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/tests/test_publish_release_platform.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/tests/test_migrate_releases_to_r2.ps1
node --test scripts/tests/r2-object.test.mjs
Set-Location desktop
& "$env:TEMP\backchannel-progressive-release-venv\Scripts\python.exe" -m unittest tests.test_platform_release_manifest tests.test_release_manifest tests.test_release_contract -v
Set-Location ..
```

Expected: zero failures and one explicit publisher-harness success line.

- [ ] **Step 7: Commit**

```powershell
git add scripts/publish_release_platform.ps1 scripts/tests/test_publish_release_platform.ps1 desktop/tests/test_release_contract.py
git commit -m "feat: publish immutable platform releases"
```

---

### Task 5: macOS-only build, protected publication, and cleanup

**Files:**
- Modify: `.github/workflows/desktop-release.yml:1-323`
- Modify: `desktop/tests/test_release_contract.py:1-249`

**Interfaces:**
- Dispatch inputs: `release_ref` and `expected_commit`.
- Build output: normalized annotated-tag timestamp.
- Artifact: exactly `Backchannel-macos-arm64.zip`, retained one day.
- Protected publication: R2 credentials only in the publish step; exact artifact deletion uses `actions: write`.

- [ ] **Step 1: Replace old matrix assertions with failing macOS-only contracts**

Add:

```python
def test_workflow_is_dispatch_only_macos_handoff(self):
    self.assertIn("workflow_dispatch:", WORKFLOW)
    self.assertNotIn("tags:", WORKFLOW)
    self.assertIn("release_ref:", WORKFLOW)
    self.assertIn("expected_commit:", WORKFLOW)
    self.assertIn("runs-on: macos-latest", WORKFLOW)
    self.assertNotIn("windows-latest", WORKFLOW)
    self.assertIn("retention-days: 1", WORKFLOW)

def test_macos_build_is_credential_free_and_publish_is_separate(self):
    build, publish = WORKFLOW.split("  publish-macos:", 1)
    for name in ("CLOUDFLARE_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY"):
        self.assertNotIn(name, build)
        self.assertIn(name, publish)
    self.assertIn("environment: production", publish)
    self.assertIn("actions: write", publish)
    self.assertIn("publish_release_platform.ps1", publish)
    self.assertLess(publish.index("publish_release_platform.ps1"), publish.index("--method DELETE"))
```

Keep assertions for frontend, model/PostgreSQL download, PyInstaller, smoke, exact filename, source-only notes, and no AWS command.

- [ ] **Step 2: Run contracts and verify the old matrix fails**

```powershell
Set-Location desktop
& "$env:TEMP\backchannel-progressive-release-venv\Scripts\python.exe" -m unittest tests.test_release_contract -v
Set-Location ..
```

Expected: failures for tag trigger, Windows/Linux runners, missing retention, and missing separate publisher.

- [ ] **Step 3: Rewrite the workflow around two source boundaries**

Use `workflow_dispatch` only. In `build-macos`, checkout current controller code to `controller/` and `release_ref` with `fetch-depth: 0` to `source/`. Verify canonical tag syntax, `git cat-file -t` equals `tag`, and peeled commit equals `expected_commit`. Normalize `%(taggerdate:iso-strict)` to UTC with Python and expose it as a job output.

Run the existing build sequence under `source/`, write the zip to `controller/Backchannel-macos-arm64.zip`, then:

```yaml
- uses: actions/upload-artifact@v4
  with:
    name: Backchannel-macos-arm64.zip
    path: controller/Backchannel-macos-arm64.zip
    retention-days: 1
```

- [ ] **Step 4: Add the protected publication and exact cleanup job**

Add `publish-macos` needing `build-macos`, running Ubuntu in `production`, with `contents: read` and `actions: write`. Checkout controller, set up Node 24/Python 3.12, download the exact artifact, and call:

```yaml
- name: Publish verified macOS platform
  env:
    CLOUDFLARE_ACCOUNT_ID: ${{ secrets.CLOUDFLARE_ACCOUNT_ID }}
    R2_ACCESS_KEY_ID: ${{ secrets.R2_ACCESS_KEY_ID }}
    R2_SECRET_ACCESS_KEY: ${{ secrets.R2_SECRET_ACCESS_KEY }}
    R2_RELEASES_BUCKET: ${{ vars.R2_RELEASES_BUCKET }}
  shell: pwsh
  run: ./scripts/publish_release_platform.ps1 -Version '${{ inputs.release_ref }}' -Commit '${{ inputs.expected_commit }}' -PublishedAt '${{ needs.build-macos.outputs.published_at }}' -PlatformId macos-arm64 -AssetPath release-assets/Backchannel-macos-arm64.zip -Confirm:$false
```

Then query only this run's artifacts, require exactly one matching name, and delete by exact ID:

```bash
artifact_id="$(gh api "repos/$GITHUB_REPOSITORY/actions/runs/$GITHUB_RUN_ID/artifacts" --jq '[.artifacts[] | select(.name == "Backchannel-macos-arm64.zip")] | if length == 1 then .[0].id else error("expected one macOS artifact") end')"
gh api --method DELETE "repos/$GITHUB_REPOSITORY/actions/artifacts/$artifact_id"
```

Keep non-canceling `backchannel-r2-publish` concurrency. Do not create GitHub notes here.

- [ ] **Step 5: Run contracts and diff checks**

```powershell
Set-Location desktop
& "$env:TEMP\backchannel-progressive-release-venv\Scripts\python.exe" -m unittest tests.test_release_contract -v
Set-Location ..
git diff --check
```

Expected: all pass; diff check is empty.

- [ ] **Step 6: Commit**

```powershell
git add .github/workflows/desktop-release.yml desktop/tests/test_release_contract.py
git commit -m "ci: publish macOS releases independently"
```

---

### Task 6: Reproducible local Linux bundle export

**Files:**
- Create: `desktop/Dockerfile.release-linux`
- Modify: `desktop/tests/test_release_contract.py:1-249`
- Uses: `desktop/backchannel.spec`
- Uses: `desktop/scripts/smoke_test.py`

**Interfaces:**
- Input: exact detached release worktree as Docker context.
- Output: Docker local output containing only `Backchannel-linux-x64.tar.gz`.
- No registry push and no runtime-image publication.

- [ ] **Step 1: Add failing Dockerfile contracts**

Add:

```python
LINUX_DOCKERFILE = (ROOT / "desktop" / "Dockerfile.release-linux").read_text()

def test_linux_release_container_builds_smokes_and_exports_one_tarball(self):
    for value in (
        "FROM node:24", "npm ci", "npm run build", "FROM python:3.12",
        "pip install", "download_models.py", "download_pg.py",
        "pyinstaller desktop/backchannel.spec", "desktop/scripts/smoke_test.py",
        'tar -C dist -czf "/out/Backchannel-linux-x64.tar.gz" Backchannel',
        "FROM scratch AS export",
        "COPY --from=bundle /out/Backchannel-linux-x64.tar.gz /",
    ):
        self.assertIn(value, LINUX_DOCKERFILE)
    self.assertNotIn("ENTRYPOINT", LINUX_DOCKERFILE)
    self.assertNotIn("CMD", LINUX_DOCKERFILE)
```

- [ ] **Step 2: Run the contract and verify the Dockerfile is absent**

```powershell
Set-Location desktop
& "$env:TEMP\backchannel-progressive-release-venv\Scripts\python.exe" -m unittest tests.test_release_contract -v
Set-Location ..
```

Expected: file-not-found failure.

- [ ] **Step 3: Add the multi-stage release Dockerfile**

Create `desktop/Dockerfile.release-linux`:

```dockerfile
# syntax=docker/dockerfile:1
FROM node:24-bookworm-slim AS frontend
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS bundle
RUN apt-get update && apt-get install -y --no-install-recommends \
    libsndfile1 libx11-6 libxext6 libxrender1 libsm6 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY backend/requirements.txt backend/requirements.txt
COPY desktop/requirements.txt desktop/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt -r desktop/requirements.txt
COPY backend/ backend/
COPY desktop/ desktop/
COPY --from=frontend /src/frontend/dist frontend/dist
RUN python backend/scripts/download_models.py
RUN python desktop/scripts/download_pg.py
RUN pyinstaller desktop/backchannel.spec --distpath dist --workpath build --noconfirm
RUN python desktop/scripts/smoke_test.py
RUN mkdir /out && tar -C dist -czf "/out/Backchannel-linux-x64.tar.gz" Backchannel

FROM scratch AS export
COPY --from=bundle /out/Backchannel-linux-x64.tar.gz /
```

If the real smoke test reports one missing shared library, add only the package providing that exact library and record the evidence in the commit.

- [ ] **Step 4: Build, smoke, and export locally**

```powershell
$tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$output = Join-Path $tempRoot ("backchannel-linux-release-check-" + [guid]::NewGuid().ToString("N"))
try {
    New-Item -ItemType Directory -Path $output | Out-Null
    docker build --file desktop/Dockerfile.release-linux --target export --output "type=local,dest=$output" .
    if ($LASTEXITCODE -ne 0) { throw "Linux release container failed" }
    $asset = Get-Item (Join-Path $output "Backchannel-linux-x64.tar.gz")
    if ($asset.Length -le 0) { throw "Linux release tarball is empty" }
} finally {
    $resolvedOutput = [IO.Path]::GetFullPath($output)
    if (-not $resolvedOutput.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing cleanup outside the temporary root"
    }
    if (Test-Path -LiteralPath $resolvedOutput) {
        Remove-Item -LiteralPath $resolvedOutput -Recurse -Force
    }
}
```

Expected: Docker exits `0`; smoke output includes `OK: healthy` and `OK: clean shutdown`; the tarball has positive length.

- [ ] **Step 5: Run desktop contracts and commit**

```powershell
Set-Location desktop
& "$env:TEMP\backchannel-progressive-release-venv\Scripts\python.exe" -m unittest tests.test_release_contract -v
Set-Location ..
git add desktop/Dockerfile.release-linux desktop/tests/test_release_contract.py
git commit -m "build: add local Linux desktop bundle"
```

---

### Task 7: One-command local Windows/Linux coordinator

**Files:**
- Create: `scripts/release_desktop.ps1`
- Create: `scripts/tests/test_release_desktop.ps1`
- Modify: `desktop/tests/test_release_contract.py:1-249`
- Uses: `desktop/Dockerfile.release-linux`
- Uses: `scripts/publish_release_platform.ps1`
- Uses: `.github/workflows/desktop-release.yml`

**Interfaces:**
- CLI: `./scripts/release_desktop.ps1 -Version vX.Y.Z [-WhatIf]`.
- Outputs: `release-assets/{version}/Backchannel-windows-x64.zip` and `Backchannel-linux-x64.tar.gz`.
- Dispatch: `gh workflow run desktop-release.yml --ref master -f release_ref={version} -f expected_commit={peeled}`.
- Exit `0` only when every platform is published; one local failure does not prevent the other local build.
- Preflight: `Get-ReleasePublicationState` validates existing progressive identity and platform metadata before any native build and returns `Pending` or `Completed` per trusted platform.

- [ ] **Step 1: Write coordinator and bounded cleanup tests**

Create `scripts/tests/test_release_desktop.ps1`. Parse the coordinator with the PowerShell AST and require functions `Invoke-Checked`, `Resolve-ReleaseTag`, `Get-ReleasePublicationState`, `Remove-StaleMacArtifacts`, `Build-WindowsRelease`, and `Build-LinuxRelease`.

Use the fake Node/R2 pattern from the publisher harness to prove that an absent identity returns every platform as `Pending`; a matching strict identity plus matching trusted platform manifest returns that platform as `Completed`; a conflicting identity stops all work; and a malformed or mismatched platform is recorded as that platform's failure before its build function can run. Assert a completed Windows or Linux platform is not rebuilt and a completed macOS platform is not redispatched.

Test `Remove-StaleMacArtifacts` with a fake `gh.cmd` returning five artifacts:

1. exact name, this workflow, completed, older than 24 hours: deleted;
2. exact name, this workflow, completed, younger than 24 hours: retained;
3. exact name, another workflow: retained;
4. another name, this workflow: retained;
5. exact name, active run: retained.

Assert the exact artifact-ID delete endpoint is used and any API failure propagates before dispatch.

Extend Python contracts:

```python
COORDINATOR = (ROOT / "scripts" / "release_desktop.ps1").read_text()

def test_local_coordinator_is_tag_pinned_progressive_and_failure_isolated(self):
    for value in (
        "SupportsShouldProcess", "git worktree add --detach", "^{commit}",
        "taggerdate", "Get-ReleasePublicationState", "Remove-StaleMacArtifacts",
        "gh workflow run",
        "desktop-release.yml", "Build-WindowsRelease", "Build-LinuxRelease",
        "publish_release_platform.ps1", "Backchannel-windows-x64.zip",
        "Backchannel-linux-x64.tar.gz", "gh run watch", "gh release",
    ):
        self.assertIn(value, COORDINATOR)
    self.assertLess(COORDINATOR.index("Build-WindowsRelease"),
                    COORDINATOR.index("Build-LinuxRelease"))
    self.assertIn("$failures", COORDINATOR)
    self.assertIn("finally", COORDINATOR)
```

- [ ] **Step 2: Run tests and verify the coordinator is absent**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/tests/test_release_desktop.ps1
Set-Location desktop
& "$env:TEMP\backchannel-progressive-release-venv\Scripts\python.exe" -m unittest tests.test_release_contract -v
Set-Location ..
```

Expected: missing-file/function failures.

- [ ] **Step 3: Implement prerequisites, exact tag resolution, and progressive preflight**

Create `scripts/release_desktop.ps1` with `SupportsShouldProcess`. Require canonical annotated tag syntax, clean synchronized `master`, matching local/remote peeled commits and tag timestamps, authenticated `gh`, Node major `>=24`, Python `3.12`, and Docker `linux/x86_64`.

After resolving the tag but before cleanup, dispatch, a worktree, or a native build, use `Invoke-R2Object` to read `release.json` and the three trusted platform-manifest keys. `Get-ReleasePublicationState` must require exact JSON property sets, the expected version and peeled commit, each trusted platform tuple, a positive integer size, and a lowercase 64-hex SHA-256. A missing platform manifest under a valid identity is `Pending`; matching valid metadata is `Completed`; conflicting release identity stops the coordinator; a platform manifest without an identity and malformed or conflicting platform metadata record that platform as failed so valid siblings can continue. When no progressive objects exist, all platforms are `Pending`. Never infer completion from an asset object without its manifest.

Create one unique temporary parent and detached worktree only when Windows or Linux remains pending:

```powershell
& git worktree add --detach $sourceRoot $Version
Invoke-Checked "Creating release worktree" $LASTEXITCODE
```

In `finally`, resolve and confirm the worktree remains inside the unique temporary parent before `git worktree remove --force` and local temporary cleanup.

- [ ] **Step 4: Implement stale macOS cleanup and exact run capture**

When macOS is pending, list repository artifacts with `gh api`. For each exact `Backchannel-macos-arm64.zip`, read its `workflow_run.id`; delete only when the run path is `.github/workflows/desktop-release.yml`, status is `completed`, and artifact `created_at` is older than 24 hours. Any list, run-read, or eligible delete failure stops before dispatch. When macOS is already `Completed`, skip both cleanup and dispatch.

Dispatch macOS first:

```powershell
gh workflow run desktop-release.yml --ref master `
    -f "release_ref=$Version" -f "expected_commit=$commit"
```

Record dispatch time, then poll `gh run list --workflow desktop-release.yml --event workflow_dispatch --json databaseId,headSha,createdAt,status` and select the matching controller HEAD created after dispatch. Save that database ID; never select "latest" again.

- [ ] **Step 5: Build, smoke, package, and publish Windows immediately**

Inside the detached source worktree:

```powershell
& npm ci --prefix (Join-Path $Source "frontend")
& npm run build --prefix (Join-Path $Source "frontend")
& $Python -m venv (Join-Path $Source ".release-venv")
$venvPython = Join-Path $Source ".release-venv\Scripts\python.exe"
& $venvPython -m pip install -r (Join-Path $Source "backend\requirements.txt") -r (Join-Path $Source "desktop\requirements.txt")
& $venvPython (Join-Path $Source "backend\scripts\download_models.py")
& $venvPython (Join-Path $Source "desktop\scripts\download_pg.py")
& $venvPython -m PyInstaller (Join-Path $Source "desktop\backchannel.spec") --distpath (Join-Path $Source "dist") --workpath (Join-Path $Source "build") --noconfirm
Push-Location $Source
try { & $venvPython desktop/scripts/smoke_test.py } finally { Pop-Location }
Compress-Archive -LiteralPath (Join-Path $Source "dist\Backchannel") -DestinationPath $windowsAsset
```

If Windows is `Pending`, check each native exit code and require a positive-length zip. Invoke `publish_release_platform.ps1` immediately with `windows-x64`. Catch the Windows exception into `$failures` and continue to Linux. If Windows is `Completed`, do not call its build or publisher.

- [ ] **Step 6: Build, export, and publish Linux independently**

Invoke:

```powershell
docker build --file desktop/Dockerfile.release-linux --target export `
    --output "type=local,dest=$linuxOutput" $Source
```

If Linux is `Pending`, require exactly one positive-length tarball, copy it to `release-assets/{version}`, and invoke the platform publisher with `linux-x64`. Catch Linux failure independently. If Linux is `Completed`, do not call its build or publisher.

- [ ] **Step 7: Reconcile macOS and source-only GitHub notes**

When a macOS run was dispatched, run `gh run watch $macRunId --exit-status`. Add `macos-arm64` to `$failures` on failure; never roll back published siblings. Treat a preflight-complete macOS platform as successful without selecting an unrelated run. Create or edit GitHub notes from `.github/release-notes/{version}.md` without uploading executables. Return nonzero after cleanup when `$failures.Count -gt 0`, listing only platform IDs and run URLs.

- [ ] **Step 8: Run tests and commit**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/tests/test_release_desktop.ps1
Set-Location desktop
& "$env:TEMP\backchannel-progressive-release-venv\Scripts\python.exe" -m unittest tests.test_release_contract -v
Set-Location ..
git add scripts/release_desktop.ps1 scripts/tests/test_release_desktop.ps1 desktop/tests/test_release_contract.py
git commit -m "feat: coordinate progressive desktop releases"
```

### Task 8: Operator documentation and complete source gate

**Files:**
- Modify: `docs/releasing.md:120-190`
- Modify: `AGENTS.md:55-85`
- Modify: `CLAUDE.md:67-97`

- [ ] **Step 1: Replace the aggregate-only release instructions**

Document the approved progressive object model exactly:

```text
releases/vX.Y.Z/release.json
releases/vX.Y.Z/platforms/windows-x64.json
releases/vX.Y.Z/platforms/linux-x64.json
releases/vX.Y.Z/platforms/macos-arm64.json
```

State that release identity and each platform manifest are immutable; a platform appears in the portal only after its asset has uploaded, its remote size has been verified, and its manifest has been created. Preserve legacy aggregate-manifest support and document that mixed progressive/legacy metadata for one version is invalid and hidden.

- [ ] **Step 2: Document the one-command hybrid release and recovery model**

Make `scripts/release_desktop.ps1 -Version vX.Y.Z` the standard entry point. Record that it dispatches macOS, builds/publishes Windows, then builds/publishes Linux, while one platform failure does not roll back or block valid siblings. Name only these required user-scoped variables—never values:

```text
CLOUDFLARE_ACCOUNT_ID
R2_ACCESS_KEY_ID
R2_SECRET_ACCESS_KEY
R2_RELEASES_BUCKET
```

Document Python 3.12, Node 24+, Docker `linux/x86_64`, authenticated `gh`, and a clean synchronized `master` as prerequisites. Include exact retry commands using `publish_release_platform.ps1` for an already-built platform, and explain that rerunning publication is safe only when the immutable metadata matches byte-for-byte.

- [ ] **Step 3: Document artifact retention and availability semantics**

State that the macOS build artifact is credential-free, retained for one day, and deleted immediately after protected publication. The coordinator may delete only exact `Backchannel-macos-arm64.zip` artifacts from completed runs of `.github/workflows/desktop-release.yml` older than 24 hours. State that Windows, Linux, and macOS become available independently as soon as their own manifest is valid, while the source-only GitHub release contains no executable assets.

- [ ] **Step 4: Run the complete automated release gate**

From the repository root, run:

```powershell
& "$env:TEMP\backchannel-progressive-release-venv\Scripts\python.exe" -m unittest discover -s backend/tests -v
& "$env:TEMP\backchannel-progressive-release-venv\Scripts\python.exe" -m unittest discover -s desktop/tests -v
npm ci --prefix frontend
npm test --prefix frontend
npm run build --prefix frontend
npm ci --prefix docs-site
npm run test:release-access --prefix docs-site
npm run test:migration --prefix docs-site
npm run test:worker --prefix docs-site
npm run test:admin --prefix docs-site
npm run test:download --prefix docs-site
npm run test:site --prefix docs-site
Set-Location docs-site
node --test *.test.js
Set-Location ..
npm run build --prefix docs-site
node --test scripts/tests/r2-object.test.mjs
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/tests/test_migrate_releases_to_r2.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/tests/test_publish_release_platform.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/tests/test_release_desktop.ps1
C:/Users/thoule/.local/bin/sentrux.exe check .
C:/Users/thoule/.local/bin/sentrux.exe gate .
git diff --check
git status --short
```

Expected: every test and build exits zero; Sentrux reports only the two documented generated-lockfile exceptions; the structural gate passes; the final status contains only the intended implementation and documentation files.

- [ ] **Step 5: Commit the operator contract**

```powershell
git add docs/releasing.md AGENTS.md CLAUDE.md
git diff --cached --check
git commit -m "docs: operate progressive desktop releases"
```

### Task 9: Publish and accept v0.2.4 platform by platform

**Inputs and evidence:**
- Release tag: `v0.2.4`
- Expected commit: immutable peeled tag commit `8a55c52f942396dd5626407a66e8a56050fadfbe`
- Operator command: `scripts/release_desktop.ps1`
- Portal: authenticated recipient release catalog and downloads
- Tracking: Linear `ALP-77`, `ALP-82`, and `ALP-89`

- [ ] **Step 1: Provision missing local prerequisites without exposing secrets**

Verify the Task 0 Python 3.12 installation remains available and that the coordinator resolves it. In the authenticated Cloudflare dashboard, create or select a bucket-scoped R2 Object Read & Write token for the release bucket. Store the account ID, access key, secret key, and bucket name in the four user-scoped environment variables documented in Task 8. Never echo, log, paste into a command transcript, commit, or write those values to the repository.

- [ ] **Step 2: Publish reviewed tooling before invoking the release**

Re-run the complete Task 8 gate on the final tree. Push `master`, verify the pushed commit equals local `HEAD`, and confirm `.github/workflows/desktop-release.yml` is visible on that controller commit. Confirm the frozen v0.2.4 source already contains its reviewed release notes, public release page, and version references; do not alter its existing tag.

- [ ] **Step 3: Audit the existing canonical release tag without changing it**

```powershell
git cat-file -t v0.2.4
git rev-parse v0.2.4^{}
git ls-remote origin refs/tags/v0.2.4 refs/tags/v0.2.4^{}
```

Expected: `git cat-file` reports `tag`; local and remote annotated tag objects agree; and both peel to `8a55c52f942396dd5626407a66e8a56050fadfbe`. The newer controller tooling on `master` builds from this frozen source commit. Stop on any mismatch; never create, move, or replace v0.2.4.

- [ ] **Step 4: Run the hybrid coordinator and observe progressive availability**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/release_desktop.ps1 -Version v0.2.4 -Confirm:$false
```

Record the macOS workflow database ID and each local platform result. After each successful platform publication, authenticate to the recipient portal and verify that platform appears immediately without waiting for unfinished siblings. If one platform fails, record its isolated failure, verify successful siblings remain downloadable, repair only the failed path, and rerun its publisher or workflow without replacing immutable valid metadata.

- [ ] **Step 5: Verify progressive R2 metadata and monotonic Latest**

Use `scripts/r2-object.mjs` to fetch `release.json`, every created platform manifest, and `releases/latest.json` into a temporary directory. Validate:

- release version is `v0.2.4`, commit equals the peeled tag commit, and `published_at` equals the annotated-tag timestamp;
- every platform ID, object key, content type, positive byte size, and SHA-256 matches its asset;
- Latest is `v0.2.4` after the first successful platform and was not rewritten to an older release;
- missing or invalid platform metadata is omitted without hiding valid sibling platforms;
- no legacy `releases/v0.2.4/manifest.json` coexists with progressive metadata.

Delete the temporary verification directory in a `finally` block after recording non-secret evidence.

- [ ] **Step 6: Verify all three recipient downloads independently**

Once each platform completes, download it through the authenticated portal. Compare the downloaded byte count and SHA-256 with that platform manifest. Verify an unavailable platform returns the private not-found response before completion and becomes available without a new Latest write after its manifest is created.

- [ ] **Step 7: Verify GitHub cleanup, source notes, and source deployment**

Use `gh run view $macRunId` to require successful macOS build and protected publish jobs. Use the GitHub artifact API to require zero matching `Backchannel-macos-arm64.zip` artifacts for that run after publication. Confirm other workflow artifacts were not deleted. Verify the v0.2.4 GitHub release uses the checked-in notes and has zero executable assets. Build and start Docker Compose from a detached v0.2.4 worktree, require healthy services, then stop it and remove only that verified disposable worktree.

- [ ] **Step 8: Close tracking only from recorded acceptance evidence**

Read `ALP-77`, `ALP-82`, and `ALP-89` immediately before editing them. Add a concise evidence comment with the exact tag commit, platform availability, manifest/download verification, macOS run URL, artifact-cleanup result, and Docker Compose result. Close only issues whose acceptance criteria are fully proven; leave any unmet issue open with the failing command and next action. Mark the persistent goal complete only when tuned diarization and every required release scenario—not merely this publication architecture—have been validated.

- [ ] **Step 9: Perform the final immutable-state audit**

```powershell
git status --short --branch
git log --oneline --decorate -5
git show --no-patch --format=fuller v0.2.4
git ls-remote origin refs/heads/master refs/tags/v0.2.4 refs/tags/v0.2.4^{}
```

Expected: clean synchronized `master`; immutable local/remote tag agreement; no release secrets or generated bundles in Git; and all acceptance evidence linked from Linear.
