# Signed Desktop Updater Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect, authorize, download, verify, and safely apply signed Backchannel desktop updates with automatic rollback.

**Architecture:** Extend the progressive R2 manifest with an Ed25519-signed public descriptor, reuse the authenticated download portal to mint short-lived exact-asset grants, and add one local FastAPI update service that streams and stages the full archive. The existing launcher performs a clean shutdown and hands one validated plan to a copied stdlib updater executable, which swaps the bundle and rolls back unless the new instance passes the existing token-bound health check.

**Tech Stack:** Python 3.12 stdlib, `cryptography` Ed25519, FastAPI/SQLAlchemy, Cloudflare Worker/D1/R2, browser DOM APIs, React 18/TypeScript/Tailwind, PyInstaller, Node test runner, stdlib `unittest`.

## Global Constraints

- Work only in `C:\Users\thoule\AppData\Local\Temp\backchannel-alp-150` on `talberthoule/alp-150-updater`; preserve the dirty shared checkout.
- Reuse full progressive platform archives; do not add delta patches, an installer framework, or a second account system.
- Never commit or log the release private key, portal password/cookie, update grant, recipient email, Access assertion, or R2 key.
- Generate the Ed25519 private key outside the repository with user-only permissions; commit only `desktop/release_signing_keys.json`.
- Automatic checks run off the startup path, use a short timeout, and cache success for 24 hours.
- Download in bounded chunks, resume only after a valid `206 Content-Range`, and verify exact platform, filename, size, SHA-256, key ID, and Ed25519 signature before extraction.
- Mutating loopback routes require the per-launch `X-Backchannel-Instance` token.
- Applying is forbidden while any session is `active`; that state covers live capture and final drain.
- The updater must preserve the only known-good bundle and automatically restore it if the new instance fails its token-bound health check.
- UI uses existing tokens, 44px targets, visible focus, polite live status, light/dark support, and reduced motion.
- No push, production secret write, CI/CD run, release publication, or remote merge is part of this plan.

---

### Plan Review Gate: `claude-comparison-1`

**Files:**
- Review: `docs/superpowers/specs/2026-07-26-desktop-updater-design.md`
- Review: `docs/superpowers/plans/2026-07-26-desktop-updater.md`

**Interfaces:**
- Produces: a reviewed, frozen plan before Task 1 starts.
- Consumes: the committed design and plan SHA.

- [ ] **Step 1: Send the frozen plan SHA**

Use the audited Herdr wrapper to ask `claude-comparison-1` for an independent
second set of eyes. The review prompt must request:

- missing user journeys or failure states;
- unnecessary complexity or reusable code that the plan missed;
- security, data-loss, rollback, accessibility, and performance risks;
- inconsistent interfaces or file ownership;
- concrete enhancements with file/task references; and
- a final verdict of ready, ready with changes, or blocked.

The reviewer must not edit updater files. Durable findings are copied to
ALP-150.

- [ ] **Step 2: Apply valid feedback to the documents**

For each finding, either revise the design/plan or record a concise technical
reason it does not apply. Re-run the red-flag, spec-coverage, and type-name
self-review, commit the document revision, and send the new SHA back for a
final plan verdict.

- [ ] **Step 3: Start Task 1 only after the verdict**

Proceed when `claude-comparison-1` reports ready or ready with all requested
changes incorporated. Stop and return to design review for any unresolved
blocking safety or scope issue.

### Task 1: Sign progressive platform manifests

**Files:**
- Create: `backend/app/services/update_signing.py`
- Create: `backend/tests/test_update_signing.py`
- Create: `desktop/release_signing_keys.json`
- Modify: `desktop/scripts/build_platform_manifest.py`
- Modify: `desktop/tests/test_platform_release_manifest.py`
- Modify: `scripts/publish_release_platform.ps1`
- Modify: `desktop/backchannel.spec`
- Modify: `.github/workflows/desktop-release.yml`

**Interfaces:**
- Produces: `canonical_update_bytes(descriptor: dict) -> bytes`
- Produces: `sign_platform_manifest(manifest: dict, key_id: str, private_key: bytes) -> dict`
- Produces: `public_update_descriptor(manifest: dict) -> dict`
- Produces: `verify_update_descriptor(descriptor: object, platform_id: str, current_version: str, public_keys: dict[str, bytes]) -> dict`
- Produces: signed platform manifests with exact `update.key_id` and `update.signature`.
- Consumes later: Tasks 2 and 4 use the same public descriptor shape and verification rules.

- [ ] **Step 1: Write failing signing and verification tests**

Add literal fixtures using the deterministic raw private key
`bytes(range(1, 33))`. Assert exact canonical bytes, a successful round trip,
wrong-key rejection, tampered schema/timestamp/notes/size/hash/version
rejection, unknown-key rejection, wrong-platform/filename rejection,
leading-zero version rejection, anti-downgrade rejection, and unsigned
descriptor rejection:

```python
class UpdateSigningTests(unittest.TestCase):
    def test_canonical_bytes_are_exact(self):
        self.assertEqual(
            canonical_update_bytes(DESCRIPTOR_WITHOUT_SIGNATURE),
            b'{"asset":{"filename":"Backchannel-windows-x64.zip",'
            b'"id":"windows-x64","platform":"Windows x64",'
            b'"sha256":"' + b"a" * 64 + b'","size":7},'
            b'"commit":"' + b"b" * 40 + b'","key_id":"test-key",'
            b'"published_at":"2026-07-26T18:00:00Z",'
            b'"release_notes":"Security and reliability fixes.",'
            b'"schema":1,"version":"v1.2.3"}',
        )

    def test_signed_descriptor_rejects_tampering(self):
        signed = sign_platform_manifest(MANIFEST, "test-key", PRIVATE)
        descriptor = public_update_descriptor(signed)
        descriptor["asset"]["size"] = 8
        with self.assertRaisesRegex(ValueError, "signature"):
            verify_update_descriptor(
                descriptor, "windows-x64", "1.2.2", {"test-key": PUBLIC}
            )
```

Extend the platform CLI test to pass a temporary keys file and
`BACKCHANNEL_RELEASE_SIGNING_PRIVATE_KEY`, then assert `update` contains exactly
`key_id`, `schema`, and `signature`, while `published_at` and the bounded
release-note Markdown are signed top-level fields.

- [ ] **Step 2: Run the focused tests and confirm RED**

Run:

```powershell
$env:PYTHONPATH="$PWD;$PWD\backend;$PWD\desktop"
python -m unittest backend.tests.test_update_signing desktop.tests.test_platform_release_manifest
```

Expected: import failure for `app.services.update_signing`.

- [ ] **Step 3: Implement the minimum shared signing module**

Use `json.dumps(..., sort_keys=True, separators=(",", ":"))`,
`base64.urlsafe_b64encode(...).rstrip(b"=")`, `hmac.compare_digest`, and
`cryptography.hazmat.primitives.asymmetric.ed25519`. Validate with exact key
sets and trusted tuples:

```python
TRUSTED_ASSETS = {
    "windows-x64": ("Windows x64", "Backchannel-windows-x64.zip"),
    "macos-arm64": ("macOS arm64", "Backchannel-macos-arm64.zip"),
    "linux-x64": ("Linux x64", "Backchannel-linux-x64.tar.gz"),
}

def canonical_update_bytes(descriptor: dict) -> bytes:
    unsigned = {key: value for key, value in descriptor.items()
                if key != "signature"}
    return json.dumps(
        unsigned, sort_keys=True, separators=(",", ":")
    ).encode()
```

`verify_update_descriptor` returns a copied, normalized public descriptor only
after schema `1`, strict UTC publication time, at-most-8-KiB release notes,
platform, version, key, and signature checks succeed. Normalize installed bare
versions once, while all signed versions remain canonical `vX.Y.Z`.

- [ ] **Step 4: Generate and protect the production key outside the repo**

Create `%LOCALAPPDATA%\Backchannel\release-signing\ed25519-2026-07.private`,
write unpadded base64url raw private bytes, restrict its ACL to the current
Windows user, and write only this public file:

```json
{
  "active": "ed25519-2026-07",
  "keys": {
    "ed25519-2026-07": "<unpadded raw public key>"
  }
}
```

Confirm `git status` never names the private path and that the public key
derives from the protected private file.

- [ ] **Step 5: Require signing in the platform publisher and bundle trust data**

Make `build_platform_manifest.py` load the active public key file, immutable
release timestamp, `.github/release-notes/<version>.md`, and
`BACKCHANNEL_RELEASE_SIGNING_PRIVATE_KEY`; add the signed fields, verify them,
then write metadata. Make `publish_release_platform.ps1` fail before upload
when the secret or release-note file is absent. Map the GitHub secret only into
the protected macOS publish step and document that the later CI phase may not
run until the secret is provisioned. Add `release_signing_keys.json` to the
PyInstaller data list. Verification passes only the file's `keys` object, not
its `active` selector.

- [ ] **Step 6: Run GREEN and release contract checks**

Run:

```powershell
$env:PYTHONPATH="$PWD;$PWD\backend;$PWD\desktop"
python -m unittest backend.tests.test_update_signing desktop.tests.test_platform_release_manifest desktop.tests.test_release_contract
```

Expected: all focused tests pass and production-key material never appears in
captured output.

- [ ] **Step 7: Commit Task 1**

```powershell
git add backend/app/services/update_signing.py backend/tests/test_update_signing.py desktop/release_signing_keys.json desktop/scripts/build_platform_manifest.py desktop/tests/test_platform_release_manifest.py scripts/publish_release_platform.ps1 desktop/backchannel.spec .github/workflows/desktop-release.yml
git commit -m "feat: sign desktop release manifests"
```

### Task 2: Expose verified public update descriptors

**Files:**
- Modify: `docs-site/release-access.js`
- Modify: `docs-site/release-access.test.js`
- Modify: `docs-site/worker.js`
- Modify: `docs-site/download.test.js`

**Interfaces:**
- Consumes: signed `update` objects from Task 1.
- Produces: `publicUpdateDescriptor(manifest: object, assetId: string) -> object | null`
- Produces: `GET /api/update/latest/{platform_id}` on the recipient host.
- Consumes later: Task 4 uses the route without portal credentials.

- [ ] **Step 1: Write failing parser and route tests**

Add signed and unsigned progressive fixtures. Assert that signed platform
metadata remains strict, catalog assets retain `update`, release summaries
still redact `key`, `content_type`, and `update`, and the public descriptor is:

```js
{
  version: 'v1.2.3',
  commit: 'b'.repeat(40),
  published_at: '2026-07-26T18:00:00Z',
  release_notes: 'Security and reliability fixes.',
  asset: {
    id: 'windows-x64',
    platform: 'Windows x64',
    filename: 'Backchannel-windows-x64.zip',
    size: 7,
    sha256: 'a'.repeat(64),
  },
  key_id: 'test-key',
  schema: 1,
  signature: 'A'.repeat(86),
}
```

Route tests must prove the exact recipient host and path return this JSON while
unknown platform, unsigned Latest, malformed metadata, wrong method, public
host, and admin host return bounded `404`/`405` responses without R2 keys.

- [ ] **Step 2: Run the docs tests and confirm RED**

Run:

```powershell
Set-Location docs-site
node --test release-access.test.js download.test.js
```

Expected: `publicUpdateDescriptor` is not exported and update paths return
`404`.

- [ ] **Step 3: Extend strict progressive parsing**

Keep unsigned historical progressive manifests valid with their existing exact
`version`, `commit`, and `asset` shape. A signed manifest instead requires
exactly `version`, `commit`, `published_at`, `release_notes`, `asset`, and
`update`; rejects notes above 8 KiB; and cross-checks `published_at` against the
release identity just as it already cross-checks version and commit. Accept
`update` only as:

```js
function parseUpdate(value) {
  return value
    && exactKeys(value, ['key_id', 'schema', 'signature'])
    && /^[a-z0-9-]{1,40}$/.test(value.key_id)
    && value.schema === 1
    && /^[A-Za-z0-9_-]{86}$/.test(value.signature)
    ? value
    : null;
}
```

Pass the release identity into `parsePlatformManifest`. Signed progressive
assets enter the in-memory catalog as `{ ...platform.asset, update }`, while
the synthesized catalog manifest keeps `published_at` and the common
`release_notes` at top level. Require byte-identical notes across every signed
platform present for a version; reject that catalog version on a mismatch.
`publicUpdateDescriptor` reads those two top-level fields plus the selected
asset's `update`. `releaseSummary()` continues selecting the same six recipient
fields and therefore redacts `update` and `release_notes` by construction.

- [ ] **Step 4: Add the public Latest descriptor route**

Parse only `/api/update/latest/(windows-x64|macos-arm64|linux-x64)`, load the
trusted catalog, select `catalog.latestVersion`, and return
`publicUpdateDescriptor`. Deliberately override `DOWNLOAD_HEADERS` with
`cache-control: public, max-age=300` for `200` responses and use the existing
no-store generic response for failures. Never return an internal asset key or
account information. Tests record unauthenticated release identity, size, hash,
timestamp, and notes as an accepted disclosure rather than an accidental leak.

- [ ] **Step 5: Run GREEN**

Run:

```powershell
node --test release-access.test.js download.test.js worker.test.js
```

Expected: all focused docs-site tests pass.

- [ ] **Step 6: Commit Task 2**

```powershell
git add docs-site/release-access.js docs-site/release-access.test.js docs-site/worker.js docs-site/download.test.js
git commit -m "feat: expose signed update descriptors"
```

### Task 3: Mint and redeem short-lived update grants

**Files:**
- Create: `docs-site/migrations/0004_release_update_grants.sql`
- Modify: `docs-site/migration.test.js`
- Modify: `docs-site/release-access.js`
- Modify: `docs-site/worker.js`
- Modify: `docs-site/download.test.js`
- Modify: `site/downloads/downloads.js`
- Modify: `site/downloads/index.html`
- Modify: `site/downloads/downloads.css`

**Interfaces:**
- Produces: `POST /api/download/update-grants` using the existing portal cookie.
- Produces: `GET /api/update/assets/{version}/{asset_id}` using `Authorization: Bearer <grant>`.
- Produces: popup handoff message `{type, nonce, version, asset_id, grant}`.
- Consumes later: Task 4 posts `grant` only to the loopback service.

- [ ] **Step 1: Write failing migration and Worker grant tests**

The migration test must create the full migration chain in SQLite and prove:

```sql
INSERT INTO release_update_grants
  (token_hash, email, version, asset_id, expires_at)
VALUES ('hash', 'recipient@example.com', 'v1.2.3', 'windows-x64',
        '2026-07-26T23:15:00.000Z');
```

Reject orphaned accounts, malformed versions/assets, and duplicate token
hashes; cascade on account deletion; and expose an expiry index.

Worker tests must assert:

- grant creation rejects no session, change-only session, wrong Origin,
  non-JSON, malformed nonce/version/asset, unsigned asset, and unauthorized
  version;
- success stores only token hash plus exact email/version/asset/expiry and
  returns the raw token once with the caller nonce;
- bearer download rechecks grant expiry, active account, approved interest,
  current Latest/explicit entitlement, and exact asset on every request;
- revoked, expired, wrong-asset, malformed bearer, and removed entitlement
  return the same private `404`;
- full, conditional, and ranged responses reuse the existing R2 streaming
  headers and never expose the R2 key.

- [ ] **Step 2: Run the focused docs tests and confirm RED**

Run:

```powershell
Set-Location docs-site
node --test migration.test.js download.test.js
```

Expected: migration `0004` and update-grant routes are missing.

- [ ] **Step 3: Add the narrow D1 table and token helper**

Use:

```sql
CREATE TABLE release_update_grants (
  token_hash TEXT PRIMARY KEY,
  email TEXT NOT NULL COLLATE NOCASE,
  version TEXT NOT NULL CHECK (version GLOB 'v[0-9]*.[0-9]*.[0-9]*'),
  asset_id TEXT NOT NULL CHECK (asset_id IN (
    'windows-x64', 'macos-arm64', 'linux-x64'
  )),
  expires_at TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY (email) REFERENCES release_accounts(email) ON DELETE CASCADE
);
CREATE INDEX idx_release_update_grants_expires
  ON release_update_grants(expires_at);
```

Reuse `createSessionToken` for 32 random bytes and SHA-256; do not introduce a
second random-token implementation.

- [ ] **Step 4: Implement grant creation and bearer download**

Grant creation calls the existing `releaseSession`, `entitledCatalog`, and
signed-asset lookup before inserting a 15-minute record. It opportunistically
deletes expired records in the same D1 batch.

Bearer download parses an exact path and token, loads the grant joined to
active account and approved interest, reloads authorization/catalog, then
calls the existing object streaming path with the grant email only for the
existing safe audit event. Factor the shared R2 response code once so cookie
and grant downloads cannot drift.

- [ ] **Step 5: Add the portal confirmation handoff**

When URL parameters contain exact `update_version`, `asset_id`, `origin`, and
`nonce`, render one confirmation panel after normal login/password change.
The button posts exact JSON to `/api/download/update-grants`, then:

```js
window.opener.postMessage({
  type: 'backchannel-update-grant',
  nonce,
  version: result.version,
  asset_id: result.asset_id,
  grant: result.grant,
}, origin);
window.close();
```

Validate `origin` as loopback HTTP on `localhost` or `127.0.0.1` with an exact
port from 1 through 65535 before showing the panel. Use safe text nodes, keep
the grant out of storage/URLs/logs, disable duplicate submission, and retain
the regular release list when update parameters are absent.

- [ ] **Step 6: Run GREEN and the complete docs-site gate**

Run:

```powershell
node --test migration.test.js release-access.test.js download.test.js worker.test.js
node --test *.test.js
npm run build
```

Expected: all docs-site tests and build pass.

- [ ] **Step 7: Commit Task 3**

```powershell
git add docs-site/migrations/0004_release_update_grants.sql docs-site/migration.test.js docs-site/release-access.js docs-site/worker.js docs-site/download.test.js site/downloads/downloads.js site/downloads/index.html site/downloads/downloads.css
git commit -m "feat: authorize desktop update downloads"
```

### Task 4: Check, resume, verify, and stage updates locally

**Files:**
- Create: `backend/app/services/update_service.py`
- Create: `backend/app/services/runtime_activity.py`
- Create: `backend/app/routers/updates.py`
- Create: `backend/tests/test_update_service.py`
- Create: `backend/tests/test_runtime_activity.py`
- Modify: `backend/requirements.txt`
- Modify: `backend/app/main.py`
- Modify: `backend/app/routers/analyze.py`
- Modify: `backend/app/routers/artifacts.py`
- Modify: `backend/app/routers/imports.py`
- Modify: `backend/app/routers/retranscribe.py`
- Modify: `backend/app/routers/synthesis.py`
- Modify: `backend/app/services/local_transcriber.py`
- Modify: `backend/app/ws/audio_handler.py`
- Modify: `desktop/launcher.py`

**Interfaces:**
- Produces: `UpdateService.status() -> dict`
- Produces: `UpdateService.check(force: bool = False) -> dict`
- Produces: `UpdateService.start_download(grant: str) -> dict`
- Produces: `UpdateService.cancel_download() -> dict`
- Produces: `UpdateService.request_apply() -> dict`
- Produces: `runtime_activity.track(name: str)`,
  `runtime_activity.busy_reason() -> str`,
  `runtime_activity.reserve_shutdown(timeout_seconds: int = 60) -> bool`, and
  `runtime_activity.release_shutdown()`.
- Produces routes: `GET /api/updates`, `POST /api/updates/check`,
  `POST /api/updates/grant`, `DELETE /api/updates/download`,
  `POST /api/updates/apply`.
- Consumes: Task 1 verifier and Task 3 descriptor/download endpoints.

- [ ] **Step 1: Write failing service and runtime-activity behavior tests**

Use a real temporary directory and local `http.server.ThreadingHTTPServer`
fixtures. Assert:

- disabled source deployments return `{"enabled": False, "state": "idle"}`;
- a forced check accepts one valid newer descriptor, rejects unsigned/tampered,
  wrong-schema, invalid timestamp, wrong-platform, downgrade, replay below the
  greatest previously observed signed version/timestamp, malformed JSON,
  oversized JSON, and timeout;
- a fresh successful check is reused for 24 hours without a second request;
- two concurrent checks produce one network request;
- downloads use 1 MiB-or-smaller reads, persist byte progress, and hash while
  streaming;
- a valid partial sends `Range`, accepts exact `206 Content-Range`, and appends;
- `200`, wrong range, excess bytes, short bytes, hash mismatch, and cancellation
  leave no `ready` state;
- an expired grant preserves the partial and enters `needs_authorization`;
- archives reject absolute paths, `..`, device entries, escaping links, extra
  roots, wrong root name, and output beyond expected expanded size;
- Windows zip and Linux tar preserve the exact expected root and safe internal
  links; on macOS, a real `ditto -c -k --keepParent` `.app` fixture round-trips
  through `/usr/bin/ditto -x -k` with executable bits and safe symlinks intact;
- free-space preflight accounts for archive, declared expanded bytes, installed
  backup, and 10 percent margin on the install filesystem;
- state JSON survives a service restart and is written by temporary-file
  replacement;
- grant and error strings never appear in persisted state or logs;
- TLS requests use an explicit `ssl` context built from `certifi.where()`;
- `/api/health` contains no instance token in its body and exposes no custom
  response header cross-origin; and
- desktop TrustedHost accepts only loopback hosts and rejects an arbitrary
  rebinding Host;
- shutdown reservation atomically rejects new tracked work and new call
  WebSockets, a failed apply precheck releases that reservation, and an
  accepted reservation expires after 60 seconds if the tray watcher never
  performs the controlled shutdown.

Example observable behavior:

```python
def test_range_mismatch_restarts_from_zero(self):
    partial.write_bytes(b"old")
    server.respond(200, body=ARCHIVE)
    service.start_download("secret-grant")
    service.wait_for_download()
    self.assertEqual(partial.read_bytes(), ARCHIVE)
    self.assertEqual(server.headers[0]["Range"], "bytes=3-")
    self.assertEqual(service.status()["state"], "ready")
```

- [ ] **Step 2: Run service tests and confirm RED**

Run:

```powershell
$env:PYTHONPATH="$PWD\backend"
python -m unittest backend.tests.test_update_service backend.tests.test_runtime_activity
```

Expected: import failures for `app.services.update_service` and
`app.services.runtime_activity`.

- [ ] **Step 3: Implement and commit the runtime activity gate**

Use one thread-safe reference count keyed by operation name. Wrap transcript
and audio import, every artifact export until its response body is materialized,
post-import analysis, destructive retranscription, on-demand synthesis, and
the first-use `onnx_asr.load_model` call. Mark startup schema patching from
lifespan entry through completion; the API is not served yet, and the explicit
marker keeps the invariant testable. New tracked operations and new audio
WebSockets reject while shutdown is reserved.

Store a `time.monotonic()` deadline with the shutdown reservation. `track`,
`busy_reason`, and `reserve_shutdown` clear an expired reservation under the
same lock, so a missed tray-watcher event returns the process to ready after
60 seconds without a timer thread.

Run:

```powershell
$env:PYTHONPATH="$PWD\backend"
python -m unittest backend.tests.test_runtime_activity
git add backend/app/services/runtime_activity.py backend/tests/test_runtime_activity.py backend/app/main.py backend/app/routers/analyze.py backend/app/routers/artifacts.py backend/app/routers/imports.py backend/app/routers/retranscribe.py backend/app/routers/synthesis.py backend/app/services/local_transcriber.py backend/app/ws/audio_handler.py
git commit -m "feat: gate shutdown around active work"
```

- [ ] **Step 4: Implement the minimum persisted state and descriptor check**

Keep one `threading.Lock`, one download thread, and one cancellation event.
Use `urllib.request`, a maximum 64 KiB descriptor body, five-second timeout,
`datetime.now(timezone.utc)`, and an explicit CA context from the now-direct
`certifi` requirement. State contains only:

```python
{
    "enabled": True,
    "state": "available",
    "current_version": "v0.3.8",
    "available_version": "v0.4.0",
    "available_notes": "Security and reliability fixes.",
    "published_at": "2026-07-26T18:00:00Z",
    "highest_seen_version": "v0.4.0",
    "highest_seen_published_at": "2026-07-26T18:00:00Z",
    "platform_id": "windows-x64",
    "filename": "Backchannel-windows-x64.zip",
    "size": 123,
    "downloaded": 0,
    "checked_at": "2026-07-26T23:00:00Z",
    "error": "",
    "blocked_reason": "",
}
```

Persist by writing adjacent `.tmp`, flushing, then `os.replace`.
Normalize the bare installed `APP_VERSION` to a leading-`v` value only at the
service boundary.

- [ ] **Step 5: Implement bounded resume, verification, and extraction**

Stream 1 MiB chunks to `.partial`, update SHA-256 in the same pass, compare
expected size/hash, re-run descriptor verification, and extract only after all
checks pass. Windows uses `zipfile`; Linux uses the Python 3.12 tar data filter
and permits only relative links resolving inside `Backchannel/`; macOS validates
every entry and link target before invoking `/usr/bin/ditto -x -k`.

Derive roots exactly:

| Platform | Archive/install root | Launcher |
| --- | --- | --- |
| Windows x64 | `Backchannel/`; `Path(sys.executable).parent` | `Backchannel.exe` |
| Linux x64 | `Backchannel/`; `Path(sys.executable).parent` | `Backchannel` |
| macOS arm64 | `Backchannel.app/`; `Path(sys.executable).parents[2]` | `Contents/MacOS/Backchannel` |

Sum declared expanded regular-file sizes and require free bytes for the
archive, expanded stage, current install backup, and 10 percent margin. Stage
under the installation parent so the final swap stays on one filesystem.

- [ ] **Step 6: Add token-gated FastAPI routes and startup check**

Read the same-origin health response token in the frontend later; for now the
router dependency compares the header-only `X-Backchannel-Instance` with
`BACKCHANNEL_INSTANCE_TOKEN` using `hmac.compare_digest`. The token must never
enter `/api/health` JSON or `access-control-expose-headers`. Add
`TrustedHostMiddleware` in desktop mode for `localhost`, `127.0.0.1`, and the
bound loopback host. `GET /api/updates` is read-only; all other routes require
the token.

`POST /api/updates/apply` executes:

```python
if not runtime_activity.reserve_shutdown():
    raise HTTPException(409, f"Finish {runtime_activity.busy_reason()} before installing.")
accepted = False
try:
    active = await db.scalar(
        select(func.count()).select_from(Session).where(Session.state == "active")
    )
    if active:
        raise HTTPException(409, "Finish the active call before installing.")
    result = service.request_apply()
    accepted = True
    return result
finally:
    if not accepted:
        runtime_activity.release_shutdown()
```

The reservation closes the race after the apply precheck; any failed final
check releases it, while an accepted reservation self-expires after 60 seconds
if the tray watcher never performs the controlled shutdown.

Register the router and schedule `service.check()` with `asyncio.to_thread`
only when `BACKCHANNEL_DESKTOP=1`; do not await it on startup.

- [ ] **Step 7: Set launcher desktop environment**

Before importing `app.main`, set `BACKCHANNEL_DESKTOP`,
`BACKCHANNEL_INSTANCE_TOKEN`, `BACKCHANNEL_INSTALL_DIR`,
`BACKCHANNEL_UPDATE_KEYS`, and `BACKCHANNEL_UPDATE_HELPER` from validated
launcher-owned paths using the per-platform table above. In headless mode set
`BACKCHANNEL_UPDATE_APPLY_DISABLED=1`; status remains testable, but apply
returns conflict because no tray watcher can perform the controlled restart.

- [ ] **Step 8: Run GREEN and focused router checks**

Run:

```powershell
$env:PYTHONPATH="$PWD\backend;$PWD\desktop"
python -m unittest backend.tests.test_update_signing backend.tests.test_update_service backend.tests.test_runtime_activity backend.tests.test_meta
```

Expected: all focused backend tests pass.

- [ ] **Step 9: Commit the updater service and routes**

```powershell
git add backend/app/services/update_service.py backend/app/routers/updates.py backend/tests/test_update_service.py backend/requirements.txt backend/app/main.py desktop/launcher.py
git commit -m "feat: download and stage desktop updates"
```

### Task 5: Apply staged bundles with automatic rollback

**Files:**
- Create: `desktop/updater.py`
- Create: `desktop/tests/test_updater.py`
- Modify: `desktop/launcher.py`
- Modify: `desktop/tests/test_launcher.py`
- Modify: `desktop/backchannel.spec`
- Modify: `desktop/tests/test_release_contract.py`

**Interfaces:**
- Produces: `validate_plan(value: object, plan_path: Path) -> ApplyPlan`
- Produces: `apply_update(plan_path: Path) -> int`
- Consumes: Task 4's `apply.json`, staged root, restart marker, and instance
  health contract.

- [ ] **Step 1: Write failing updater and launcher tests**

With real temporary sibling directories, assert:

- plan validation rejects extra/missing keys, relative paths, roots outside the
  declared parents, symlink paths, mismatched launcher names, pre-existing
  backup, cross-filesystem device IDs, and non-ready state;
- success waits for the old PID and launcher lock file to disappear, renames
  install to backup and stage to install, starts the exact per-platform
  launcher, accepts only matching `launcher.json` token/health, then removes
  backup and plan;
- failed start, timeout, missing lock, wrong health token, and nonzero child
  exit move the failed bundle aside, restore backup, and relaunch old;
- a still-running child gets up to 300 seconds for PostgreSQL/schema startup,
  while an exited child rolls back immediately;
- rollback failure preserves both recoverable directories and writes the local
  recovery result;
- launcher watcher notices only the exact restart marker, stops the tray, runs
  normal cleanup, copies the helper outside install, and starts it only after
  cleanup;
- tray Check for updates sends the instance token and opens the app;
- an available update changes the tray label to include version and signed
  release-note title and opens About;
- headless apply returns conflict and starts no watcher; and
- PyInstaller produces a self-contained one-file `BackchannelUpdater`, collects
  it and the public key on Windows/Linux, and places both inside the macOS
  `.app` so the launcher can copy the updater out before renaming the bundle.

Example swap assertion:

```python
result = apply_update(plan_path, process_factory=fake_process, health=fake_health)
self.assertEqual(result, 0)
self.assertEqual((install / "version.txt").read_text(), "new")
self.assertFalse(backup.exists())
self.assertEqual(fake_health.calls, 1)
```

- [ ] **Step 2: Run updater tests and confirm RED**

Run:

```powershell
$env:PYTHONPATH="$PWD;$PWD\desktop"
python -m unittest desktop.tests.test_updater desktop.tests.test_launcher desktop.tests.test_release_contract
```

Expected: import failure for `desktop.updater`.

- [ ] **Step 3: Implement stdlib plan validation and swap**

Use a frozen dataclass for exact plan fields, `Path.resolve(strict=True)` for
existing roots, strict resolution of each absent target's existing parent,
`os.stat(...).st_dev`, `os.replace`, `subprocess.Popen`, `urllib.request`, and
bounded polling. Wait for both the old PID and its exact launcher lock file to
disappear before the first rename. The helper accepts one CLI argument: the
absolute plan path. It never accepts install or staging paths directly from
command-line flags.

On rollback, move the failed new bundle to the plan's `failed_dir` only if that
path is absent, restore backup, and relaunch the prior launcher. Cleanup never
deletes backup before verified health.

- [ ] **Step 4: Connect launcher restart and tray actions**

Run one one-second watcher beside the tray. When the exact marker exists,
`icon.stop()` lets the existing `finally` close uvicorn, listener, PostgreSQL,
and lock file. After cleanup, copy the bundled updater to
`<app-data>/updates/bin`, launch it with the validated plan, and exit.
Headless mode never starts this watcher and the backend rejects apply.

Add a tray `Check for updates` item that POSTs `/api/updates/check` with the
current instance header, then opens Backchannel. When status is available, the
same item names the version and first release-note title. Do not add a second
tray process or IPC service.

- [ ] **Step 5: Build the second PyInstaller executable**

Add a separate stdlib `Analysis`/`PYZ`/one-file `EXE` for
`desktop/updater.py`; do not set `exclude_binaries=True` or make it depend on
the main `_internal` directory. Collect the completed standalone binary beside
`Backchannel` on Windows/Linux and into the macOS `BUNDLE`. Keep its console
disabled and give the Windows binary the existing icon.

- [ ] **Step 6: Run GREEN and desktop suite**

Run from the repository root with both import roots:

```powershell
$env:PYTHONPATH="$PWD;$PWD\desktop"
python -m unittest desktop.tests.test_updater desktop.tests.test_launcher desktop.tests.test_release_contract
python -m unittest discover -s desktop/tests
```

Expected: focused and complete desktop suites pass. Run the suite elevated on
Windows only for the existing symlink test.

- [ ] **Step 7: Commit Task 5**

```powershell
git add desktop/updater.py desktop/tests/test_updater.py desktop/launcher.py desktop/tests/test_launcher.py desktop/backchannel.spec desktop/tests/test_release_contract.py
git commit -m "feat: apply desktop updates with rollback"
```

### Task 6: Add About, banner, and portal handoff UI

**Files:**
- Create: `frontend/src/hooks/useDesktopUpdate.ts`
- Create: `frontend/src/components/DesktopUpdate.tsx`
- Create: `frontend/src/components/DesktopUpdate.test.mjs`
- Modify: `frontend/src/services/api.ts`
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/components/AboutCard.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/package.json`

**Interfaces:**
- Produces: `useDesktopUpdate(pollMs?: number)` with status and
  `check`, `authorize`, `cancel`, `apply` actions.
- Produces: `DesktopUpdateCard` for About and `DesktopUpdateBanner` for App.
- Consumes: Task 4 routes and Task 3 exact popup message.

- [ ] **Step 1: Write failing UI behavior tests**

Bundle the real TSX with the existing esbuild test pattern and render states to
static markup. Assert:

- unsupported/source mode renders no update controls;
- idle/checking has Check again with `aria-live="polite"`;
- available shows signed version, human size, and signed release notes plus
  Download update;
- `needs_authorization` preserves progress and shows Resume download;
- downloading shows text byte progress, native progress semantics, and Cancel;
- ready shows Restart and install, disabled with the exact busy reason;
- error shows bounded text and Retry;
- banner appears only for available/downloading/ready and its open action is
  keyboard-accessible;
- the exported pure `isUpdateGrantMessage(...)` predicate accepts only when
  `event.origin`, `event.source`, `type`, nonce, version, and asset ID all
  match; literal mismatches return false.

Use literal status objects rather than deriving expectations from production
helpers. Static rendering proves markup; pure-function tests prove the message
predicate. Focus, keyboard operation, and real popup behavior remain in the
ui-craft browser gate because `renderToStaticMarkup` cannot exercise them.

- [ ] **Step 2: Run frontend tests and confirm RED**

Run:

```powershell
Set-Location frontend
npm test
```

Expected: `DesktopUpdate.tsx` and `useDesktopUpdate.ts` are missing.

- [ ] **Step 3: Add typed API operations and the hook**

Add `DesktopUpdateStatus` with exact state union:

```ts
type DesktopUpdateState =
  | "idle" | "checking" | "available" | "authorizing"
  | "downloading" | "needs_authorization"
  | "ready" | "applying" | "error";
```

The API helper reads `X-Backchannel-Instance` from same-origin `/api/health`
at mount, verifies the body contains no token, and includes the header on
mutation calls. It never reads an exposed JSON token. The hook polls local
status every five seconds, increasing to one second only while
downloading/applying.

`authorize()` generates a nonce with `crypto.getRandomValues` and calls
`window.open` synchronously before its first `await`, so Chromium retains the
click gesture. It opens:

```text
https://downloads.backchannel.page/?update_version=<version>&asset_id=<id>&origin=<loopback-origin>&nonce=<nonce>
```

and installs one bounded message listener using the pure predicate. It accepts
loopback origins on `localhost` or `127.0.0.1`, posts only the grant to the
local backend, and clears the grant variable/listener and closes the popup in
`finally`. Expired-grant download responses enter `needs_authorization`; only a
fresh Resume download click opens the portal again.

- [ ] **Step 4: Build the two accessible views**

`DesktopUpdateCard` goes directly after the Backchannel version card in About.
Render bounded signed release-note Markdown with the existing safe
`ReactMarkdown` path. Use existing surface/ring/teal classes, a native
`<progress>`, `tabular-nums`, 44px controls, visible status text, and no
animation beyond existing color transitions.

`DesktopUpdateBanner` reuses the existing bottom-right banner placement and
does not compete with the post-update What's new notice. Available and ready
copy are concise; downloading exposes progress but no modal.

- [ ] **Step 5: Run GREEN, typecheck, and build**

Run:

```powershell
npm test
npm run build
```

Expected: all frontend tests and the production build pass with no TypeScript
errors.

- [ ] **Step 6: Perform the ui-craft visual gate**

Run the desktop frontend with fixture status states and inspect at 320px,
768px, and desktop widths in light/dark and reduced-motion modes. Verify no
overflow, one teal accent hierarchy, 44px targets, visible focus, useful
screen-reader status, no layout shift during progress, and no obstruction of
active-call controls. Capture only temporary review screenshots outside the
repository.

- [ ] **Step 7: Commit Task 6**

```powershell
git add frontend/src/hooks/useDesktopUpdate.ts frontend/src/components/DesktopUpdate.tsx frontend/src/components/DesktopUpdate.test.mjs frontend/src/services/api.ts frontend/src/types/index.ts frontend/src/components/AboutCard.tsx frontend/src/App.tsx frontend/package.json
git commit -m "feat: add desktop update experience"
```

### Task 7: Prove end-to-end safety and prepare the local merge

**Files:**
- Create: `desktop/tests/test_update_acceptance.py`
- Create: `desktop/scripts/smoke_update_archive.py`
- Modify: `desktop/tests/test_release_contract.py`
- Modify: `scripts/release_desktop.ps1`
- Modify: `desktop/Dockerfile.release-linux`
- Modify: `.github/workflows/desktop-release.yml`
- Modify: `docs/releasing.md`
- Modify: `AGENTS.md`
- Modify: `CLAUDE.md`
- Modify: `docs/superpowers/specs/2026-07-26-desktop-updater-design.md`
- Modify: `docs/superpowers/plans/2026-07-26-desktop-updater.md`

**Interfaces:**
- Consumes: every prior task.
- Produces: one frozen feature-branch SHA for `claude-2` review and local merge.

- [ ] **Step 1: Write the Windows acceptance test before its harness**

Create a temporary old install, signed full update zip, local descriptor/grant
server, and real updater plan. The Windows test must:

1. detect the newer signed version;
2. interrupt after a partial download and resume with exact Range;
3. verify and stage the bundle;
4. apply it and observe the new health token;
5. repeat with a forced failed health check; and
6. assert the old bundle is restored and relaunched.

The test records check wall time, peak traced Python memory during download,
and archive bytes. Fail if check startup work is awaited by launcher setup or
peak incremental memory exceeds 8 MiB over the 1 MiB transfer fixture.

Add a native packaged-archive smoke runner that takes one real platform archive
and:

1. verifies and extracts it through the production platform path;
2. asserts the exact root, launcher, executable mode, and contained links;
3. swaps it into a temporary install and observes real launcher health;
4. repeats with forced failed health and proves the prior temp install returns.

Contract tests require that Windows calls this runner after
`Compress-Archive`, Linux calls it inside `Dockerfile.release-linux` after
creating the tarball, and the credential-free macOS build calls it after
`ditto -c -k --keepParent` and before cache handoff. The macOS job must use the
real `.app` archive, not a synthetic zip.

- [ ] **Step 2: Run the acceptance test and confirm RED**

Run:

```powershell
$env:PYTHONPATH="$PWD;$PWD\backend;$PWD\desktop"
python -m unittest desktop.tests.test_update_acceptance
```

Expected: failure at the first missing integrated behavior, before adding any
acceptance-only production path, and release-contract failure because the three
native packaging paths do not yet invoke the smoke runner.

- [ ] **Step 3: Make only integration corrections**

Wire existing interfaces until the acceptance test passes. Do not add a
second downloader, test-only production switch, generic plugin interface, or
new state store. Every discovered bug first receives the smallest focused
regression test in the owning task's test file.

- [ ] **Step 4: Update operator documentation**

Document:

- signed manifest schema and canonical payload;
- protected local private-key path and later CI secret name;
- public key rotation by adding a new key while retaining old accepted keys;
- accepted offline key-revocation limitation;
- update-grant migration and routes;
- direct `certifi` TLS trust and platform install-root/free-space rules;
- local fake-server acceptance command;
- real Windows/Linux update and forced rollback smoke sequence;
- macOS native archive smoke command reserved for the later CI phase;
- blocking setup of `BACKCHANNEL_RELEASE_SIGNING_PRIVATE_KEY` in the protected
  GitHub environment before any macOS publication; and
- the explicit boundary that no push/publication/CI run occurs in this phase.

Change the design status footer to record implementation verification date,
and check completed plan boxes only after their commands have passed.

- [ ] **Step 5: Run fresh complete verification**

Create an isolated Python 3.12 environment for the backend requirements, then
run:

```powershell
Set-Location backend
python -m unittest discover -s tests
Set-Location ..\desktop
python -m unittest discover -s tests
Set-Location ..\frontend
npm test
npm run build
Set-Location ..\docs-site
npm run test:release-access
npm run test:migration
npm run test:worker
npm run test:admin
npm run test:download
npm run test:site
node --test *.test.js
npm run build
Set-Location ..
sentrux check .
sentrux gate .
git diff --check
```

Expected: every command exits zero except the two documented generated
lockfile `sentrux check` exceptions allowed by `.sentrux/rules.toml`; `sentrux
gate` introduces no new structural regression. Also run the Windows native
archive smoke and the Linux release-container archive smoke locally. The
macOS workflow modification and contract test must be clean, but its native
execution remains explicitly pending the later approved CI/secret phase.

- [ ] **Step 6: Freeze and send `claude-2` the review SHA**

Commit verified integration/documentation, record `BASE_SHA=f142913` and
`HEAD_SHA=$(git rev-parse HEAD)`, then use the audited Herdr wrapper to ask
`w2:pG` for an independent review against ALP-150 and this plan. Require
Critical/Important findings to name file/line, user impact, and a reproducible
case. Keep `claude-2` off the updater files.

- [ ] **Step 7: Resolve review findings test-first**

For each valid Critical or Important finding, add a failing focused test, run
RED, make the minimal correction, run GREEN, and commit. Record rejected
findings with technical evidence. Ask `claude-2` to confirm the final SHA.

- [ ] **Step 8: Merge locally into `master`**

Use the finishing-a-development-branch skill. The user already selected local
merge and explicitly excluded push/CI. First refresh and verify the dirty main
checkout contains only preserved screenshot work, merge
`talberthoule/alp-150-updater` without touching those files, then rerun the
focused update suites and production builds on the merged result. Do not
remove the externally located worktree automatically.

- [ ] **Step 9: Update Linear**

Comment on ALP-150 with:

- local merge commit;
- test/build/Sentrux evidence;
- functionality, UI, UX, and performance acceptance results;
- `claude-2` review disposition; and
- explicit note that push, scanning, CI/CD, production secret setup, and final
  release tasks remain pending.

Move ALP-150 to the workspace's review-ready state, not Done, because the user
reserved CI/CD scanning and final run tasks for the next phase.
