# Releasing Backchannel

This is the authoritative release checklist. GitHub keeps source tags and
release notes; customer executables are published to private Cloudflare R2 and
delivered through `https://downloads.backchannel.page/`.

## Delivery paths

| Target | Publication trigger | Result |
| --- | --- | --- |
| Docker Compose | Source commit or tag; users rebuild locally | Public source-built `backend` and `frontend` images; no container registry image is published |
| Documentation site | Push to `master` changing site/docs inputs | Cloudflare deploy of `backchannel.page`, `admin.backchannel.page`, and `downloads.backchannel.page` |
| Desktop | Canonical `vX.Y.Z` tag | Three smoke-tested native assets published to private R2; GitHub receives notes without files |

`workflow_dispatch` builds and smoke-tests workflow artifacts only. It never
publishes R2 objects, advances Latest, or creates a GitHub release. A normal
`master` push does not rebuild desktop bundles.

## R2 publication contract

The private bucket is exactly `backchannel-desktop-releases`, bound to the site
Worker as `RELEASES`. Keep both its `r2.dev` URL and every bucket custom domain
disabled. Objects use this layout:

```text
releases/latest.json
releases/vX.Y.Z/manifest.json
releases/vX.Y.Z/Backchannel-windows-x64.zip
releases/vX.Y.Z/Backchannel-macos-arm64.zip
releases/vX.Y.Z/Backchannel-linux-x64.tar.gz
```

Current tags contain exactly those three assets. The legacy `v0.1.0` and
`v0.1.1` manifests contain only their original Windows and macOS pair.

`latest.json` is one-field JSON:

```json
{"version":"vX.Y.Z"}
```

Each immutable manifest has exactly `version`, `published_at`, `commit`, and
`assets`. Every asset has `id`, `platform`, `filename`, `key`, `size`,
`sha256`, and `content_type`:

```json
{
  "assets": [
    {
      "content_type": "application/zip",
      "filename": "Backchannel-windows-x64.zip",
      "id": "windows-x64",
      "key": "releases/vX.Y.Z/Backchannel-windows-x64.zip",
      "platform": "Windows x64",
      "sha256": "<64 lowercase hex characters>",
      "size": 1
    }
  ],
  "commit": "<40 lowercase hex characters>",
  "published_at": "<strict UTC ISO-8601 timestamp>",
  "version": "vX.Y.Z"
}
```

Content types are `application/zip` for Windows and macOS,
`application/gzip` for Linux, and `application/json` for both metadata files.
Asset responses use attachment filenames. Metadata uses `Cache-Control:
no-store`.

## Publication credentials

The production GitHub environment requires these repository secrets:

- `CLOUDFLARE_ACCOUNT_ID`
- `R2_ACCESS_KEY_ID`
- `R2_SECRET_ACCESS_KEY`

It also requires repository variable `R2_RELEASES_BUCKET` with value
`backchannel-desktop-releases`. Create a separate bucket-scoped R2 S3 Object
Read & Write credential for publication. Do not reuse or expand the site
deployment token.

## Release checklist

### 1. Prepare and validate

1. Start from clean `master`, synchronized with `origin/master`.
2. Confirm `vX.Y.Z` is unused locally, remotely, and in R2.
3. Update `.github/release-notes/vX.Y.Z.md`, the public release page, and
   current-version references.
4. Run the local test/build gate and `git diff --check`.
5. Commit release metadata, then create and push an annotated canonical tag:

   ```powershell
   git tag -a vX.Y.Z -m "Backchannel vX.Y.Z"
   git push origin vX.Y.Z
   ```

Never move or replace a published tag. Correct a bad release with a new patch
tag.

### 2. Verify the tag workflow

The build matrix must build and smoke-test exactly the Windows x64 zip, macOS
arm64 zip, and Linux x64 tarball. Its final publication job must then, in this
order:

1. Resolve the peeled tag commit and download the three workflow artifacts.
2. Reject an existing `releases/vX.Y.Z/manifest.json`.
3. Read the current Latest metadata and build the deterministic manifest.
4. Upload all three assets with manifest-owned content types.
5. verify every remote object size.
6. Conditionally create the immutable manifest with `If-None-Match: *`.
7. Read back and validate the manifest bytes and schema.
8. Conditionally advance monotonic `releases/latest.json` last, using its ETag
   or `If-None-Match: *`; an older version must never replace a newer Latest.
9. Create GitHub release notes from the checked-in note file without attaching
   executable files.

Do not call the release complete until all three build jobs and the final job
pass, the portal presents the new entitled version, downloads match manifest
sizes and SHA-256 values, the public release page and notes are live, and a
Compose build from the source tag succeeds.

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
$v010Time = (& git show -s --format=%cI 'v0.1.0^{commit}').Trim()
.\scripts\migrate_releases_to_r2.ps1 -Version v0.1.0 -Commit $v010Commit -PublishedAt $v010Time -AssetDirectory .\release-assets\v0.1.0

$v011Commit = (& git rev-parse 'v0.1.1^{commit}').Trim()
$v011Time = (& git show -s --format=%cI 'v0.1.1^{commit}').Trim()
.\scripts\migrate_releases_to_r2.ps1 -Version v0.1.1 -Commit $v011Commit -PublishedAt $v011Time -AssetDirectory .\release-assets\v0.1.1

$v020Commit = (& git rev-parse 'v0.2.0^{commit}').Trim()
$v020Time = (& git show -s --format=%cI 'v0.2.0^{commit}').Trim()
.\scripts\migrate_releases_to_r2.ps1 -Version v0.2.0 -Commit $v020Commit -PublishedAt $v020Time -AssetDirectory .\release-assets\v0.2.0

$v021Commit = (& git rev-parse 'v0.2.1^{commit}').Trim()
$v021Time = (& git show -s --format=%cI 'v0.2.1^{commit}').Trim()
.\scripts\migrate_releases_to_r2.ps1 -Version v0.2.1 -Commit $v021Commit -PublishedAt $v021Time -AssetDirectory .\release-assets\v0.2.1 -SetLatest
```

Use `-SetLatest` only on the final intended version and only after every older
asset and manifest has verified. The migration script never grants an account
and never deletes old assets.

## Failure recovery and rollback

- Any failure before the last step leaves Latest unchanged. Do not point Latest
  at a partial release.
- Never overwrite a published version prefix or manifest. Use a new patch tag.
- If upload fails before a manifest exists, manually inspect the unpublished
  prefix and delete only confirmed partial objects before retrying. Never let an
  automated cleanup guess what to remove.
- If a manifest was created, treat that version as published and immutable even
  when a later step fails; repair with a patch release.
- If only GitHub note creation fails after Latest advances, leave verified R2
  metadata unchanged and repair the notes without attaching files.
- Retain old private GitHub executable files for one full release cycle as a
  rollback source. Remove those executable files manually only after R2 and
  portal acceptance for the next release. Keep every GitHub source tag and
  release-note page permanently.
