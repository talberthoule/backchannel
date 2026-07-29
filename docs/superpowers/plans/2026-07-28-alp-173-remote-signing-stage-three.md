# ALP-173 Remote Signing Stage Three Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply the three approved security amendments, provision the production Cloudflare signing boundary, and prove remote signing against the genesis public key without publishing a release.

**Architecture:** The existing ceremony performs an authenticated exact-name Secrets Store preflight before it can generate a key. The Worker pins the verified Access `common_name` claim to the dedicated service-token client ID. After live provisioning, only public identifiers and the generated public key enter the repository; remote signing remains the default and local signing remains explicit break-glass only.

**Tech Stack:** Node 24 WebCrypto and `node:test`, Cloudflare Workers/Access/Secrets Store, Wrangler 4.115.0, PowerShell 7, Python 3.12.

## Global Constraints

- Never echo, log, persist, or pass production Ed25519 private-key material in an argument.
- `ed25519-2026-07b` is the only production key ID and the only active trust-file entry.
- The ceremony must list Secrets Store metadata by the exact key name before key generation and hard-stop if that name already exists.
- The Worker must verify the exact Access issuer, audience, and service-token `common_name`.
- `workers.dev` and preview URLs remain disabled; the only route is the custom domain `signing.backchannel.page`.
- Remote signing is the default. Local signing requires explicit `-SigningMode Local` and never becomes an automatic fallback.
- No R2 object is published during stage-three proof.
- Commit locally on `agent/alp-173-remote-signing`; never push.

---

### Task 1: Ceremony preflight and Access identity pin

**Files:**
- Modify: `release-signing-worker/scripts/create-signing-key.mjs`
- Modify: `release-signing-worker/test/create-signing-key.test.mjs`
- Modify: `release-signing-worker/src/index.mjs`
- Modify: `release-signing-worker/test/index.test.mjs`
- Modify: `docs/superpowers/specs/2026-07-28-alp-173-remote-signing.md`

**Interfaces:**
- Consumes: the existing captured Wrangler auth object, Secrets Store collection URL, and verified Access JWT payload.
- Produces: an authenticated `GET ?search=ed25519-2026-07b&per_page=100` before `generateKeyPair()`, plus `ACCESS_COMMON_NAME` exact matching against `payload.common_name`.

- [ ] **Step 1: Write failing ceremony tests**

Add tests that require a `GET` list request before the existing `POST`, accept only successful list metadata, continue past near-name results, and prove an exact `ed25519-2026-07b` result raises `Signing key already exists` without calling `generateKeyPair`.

- [ ] **Step 2: Run ceremony tests and verify RED**

Run: `cd release-signing-worker; npm test -- --test-name-pattern="preflight|posts the PKCS8"`

Expected: FAIL because the ceremony currently generates and posts without a list request.

- [ ] **Step 3: Implement the minimal ceremony preflight**

Use the existing authenticated fetch dependency, timeout factory, endpoint, redirect policy, and generic Cloudflare failure handling. Parse only successful list metadata, require `success: true` and an array result, compare result names exactly, and execute the preflight before `generateKeyPair()`.

- [ ] **Step 4: Write failing Access claim tests**

Require `ACCESS_COMMON_NAME` configuration, accept the exact verified `payload.common_name`, and reject missing or different claims before any request-body or signing-secret read.

- [ ] **Step 5: Run Worker tests and verify RED**

Run: `cd release-signing-worker; npm test -- --test-name-pattern="common_name|Access configuration"`

Expected: FAIL because authorization currently discards the verified payload and has no configured common-name pin.

- [ ] **Step 6: Implement exact common-name authorization**

After `verifyAccessToken` succeeds, require:

```js
payload.common_name === env.ACCESS_COMMON_NAME
```

Treat missing configuration as `503` and a missing/mismatched claim as generic `401`.

- [ ] **Step 7: Update the approved design**

Document the mandatory exact-name preflight and `ACCESS_COMMON_NAME` binding. Keep the service-token client secret out of the document.

- [ ] **Step 8: Run focused and package tests**

Run:

```powershell
cd release-signing-worker
npm test
npx wrangler deploy --dry-run
```

Expected: all tests pass with pristine output and Wrangler validates the deployable base configuration.

- [ ] **Step 9: Commit**

```powershell
git add release-signing-worker docs/superpowers/specs/2026-07-28-alp-173-remote-signing.md docs/superpowers/plans/2026-07-28-alp-173-remote-signing-stage-three.md
git commit -m "fix: harden release signing cutover"
```

### Task 2: Public cutover artifacts and break-glass cleanup

**Files:**
- Modify: `release-signing-worker/wrangler.jsonc`
- Modify: `desktop/release_signing_keys.json`
- Modify: `scripts/publish_release_platform.ps1`
- Modify: `scripts/tests/test_publish_release_platform.ps1`
- Modify: `docs/releasing.md`

**Interfaces:**
- Consumes: the ceremony's public `{key_id, public_key}` JSON and the provisioned public Secrets Store ID, secret name, Access team domain, audience, and service-token client ID.
- Produces: the deployable production Worker configuration, sole genesis trust entry, and `ed25519-2026-07b.private` break-glass default path.

- [ ] **Step 1: Write the failing break-glass path test**

Change the default-path fixture to place its test-only private value at:

```text
%LOCALAPPDATA%\Backchannel\release-signing\ed25519-2026-07b.private
```

Run: `pwsh -NoProfile -File scripts/tests/test_publish_release_platform.ps1`

Expected: FAIL because the publisher still resolves the never-used `ed25519-2026-07.private` filename.

- [ ] **Step 2: Apply the public genesis trust root and path**

Set `desktop/release_signing_keys.json` to exactly one active `ed25519-2026-07b` entry containing the ceremony's public key. Change the publisher's default local path to `ed25519-2026-07b.private`.

- [ ] **Step 3: Complete the public Worker configuration**

Keep `SIGNING_KEY_ID` fixed at `ed25519-2026-07b`; add the provisioned
`ACCESS_TEAM_DOMAIN`, `ACCESS_AUD`, and `ACCESS_COMMON_NAME`. Add one custom
domain route whose `pattern` is `signing.backchannel.page` and whose
`custom_domain` is `true`. Add one Secrets Store binding with binding name
`RELEASE_SIGNING_PRIVATE_KEY`, the consumed 32-lowercase-hex store ID, and
secret name `ed25519-2026-07b`.

Only the public store ID, audience, team domain, client ID, and public key may be written.

- [ ] **Step 4: Update operator documentation**

Document the exact common-name binding, genesis trust root, new break-glass filename, and successful no-release remote proof. Do not document credential values.

- [ ] **Step 5: Run focused validation**

Run:

```powershell
cd release-signing-worker
npm test
npx wrangler deploy --dry-run
cd ..
pwsh -NoProfile -File scripts/tests/test_publish_release_platform.ps1
C:/Users/Houle/.venvs/backchannel312/Scripts/python.exe -m unittest backend.tests.test_update_signing backend.tests.test_build_platform_manifest
```

Expected: Worker, transport, signing, and manifest tests all pass.

- [ ] **Step 6: Commit**

```powershell
git add release-signing-worker/wrangler.jsonc desktop/release_signing_keys.json scripts/publish_release_platform.ps1 scripts/tests/test_publish_release_platform.ps1 docs/releasing.md
git commit -m "feat: cut over release signing"
```

## Controller-only production sequence between Tasks 1 and 2

1. Confirm the reviewed commit, clean worktree, Wrangler identity, account ID, and store ID without printing credentials.
2. Run the ceremony. Its mandatory exact-name list preflight must pass before WebCrypto key generation; capture only the one-line public JSON.
3. Provision the dedicated self-hosted Access application, Service Auth policy, and service token. Store the client ID and secret in the operator environment and protected GitHub `production` environment without printing the secret.
4. Supply only public identifiers and ceremony public output to Task 2.
5. Deploy the reviewed Worker configuration and custom domain.
6. Send one canonical test descriptor through Access and locally verify the detached signature against `desktop/release_signing_keys.json`.
7. Confirm unauthorized requests fail closed and the proof performs no R2 operation.

## Self-review

- Spec coverage: all three review amendments, ceremony/deploy/access cutover, genesis trust update, remote proof, and no-push/no-release boundaries are assigned.
- Placeholder scan: no TBD, TODO, or invented production identifier appears; Task 2 consumes the live public provisioning values through its declared interface.
- Type consistency: `ACCESS_COMMON_NAME` is the Access JWT `common_name`, which Cloudflare documents as the service-token client ID.
