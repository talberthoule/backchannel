# Progressive hybrid desktop release design

Date: 2026-07-15

Status: Approved

## Objective

Build Windows x64 and Linux x64 desktop bundles from the operator's Windows
workstation and use GitHub Actions only for the macOS arm64 build. Publish each
platform to the authenticated download portal immediately after that platform
passes its native smoke test, without waiting for either of the other builds.

Preserve immutable release metadata, canonical tag and commit provenance,
monotonic Latest, private Cloudflare R2 delivery, and source-only GitHub
releases. Prevent the temporary macOS handoff artifact from accumulating in
GitHub Actions storage.

The design must publish the already-created `v0.2.4` tag without moving it.
Release tooling may execute from a newer `master`, but every platform bundle
must be built from the peeled `v0.2.4` commit.

## Existing foundation

The repository already provides the release primitives to retain:

- `desktop/backchannel.spec` creates an OS-native PyInstaller bundle and
  selects the platform-specific tray implementation.
- `desktop/scripts/smoke_test.py` starts a bundle, verifies its health endpoint,
  and checks clean shutdown.
- `desktop/scripts/build_release_manifest.py` validates trusted asset names and
  calculates sizes and SHA-256 hashes.
- `scripts/r2-object.mjs` is the sole release object transport. It already
  supports streamed uploads, metadata reads, downloads, immutable creation,
  and ETag-conditional replacement with Cloudflare-issued credentials.
- `scripts/migrate_releases_to_r2.ps1` proves the required fail-closed ordering
  for aggregate historical releases: upload, verify, create immutable metadata,
  read it back, then update Latest conditionally.
- The portal already turns validated release manifests into a common release
  summary and resolves downloads by trusted asset ID.

The current workstation is Windows x64 and its Docker engine runs Linux x64
containers. It can build Windows natively and Linux through Docker. PyInstaller
is not a cross-compiler, so macOS arm64 must still build on a macOS arm64 host.

## Why the catalog must change

The current `releases/{version}/manifest.json` is one immutable object
containing every available asset. Publishing it after the first platform would
make that platform visible, but the object could not later be changed to add
Linux or macOS. Making it mutable would weaken the established release
guarantee and create concurrent-update conflicts.

New releases therefore separate immutable release identity from independently
immutable platform completion. Historical aggregate manifests remain valid and
require no migration.

## R2 object model

New progressively published releases use:

```text
releases/latest.json
releases/vX.Y.Z/release.json
releases/vX.Y.Z/platforms/windows-x64.json
releases/vX.Y.Z/platforms/linux-x64.json
releases/vX.Y.Z/platforms/macos-arm64.json
releases/vX.Y.Z/Backchannel-windows-x64.zip
releases/vX.Y.Z/Backchannel-linux-x64.tar.gz
releases/vX.Y.Z/Backchannel-macos-arm64.zip
```

### Release identity

`release.json` is created with `If-None-Match: *` and contains exactly:

```json
{
  "commit": "<40 lowercase hex characters>",
  "published_at": "<annotated tag timestamp in strict UTC ISO-8601>",
  "version": "vX.Y.Z"
}
```

The annotated tag timestamp makes the bytes deterministic when two platform
publishers race to initialize the same release. If the object already exists,
a publisher reads it and requires an exact version, commit, and timestamp match
before continuing. An anchor without a valid platform manifest is not shown in
the portal.

### Platform completion

Each platform manifest is created with `If-None-Match: *` only after its bundle
has uploaded and its remote size has been verified. It contains exactly:

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
  "commit": "<the release identity commit>",
  "version": "vX.Y.Z"
}
```

The other two files use their existing trusted IDs, names, content types, and
platform labels. A platform manifest is the visibility boundary: once its
readback validates, the portal may show and serve that asset. It is never
overwritten. A retry may accept an existing manifest only after proving its
version, commit, asset identity, size, and SHA-256 match the local result.

### Legacy compatibility

The portal continues to load existing immutable
`releases/{version}/manifest.json` objects unchanged. For the new layout, it
loads `release.json`, validates every matching platform manifest, rejects
duplicate platform IDs or commit mismatches, and synthesizes the same in-memory
manifest shape currently used by entitlements, summaries, and downloads.

If both legacy and progressive metadata exist for one version, the catalog
reports a conflict and exposes neither representation. A progressive release
becomes catalog-visible when at least one platform manifest is valid.

## Platform publisher

Add one narrow publisher command shared by the local and GitHub paths. It takes
the canonical version, peeled commit, annotated tag timestamp, platform ID, and
one asset file. It reuses `scripts/r2-object.mjs` and the existing manifest
validation constants and performs this order:

1. Validate the canonical version, commit, timestamp, platform ID, exact
   filename, regular-file status, nonzero size, and SHA-256.
2. Read or conditionally create the deterministic `release.json`, then read it
   back and validate it.
3. Reject a conflicting platform manifest. Accept an identical existing one as
   an idempotent completed publication.
4. Upload the platform asset with manifest-owned content type and attachment
   filename.
5. Read remote object metadata and require the exact expected size.
6. Conditionally create the immutable platform manifest.
7. Read it back and require byte and schema equivalence.
8. Read Latest. If this version is newer, advance Latest using its ETag or
   `If-None-Match: *`; retry one precondition conflict. If Latest already names
   this version or a newer one, do not regress it.

Latest is therefore updated only after a platform is independently complete.
The first completed platform makes the version available to Latest-entitled
users; later platform manifests appear automatically without rewriting Latest.

R2 credentials remain step-scoped, and no automated path deletes an R2 object.

## Local Windows and Linux coordinator

Add `scripts/release_desktop.ps1` with PowerShell `SupportsShouldProcess`. It:

1. Requires a canonical annotated tag, clean synchronized `master`, GitHub CLI
   authentication, Node 24+, Python 3.12, and a reachable Linux x64 Docker
   engine.
2. Resolves local and remote peeled tag commits and tag timestamps and rejects
   any mismatch.
3. Rejects conflicting release identity or platform metadata before spending
   build time and skips any platform that is already published with matching
   immutable metadata.
4. Creates a disposable source worktree at the exact tag commit without
   switching or modifying the operator's current checkout.
5. Dispatches the macOS workflow immediately so its remote build can proceed in
   parallel with local work.
6. Builds, smoke-tests, packages, and immediately publishes Windows through the
   shared platform publisher. It records a Windows failure and continues to
   Linux rather than blocking the independent platform.
7. Builds, smoke-tests, packages, and immediately publishes Linux through the
   shared platform publisher, recording any independent failure.
8. Waits for the macOS workflow at the end only to provide a single-command
   release verdict; the workflow publishes macOS independently as soon as its
   own build completes.
9. Creates or repairs the source-only GitHub release notes from
   `.github/release-notes/{version}.md` without attaching executables.
10. Removes only its disposable source worktree and temporary build state.
    Versioned local Windows and Linux assets remain until portal acceptance.

Windows is intentionally first so the largest current user group receives the
first local result. Linux publication does not wait for macOS or require a
successful Windows result. The coordinator stops the affected platform on
every failed native command, continues the other platforms, and returns a
failing final verdict if any required platform remains incomplete. It never
infers success from the presence of an output file alone.

## Linux release container

Add one release-only multi-stage Dockerfile under `desktop/`. The frontend
stage uses the tag source to run `npm ci` and the production build. The Python
3.12 stage installs the existing backend and desktop requirements, copies the
built frontend, downloads the existing ONNX models and Linux embedded
PostgreSQL, runs the existing PyInstaller spec and smoke test, and creates the
expected tarball. A final export stage contains only the tarball so the
coordinator can use Docker's local output mode without a registry.

This is a build environment, not a new runtime image or customer distribution
format.

## macOS build, publication, and cleanup

Convert `.github/workflows/desktop-release.yml` into a manually dispatched
macOS-only workflow with `release_ref` and `expected_commit` inputs. The
workflow definition and release tools come from current `master`; a separate
checkout supplies application source from `release_ref`. This permits recovery
of `v0.2.4` while ensuring PyInstaller consumes only that tag's source.

The workflow contains two trust-separated jobs:

1. A `macos-latest` build job verifies the peeled source commit, retains the
   current frontend, dependency, model, embedded PostgreSQL, PyInstaller,
   smoke-test, and zip sequence, then uploads exactly
   `Backchannel-macos-arm64.zip` with `retention-days: 1`. It has only
   `contents: read` and receives no Cloudflare credentials.
2. A protected Ubuntu publication job downloads only that run's named artifact,
   invokes the shared platform publisher with step-scoped production R2
   credentials, verifies macOS visibility, and deletes the artifact by its
   exact GitHub artifact ID. Its permissions add only the Actions write access
   required for that deletion.

The one-day retention is the fallback for cancellation or failure before the
cleanup step. Before dispatch, the local coordinator deletes only stale,
completed artifacts produced by this macOS handoff workflow with the exact
Backchannel macOS artifact name. It never deletes active-run or unrelated
workflow artifacts. A cleanup failure blocks a new dispatch so storage debt is
visible before another macOS build starts.

If publication succeeds but immediate artifact deletion fails, the macOS asset
remains available in R2 and the workflow reports the cleanup failure; the
one-day retention still removes the temporary GitHub copy.

## Progressive portal behavior

Catalog loading supports both layouts and returns one common release model.
For progressive releases:

- an anchor alone is ignored;
- each valid platform manifest adds exactly one available asset;
- invalid or unavailable platform metadata is omitted with an operator
  diagnostic and cannot affect valid sibling platforms;
- release version and commit mismatches fail closed;
- Latest entitlement follows `latest.json` after the first platform completes;
- explicit historical entitlements work unchanged; and
- download authorization continues to resolve only a trusted version and asset
  ID to a manifest-owned R2 key.

The recipient UI renders only completed platforms. It requires no pending
placeholder and never exposes an object key or unfinished build.

## Concurrency and failure recovery

- macOS may finish before, between, or after the local builds; Windows is
  intentionally attempted before Linux. Each platform publication is
  independently serialized by its immutable manifest key.
- Concurrent release-anchor creation is safe because the bytes are
  deterministic and creation is conditional.
- Concurrent Latest updates use the existing compare-and-swap behavior and may
  retry one precondition conflict. They never replace a newer version.
- Invalid, missing, moved, or mismatched tags stop before publication.
- A native build or smoke-test failure affects only that platform. Already
  published sibling platforms remain available.
- An asset-upload or size-verification failure creates no platform manifest, so
  the portal cannot expose that asset.
- A failure after asset upload but before platform-manifest creation leaves an
  unpublished object for manual inspection. No automated cleanup guesses which
  R2 object to remove.
- Once a platform manifest exists, that platform build is immutable. A
  correction uses a new patch version.
- GitHub notes failure does not roll back verified platform publications.

## Verification

Automated tests must prove:

- deterministic release identity and strict platform-manifest schemas;
- rejection of unknown IDs, filenames, keys, content types, duplicate IDs,
  commit mismatches, extra fields, empty files, and invalid hashes;
- legacy aggregate manifests still load exactly as before;
- progressive manifests synthesize the common release model from one, two, or
  three completed platforms in any order;
- one invalid platform does not expose that asset or hide valid siblings;
- Latest and explicit entitlements work for partial progressive releases;
- downloads can resolve only assets represented by valid platform manifests;
- the platform publisher orders asset upload, remote-size verification,
  immutable platform metadata, readback, and conditional Latest correctly;
- idempotent retries accept only byte-equivalent release and platform metadata;
- the local coordinator is tag-pinned, publishes Windows before beginning the
  Linux build, and never waits for macOS before either local publication;
- the Linux container exports only a smoke-tested named tarball;
- the macOS build job is source-pinned, credential-free, and one-day retained;
- the macOS publication job scopes R2 credentials, publishes before deleting
  its exact artifact, and does not attach an executable to GitHub; and
- proactive cleanup selects only stale artifacts from the macOS handoff
  workflow.

Live acceptance for `v0.2.4` must then:

1. Build and smoke-test Windows locally and verify it appears in the entitled
   portal before Linux and macOS are required to finish.
2. Build and smoke-test Linux in local Docker and verify it appears without
   waiting for macOS.
3. Build and smoke-test macOS in GitHub and verify it appears after the
   protected publication job.
4. Confirm the temporary macOS artifact is deleted and the repository artifact
   inventory returns to zero.
5. Download each available platform through the entitled portal and verify its
   bytes against the platform manifest size and SHA-256.
6. Verify `release.json`, all three platform manifests, monotonic Latest, the
   public release page, and source-only GitHub notes.
7. Build Docker Compose from the `v0.2.4` source tag successfully.

## Rejected alternatives

- Mutating one aggregate manifest on each completion would use fewer objects
  but would discard the release immutability guarantee and create avoidable
  compare-and-swap conflicts.
- Waiting for all three builds would preserve the old aggregate format but
  directly violate progressive platform availability.
- Publishing macOS from the build job would remove the temporary artifact but
  would expose production R2 credentials inside the untrusted build boundary.
- Keeping Windows and Linux in the GitHub matrix would remain coupled to
  Actions artifact quota and spend unnecessary runner minutes.
- A self-hosted macOS runner would need Mac hardware, patching, and runner
  maintenance that are not currently justified.
- A new upload service or object transport is unnecessary because the checked-
  in R2 client already provides the required conditions and verification.

## Deliberate exclusions

- Code signing, notarization, MSI, DMG, DEB, RPM, and automatic updates remain
  separate release work.
- Cleanup does not delete arbitrary repository artifacts or any R2 object.
- The design does not publish Docker registry images or change the source-built
  Docker Compose delivery model.
- The design does not change desktop runtime behavior, diarization, recipient
  identity, or entitlement rules.
