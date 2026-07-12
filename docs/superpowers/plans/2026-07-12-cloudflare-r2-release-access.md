# Backchannel Cloudflare R2 Release Access Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver Backchannel desktop bundles from a private Cloudflare R2 bucket through operator-approved accounts, one-time temporary credentials, version grants, and authenticated streaming downloads without GitHub identity.

**Architecture:** Extend the existing `docs-site` Worker and D1 database instead of adding a service. Keep the public, Access-protected admin, and recipient surfaces on three explicit host allowlists; isolate release-account primitives in one Worker module and resolve every R2 object through an immutable CI-written manifest. A tag-only final workflow job publishes all verified native assets, the immutable version manifest, and then the mutable Latest pointer.

**Tech Stack:** Cloudflare Workers Web Crypto, D1, R2 Worker binding, Turnstile, static HTML/CSS/JavaScript, Node built-in test runner, Python 3.12, GitHub Actions, AWS CLI R2 S3 API.

## Global Constraints

- Target repository: Backchannel only; do not modify `Anlysis-Inference-Engine`.
- Keep one Worker, the existing D1 database, and the existing static-site build.
- R2 bucket `backchannel-desktop-releases` remains private: no `r2.dev` URL and no R2 custom domain.
- Allow only `backchannel.page`, `www.backchannel.page`, `admin.backchannel.page`, and `downloads.backchannel.page`; disable `workers.dev` and preview URLs.
- Preserve Cloudflare Access issuer, audience, expiry, and exact `ADMIN_EMAIL` checks before parsing any admin mutation body.
- Use PBKDF2-HMAC-SHA256 with a 16-byte salt, 32-byte hash, and stored work factor fixed initially at 600,000 iterations.
- Generate 20-character temporary passwords containing upper-case, lower-case, number, and symbol characters from an ambiguity-free alphabet.
- Temporary passwords expire 72 hours after approval/reset; their password-change-only sessions expire at the earlier of 30 minutes or the temporary-password expiry.
- Permanent passwords are 14-128 characters. Recipient normal sessions last seven days.
- Store only SHA-256 hashes of random 32-byte session tokens.
- Set the recipient cookie exactly as `__Host-backchannel_release=<token>; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age=<bounded-seconds>`.
- Admin and recipient mutation endpoints accept bounded JSON only and require exact same-origin `Origin`.
- Do not store or log plaintext passwords, raw session tokens, Access assertions, hashes, salts, emails, R2 keys, response bodies, or D1 result rows.
- Latest is dynamic through `releases/latest.json`; explicit historical grants are additive and duplicate-free.
- Manifest assets include `content_type`; only `application/zip` and `application/gzip` are allowed.
- Stream R2 bodies without `arrayBuffer()` and implement single-range, conditional, `200`, `206`, `304`, `412`, and `416` semantics.
- Published version manifests are immutable through conditional creation; concurrent or older jobs cannot regress Latest.
- Keep GitHub release notes but attach no executable assets. `workflow_dispatch` builds but never publishes.
- Use a separate least-privilege R2 S3 writer credential in GitHub Actions; do not broaden the site-deployment token.
- Preserve the user-owned untracked `docs/admin-interest-workflow.html` file unchanged.

## File map

- `docs-site/migrations/0002_release_access.sql`: D1 release decisions, accounts, version grants, sessions, and audit events.
- `docs-site/release-access.js`: crypto, validation, catalog, entitlement, session, and R2 response primitives shared by admin and recipient routes.
- `docs-site/release-access.test.js`: deterministic unit tests for all shared primitives.
- `docs-site/migration.test.js`: applies both migrations to an in-memory SQLite database and checks constraints/integrity.
- `docs-site/worker.js`: explicit host router plus admin and recipient API orchestration.
- `docs-site/worker.test.js`: host, API, D1 batch, authentication, and download integration contracts with fake bindings.
- `site/admin/{index.html,admin.js,admin.css}`: review/grant controls and ephemeral credential dialog.
- `docs-site/admin.test.js`: safe admin rendering, copy/save, clearing, and accessibility contracts.
- `site/downloads/{index.html,downloads.js,downloads.css}`: recipient login, forced password change, catalog, and download UI.
- `docs-site/download.test.js`: recipient UI security, state, and accessibility contracts.
- `docs-site/wrangler.jsonc`: recipient custom domain, private R2 binding, and disabled public Worker hosts.
- `docs-site/package.json`: migration/release/download test commands.
- `desktop/scripts/build_release_manifest.py`: exact-asset manifest and monotonic Latest generator.
- `desktop/tests/test_release_manifest.py`: hashes, sizes, schema, validation, and Latest monotonicity tests.
- `desktop/tests/test_release_contract.py`: workflow publication and GitHub attachment contracts.
- `.github/workflows/desktop-release.yml`: tag-only final R2 publication job.
- `scripts/migrate_releases_to_r2.ps1`: owner-run historical migration using authenticated GitHub downloads and the same manifest generator.
- `README.md`, `docs/{quickstart.md,releasing.md,deployment.md,README.md}`, `site/**`, `AGENTS.md`, `CLAUDE.md`: authenticated-download links, operations, and authoritative release guidance.

---

### Task 1: D1 schema and release security primitives

**Files:**
- Create: `docs-site/migrations/0002_release_access.sql`
- Create: `docs-site/release-access.js`
- Create: `docs-site/release-access.test.js`
- Create: `docs-site/migration.test.js`
- Modify: `docs-site/package.json`

**Interfaces:**
- Produces: `generateTemporaryPassword(randomBytes?) -> string`
- Produces: `hashPassword(password, {salt?, iterations?}) -> Promise<{hash,salt,iterations}>`
- Produces: `verifyPassword(password, record) -> Promise<boolean>`; malformed records use the fixed dummy derivation and return false.
- Produces: `createSessionToken(randomBytes?) -> Promise<{token,tokenHash}>`
- Produces: `parseManifest(value, expectedVersion?) -> manifest|null`
- Produces: `loadReleaseCatalog(bucket) -> Promise<{latestVersion:string|null, manifests:Map<string,object>, diagnostics:string[]}>`
- Produces: `resolveEntitlements(account, explicitVersions, catalog) -> object[]`
- Produces: `parseSingleRange(header, size) -> {offset,length,contentRange}|{unsatisfiable:true}|null`
- Produces: constants `PASSWORD_ITERATIONS`, `TEMPORARY_PASSWORD_TTL_SECONDS`, `CHANGE_SESSION_TTL_SECONDS`, `SESSION_TTL_SECONDS`, and `SESSION_COOKIE`.

- [ ] **Step 1: Add failing migration and primitive tests**

Create table-driven tests that assert the exact migration columns, constraints, foreign keys, cascade behavior, and release-account interest invariant. Add crypto tests using an injected deterministic byte source, a PBKDF2-SHA256 known vector, correct/wrong passwords, malformed base64/length/work-factor rejection, dummy derivation on invalid records, 10,000 unique generated passwords, and raw-token absence from `tokenHash`.

```js
test('temporary passwords meet the complete contract', () => {
  const seen = new Set();
  for (let i = 0; i < 10_000; i += 1) {
    const value = generateTemporaryPassword();
    assert.match(value, /^(?=.*[A-Z])(?=.*[a-z])(?=.*[2-9])(?=.*[!#$%&*+?@])[A-HJ-NP-Za-km-z2-9!#$%&*+?@]{20}$/);
    seen.add(value);
  }
  assert.equal(seen.size, 10_000);
});

test('manifest validation rejects an untrusted key or content type', () => {
  assert.equal(parseManifest({...validManifest, assets: [{...validAsset, key: '../secret'}]}), null);
  assert.equal(parseManifest({...validManifest, assets: [{...validAsset, content_type: 'text/html'}]}), null);
});
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `cd docs-site; node --test release-access.test.js migration.test.js`

Expected: failure because `release-access.js` and migration 0002 do not exist.

- [ ] **Step 3: Implement migration 0002**

Use `ALTER TABLE` for the decision fields, then create the four tables and indexes. Enforce the request-record invariant with a foreign key from `release_accounts(email)` to `interest_subscribers(email)` and enable cascades only from accounts to grants/sessions.

```sql
ALTER TABLE interest_subscribers ADD COLUMN release_decision TEXT NOT NULL DEFAULT 'pending'
  CHECK (release_decision IN ('pending', 'approved', 'rejected'));
ALTER TABLE interest_subscribers ADD COLUMN release_reviewed_at TEXT;

CREATE TABLE release_accounts (
  email TEXT PRIMARY KEY COLLATE NOCASE,
  state TEXT NOT NULL CHECK (state IN ('active', 'revoked')),
  password_hash TEXT NOT NULL,
  password_salt TEXT NOT NULL,
  password_iterations INTEGER NOT NULL DEFAULT 600000 CHECK (password_iterations = 600000),
  must_change_password INTEGER NOT NULL DEFAULT 1 CHECK (must_change_password IN (0, 1)),
  password_expires_at TEXT,
  include_latest INTEGER NOT NULL DEFAULT 1 CHECK (include_latest IN (0, 1)),
  approved_at TEXT NOT NULL DEFAULT (datetime('now')),
  password_changed_at TEXT,
  revoked_at TEXT,
  FOREIGN KEY (email) REFERENCES interest_subscribers(email)
);
```

Add `release_account_versions`, `release_sessions`, and `release_access_events` exactly as specified, plus indexes on session email/expiry, event email/time, and explicit version.

- [ ] **Step 4: Implement the minimal shared module**

Use Web Crypto only. Generate random characters with rejection sampling (`byte < 256 - (256 % alphabet.length)`) to remove modulo bias, shuffle class-guaranteed characters with the same unbiased source, encode salt/hash/token as base64url, validate fixed byte lengths before comparison, cap accepted iterations at 600,000, and always perform a 600,000-iteration dummy derivation on an invalid account record.

Catalog listing must paginate `bucket.list({prefix: 'releases/', cursor})`, retain only `^releases/(v[0-9]+\.[0-9]+\.[0-9]+)/manifest\.json$`, and parse `latest.json` separately. Manifest parsing must validate exact version/key ownership, unique IDs/filenames, 40-hex commit, 64-hex SHA-256, safe attachment filenames, positive safe-integer sizes, and allowlisted content types.

- [ ] **Step 5: Add package scripts and run GREEN**

```json
"test:release-access": "node --test release-access.test.js",
"test:migration": "node --test migration.test.js"
```

Run: `cd docs-site; npm run test:release-access; npm run test:migration`

Expected: all release-access and migration tests pass; `PRAGMA foreign_key_check` returns no rows and `PRAGMA integrity_check` returns `ok`.

- [ ] **Step 6: Commit Task 1**

```powershell
git add docs-site/migrations/0002_release_access.sql docs-site/release-access.js docs-site/release-access.test.js docs-site/migration.test.js docs-site/package.json
git commit -m "feat: add release access data model and primitives"
```

### Task 2: Admin approval, grants, reset, and one-time credential UI

**Files:**
- Modify: `docs-site/worker.js`
- Modify: `docs-site/worker.test.js`
- Modify: `site/admin/index.html`
- Modify: `site/admin/admin.js`
- Modify: `site/admin/admin.css`
- Modify: `docs-site/admin.test.js`

**Interfaces:**
- Consumes: Task 1 crypto/catalog constants and functions.
- Produces: `GET /api/admin/interests` with decision/account/grant fields.
- Produces: `GET /api/admin/releases -> {items:[manifest summary],latest_version}`.
- Produces: `POST /api/admin/access/approve|reject|reset-password|revoke` and `PUT /api/admin/access/grants`.
- Produces: approval/reset response `{ok:true,credential:{email,password,password_expires_at,include_latest,versions}}` exactly once.

- [ ] **Step 1: Replace the old mutation-denial assertion with failing admin API tests**

Test Access authorization before `request.json()`, exact Origin, `application/json`, 8 KiB maximum body, normalized email, version format, request-record existence, duplicate/concurrent approval failure, default Latest, explicit grants, transactional rollback, reset/revoke session deletion, rejection without account creation, and generic failures. Inspect every fake D1 bound value and event to prove the plaintext password is absent.

```js
test('approval creates a one-time credential without persisting plaintext', async () => {
  const response = await route(adminJson('/api/admin/access/approve', {
    email: 'person@example.com', include_latest: true, versions: ['v0.2.0'],
  }), env, allowOwner);
  assert.equal(response.status, 201);
  const {credential} = await response.json();
  assert.equal(credential.password.length, 20);
  assert.equal(JSON.stringify(env.INTEREST_DB.boundValues).includes(credential.password), false);
  assert.equal(env.INTEREST_DB.batchCalls, 1);
});
```

- [ ] **Step 2: Run admin Worker tests and verify RED**

Run: `cd docs-site; npm run test:worker`

Expected: new admin mutation tests fail with `405` or `404`.

- [ ] **Step 3: Implement bounded admin orchestration**

Add a small route table after `authorizeAdmin`. Use `request.body.getReader()` to reject oversized JSON before parsing. Require `Origin: https://admin.backchannel.page`. Use prepared statements and one `INTEREST_DB.batch()` for approval, grant replacement, reset, and revoke.

Approval order must be: insert account with `INSERT ... SELECT ... WHERE EXISTS`, insert grants, update interest, insert event. Reset must update password material and expiry, set `must_change_password=1`, reactivate only when explicitly resetting an active account, delete all sessions, and insert an event in one batch. Revoke must update state/timestamp, delete sessions, and insert an event in one batch.

- [ ] **Step 4: Add failing admin browser-contract tests**

Assert the review table exposes decision and grant controls; dialogs use native `<dialog>`, labelled fields, focus restoration, and Escape/Cancel; Copy uses `navigator.clipboard.writeText`; Save uses `Blob` and a temporary object URL; the filename is sanitized; plaintext exists only in one module-scoped variable and is cleared on dialog close and `pagehide`; no local/session storage, cookies, console logging, or HTML insertion APIs are present.

- [ ] **Step 5: Implement the admin UI minimally**

Render actions with `createElement`/`textContent`. Load releases once with interests. Default the Latest checkbox to checked for new approvals. On a successful approval/reset, construct the exact credential text from the JSON response, show it in a read-only `<textarea>`, implement Copy and Save, then set both the textarea value and in-memory credential variable to an empty string on close/unload.

```js
let activeCredentialText = '';
function clearCredential() {
  activeCredentialText = '';
  credentialText.value = '';
}
credentialDialog.addEventListener('close', clearCredential);
addEventListener('pagehide', clearCredential);
```

- [ ] **Step 6: Run admin suites and commit Task 2**

Run: `cd docs-site; npm run test:worker; npm run test:admin`

Expected: all Worker and admin tests pass.

```powershell
git add docs-site/worker.js docs-site/worker.test.js site/admin/index.html site/admin/admin.js site/admin/admin.css docs-site/admin.test.js
git commit -m "feat: add release approval administration"
```

### Task 3: Recipient authentication and forced password change

**Files:**
- Modify: `docs-site/worker.js`
- Modify: `docs-site/worker.test.js`
- Create: `site/downloads/index.html`
- Create: `site/downloads/downloads.js`
- Create: `site/downloads/downloads.css`
- Create: `docs-site/download.test.js`
- Modify: `docs-site/package.json`

**Interfaces:**
- Consumes: Task 1 password/session helpers and session constants.
- Produces: `POST /api/download/login`, `GET /api/download/session`, `POST /api/download/password`, and `POST /api/download/logout`.
- Produces: authenticated session shape `{authenticated:true,must_change_password:boolean,email:string}`; unauthenticated response is `{authenticated:false}`.

- [ ] **Step 1: Add failing recipient authentication tests**

Cover exact download host/action Turnstile validation, generic `401` for unknown/pending/revoked/expired/wrong-password cases, dummy PBKDF2 execution, exact Origin/content type/body limits, session-token hashing, cookie flags, 30-minute change-session cap, seven-day normal session, account/session expiry/state checks per request, change-only route restriction, 14-128 character permanent passwords, atomic password change/session rotation, logout, and cookie clearing.

```js
assert.match(login.headers.get('set-cookie'), /^__Host-backchannel_release=/);
for (const attribute of ['Path=/', 'Secure', 'HttpOnly', 'SameSite=Strict', 'Max-Age=1800']) {
  assert.match(login.headers.get('set-cookie'), new RegExp(attribute));
}
assert.equal(env.INTEREST_DB.boundValues.includes(rawSessionToken), false);
```

- [ ] **Step 2: Run Worker tests and verify RED**

Run: `cd docs-site; npm run test:worker`

Expected: download authentication routes return `404`.

- [ ] **Step 3: Implement recipient authentication routes**

Use the separate recipient CSP and private headers. Validate Turnstile against `downloads.backchannel.page` and action `download_login`. Query by normalized email but perform one fixed-cost derivation even if the account is missing or invalid. Store token hash only. On every authenticated call, join session to account and reject expired/revoked rows.

Password change must create a new token, delete every existing session in the same D1 batch, update password material/flags, insert the new normal session, and add the event. Return a rotated seven-day cookie. Logout deletes the current hash and expires the cookie with `Max-Age=0`.

- [ ] **Step 4: Add failing recipient UI tests**

Assert local assets only, a Turnstile widget carrying `data-action="download_login"`, mutually exclusive login/change/releases panels, labelled inputs, error `role="alert"`, status hydration from `/api/download/session`, JSON mutation calls, no browser persistence or console logging, and no use of `innerHTML`.

- [ ] **Step 5: Implement the three-state recipient UI**

Create a restrained Backchannel-branded page. On load, fetch session status. Submit login with the Turnstile token; show password change immediately for a change-only session; fetch releases only for a normal session. Reset the Turnstile widget after any login response. Keep errors generic and restore focus to the relevant input.

- [ ] **Step 6: Add the download test command, run suites, and commit Task 3**

```json
"test:download": "node --test download.test.js"
```

Run: `cd docs-site; npm run test:worker; npm run test:download; npm run build`

Expected: all tests pass and `dist-site/downloads/index.html`, `downloads.js`, and `downloads.css` exist.

```powershell
git add docs-site/worker.js docs-site/worker.test.js docs-site/download.test.js docs-site/package.json site/downloads
git commit -m "feat: add recipient release authentication"
```

### Task 4: Entitlements and authorized R2 streaming

**Files:**
- Modify: `docs-site/release-access.js`
- Modify: `docs-site/release-access.test.js`
- Modify: `docs-site/worker.js`
- Modify: `docs-site/worker.test.js`
- Modify: `site/downloads/downloads.js`
- Modify: `docs-site/wrangler.jsonc`

**Interfaces:**
- Consumes: Task 1 catalog and range helpers; Task 3 normal sessions.
- Produces: `GET /api/download/releases -> {items:[{version,published_at,assets:[{id,platform,filename,size,sha256}]}]}`.
- Produces: `GET /api/download/releases/{version}/{asset_id}` with authorized streaming response.
- Produces: R2 binding `RELEASES` and recipient route.

- [ ] **Step 1: Add failing entitlement and R2 integration tests**

Cover Latest advancing dynamically, explicit history remaining, duplicate removal, pagination, malformed/missing manifests, unauthorized/missing indistinguishable `404`, arbitrary/path-encoded version/asset rejection, full/open-ended/suffix/single-byte ranges, multi-range rejection, `If-Match`, `If-None-Match`, `If-Modified-Since`, `If-Unmodified-Since`, `200/206/304/412/416`, `Content-Range: bytes */size`, manifest-owned type/disposition, quoted ETag, and body object identity proving streaming.

```js
test('download streams the R2 body without buffering', async () => {
  const body = new ReadableStream({start(controller) { controller.enqueue(new Uint8Array([1])); controller.close(); }});
  env.RELEASES.get = async () => ({body, size: 1, httpEtag: '"etag"', range: undefined});
  const response = await route(authenticatedDownload('/api/download/releases/v0.2.1/windows-x64'), env);
  assert.equal(response.body, body);
});
```

- [ ] **Step 2: Run focused tests and verify RED**

Run: `cd docs-site; npm run test:release-access; npm run test:worker`

Expected: release-list and asset-download tests fail with `404`.

- [ ] **Step 3: Implement entitlement resolution and R2 responses**

Require a normal session first. Resolve authorized versions from the catalog; never sort keys to infer Latest. Validate URL-decoded segments against `^v[0-9]+\.[0-9]+\.[0-9]+$` and `^[a-z0-9-]{1,32}$`, confirm entitlement, resolve the asset ID from its validated manifest, then call `RELEASES.get(asset.key, {range: request.headers, onlyIf: request.headers})`.

Reject multi-range before R2. Map R2 conditional failure to `304` for `If-None-Match`/`If-Modified-Since`, otherwise `412`; map unsatisfied range to `416`; return the R2 `ReadableStream` directly for `200/206`. Add the private no-store headers and audit only a `download_start` event with email/action/version.

- [ ] **Step 4: Add download links to recipient UI**

Render one release section per entitled version, mark the latest pointer textually, show platform/size/SHA-256, and create same-origin anchor URLs using `encodeURIComponent(version)` and `encodeURIComponent(asset.id)`. Do not expose the R2 key.

- [ ] **Step 5: Configure strict Worker host and binding isolation**

Add `downloads.backchannel.page`, `r2_buckets: [{binding:"RELEASES",bucket_name:"backchannel-desktop-releases"}]`, `workers_dev:false`, and `preview_urls:false`. In `route`, redirect only the exact `www.backchannel.page`; reject every unknown host with a no-store `404` before any API or asset handling. Add a full host/route matrix test.

- [ ] **Step 6: Run suites/dry-run and commit Task 4**

Run: `cd docs-site; npm run test:release-access; npm run test:worker; npm run test:download; npm run build; npx wrangler deploy --dry-run`

Expected: all tests pass, build succeeds, and Wrangler reports the `RELEASES` R2 binding plus all four custom domains with public Worker URLs disabled.

```powershell
git add docs-site/release-access.js docs-site/release-access.test.js docs-site/worker.js docs-site/worker.test.js site/downloads/downloads.js docs-site/wrangler.jsonc
git commit -m "feat: stream entitled releases from private R2"
```

### Task 5: Immutable R2 publication and historical migration

**Files:**
- Create: `desktop/scripts/build_release_manifest.py`
- Create: `desktop/tests/test_release_manifest.py`
- Modify: `desktop/tests/test_release_contract.py`
- Modify: `.github/workflows/desktop-release.yml`
- Create: `scripts/migrate_releases_to_r2.ps1`

**Interfaces:**
- Produces: `build_manifest(asset_dir: Path, tag: str, commit: str, published_at: str, allow_legacy_partial: bool = False) -> dict`.
- Produces CLI: `python desktop/scripts/build_release_manifest.py --asset-dir <dir> --tag <vX.Y.Z> --commit <40hex> --published-at <UTC> --manifest-out <path> --latest-out <path> [--current-latest <path>]`.
- Consumes GitHub secrets `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `CLOUDFLARE_ACCOUNT_ID`; repository variable `R2_RELEASES_BUCKET` equals `backchannel-desktop-releases`.

- [ ] **Step 1: Write failing manifest-generator tests**

Use temporary directories to assert the exact three filenames in normal mode, rejection of extras/missing assets/symlinks/empty files, streaming SHA-256/size, deterministic asset ordering/IDs/platform/content types/keys, strict semantic tag and 40-hex commit, UTC publication time, and monotonic Latest comparison using numeric semantic-version tuples. A separately tested `allow_legacy_partial=True` mode accepts only the exact Windows/macOS pair used by v0.1.0 and v0.1.1; the CI workflow never passes that flag.

```python
def test_older_release_cannot_regress_latest(tmp_path):
    current = tmp_path / "latest.json"
    current.write_text('{"version":"v0.3.0"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="regress Latest"):
        write_release_files(tmp_path, "v0.2.1", "a" * 40, PUBLISHED_AT, current)
```

- [ ] **Step 2: Update workflow contract tests and verify RED**

Require `publish.needs: build`, exact push/tag gate, merged download of all artifacts, one global R2 publication concurrency group with `cancel-in-progress:false`, conditional immutable manifest creation, asset verification before manifest, manifest verification before Latest, conditional monotonic Latest update, separate S3 credentials, no `files:` release attachment, GitHub release notes retained, and dispatch non-publication.

Run: `python -m pytest desktop/tests/test_release_manifest.py desktop/tests/test_release_contract.py -q`

Expected: new helper import and workflow assertions fail.

- [ ] **Step 3: Implement the manifest generator**

Read assets in 1 MiB chunks. Emit compact deterministic JSON with newline. Include `content_type: application/zip` for Windows/macOS and `application/gzip` for Linux. Reject any current Latest version greater than the candidate; equality is allowed only for verification and never for an immutable manifest write.

- [ ] **Step 4: Replace per-matrix attachment with a final publish job**

Set workflow-level `permissions: contents: read`; grant `contents: write` only to publish. Keep build/smoke/artifact steps unchanged. The publish job must:

1. Download all artifacts with `actions/download-artifact@v4`, pattern `Backchannel-*`, `merge-multiple:true`.
2. Configure AWS CLI with the R2 endpoint `https://${CLOUDFLARE_ACCOUNT_ID}.r2.cloudflarestorage.com`.
3. Fetch current Latest when present and generate/validate manifest locally.
4. Fail on any error checking the existing manifest; treat only an exact S3 `404` as absence.
5. Upload assets with `aws s3 cp` so large bundles use multipart.
6. Verify each remote `ContentLength` against the manifest.
7. Create the version manifest with `aws s3api put-object --if-none-match '*'`; a `412` means immutable version already exists and fails.
8. Read back and byte-compare the manifest.
9. Re-read Latest, reject a numerically newer version, then write `latest.json` last with `--if-match <current-etag>` or `--if-none-match '*'`. On `412`, re-read, revalidate monotonicity, and retry once so a concurrent publication cannot regress the pointer.
10. Run `softprops/action-gh-release@v2` with `body_path` only.

Use job concurrency `backchannel-r2-publish` with `cancel-in-progress: false` and environment `production`, serializing publication across every tag. The job gate is exactly `${{ github.event_name == 'push' && startsWith(github.ref, 'refs/tags/v') }}`.

- [ ] **Step 5: Add an owner-run historical migration script**

Accept `-Version`, `-Commit`, `-PublishedAt`, and `-AssetDirectory`. Validate with the Python helper, passing `--allow-legacy-partial` only when the directory contains the exact Windows/macOS pair, use the same R2 endpoint/credentials, upload only versions whose manifest is absent, verify all sizes, conditionally create the manifest, and update Latest only with explicit `-SetLatest`. The script must never grant an account and must not delete GitHub assets.

- [ ] **Step 6: Run tests and commit Task 5**

Run: `python -m pytest desktop/tests/test_release_manifest.py desktop/tests/test_release_contract.py -q`

Expected: all manifest and workflow contracts pass.

```powershell
git add desktop/scripts/build_release_manifest.py desktop/tests/test_release_manifest.py desktop/tests/test_release_contract.py .github/workflows/desktop-release.yml scripts/migrate_releases_to_r2.ps1
git commit -m "feat: publish desktop releases to private R2"
```

### Task 6: Customer links, operational documentation, and full local gate

**Files:**
- Modify: `README.md`
- Modify: `docs/quickstart.md`
- Modify: `docs/releasing.md`
- Modify: `docs/deployment.md`
- Modify: `docs/README.md`
- Modify: `site/index.html`
- Modify: `site/fireflies-alternative/index.html`
- Modify: `site/granola-alternative/index.html`
- Modify: `site/otter-alternative/index.html`
- Modify: `site/vs-meetily/index.html`
- Modify: `site/releases/v0.1.0/index.html`
- Modify: `site/releases/v0.1.1/index.html`
- Modify: `site/releases/v0.2.0/index.html`
- Modify: `site/releases/v0.2.1/index.html`
- Modify: `site/llms.txt`
- Modify: `site/sitemap.xml`
- Modify: `.github/release-notes/v0.1.1.md`
- Modify: `.github/release-notes/v0.2.0.md`
- Modify: `.github/release-notes/v0.2.1.md`
- Modify: `AGENTS.md`
- Modify: `CLAUDE.md`
- Modify: `docs-site/site.test.js`

**Interfaces:**
- Consumes: authenticated recipient host and tag publication from Tasks 3-5.
- Produces: one authoritative release checklist and no customer-facing GitHub executable URL.

- [ ] **Step 1: Add failing stale-link/site tests**

Assert customer-facing files contain no `github.com/.../releases/download`, no claim that executable assets are attached to GitHub releases, and no GitHub membership requirement. Require authenticated portal links and sitemap entry `https://downloads.backchannel.page/`. Preserve source, issues, license, star, and tag-note GitHub links.

Run: `cd docs-site; npm run test:site`

Expected: failures identify current direct executable links and stale guidance.

- [ ] **Step 2: Update customer-facing links and release copy**

Point general download actions to `https://downloads.backchannel.page/`; release-specific buttons use `https://downloads.backchannel.page/?version=v0.2.1` and the recipient UI reads only a validated `version` query parameter to focus an entitled release after authentication. State clearly that an approved Backchannel account is required, not a GitHub account.

- [ ] **Step 3: Make deployment and release runbooks authoritative**

Document:

- D1 backup then remote migration 0002 and `PRAGMA foreign_key_check`/`integrity_check`.
- Creation of private bucket `backchannel-desktop-releases` with both `r2.dev` and bucket custom domains disabled.
- `RELEASES` binding and `downloads.backchannel.page` custom domain.
- Recipient Turnstile hostname/action and Cloudflare rate-limit rule for `POST /api/download/login`.
- separate R2 Object Read & Write S3 credentials scoped to this bucket and the three GitHub secret names.
- Worker deployment before publication enablement.
- historical migration commands for v0.1.0, v0.1.1, v0.2.0, and v0.2.1, noting older releases have only the assets originally built.
- one-release-cycle rollback retention and subsequent manual GitHub asset removal.
- CPU benchmark gate showing PBKDF2 stays under the deployed Worker plan ceiling; if not, upgrade the Worker plan before enabling accounts rather than lowering 600,000 iterations.

- [ ] **Step 4: Update contributor guidance**

Replace statements that the admin API is read-only. State that R2 manifests and `docs/releasing.md` are authoritative, customer executables never attach to GitHub, and recipient identity stays in D1 rather than the local app/PostgreSQL.

- [ ] **Step 5: Run the complete local verification gate**

```powershell
cd docs-site
npm run test:release-access
npm run test:migration
npm run test:worker
npm run test:admin
npm run test:download
npm run test:site
npm run build
npx wrangler deploy --dry-run
npx wrangler d1 migrations apply INTEREST_DB --local
npx wrangler d1 execute INTEREST_DB --local --command "PRAGMA foreign_key_check; PRAGMA integrity_check;"
cd ..
python -m pytest desktop/tests/test_release_manifest.py desktop/tests/test_release_contract.py -q
rg -n "releases/download|private GitHub repository|assets are attached" README.md docs site .github AGENTS.md CLAUDE.md
git diff --check
```

Expected: every test/build/dry-run/integrity check passes; stale-link search returns no customer executable links or obsolete access claims; `git diff --check` is silent.

- [ ] **Step 6: Commit Task 6**

```powershell
git add README.md docs/quickstart.md docs/releasing.md docs/deployment.md docs/README.md site .github/release-notes AGENTS.md CLAUDE.md docs-site/site.test.js
git commit -m "docs: route desktop recipients through Backchannel"
```

### Task 7: Cloudflare provisioning, migration, deployment, and live acceptance

**Files:**
- No source changes unless a live verification exposes a defect; any defect follows a new failing test, minimal fix, focused verification, and separate commit.

**Interfaces:**
- Consumes: deployed Worker, D1 migration, private R2 bucket, DNS, Turnstile, rate limit, and GitHub Actions secrets.
- Produces: verified production release access independent of GitHub identity.

- [ ] **Step 1: Provision the private delivery boundary**

Create `backchannel-desktop-releases`, disable its public development URL, confirm it has no custom domain, bind it as `RELEASES`, add `downloads.backchannel.page`, and confirm Worker `workers.dev` plus preview URLs are disabled. Create the recipient Turnstile configuration and exact login rate-limit rule.

- [ ] **Step 2: Back up and migrate production D1**

Export the current D1 database, apply migration 0002 remotely, then run foreign-key and integrity checks. Stop deployment if either check returns anything other than no FK rows and `ok`.

- [ ] **Step 3: Configure independent publication credentials**

Create bucket-scoped R2 S3 Object Read & Write credentials. Store access key, secret, and account ID as `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, and `CLOUDFLARE_ACCOUNT_ID`; set `R2_RELEASES_BUCKET=backchannel-desktop-releases`. Do not change the site deploy token permissions.

- [ ] **Step 4: Deploy control plane with publication disabled**

Deploy the Worker/site. Verify public interest capture, Access-protected admin read/mutations, recipient login page, unknown-host denial, private headers, and anonymous download denial before uploading any object.

- [ ] **Step 5: Migrate and verify existing releases**

Use owner-authenticated local copies of the historical GitHub assets with `scripts/migrate_releases_to_r2.ps1`; publish manifests only for their actual asset sets, and set `v0.2.1` as Latest after every intended object verifies. Do not grant any account automatically.

- [ ] **Step 6: Run live account and delivery acceptance**

Approve two test accounts and prove their generated passwords differ. Exercise Copy and Save `.txt`; change both temporary passwords; verify old cookies fail. Grant Latest plus one historical version to one account and only Latest to the other. Download each available Windows, macOS, and Linux bundle without GitHub cookies and compare SHA-256 against the manifest. Revoke one account during a ranged download and prove its next range request fails. Confirm anonymous portal, unknown Worker host, `workers.dev`, preview URL, `r2.dev`, and any bucket custom-domain access are denied.

- [ ] **Step 7: Exercise a real patch-tag publication**

Push the next approved patch tag. Verify all build jobs pass, all three assets precede the manifest, Latest updates last, GitHub release notes contain no executables, a deliberately older candidate cannot regress Latest, and existing approved Latest accounts see the new release without a grant edit.

- [ ] **Step 8: Enable customer links and record the release gate**

Deploy the link changes only after Steps 1-7 pass. Record object counts, manifest hashes, D1 integrity result, host-denial results, and the successful three-platform download hashes in the release checklist. Retain old private GitHub assets for one release cycle.

## Self-review record

- Spec coverage: every design section maps to Tasks 1-7; security review additions cover strict unknown-host rejection, dummy PBKDF2, bounded temporary sessions, manifest `content_type`, D1 interest foreign key, paginated R2 listing, conditional version creation, monotonic Latest, separate R2 writer credentials, range/conditional semantics, and private-bucket verification.
- Placeholder scan: the plan contains no deferred implementation instruction; each code-changing task names exact files, interfaces, tests, commands, and observable outcomes.
- Type consistency: `credential`, manifest, catalog, session, and publication field names remain identical across producer and consumer tasks.
- Scope check: all slices change one cohesive release-access capability and independently end in a testable commit; no second service, framework, updater, or licensing system is introduced.
