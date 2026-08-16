# Releasing Backchannel

This is the authoritative release checklist. GitHub keeps source tags and
release notes; customer executables are published to private Cloudflare R2 and
delivered through `https://downloads.backchannel.page/`.

## Delivery paths

| Target | Publication trigger | Result |
| --- | --- | --- |
| Docker Compose | Source commit or tag; users rebuild locally | Public source-built `backend` and `frontend` images; no container registry image is published |
| Documentation site | Push to `master` changing site/docs inputs | Cloudflare deploy of `backchannel.page`, `admin.backchannel.page`, and `downloads.backchannel.page` |
| Desktop | `scripts/release_desktop.ps1 -Version vX.Y.Z` after an annotated tag exists | Windows and Linux build locally while macOS builds in GitHub; each smoke-tested platform publishes to private R2 as soon as it finishes |

The coordinator dispatches the macOS workflow and builds Windows before Linux.
The protected macOS publication job is the only GitHub job with R2 credentials.
A normal `master` push does not rebuild desktop bundles. GitHub releases keep
source tags and notes only; they never contain executable files.

Any site release containing the modular admin identity/authorization change
must first complete the preview rehearsal and production mutation freeze,
backup, migration `0003`, zero-count parity checks, atomic Worker/assets
deployment, unfreeze, and smoke sequence in the
[deployment migration cutover](deployment.md#admin-identity-and-authorization-migration-cutover).
Do not roll back after the first new policy mutation without a forward fix or
an explicit policy-to-legacy synchronization.

## Staged customer-link cutover

Follow [Deployment](deployment.md) as the ordered gate for this rollout, using
its [admin migration cutover](deployment.md#admin-identity-and-authorization-migration-cutover).
Merge
the control-plane branch to `master` with a merge commit that preserves hold
commit `57fc8d991b8101a2db5889df16ce5a26078baff2`. Do not squash or rebase this
rollout. Wait for the Site workflow to finish successfully, then verify the
deployed branch before any live R2 catalog write:

```powershell
git fetch origin master
git merge-base --is-ancestor 57fc8d991b8101a2db5889df16ce5a26078baff2 origin/master
if ($LASTEXITCODE -ne 0) { throw 'The download-link hold is not an ancestor of origin/master.' }
```

Stop unless the command exits 0. Then migrate `v0.1.0` once as the catalog
seed, verify it, and continue with the remaining historical versions; do not
migrate the seed a second time. Complete PBKDF2 and account/download acceptance
in the order specified by Deployment.

Only after live Task 7 acceptance, create the sole link-cutover revision:

```powershell
git revert 57fc8d991b8101a2db5889df16ce5a26078baff2
git push origin master
```

That revert restores the exact portal links and site-test expectations. Do not
hand-edit those links, squash unrelated changes into the revert, or use any
other revision for link cutover. Wait for the resulting `master` auto-deploy to
finish before announcing portal availability.

## R2 publication contract

The private bucket is exactly `backchannel-desktop-releases`, bound to the site
Worker as `RELEASES`. Keep both its `r2.dev` URL and every bucket custom domain
disabled. Objects use this layout:

```text
releases/latest.json
releases/vX.Y.Z/release.json
releases/vX.Y.Z/platforms/windows-x64.json
releases/vX.Y.Z/platforms/macos-arm64.json
releases/vX.Y.Z/platforms/linux-x64.json
releases/vX.Y.Z/Backchannel-windows-x64.zip
releases/vX.Y.Z/Backchannel-macos-arm64.zip
releases/vX.Y.Z/Backchannel-linux-x64.tar.gz
```

`release.json` is immutable release identity. Each `platforms/{id}.json` is an
independently immutable completion record for one verified asset. The portal
shows a platform only after its asset uploads, its remote size verifies, and
its platform manifest is created and read back. Windows, Linux, and macOS can
therefore appear independently without waiting for unfinished siblings.

Historical `releases/vX.Y.Z/manifest.json` aggregate manifests remain valid.
The legacy `v0.1.0` and `v0.1.1` manifests contain only their original Windows
and macOS pair. Progressive and aggregate metadata must never coexist for the
same version; the portal treats that version as conflicted and hides it.

`latest.json` is one-field JSON:

```json
{"version":"vX.Y.Z"}
```

Each progressive release identity has exactly `version`, `published_at`, and
`commit`:

```json
{
  "commit": "<40 lowercase hex characters>",
  "published_at": "<strict UTC ISO-8601 timestamp>",
  "version": "vX.Y.Z"
}
```

Each newly published platform manifest has exactly `version`, `commit`,
`published_at`, `release_notes`, `asset`, and `update`. The asset has `id`,
`platform`, `filename`, `key`, `size`, `sha256`, and `content_type`; `update`
has the signing key ID, schema, and unpadded base64url Ed25519 signature:

```json
{
  "asset": {
    "content_type": "application/zip",
    "filename": "Backchannel-windows-x64.zip",
    "id": "windows-x64",
    "key": "releases/vX.Y.Z/Backchannel-windows-x64.zip",
    "platform": "Windows x64",
    "sha256": "<64 lowercase hex characters>",
    "size": 1
  },
  "commit": "<40 lowercase hex characters>",
  "published_at": "<strict UTC ISO-8601 timestamp>",
  "release_notes": "<1 to 8192 UTF-8 bytes>",
  "update": {
    "key_id": "ed25519-2026-07b",
    "schema": 1,
    "signature": "<86-character unpadded base64url Ed25519 signature>"
  },
  "version": "vX.Y.Z"
}
```

The signature covers the public descriptor only: `version`, `commit`,
`published_at`, `release_notes`, public asset fields (`id`, `platform`,
`filename`, `size`, `sha256`), `key_id`, and `schema`. Canonical bytes are
UTF-8 JSON with recursively sorted keys, no insignificant whitespace, and
non-ASCII characters preserved. The private R2 object key and content type are
not signed or returned by `GET /api/update/latest/{platform_id}`.
`latest.json` remains an unsigned pointer; clients verify the pointed
descriptor and retain the greatest signed version and publication time they
have observed.

Content types are `application/zip` for Windows and macOS,
`application/gzip` for Linux, and `application/json` for metadata files.
Asset responses use attachment filenames. Metadata uses `Cache-Control:
no-store`.

## Publication credentials

The protected `production` GitHub environment requires these environment
secrets:

- `CLOUDFLARE_ACCOUNT_ID`
- `R2_ACCESS_KEY_ID`
- `R2_SECRET_ACCESS_KEY`
- `CLOUDFLARE_ACCESS_CLIENT_ID`
- `CLOUDFLARE_ACCESS_CLIENT_SECRET`

The protected environment also requires
`BACKCHANNEL_RELEASE_SIGNING_URL=https://signing.backchannel.page/v1/sign`.
`R2_RELEASES_BUCKET`, with value `backchannel-desktop-releases`, is the one
repository-scoped release variable. Create a separate bucket-scoped Cloudflare
R2 API token with Object Read & Write permission; Cloudflare exposes its
S3-compatible writer credentials as access-key and secret fields. Do not reuse
or expand the site deployment token.

The publisher environment, whether local or the protected macOS publish job,
must provide `BACKCHANNEL_RELEASE_SIGNING_URL`,
`CLOUDFLARE_ACCESS_CLIENT_ID`, and `CLOUDFLARE_ACCESS_CLIENT_SECRET`. The
protected job uses `-SigningMode Remote`; never expose those credentials to the
credential-free build or cleanup jobs.

The Access application allows only the dedicated release publisher service
token. The signing Worker verifies the Access issuer and audience, then
requires the JWT `common_name` to exactly match that token's client ID before
it reads the request body or signing secret.

The local coordinator also requires `CLOUDFLARE_ACCOUNT_ID`,
`R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, and `R2_RELEASES_BUCKET` as
user-scoped environment variables. Set the signer URL to the exact endpoint
above and provide the Access client ID and secret in the same shell. The
coordinator clears the four R2 values and both Access values before setup,
build, and smoke subprocesses; it restores only the R2 values for publication
preflight and all six values around each explicit platform publisher call.
Never print their values. It also requires Python 3.12, Node 24 or newer,
authenticated `gh`, a reachable Docker engine reporting `linux/x86_64`, and
clean `master` synchronized with `origin/master`.

### Genesis key and stage-three cutover

`v0.4.0` is the genesis release of the update channel. After stage-two review
and before its tag was created, the one-time stage-three ceremony below was
completed. It is recorded here as the audit trail; later releases inherit the
established trust root and do not repeat it:

1. Provision the dedicated Access application and service-token policy,
   Secrets Store, and `signing.backchannel.page` custom domain.
2. From the repository root, preflight the required IDs and Wrangler
   authentication, then run the no-disk ceremony:

   ```powershell
   foreach ($name in @("CLOUDFLARE_ACCOUNT_ID", "BACKCHANNEL_RELEASE_SIGNING_STORE_ID")) {
       if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($name))) {
           throw "Missing required environment variable: $name"
       }
   }
   Push-Location release-signing-worker
   try {
       npm ci
       if ($LASTEXITCODE -ne 0) { throw "Signing Worker install failed" }
       npx --no-install wrangler auth token --json | Out-Null
       if ($LASTEXITCODE -ne 0) { throw "Wrangler authentication preflight failed" }
       node scripts/create-signing-key.mjs
       if ($LASTEXITCODE -ne 0) { throw "Signing key ceremony failed" }
   } finally {
       Pop-Location
   }
   ```

   Capture only the ceremony's public JSON output. Do not enable shell tracing
   or save Wrangler authentication output.
3. Replace `desktop/release_signing_keys.json` with
   `ed25519-2026-07b` as its only key and active entry, using the exact public
   key emitted by the ceremony. Do not use a placeholder.
4. Add the real Access audience, Secrets Store binding, and custom domain to
   the signing Worker's stage-three configuration, then deploy and verify it.
5. Rerun the signing and release gates, commit the exact public-only trust-file
   change, complete stage-three review, and only then create the `v0.4.0` tag.

Stage three was proven on 2026-07-28 with Worker version
`cd26d9da-4d07-47f2-b966-332577273337`. An unauthenticated signing request
returned `401`; an authenticated canonical descriptor with SHA-256
`23ebb3b8529859f7cf39272dc3ed6e16f3abe2e60439af2cd53c472bafbda179`
was signed as `ed25519-2026-07b` and verified locally against the checked-in
public key. The proof performed zero R2 operations and published no release.

Every `v0.4.0` platform was published through remote mode. All normal and
planned production publishing uses remote mode.
Deleting the never-used old laptop-held private-key file is a separate ALP-170
operator action.

After `v0.4.0` establishes the installed trust root, future rotations require
a two-release bridge. First add the new public key while keeping the old key
active and publish that bridge through the old remote signer. After the
supported-version floor trusts both keys, switch `active` and publish the next
release through the new remote signer. Keep the prior public key for the
documented compatibility window.

`-SigningMode Local` is reserved for a future, explicitly approved emergency
rotation and is the sole possible exception to remote production publishing.
Stage two exercises Local only in tests. There is no stored local production
key and no automatic fallback from remote mode. An emergency operator must
supply newly generated matching key material explicitly. If no path is passed,
the publisher checks
`%LOCALAPPDATA%\Backchannel\release-signing\ed25519-2026-07b.private`.
Afterward, publish a new patch release, clean up the transient key, and
communicate directly with affected users. An offline client cannot receive an
emergency revocation; the persisted greatest-seen version/time only limits
replay after a client has observed the replacement.

The checked-in `scripts/r2-object.mjs` client calls Cloudflare R2 directly and
is the only release object transport. `AWS4-HMAC-SHA256` and `x-amz-*` are the
protocol field names Cloudflare requires for its S3-compatible API; they are
not AWS credentials or services.

## Update authorization and desktop trust

Deploy `docs-site/migrations/0004_release_update_grants.sql` before enabling
desktop update authorization. The authenticated recipient portal calls
`POST /api/download/update-grants`; the Worker stores only the grant hash with
its exact account, version, asset, and 15-minute expiry. The desktop then
streams `GET /api/update/assets/{version}/{asset_id}` with the raw grant once.
Every request rechecks expiry, account state, revocation, and Latest or
explicit-version entitlement. Raw grants must not enter D1, browser storage,
URLs, logs, or desktop state.

Frozen desktop TLS uses the direct `certifi` CA bundle. Downloads stay under
the application-data update directory, while staging is an exact sibling of
the install root so the final rename remains on one filesystem. Platform roots
and launchers are:

| Platform | Install/archive root | Launcher |
| --- | --- | --- |
| Windows x64 | `Backchannel/` | `Backchannel.exe` |
| Linux x64 | `Backchannel/` | `Backchannel` |
| macOS arm64 | `Backchannel.app/` | `Contents/MacOS/Backchannel` |

Before extraction, require free space for the archive, declared expanded
files, the installed backup, and a 10 percent margin. macOS extraction uses
`/usr/bin/ditto -x -k`; Linux and macOS links must resolve within the one
trusted root. Never replace these paths with a shared temporary filesystem or
Python-only macOS zip extraction.

## Updater acceptance

Run the signed fake-server acceptance from the repository root:

```powershell
$env:PYTHONPATH="$PWD;$PWD\backend;$PWD\desktop"
python -m unittest desktop.tests.test_update_acceptance
```

Run a real Windows archive through native extraction, token-bound health,
successful swap, and forced rollback:

```powershell
python desktop/scripts/smoke_update_archive.py --platform windows-x64 --archive .\release-assets\vX.Y.Z\Backchannel-windows-x64.zip
```

The Linux release-container build performs the same native archive smoke after
creating its tarball and before export:

```powershell
docker build --file desktop/Dockerfile.release-linux --build-context controller=desktop/scripts --target export --output type=local,dest=linux-output .
```

The credential-free macOS build runs
`smoke_update_archive.py --platform macos-arm64` against the real
`ditto -c -k --keepParent` `.app` archive before cache handoff. Its native run
is reserved for the later approved CI phase. Configure the remote publisher
URL and Access service-token credentials in the protected production
environment before allowing that publication job to proceed.

Historical note: ALP-150's staged hold -- no push, publication, production
secrets, or CI/CD until the user explicitly approved the final release phase
-- applied through the `v0.4.0` genesis release and is now closed; `v0.4.0`
is tagged and published.

## Release checklist

### 1. Prepare and validate

1. Start from clean `master`, synchronized with `origin/master`.
2. For a new version, confirm `vX.Y.Z` is unused locally, remotely, and in R2.
   If the annotated tag already exists, verify it and never move it.
3. Update `.github/release-notes/vX.Y.Z.md`, the in-app version and release
   notes (`APP_VERSION` and a new `RELEASE_NOTES` entry in
   `backend/app/release_notes.py`), the public release page, and
   current-version references. The public site carries SEO metadata that must
   track the release:
   - the new `site/releases/vX.Y.Z/index.html` page's JSON-LD block
     (`softwareVersion`, `datePublished`, `downloadUrl`, `releaseNotes`,
     GitHub tag `sameAs`) - copy the prior release's block and substitute;
   - `softwareVersion` and `releaseNotes` in the homepage JSON-LD
     (`site/index.html`);
   - a new row plus updated "Latest" references in `site/releases/index.html`;
   - a new `<url>` entry with `<lastmod>` in `site/sitemap.xml`, and refreshed
     `<lastmod>` on every page the release touches;
   - the "Desktop release" links and version references in `site/llms.txt`.
4. Run the local test/build gate and `git diff --check`, including the focused
   release transport checks:

   ```powershell
   node --test scripts/tests/r2-object.test.mjs
   powershell -NoProfile -ExecutionPolicy Bypass -File scripts/tests/test_migrate_releases_to_r2.ps1
   powershell -NoProfile -ExecutionPolicy Bypass -File scripts/tests/test_publish_release_platform.ps1
   powershell -NoProfile -ExecutionPolicy Bypass -File scripts/tests/test_release_desktop.ps1
   ```

5. Commit release metadata, then create and push an annotated canonical tag
   (`v0.4.0` completed the one-time reviewed stage-three genesis ceremony and
   cutover above before its tag; later releases skip that ceremony):

   ```powershell
   git tag -a vX.Y.Z -m "Backchannel vX.Y.Z"
   git push origin vX.Y.Z
   ```

Never move or replace a published tag. Correct a bad release with a new patch
tag.

### 2. Run the hybrid desktop release

Run the coordinator from clean synchronized `master`:

```powershell
& ./scripts/release_desktop.ps1 -Version vX.Y.Z -Confirm:$false
```

Use the call operator from inside PowerShell. Do not "simplify" this back to
`powershell -File`: that form passes every argument as a string, so
`-Confirm:$false` never binds to the switch and the run dies immediately with
`Cannot convert 'System.String' to the type
'System.Management.Automation.SwitchParameter'`. It fails before doing any
work, but it cost a cycle on both v0.4.0 and v0.5.0 (ALP-268).

The run ends with a per-platform outcome summary. Read that rather than the
exit code alone; cleanup failures after a successful publish are warnings and
deliberately do not change the exit status, because this checkout is
OneDrive-synced and its worktree is routinely locked.

It verifies the immutable local and remote annotated tag, checks existing R2
metadata, dispatches macOS, builds and immediately publishes Windows, then
builds and immediately publishes Linux. One platform failure does not roll
back or block valid siblings. Rerunning the coordinator skips platforms whose
immutable metadata already matches.

Every platform publisher performs this fail-closed sequence:

1. Require the versioned release-note file and remote signer environment, ask
   the Worker to sign the complete public update descriptor, then verify the
   detached signature against the active checked-in public key before any R2
   request.
2. Read or conditionally create the immutable release identity, then read it
   back and require byte-equivalent metadata.
3. Reject a conflicting platform manifest or accept an identical one as an
   idempotent completed publication.
4. Conditionally create the asset with `If-None-Match: *`, its trusted content
   type, and attachment filename. On a retry, download an existing object and
   require byte-equivalence instead of overwriting it.
5. Verify the remote object size.
6. Conditionally create the platform manifest with `If-None-Match: *`.
7. Read back and validate the platform manifest.
8. Conditionally advance monotonic `releases/latest.json` last, using its ETag
   or `If-None-Match: *`; an older version never replaces a newer Latest.

The macOS handoff is a non-secret Actions cache entry keyed as
`backchannel-macos-{run_id}-{run_attempt}-{commit}-{sha256}`. A fresh protected
macOS runner restores only that full key with no fallback, verifies its SHA-256,
and publishes it. A separate secret-free cleanup job deletes the cache by exact
ID after publication, including publisher failure paths. GitHub's cache eviction
is the fallback for whole-workflow cancellation or runner loss.
The coordinator may still delete legacy one-day handoff artifacts from older
completed runs. Neither cleanup path deletes R2 objects.

To retry an already-built Windows or Linux asset directly, first resolve the
same immutable tag commit and timestamp, then invoke its publisher:

```powershell
$version = 'vX.Y.Z'
$commit = (& git rev-parse "$version^{commit}").Trim()
$publishedAt = [DateTimeOffset]::Parse(
    (& git for-each-ref '--format=%(taggerdate:iso-strict)' "refs/tags/$version").Trim()
).ToUniversalTime().ToString("yyyy-MM-dd'T'HH:mm:ss'Z'")

.\scripts\publish_release_platform.ps1 -Version $version -Commit $commit -PublishedAt $publishedAt -PlatformId windows-x64 -AssetPath ".\release-assets\$version\Backchannel-windows-x64.zip" -Confirm:$false
.\scripts\publish_release_platform.ps1 -Version $version -Commit $commit -PublishedAt $publishedAt -PlatformId linux-x64 -AssetPath ".\release-assets\$version\Backchannel-linux-x64.tar.gz" -Confirm:$false
```

A retry is safe only when release and platform metadata match byte-for-byte.
Use a new patch version to correct an already published platform.

Do not call the release complete until every platform build and publication
passes, each platform appears in the entitled portal as soon as it completes,
downloads match manifest sizes and SHA-256 values, the macOS cache is deleted,
the public release page and source-only GitHub notes are live, and a Compose
build from the source tag succeeds.

## Historical migration

Use owner-authenticated local copies of the original assets. Each asset
directory must contain only the files named below:

| Version | Required files |
| --- | --- |
| `v0.1.0` | Windows zip, macOS zip |
| `v0.1.1` | Windows zip, macOS zip |
| `v0.2.0` | Windows zip, macOS zip, Linux tarball |
| `v0.2.1` | Windows zip, macOS zip, Linux tarball |

Set the four publication environment variables without printing their values,
then resolve each original peeled tag commit and time and migrate in order:

```powershell
$env:R2_RELEASES_BUCKET = 'backchannel-desktop-releases'

$v010Commit = (& git rev-parse 'v0.1.0^{commit}').Trim()
$v010Time = [DateTimeOffset]::Parse(
    (& git show -s --format=%cI 'v0.1.0^{commit}').Trim(),
    [Globalization.CultureInfo]::InvariantCulture
).UtcDateTime.ToString("yyyy-MM-dd'T'HH:mm:ss'Z'", [Globalization.CultureInfo]::InvariantCulture)
.\scripts\migrate_releases_to_r2.ps1 -Version v0.1.0 -Commit $v010Commit -PublishedAt $v010Time -AssetDirectory .\release-assets\v0.1.0

$v011Commit = (& git rev-parse 'v0.1.1^{commit}').Trim()
$v011Time = [DateTimeOffset]::Parse(
    (& git show -s --format=%cI 'v0.1.1^{commit}').Trim(),
    [Globalization.CultureInfo]::InvariantCulture
).UtcDateTime.ToString("yyyy-MM-dd'T'HH:mm:ss'Z'", [Globalization.CultureInfo]::InvariantCulture)
.\scripts\migrate_releases_to_r2.ps1 -Version v0.1.1 -Commit $v011Commit -PublishedAt $v011Time -AssetDirectory .\release-assets\v0.1.1

$v020Commit = (& git rev-parse 'v0.2.0^{commit}').Trim()
$v020Time = [DateTimeOffset]::Parse(
    (& git show -s --format=%cI 'v0.2.0^{commit}').Trim(),
    [Globalization.CultureInfo]::InvariantCulture
).UtcDateTime.ToString("yyyy-MM-dd'T'HH:mm:ss'Z'", [Globalization.CultureInfo]::InvariantCulture)
.\scripts\migrate_releases_to_r2.ps1 -Version v0.2.0 -Commit $v020Commit -PublishedAt $v020Time -AssetDirectory .\release-assets\v0.2.0

$v021Commit = (& git rev-parse 'v0.2.1^{commit}').Trim()
$v021Time = [DateTimeOffset]::Parse(
    (& git show -s --format=%cI 'v0.2.1^{commit}').Trim(),
    [Globalization.CultureInfo]::InvariantCulture
).UtcDateTime.ToString("yyyy-MM-dd'T'HH:mm:ss'Z'", [Globalization.CultureInfo]::InvariantCulture)
.\scripts\migrate_releases_to_r2.ps1 -Version v0.2.1 -Commit $v021Commit -PublishedAt $v021Time -AssetDirectory .\release-assets\v0.2.1 -SetLatest
```

Use `-SetLatest` only on the final intended version and only after every older
asset and manifest has verified. The migration script never grants an account
and never deletes old assets.

## Failure recovery and rollback

- Any failure before one platform's manifest is created leaves that platform
  hidden. Valid siblings remain available, and Latest may name the progressive
  release as soon as its first platform is complete.
- Never overwrite release identity or a published platform manifest. Use a new
  patch tag to correct completed metadata.
- A failure after asset upload but before platform-manifest creation leaves an
  unpublished object for manual inspection. No automated R2 cleanup guesses
  which object to remove.
- If a platform manifest was created, treat that platform as published and
  immutable even when a sibling or later step fails.
- If only GitHub note creation fails after Latest advances, leave verified R2
  metadata unchanged and repair the notes without attaching files.
- Keep every GitHub source tag and release-note page permanently. GitHub
  Releases have no executable attachments and this workflow creates no Actions
  artifacts; the temporary macOS cache follows the bounded cleanup policy above.
