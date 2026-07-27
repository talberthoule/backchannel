# Signed desktop updater design

Date: 2026-07-26

Status: Approved

Issue: ALP-150

Branch: `talberthoule/alp-150-updater`

## Goal

Let an installed Backchannel desktop bundle detect a newer release without
slowing startup, guide an entitled user through one browser authorization
step, download the correct full bundle with resume support, verify it before
installation, and safely restart into it. If the new bundle does not become
healthy, restore and relaunch the prior bundle.

The update must never interrupt an active call or post-call drain. It must not
put portal passwords, cookies, R2 credentials, or release-signing private keys
in the desktop bundle.

## Existing foundation

This design extends the current release and runtime paths instead of adding a
second distribution system:

- `scripts/release_desktop.ps1` and
  `scripts/publish_release_platform.ps1` publish full, smoke-tested platform
  archives through the checked-in R2 transport.
- Progressive platform manifests already bind a version and commit to one
  platform's filename, size, SHA-256, content type, and private R2 key.
- `downloads.backchannel.page` already authenticates recipients, resolves
  Latest and explicit-version entitlements, supports HTTP ranges, and checks
  account state on every download request.
- `desktop/launcher.py` owns the desktop process, embedded PostgreSQL,
  loopback server, health check, tray, and clean shutdown.
- `backend/app/release_notes.py` is the installed version source, and
  Administration -> About is the existing release-information surface.

## User experience

The desktop checks at most once every 24 hours in the background after startup.
The check has a short timeout and never blocks the application becoming ready.
A tray action and Administration -> About provide an explicit Check again
action. When an update is available, the tray label names the version and
release-note title and opens About for the full signed notes.

When a newer signed platform release exists:

1. A compact, non-modal application banner says that the version is available.
   It can be dismissed for the session or opened in About.
2. About shows the version, download size, signed release notes, and one
   Download update action.
3. If the desktop has no current update grant, that action opens the existing
   download portal in a user-initiated popup. An already signed-in recipient
   confirms the exact version and platform. Otherwise the existing portal login
   appears first.
4. The portal sends a short-lived, asset-specific grant to the opener with
   `postMessage`. The grant is not placed in a URL, browser storage, or the
   desktop log.
5. Download continues in the background. About and the banner show byte
   progress and a Cancel action. Closing the app preserves the partial file;
   the next download resumes it.
6. After verification, the action becomes Restart and install.
7. If a session is active or its final drain is incomplete, installation is
   disabled with "Finish the call first." Otherwise explicit activation
   requests a clean restart.
8. The launcher shuts down the API and PostgreSQL, then hands the staged bundle
   to the external updater. Success reopens Backchannel and uses the existing
   What's new notice. A failed health check automatically restores and opens
   the previous version.

The UI follows the existing teal token, system font, 44px target, focus-ring,
light/dark, and reduced-motion rules. Progress uses text as well as a bar and
status changes use a polite live region. No forced modal, countdown, automatic
restart, or list animation is added.

## Signed release descriptor

New platform manifests keep their existing exact fields and add an `update`
object:

```json
{
  "asset": {
    "content_type": "application/zip",
    "filename": "Backchannel-windows-x64.zip",
    "id": "windows-x64",
    "key": "releases/v0.4.0/Backchannel-windows-x64.zip",
    "platform": "Windows x64",
    "sha256": "<64 lowercase hex characters>",
    "size": 123
  },
  "commit": "<40 lowercase hex characters>",
  "published_at": "2026-07-26T18:00:00Z",
  "release_notes": "Security and reliability fixes.",
  "update": {
    "key_id": "ed25519-2026-07",
    "schema": 1,
    "signature": "<unpadded base64url Ed25519 signature>"
  },
  "version": "v0.4.0"
}
```

The Ed25519 signature covers canonical UTF-8 JSON with sorted keys and compact
separators containing exactly:

```json
{
  "asset": {
    "filename": "Backchannel-windows-x64.zip",
    "id": "windows-x64",
    "platform": "Windows x64",
    "sha256": "<hash>",
    "size": 123
  },
  "commit": "<commit>",
  "key_id": "ed25519-2026-07",
  "published_at": "2026-07-26T18:00:00Z",
  "release_notes": "Security and reliability fixes.",
  "schema": 1,
  "version": "v0.4.0"
}
```

`schema` is exactly `1`, `published_at` is the immutable release identity
timestamp, and `release_notes` is the bounded ASCII/UTF-8 Markdown release-note
file for that version. The private R2 key and transport content type are
intentionally excluded from the public signed descriptor because the desktop
neither receives nor chooses them. The Worker continues to resolve those
trusted internal fields.

`desktop/release_signing_keys.json` maps accepted key IDs to raw Ed25519 public
keys. It is included in each desktop bundle. The matching private key is
generated outside the repository with restrictive user permissions and later
copied into the release CI secret
`BACKCHANNEL_RELEASE_SIGNING_PRIVATE_KEY`. Adding that production CI secret is
a required gate before the later macOS publication workflow can run; this
local-only phase does not write it. The private key is never written to the
worktree, test output, release metadata, or logs.

The platform-manifest builder requires the selected key ID and private key for
new publications, signs before immutable publication, and verifies the
signature with the checked-in public key before returning. Existing unsigned
historical releases remain available through the portal but are never offered
as automatic updates.

## Detection and authorization

The recipient host adds:

```text
GET  /api/update/latest/{platform_id}
POST /api/download/update-grants
GET  /api/update/assets/{version}/{asset_id}
```

The Latest descriptor route is public because it contains only already-visible
release identity, asset display metadata, hash, and signature. It never returns
an R2 key, account state, or download capability. The desktop verifies the
signature, schema, timestamp, exact platform and filename, semantic version,
and anti-downgrade rule before displaying an update. It persists the greatest
valid signed version and publication timestamp it has observed, including an
update that was not installed, and rejects any later response below either
value. This makes replay fail after a client has observed a newer signed
release even though the small `latest.json` catalog pointer remains unsigned.
Publishing release existence, archive size, hash, timestamp, and release notes
without portal authentication is an accepted disclosure required for
credential-free detection. The public route deliberately overrides the
recipient host's normal private/no-store cache rule with a five-minute public
cache.

Grant creation uses the existing secure portal session and entitlement logic.
It accepts an exact version, asset ID, and caller nonce, then stores only a
SHA-256 hash of a random 32-byte token in a new D1
`release_update_grants` table:

```text
token_hash TEXT PRIMARY KEY
email TEXT NOT NULL
version TEXT NOT NULL
asset_id TEXT NOT NULL
expires_at TEXT NOT NULL
created_at TEXT NOT NULL DEFAULT datetime('now')
```

The raw token is returned once to the portal page. The page posts the token,
nonce, version, and asset ID only to the exact loopback opener origin. The
desktop accepts the message only from the exact recipient origin, the popup it
opened, and its single-use random nonce, then immediately forwards it to the
local backend and clears browser state.

The asset route accepts that token in an Authorization header. Every full or
ranged request hashes the token and rechecks grant expiry, active account
state, current entitlement, exact manifest asset, and object availability.
Revocation therefore blocks the next resumed request. Grants expire after 15
minutes and are useful only for one version and asset. If a resumed request
outlives a grant, the desktop retains the partial file, returns to an
authorization-required available state, and waits for a user-initiated Resume
download action. It never tries to open a popup without a fresh user gesture.

## Desktop update service

A small backend service owns one persisted update state under the existing
application data directory:

```text
idle -> available -> authorizing -> downloading -> ready -> applying
                              \-> needs_authorization
                  \-> error
```

The service exposes local status, check, grant, download, cancel, and apply
routes. Mutating routes require the launcher's random instance token in the
existing `X-Backchannel-Instance` header. This prevents an unrelated web page
from triggering a download or restart against localhost. The frontend reads
the token from a same-origin health response; the tray already owns it.

Checks use the Python standard library with a bounded timeout and the bundled
`certifi` CA file so frozen macOS Python does not depend on a missing system
OpenSSL path. State writes use write-then-replace JSON so a crash cannot leave
a half-written record. Only one check or download runs at a time in the
process. The launcher instance token is returned only as the existing response
header; it is never copied into JSON, HTML, persisted state, or logs. Desktop
mode also restricts accepted Host headers to `localhost`, `127.0.0.1`, and the
actual bound loopback host. The frontend prefetches the header before an update
click so opening the portal remains synchronous and preserves the browser user
gesture. IPv6 loopback is not advertised because this launcher binds only
IPv4; the portal accepts `localhost` and `127.0.0.1` origins with exact ports.

Downloads stream into `updates/<version>/<filename>.partial` in bounded chunks.
An existing partial file supplies a Range start. A server response that does
not confirm that range restarts from byte zero. The service never buffers the
archive and never writes outside the update directory.

After the expected byte count arrives, the service computes SHA-256 while
streaming the file, verifies it in constant time against the signed descriptor,
re-verifies the Ed25519 signature and current platform, then inspects every
archive entry before extraction. It rejects absolute paths, traversal, device
entries, links escaping the single expected bundle root, extra roots, and
unbounded expanded size.

Windows uses `zipfile` because its bundle contains no required POSIX mode or
link semantics. Linux uses `tarfile` with the Python 3.12 data filter and
permits only relative links that resolve inside `Backchannel/`. macOS first
validates the zip paths and relative in-bundle symlink targets, then invokes
the native `/usr/bin/ditto -x -k` extractor so `Backchannel.app` executable
bits and framework symlinks survive. Synthetic extraction is not accepted as
macOS evidence; the packaged `.app` archive must pass a native update smoke
test.

Before extraction, the service identifies the exact platform install root
(`Backchannel/` on Windows/Linux or `Backchannel.app/` on macOS), sums declared
expanded file sizes, measures the installed root, and requires free space for
the archive, expanded stage, installed backup, and a 10 percent margin on the
same filesystem. A failed check removes the staged extraction but retains no
file marked ready.

## Apply and rollback

The release bundle includes one small, self-contained PyInstaller one-file
updater executable built from stdlib-only desktop code. Before shutdown the
launcher copies that executable into the application data update directory,
outside the installation tree; it must not depend on the main bundle's
`_internal` directory.

`POST /api/updates/apply` first queries for an active session. The session stays
active through WebSocket final draining, so that database gate covers both live
capture and post-call processing. A shared in-process activity counter also
covers on-demand briefing, import, export, analysis/retranscription, and
first-use local ASR model download, plus startup database migration. The
launcher lock and plan PID must identify this one running instance, and the
external updater waits for that lock to disappear before swapping. If any gate
is busy or inconsistent, apply returns a conflict and does not create the
restart marker. Retranscription is included because it replaces existing
transcript rows and must never be interrupted. Headless mode has no tray/user
restart path and therefore reports apply as unavailable instead of watching
for the marker.

Apply atomically reserves shutdown in the activity counter before its final
database/lock checks. New tracked work and new live-call WebSockets receive a
conflict after that reservation, closing the check-to-shutdown race. A failed
final check releases the reservation. An accepted reservation expires after
60 seconds; the status service and launcher then delete its stale marker and
return to `ready`, so a later launch cannot apply an abandoned request.

For an allowed request:

1. The backend writes a narrowly validated apply plan and restart marker.
2. The launcher's existing control loop notices the marker, closes the tray,
   and runs its normal server, database, lock-file, and PostgreSQL cleanup.
3. The launcher starts the copied updater and exits.
4. The updater waits for the old launcher PID, renames the install bundle to a
   sibling backup, renames the staged bundle into the exact install location,
   and launches the new executable.
5. It reads the new `launcher.json` and uses the existing instance-token health
   check for up to five minutes, while also failing early if the new process
   exits. This accommodates embedded PostgreSQL startup and schema migration.
6. On success it removes the backup and completed update state.
7. On failure it terminates the failed new process, moves that bundle aside,
   restores the backup to the exact install location, launches the old
   executable, and records a non-sensitive rollback result for About.

Every plan path is resolved before use and must match the known install,
staging, backup, and application-data roots. Symlinks and pre-existing
unexpected backup paths fail closed. Rename is used only within the same
filesystem. A non-writable install location is reported before shutdown.

Installed-version strings are normalized once by removing one leading `v`;
signed release versions always retain their canonical `vX.Y.Z` form. A public
key remains trusted in already-installed clients until those clients install a
release that removes it. That unavoidable offline key-revocation limit is an
accepted risk at this scale; rotation adds a new key before switching the
active signer, and the verifier receives only the JSON file's `keys` map, never
its `active` selector.

## Failure behavior

- Network, portal, or R2 unavailable: keep the installed version and offer
  Retry.
- Invalid Latest or platform descriptor: show no update and log only the
  validation category.
- Unsupported or revoked account: return to Authorize without revealing portal
  account state.
- Range mismatch: restart the partial download from zero.
- Size, hash, signature, platform, filename, or extraction mismatch: delete
  staging, never enable install, and require a new download.
- App closes during download: retain the bounded partial file and resume later.
- Call or another tracked destructive/runtime operation starts before apply:
  the server-side gates win and the update remains ready.
- Disk or permission failure before shutdown: keep the current app running.
- Swap or startup failure after shutdown: restore and relaunch the backup.
- Rollback itself fails: retain both paths, write a local recovery message, and
  show the native error dialog. Never delete the only known-good bundle.

Logs may contain version, platform, byte counts, state, and validation category.
They may not contain email, grant, portal session, signature private material,
R2 key, response body, or local transcript data.

## Verification

Focused automated checks must cover:

- canonical descriptor bytes, Ed25519 signing and verification, wrong-key and
  tampered-field rejection, strict key IDs, exact platform/filename matching,
  schema/timestamp/release-note validation, greatest-observed replay rejection,
  version ordering, and unsigned historical exclusion;
- public descriptor redaction, grant hashing/expiry, session and entitlement
  rechecks, revocation, exact-asset binding, and ranged streaming;
- single-flight checks/downloads, 24-hour cache, resume, expired-grant
  reauthorization, bundled CA use, bounded chunks, cancellation, atomic state,
  hash/size mismatch, safe platform-native extraction, free-space checks, and
  every apply activity gate;
- launcher restart signaling, exact-path validation, successful swap, failed
  health rollback, and preservation of the only known-good bundle;
- About and banner states, popup origin/source/nonce checks, keyboard and focus
  behavior, visible status text, reduced motion, and light/dark rendering; and
- release build contracts requiring a signature, release notes, a one-file
  updater, and public key file on Windows x64, Linux x64, and macOS arm64; and
- native packaged-archive update smoke on Windows x64, Linux x64, and macOS
  arm64, including macOS executable modes and in-bundle symlinks.

Local acceptance uses a fake update server and signed fixture, then performs a
real Windows bundle update and forced-health-failure rollback. Linux native
archive smoke runs in the release container. macOS archive smoke is added to
the credential-free build job and is executed only in the later approved CI
phase. These checks record startup latency, steady-state download memory, and
UI interaction timings. The pass targets are: no measurable startup blocking,
check work finishes off the render path, download memory stays bounded by a
small multiple of the chunk size, and the UI remains responsive.

The work is merged locally only after focused suites, backend and desktop
unittest suites, frontend tests/build, docs-site tests/build, Sentrux check and
gate, visual UI review, and the independent `claude-2` Herdr review are clean.
Push, production secrets, CI/CD publication, scanning, and final release tasks
remain a later explicitly approved phase.

## Deliberate exclusions

- Delta patches, a custom patch format, or multiple simultaneous downloads.
- Silent download before user authorization, forced installation, automatic
  restart, or installation during a call.
- Reuse of portal passwords/cookies in the desktop or presigned R2 URLs.
- MSI, DMG, DEB, RPM, code signing, and Apple notarization changes.
- Updating Docker/source deployments or unsigned historical desktop versions.
- A generic updater framework or service abstraction with one implementation.

Full signed archives, one persisted state file, one short-lived grant table,
and one external swap helper are sufficient for ALP-150.
