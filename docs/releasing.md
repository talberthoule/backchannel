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

Each platform manifest has exactly `version`, `commit`, and `asset`. The asset
has `id`, `platform`, `filename`, `key`, `size`, `sha256`, and `content_type`:

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
  "version": "vX.Y.Z"
}
```

Content types are `application/zip` for Windows and macOS,
`application/gzip` for Linux, and `application/json` for metadata files.
Asset responses use attachment filenames. Metadata uses `Cache-Control:
no-store`.

## Publication credentials

The production GitHub environment requires these repository secrets:

- `CLOUDFLARE_ACCOUNT_ID`
- `R2_ACCESS_KEY_ID`
- `R2_SECRET_ACCESS_KEY`

It also requires repository variable `R2_RELEASES_BUCKET` with value
`backchannel-desktop-releases`. Create a separate bucket-scoped Cloudflare R2
API token with Object Read & Write permission; Cloudflare exposes its
S3-compatible writer credentials as access-key and secret fields. Do not reuse
or expand the site deployment token.

The local coordinator requires the same four names as user-scoped environment
variables: `CLOUDFLARE_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`,
`R2_SECRET_ACCESS_KEY`, and `R2_RELEASES_BUCKET`. Never print their values. It
also requires Python 3.12, Node 24 or newer, authenticated `gh`, a reachable
Docker engine reporting `linux/x86_64`, and clean `master` synchronized with
`origin/master`.

The checked-in `scripts/r2-object.mjs` client calls Cloudflare R2 directly and
is the only release object transport. `AWS4-HMAC-SHA256` and `x-amz-*` are the
protocol field names Cloudflare requires for its S3-compatible API; they are
not AWS credentials or services.

## Release checklist

### 1. Prepare and validate

1. Start from clean `master`, synchronized with `origin/master`.
2. For a new version, confirm `vX.Y.Z` is unused locally, remotely, and in R2.
   If the annotated tag already exists, verify it and never move it.
3. Update `.github/release-notes/vX.Y.Z.md`, the public release page, and
   current-version references.
4. Run the local test/build gate and `git diff --check`, including the focused
   release transport checks:

   ```powershell
   node --test scripts/tests/r2-object.test.mjs
   powershell -NoProfile -ExecutionPolicy Bypass -File scripts/tests/test_migrate_releases_to_r2.ps1
   powershell -NoProfile -ExecutionPolicy Bypass -File scripts/tests/test_publish_release_platform.ps1
   powershell -NoProfile -ExecutionPolicy Bypass -File scripts/tests/test_release_desktop.ps1
   ```

5. Commit release metadata, then create and push an annotated canonical tag:

   ```powershell
   git tag -a vX.Y.Z -m "Backchannel vX.Y.Z"
   git push origin vX.Y.Z
   ```

Never move or replace a published tag. Correct a bad release with a new patch
tag.

### 2. Run the hybrid desktop release

Run the coordinator from clean synchronized `master`:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/release_desktop.ps1 -Version vX.Y.Z -Confirm:$false
```

It verifies the immutable local and remote annotated tag, checks existing R2
metadata, dispatches macOS, builds and immediately publishes Windows, then
builds and immediately publishes Linux. One platform failure does not roll
back or block valid siblings. Rerunning the coordinator skips platforms whose
immutable metadata already matches.

Every platform publisher performs this fail-closed sequence:

1. Read or conditionally create the immutable release identity, then read it
   back and require byte-equivalent metadata.
2. Reject a conflicting platform manifest or accept an identical one as an
   idempotent completed publication.
3. Upload the asset with its trusted content type and attachment filename.
4. Verify the remote object size.
5. Conditionally create the platform manifest with `If-None-Match: *`.
6. Read back and validate the platform manifest.
7. Conditionally advance monotonic `releases/latest.json` last, using its ETag
   or `If-None-Match: *`; an older version never replaces a newer Latest.

The macOS handoff artifact contains no credentials, is retained for one day,
and is deleted immediately after protected publication. Before dispatch, the
coordinator may delete only exact `Backchannel-macos-arm64.zip` artifacts from
completed runs of `.github/workflows/desktop-release.yml` older than 24 hours.
It never deletes R2 objects.

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
downloads match manifest sizes and SHA-256 values, the macOS handoff is deleted,
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
- Keep every GitHub source tag and release-note page permanently. GitHub does
  not retain executable release assets; the temporary macOS handoff follows the
  bounded cleanup policy above.
