# Cloudflare R2 Release Access - Design

Date: 2026-07-12

Status: Approved

Branch: `agent/r2-release-access`

## Goal

Move Backchannel's Windows, macOS, and Linux desktop bundles from private
GitHub release assets to a private Cloudflare R2 bucket. Recipients must not
need a GitHub account, repository membership, or GitHub-managed release
permission.

Reuse the existing early-access request, Cloudflare Worker, D1 database, and
Cloudflare Access-protected admin console. An operator reviews each request,
approves or rejects it, grants Latest by default, may add specific historical
versions, and receives a unique temporary password that can be viewed, copied,
or saved as a text file from the admin console.

## Existing foundation

Backchannel already has the components this feature needs:

- `backchannel.page` accepts Turnstile-protected early-access requests and
  stores duplicate-safe consent records in D1.
- `admin.backchannel.page` is protected by Cloudflare Access and the Worker
  independently verifies issuer, audience, expiry, and exact `ADMIN_EMAIL`.
- GitHub Actions builds and smoke-tests exactly three native assets on version
  tags:
  - `Backchannel-windows-x64.zip`
  - `Backchannel-macos-arm64.zip`
  - `Backchannel-linux-x64.tar.gz`
- Static release pages and the landing page currently link those assets from
  private GitHub releases.

The self-hosted Backchannel application's local Administration panel and
PostgreSQL database are outside this feature. Release identity remains in the
site Worker and D1, not in the desktop application.

## Decisions

| Decision | Choice | Reason |
| --- | --- | --- |
| Artifact store | Private Cloudflare R2 bucket | Removes GitHub as the executable access boundary and fits the existing Cloudflare deployment |
| Control plane | Existing `docs-site` Worker and D1 database | Reuses the current request, admin, deployment, and security boundaries |
| Recipient host | `downloads.backchannel.page` | Keeps account and download routes distinct from the public and operator hosts |
| Operator identity | Existing Cloudflare Access exact-email policy and Worker JWT verification | No second operator account system is needed |
| Recipient identity | D1 account with a one-time temporary password and opaque server-side session | Meets the requested credential-file workflow without GitHub or Cloudflare account membership |
| Password storage | PBKDF2-HMAC-SHA256, 600,000 iterations, unique 16-byte salt | Supported by Workers Web Crypto and aligned with current OWASP PBKDF2 guidance |
| Artifact delivery | Worker-authorized R2 stream with conditional and range support | Every request remains account-gated; no transferable presigned bearer URL is created |
| Default entitlement | Dynamic Latest plus optional explicit versions | New releases become available automatically while historical access remains deliberate |
| Publication | A final tag-workflow job uploads all verified assets, then the manifest, then `latest.json` | Latest cannot point at a partial release |

Cloudflare Access one-time PIN is not used for recipients because it cannot
produce the operator-generated credential text requested here and would move
recipient management into Access policies. R2 presigned URLs are not used
because anyone holding the URL could download until it expires, even after an
account is revoked.

## R2 release catalog

Bind one private bucket to the existing site Worker as `RELEASES`:

```text
releases/
  latest.json
  v0.2.1/
    manifest.json
    Backchannel-windows-x64.zip
    Backchannel-macos-arm64.zip
    Backchannel-linux-x64.tar.gz
  v0.3.0/
    manifest.json
    Backchannel-windows-x64.zip
    Backchannel-macos-arm64.zip
    Backchannel-linux-x64.tar.gz
```

Each version manifest is immutable:

```json
{
  "version": "v0.3.0",
  "published_at": "2026-07-12T18:00:00Z",
  "commit": "0123456789abcdef0123456789abcdef01234567",
  "assets": [
    {
      "id": "windows-x64",
      "platform": "Windows x64",
      "filename": "Backchannel-windows-x64.zip",
      "key": "releases/v0.3.0/Backchannel-windows-x64.zip",
      "size": 123456789,
      "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
    }
  ]
}
```

`latest.json` contains only a validated version:

```json
{"version":"v0.3.0"}
```

The publish workflow rejects an existing version manifest. Corrected binaries
use a new patch version; a published version is never overwritten. Asset keys
come only from a trusted manifest written by CI. Browser requests never supply
or receive an arbitrary R2 key.

The Worker discovers historical releases by listing keys matching
`releases/v*/manifest.json`. The expected release count is small, so a separate
catalog service or database copy is unnecessary. Add one only if observed list
latency becomes material.

## D1 model

Keep `interest_subscribers` as the request and consent record. Migration 0002
adds `release_decision TEXT NOT NULL DEFAULT 'pending'` constrained to
`pending`, `approved`, or `rejected`, plus nullable `release_reviewed_at`.
Approval sets `release_decision` to `approved` and the existing status to
`active`. Rejection sets only `release_decision` to `rejected`, preserving the
separate mailing-consent status and record.

Add migration `0002_release_access.sql` with four focused tables.

### `release_accounts`

```text
email TEXT PRIMARY KEY COLLATE NOCASE
state TEXT NOT NULL CHECK (state IN ('active', 'revoked'))
password_hash TEXT NOT NULL
password_salt TEXT NOT NULL
password_iterations INTEGER NOT NULL DEFAULT 600000
must_change_password INTEGER NOT NULL DEFAULT 1 CHECK (... IN (0, 1))
password_expires_at TEXT
include_latest INTEGER NOT NULL DEFAULT 1 CHECK (... IN (0, 1))
approved_at TEXT NOT NULL DEFAULT datetime('now')
password_changed_at TEXT
revoked_at TEXT
```

The account email must already exist in `interest_subscribers`. Approval is
the only account-creation path.

### `release_account_versions`

```text
email TEXT NOT NULL
version TEXT NOT NULL CHECK (length(version) BETWEEN 2 AND 32)
granted_at TEXT NOT NULL DEFAULT datetime('now')
PRIMARY KEY (email, version)
FOREIGN KEY (email) REFERENCES release_accounts(email) ON DELETE CASCADE
```

Explicit versions are additive to Latest. An operator may disable Latest and
leave only explicit versions for a pinned edge case.

### `release_sessions`

```text
token_hash TEXT PRIMARY KEY
email TEXT NOT NULL
password_change_only INTEGER NOT NULL CHECK (... IN (0, 1))
created_at TEXT NOT NULL DEFAULT datetime('now')
expires_at TEXT NOT NULL
FOREIGN KEY (email) REFERENCES release_accounts(email) ON DELETE CASCADE
```

Only a SHA-256 hash of the random 32-byte session token is stored. The raw
token exists only in the secure, HTTP-only cookie.

### `release_access_events`

```text
id INTEGER PRIMARY KEY AUTOINCREMENT
email TEXT NOT NULL
action TEXT NOT NULL
version TEXT
created_at TEXT NOT NULL DEFAULT datetime('now')
```

Events cover approval, rejection, password reset, password change, grant
change, revocation, login success, logout, and download start. They never
contain a password, password hash, salt, session token, Access JWT, R2 key, or
response body.

Use prepared statements throughout. Approval and grant replacement use D1
`batch()` so all statements commit or roll back together.

## Account approval and credential text

The existing admin table gains Approve and Reject actions for interested
records and release controls for active accounts.

Approval flow:

1. Load the current R2 release catalog.
2. Open a dialog with Latest checked by default and published historical
   versions available as optional checkboxes.
3. Generate a 20-character temporary password with Workers
   `crypto.getRandomValues()`, excluding visually ambiguous characters and
   guaranteeing upper-case, lower-case, number, and symbol characters.
4. Generate a unique 16-byte salt and derive a 32-byte
   PBKDF2-HMAC-SHA256 hash with 600,000 iterations.
5. In one D1 batch, insert the previously nonexistent account, replace
   explicit grants, mark the interest record active/approved, and add an
   approval event. The account primary key makes a repeated or concurrent
   approval fail without rotating credentials.
6. Return the plaintext password exactly once in the successful admin
   response. D1 stores only its salt, work factor, and derived hash.
7. Show a credential dialog with visible text, Copy, and Save `.txt` actions.
8. Clear the plaintext from page state when the dialog closes or the page
   unloads.

The generated text file is:

```text
Backchannel desktop access
Account: recipient@example.com
Temporary password: <generated password>
Sign in: https://downloads.backchannel.page/
Password expires: <UTC timestamp, 72 hours after approval>
Release access: Latest[, v0.2.0, v0.2.1]
```

The admin page creates the file with a browser `Blob` and a sanitized filename
such as `backchannel-access-recipient-example-com.txt`. It uses the Clipboard
API for Copy. Neither operation sends the text to another service or stores it
in local storage, session storage, cookies, client logs, or D1.

If the response or saved file is lost, Reset password generates a new
temporary password, invalidates all existing recipient sessions, and returns a
new one-time credential response. The old password cannot be recovered.

Reject changes the interest decision but does not create an account. Revoke
sets the account to `revoked` and deletes its sessions; it does not delete the
consent or event history.

## Recipient authentication

`downloads.backchannel.page` is served by the same Worker but is not protected
by the operator's Cloudflare Access application. It has its own narrow route
map, CSP, and static assets.

The login form accepts email, temporary or permanent password, and a
hostname-bound Turnstile token using action `download_login`. The Worker:

1. validates method, same-origin request, body size, email, password length,
   and Turnstile result;
2. loads an active account with a generic query result;
3. derives PBKDF2 with the stored salt and work factor;
4. compares the derived value with `crypto.subtle.timingSafeEqual()`;
5. rejects inactive, revoked, or expired temporary credentials with the same
   generic login response; and
6. creates a random session and secure cookie on success.

Cookie attributes:

```text
__Host-backchannel_release=<opaque token>;
Path=/;
Secure;
HttpOnly;
SameSite=Strict;
Max-Age=604800
```

A temporary-password login creates a `password_change_only` session. That
session may call only session status, password change, and logout endpoints.
The UI immediately presents a new-password form. Permanent passwords must be
14-128 characters. Successful change writes a new salt/hash, clears the
temporary expiry and `must_change_password`, deletes all other sessions, and
promotes the current session to normal access.

Authentication responses and timing do not reveal whether an email is
pending, approved, revoked, or unknown. Turnstile and a Cloudflare rate-limit
rule protect the login endpoint from bulk guessing. Password derivation is
kept below the Worker's request CPU ceiling and measured in deployment before
release; the iteration count remains stored per account for future upgrades.

## Entitlements and downloads

An authenticated normal session receives:

- the manifest named by `latest.json` when `include_latest = 1`; and
- each valid manifest named in `release_account_versions`.

Duplicates are removed. Missing or malformed manifests are omitted from the
recipient list and reported as a generic admin diagnostic. Latest is never
guessed from object name sorting.

Download requests contain only a version and manifest asset ID. The Worker
authorizes the version, loads its trusted manifest, resolves the asset, then
uses the `RELEASES` binding to stream the object. It passes conditional and
Range headers to R2, returns the appropriate `200`, `206`, `304`, or `412`, and
sets:

- the object's quoted ETag;
- `Content-Length` and `Content-Range` when applicable;
- manifest-owned `Content-Type` and attachment filename;
- `Accept-Ranges: bytes`;
- `Cache-Control: private, no-store`; and
- the existing private response hardening headers.

The Worker does not buffer the executable in memory. Revocation blocks the
next request immediately, including a resumed range request. An already
streaming response may finish.

## Worker routes and host isolation

### Public host: `backchannel.page`

```text
POST /api/interest
GET  public site assets
```

No admin, login, account, entitlement, or download route is served here.

### Admin host: `admin.backchannel.page`

```text
GET  /
GET  private admin assets
GET  /api/admin/interests
GET  /api/admin/releases
POST /api/admin/access/approve
POST /api/admin/access/reject
PUT  /api/admin/access/grants
POST /api/admin/access/reset-password
POST /api/admin/access/revoke
```

Every request first passes the existing Access JWT and exact-email check.
Emails stay in JSON request bodies, never URL paths.

### Recipient host: `downloads.backchannel.page`

```text
GET  /
GET  recipient assets
POST /api/download/login
GET  /api/download/session
POST /api/download/password
POST /api/download/logout
GET  /api/download/releases
GET  /api/download/releases/{version}/{asset_id}
```

Unknown API paths return no-store JSON `404` responses. Unknown static paths
return no-store `404` and never fall through to public or admin assets.

## Release publication workflow

Keep the existing three-platform build matrix, frontend build, Python
dependency installation, ONNX model download, embedded PostgreSQL download,
PyInstaller build, smoke test, and workflow artifact upload.

Remove the per-matrix `Attach to release` step. Add one tag-only publish job
that runs after all matrix builds succeed:

1. Download all three workflow artifacts.
2. Assert the exact filenames and reject extras or missing assets.
3. Compute SHA-256 and byte size for each asset.
4. Build and validate the immutable version manifest from the tag and commit.
5. Confirm `releases/{tag}/manifest.json` does not already exist.
6. Upload all three bundles to `releases/{tag}/` with attachment metadata.
7. Read back object metadata and verify size for all three.
8. Upload `manifest.json`.
9. Read and validate the uploaded manifest.
10. Replace `releases/latest.json` last.
11. Create or update GitHub release notes without attaching executable assets.

Workflow dispatch remains a non-publishing packaging check. Only a `v*` tag
publishes to R2. The workflow uses the repository's existing Cloudflare
account secret plus an R2 object-write API token; the Worker binding requires
no S3 credential.

Existing release assets may be migrated to R2 once using owner-authenticated
GitHub downloads and generated manifests. Migration does not make them
available to an account unless Latest or that explicit version grants access.

## Site and documentation changes

- Replace direct GitHub executable URLs with the authenticated download host.
- Current release pages identify the three builds and link to the matching
  authenticated release view.
- Keep GitHub source, issue, license, and star links where they are genuinely
  about the open-source project; the restriction is removal of GitHub as the
  executable identity and access manager.
- Update `README.md`, `docs/quickstart.md`, `docs/releasing.md`, `site/index.html`,
  comparison pages, release pages, `site/llms.txt`, and `site/sitemap.xml`.
- Update `AGENTS.md` and `CLAUDE.md` so the admin API is no longer described as
  read-only and R2 publication becomes the authoritative release checklist.

## Security boundary

- Preserve the existing Access issuer, audience, expiry, and exact-email
  verification on the entire admin hostname.
- Add no public admin mutation or export route.
- Keep email out of route paths, logs, events emitted to console, and R2 keys.
- Use prepared D1 statements and transactional `batch()` for multi-row writes.
- Store no plaintext or reversibly encrypted password.
- Generate passwords, salts, and sessions only with Workers cryptographic
  randomness.
- Use PBKDF2-HMAC-SHA256 with a per-account salt and constant-time comparison.
- Validate Turnstile hostname and action for recipient login.
- Use generic authentication and service errors.
- Store only session-token hashes and delete sessions on reset/revoke.
- Require CSRF-resistant same-origin requests and `SameSite=Strict`; mutation
  endpoints accept JSON only and validate Origin.
- Resolve R2 keys only through trusted manifests and validate tag, asset ID,
  filename, size, and SHA-256 bounds.
- Never log Access assertions, emails, passwords, hashes, salts, session
  tokens, cookie values, R2 object bodies, or D1 result rows.
- Apply no-store, restrictive CSP, referrer, frame, and content-type headers to
  admin and recipient pages and APIs.

## Error handling

- Missing D1, R2, Turnstile, or Access configuration: fail closed with `503`.
- Invalid public/request/login input: bounded `400` without internal details.
- Invalid recipient credentials: generic `401` regardless of account state.
- Expired temporary password: generic login failure; operator reset restores
  the path.
- Unauthorized or missing release: generic `404` so accounts cannot enumerate
  catalog entries they do not hold.
- R2 unavailable or malformed manifest: `503`; do not fall back to GitHub.
- Existing version manifest during publication: fail the workflow before any
  overwrite.
- Partial asset upload: leave `latest.json` unchanged; an operator may delete
  the unpublished prefix and rerun after diagnosis.
- Admin approval response lost: the account exists but plaintext is
  unrecoverable; Reset password produces a new credential.
- Clipboard failure: keep the credential visible and retain Save `.txt`.
- Range outside the object: return `416` without reading the complete object.

## Testing

Node's built-in test runner covers:

- password generation constraints and uniqueness;
- PBKDF2 hashing, verification, wrong-password failure, and constant-time
  comparison path;
- approval batch contents, default Latest, explicit historical grants,
  rejection, reset, and revocation;
- one-time plaintext response and absence of sensitive values in D1 writes;
- temporary expiry, forced password change, session hashing, cookie flags,
  logout, reset/revoke invalidation, and host/path isolation;
- generic login responses and Turnstile validation;
- entitlement resolution as Latest advances and historical access remains;
- arbitrary version/asset/key rejection;
- R2 full, conditional, and ranged response behavior without buffering;
- admin Copy/Save controls, plaintext clearing, safe DOM rendering, accessible
  dialogs, and absence of browser persistence/logging;
- recipient login/change/download states and accessible error feedback; and
- public/admin/recipient hostname isolation and security headers.

Desktop and workflow contract tests cover:

- the exact three asset names;
- build and smoke-test matrix retention;
- tag-only R2 publication;
- all assets uploaded before manifest and Latest;
- no executable attachment to GitHub releases;
- immutable-version checks;
- manifest size and SHA-256 accuracy; and
- workflow dispatch remaining non-publishing.

Build and live verification cover:

- docs-site Worker/admin/recipient tests and production build;
- frontend production build;
- backend and desktop unit suites;
- Compose configuration and source-built images;
- a private R2 bucket with no public development URL or custom-domain bypass;
- two approvals producing different temporary passwords;
- first-login password change and session invalidation;
- Latest access following a newly published pointer;
- explicit access to one older version;
- revocation blocking new and resumed downloads;
- Windows, macOS, and Linux bundles downloaded without a GitHub session; and
- anonymous R2 and download-route requests remaining denied.

## Rollout

1. Create the private R2 bucket and bind it to the Worker.
2. Apply the D1 migration and deploy admin/recipient routes with publication
   disabled.
3. Configure `downloads.backchannel.page`, Turnstile hostname/action, and
   rate-limit policy.
4. Add the R2 writer permission to the GitHub Actions Cloudflare token.
5. Migrate one historical version and grant it only to an operator test
   account.
6. Approve two test accounts, validate credential files and password change,
   and test all three platform downloads.
7. Publish a new patch tag to R2 and confirm dynamic Latest behavior.
8. Change current site links from GitHub assets to the download host.
9. Retain old private GitHub assets for rollback during one release cycle,
   then remove them only after R2 verification is complete.

## Deliberate exclusions

- Cloudflare Access accounts or emailed OTP for recipients.
- R2 public buckets, public development URLs, custom-domain bucket exposure,
  or presigned download URLs.
- A second Worker, framework, authentication service, or mailing provider.
- Organization, seat, license, billing, hardware-binding, or device-token
  models.
- Automatic desktop updates, delta patches, resumable updater orchestration,
  MSI/DMG/DEB/RPM packaging, signing, or notarization.
- Changes to Backchannel's local Administration panel or PostgreSQL schema.
- Moving Docker source distribution or public third-party dependencies into
  R2.

These can be added only after the account, entitlement, publication, and audit
boundaries are proven with real desktop release usage.
