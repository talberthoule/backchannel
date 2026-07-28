# ALP-173 Remote Release Signing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a minimal Access-protected Cloudflare signing Worker and make remote Ed25519 signing the fail-closed desktop publication path.

**Architecture:** Python remains the sole owner of platform-manifest construction and canonical descriptor bytes. PowerShell sends those bytes to a dedicated Worker, receives a detached signature, and asks Python to verify and attach it before any R2 request. Stage two uses fixture keys only; stage three creates the production key in Secrets Store and commits its public half before the `v0.4.0` tag.

**Tech Stack:** Python 3.12, PowerShell 7, Node.js 24, Cloudflare Workers WebCrypto, Secrets Store, Cloudflare Access, `jose`, stdlib `unittest` and `node:test`.

## Global Constraints

- Work only in `C:/work/backchannel/alp-173` on `agent/alp-173-remote-signing`.
- Do not push.
- Never echo, log, persist, or pass production private-key material in an argument.
- Stage two performs no Cloudflare provisioning, key ceremony, deployment, cutover, or tagging.
- `v0.4.0` is the genesis update-channel release and will trust only `ed25519-2026-07b`.
- Do not change `desktop/release_signing_keys.json` until stage three supplies the real public key.
- Remote signing is the default; local signing is explicit break-glass only with no automatic fallback.
- Verify a detached signature locally before the first R2 operation.
- `scripts/r2-object.mjs` remains the sole release-object transport.

## File map

- `backend/app/services/update_signing.py`: shared canonical request and detached-signature attachment.
- `desktop/scripts/build_platform_manifest.py`: request-output, detached-input, and explicit local signing modes.
- `release-signing-worker/src/index.mjs`: Access authorization, request validation, Secrets Store read, WebCrypto signature.
- `release-signing-worker/scripts/create-signing-key.mjs`: stage-three no-disk key ceremony.
- `scripts/publish_release_platform.ps1`: remote HTTP transport and explicit local break-glass selection.
- `.github/workflows/desktop-release.yml`: protected macOS publication credentials and remote mode.
- `docs/releasing.md`: operator ceremony, remote publication, future rotation, and break-glass procedure.

---

### Task 1: Shared detached-signature contract

**Files:**
- Modify: `backend/app/services/update_signing.py`
- Modify: `backend/tests/test_update_signing.py`

**Interfaces:**
- Produces: `platform_signing_request(manifest: dict, key_id: str) -> tuple[dict, bytes]`
- Produces: `attach_platform_signature(manifest: dict, key_id: str, signature: str, public_key: bytes) -> dict`
- Preserves: `sign_platform_manifest(manifest: dict, key_id: str, private_key: bytes) -> dict`

- [ ] **Step 1: Write failing detached-signature tests**

```python
descriptor, request = platform_signing_request(MANIFEST, "test-key")
signature = Ed25519PrivateKey.from_private_bytes(PRIVATE).sign(request)
encoded = base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")
signed = attach_platform_signature(
    MANIFEST, "test-key", encoded, PUBLIC
)
self.assertEqual(public_update_descriptor(signed) | {"signature": None},
                 descriptor | {"signature": None})
```

Also assert that a malformed signature, wrong public key, tampered manifest,
invalid key ID, and extra manifest field each raise `ValueError`.

- [ ] **Step 2: Run the focused test and confirm RED**

Run: `C:/Users/Houle/.venvs/backchannel312/Scripts/python.exe -m unittest tests.test_update_signing`

Expected: import failure for `platform_signing_request` and
`attach_platform_signature`.

- [ ] **Step 3: Implement the smallest shared path**

```python
def platform_signing_request(manifest: dict, key_id: str) -> tuple[dict, bytes]:
    unsigned = _validated_platform_manifest(manifest)
    signed = copy.deepcopy(unsigned)
    signed["update"] = {"key_id": key_id, "schema": 1}
    descriptor = _public_from_manifest(signed, include_signature=False)
    return descriptor, canonical_update_bytes(descriptor)


def attach_platform_signature(
    manifest: dict, key_id: str, signature: str, public_key: bytes
) -> dict:
    descriptor, request = platform_signing_request(manifest, key_id)
    Ed25519PublicKey.from_public_bytes(public_key).verify(
        _decode_signature(signature), request
    )
    signed = copy.deepcopy(manifest)
    signed["update"] = {"key_id": key_id, "schema": 1, "signature": signature}
    return signed
```

Refactor local signing to call the same validator and descriptor builder.

- [ ] **Step 4: Run the focused test and confirm GREEN**

Run: `C:/Users/Houle/.venvs/backchannel312/Scripts/python.exe -m unittest tests.test_update_signing`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/services/update_signing.py backend/tests/test_update_signing.py
git commit -m "feat: support detached release signatures"
```

### Task 2: Python request and detached CLI modes

**Files:**
- Modify: `desktop/scripts/build_platform_manifest.py`
- Modify: `desktop/tests/test_platform_release_manifest.py`

**Interfaces:**
- Produces: `--signing-request-out <path>` without reading a private key.
- Produces: `--detached-key-id <id> --detached-signature <base64url>`.
- Preserves: local signing when neither remote-only option is present.

- [ ] **Step 1: Write failing CLI tests**

```python
request_result = subprocess.run(
    [
        sys.executable, str(CLI), "--asset", str(asset),
        "--platform-id", "linux-x64", "--tag", TAG, "--commit", COMMIT,
        "--published-at", PUBLISHED_AT, "--keys-file", str(keys_file),
        "--release-notes-file", str(notes_file),
        "--signing-request-out", str(request_out),
    ],
    cwd=ROOT,
    env={key: value for key, value in os.environ.items()
         if key != "BACKCHANNEL_RELEASE_SIGNING_PRIVATE_KEY"},
    capture_output=True,
    text=True,
)
self.assertEqual(request_result.returncode, 0)
self.assertEqual(request_out.read_bytes(), canonical_update_bytes(expected))
self.assertFalse(platform_out.exists())
```

Sign the request with the fixture private key, invoke detached mode, and assert
the output equals local mode. Assert invalid signatures and missing option
pairs create no release or platform output.

- [ ] **Step 2: Run the focused test and confirm RED**

Run: `C:/Users/Houle/.venvs/backchannel312/Scripts/python.exe -m unittest desktop.tests.test_platform_release_manifest`

Expected: argparse rejects the new options.

- [ ] **Step 3: Implement mutually exclusive output modes**

```python
parser.add_argument("--signing-request-out", type=Path)
parser.add_argument("--detached-key-id")
parser.add_argument("--detached-signature")
```

Build release inputs once. Request mode writes only canonical bytes. Detached
mode calls `attach_platform_signature` with the active checked-in public key.
Local mode retains the current private/public match check. Validate mode and
output combinations before writing any file.

- [ ] **Step 4: Run the focused tests and confirm GREEN**

Run: `C:/Users/Houle/.venvs/backchannel312/Scripts/python.exe -m unittest desktop.tests.test_platform_release_manifest backend.tests.test_update_signing`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add desktop/scripts/build_platform_manifest.py desktop/tests/test_platform_release_manifest.py
git commit -m "feat: add detached manifest signing flow"
```

### Task 3: Minimal signing Worker

**Files:**
- Create: `release-signing-worker/package.json`
- Create: `release-signing-worker/package-lock.json`
- Create: `release-signing-worker/wrangler.jsonc`
- Create: `release-signing-worker/src/index.mjs`
- Create: `release-signing-worker/test/index.test.mjs`

**Interfaces:**
- Consumes: canonical descriptor bytes no larger than 16 KiB.
- Consumes: `SIGNING_KEY_ID`, `ACCESS_TEAM_DOMAIN`, `ACCESS_AUD`, and `RELEASE_SIGNING_PRIVATE_KEY.get()`.
- Produces: exact JSON `{ "key_id": string, "signature": string }`.

- [ ] **Step 1: Write failing Worker boundary tests**

```javascript
const pair = await crypto.subtle.generateKey("Ed25519", true, ["sign", "verify"]);
const pkcs8 = new Uint8Array(await crypto.subtle.exportKey("pkcs8", pair.privateKey));
const descriptor = {
  asset: {
    filename: "Backchannel-windows-x64.zip",
    id: "windows-x64",
    platform: "Windows x64",
    sha256: "a".repeat(64),
    size: 7,
  },
  commit: "b".repeat(40),
  key_id: "fixture-key",
  published_at: "2026-07-26T18:00:00Z",
  release_notes: "Fixture release.",
  schema: 1,
  version: "v1.2.3",
};
const canonicalBytes = new TextEncoder().encode(JSON.stringify(descriptor));
const env = {
  SIGNING_KEY_ID: "fixture-key",
  RELEASE_SIGNING_PRIVATE_KEY: {
    get: async () => Buffer.from(pkcs8).toString("base64url"),
  },
};
const request = new Request("https://signing.example/v1/sign", {
  method: "POST",
  headers: { "content-type": "application/json" },
  body: canonicalBytes,
});
const response = await handleRequest(request, env, {
  verifyAccess: async () => {},
});
assert.equal(response.status, 200);
const result = await response.json();
assert.equal(result.key_id, "fixture-key");
assert.equal(
  await crypto.subtle.verify(
    "Ed25519", pair.publicKey,
    Buffer.from(result.signature, "base64url"), canonicalBytes,
  ),
  true,
);
```

Cover exact Access issuer/audience verification, missing assertion,
method/path/content type, 16 KiB limit, strict UTF-8, canonical byte equality,
exact descriptor fields, schema/key ID, secret-read ordering, real WebCrypto
verification, response headers, and generic errors without fixture leakage.

- [ ] **Step 2: Run the Worker test and confirm RED**

Run: `cd release-signing-worker; npm test`

Expected: module or exported handler is missing.

- [ ] **Step 3: Implement the handler**

```javascript
const key = await crypto.subtle.importKey(
  "pkcs8",
  decodeBase64Url(await env.RELEASE_SIGNING_PRIVATE_KEY.get()),
  { name: "Ed25519" },
  false,
  ["sign"],
);
const signature = await crypto.subtle.sign("Ed25519", key, body);
```

Reuse the `docs-site/worker.js` Access JWT pattern with `jose`. Read a bounded
body only after authorization, validate exact descriptor constraints, require
canonical re-encoding byte equality, zero the decoded PKCS#8 buffer in
`finally`, and return only generic errors. Add no R2 binding and no console
logging.

- [ ] **Step 4: Add the stage-two base Wrangler config**

```jsonc
{
  "name": "backchannel-release-signer",
  "main": "src/index.mjs",
  "compatibility_date": "2026-07-28",
  "compatibility_flags": ["nodejs_compat"],
  "workers_dev": false,
  "preview_urls": false,
  "vars": { "SIGNING_KEY_ID": "ed25519-2026-07b" },
  "observability": { "enabled": true }
}
```

Do not invent the stage-three Access audience, store ID, or secret name.

- [ ] **Step 5: Install the pinned dependencies and run checks**

Run: `cd release-signing-worker; npm install --save-exact jose; npm install --save-dev --save-exact wrangler; npm test; npx wrangler deploy --dry-run --outdir .wrangler-dry-run`

Expected: tests and dry-run build pass; remove the untracked dry-run directory
after inspection.

- [ ] **Step 6: Commit**

```powershell
git add release-signing-worker
git commit -m "feat: add protected release signing worker"
```

### Task 4: No-disk key ceremony

**Files:**
- Create: `release-signing-worker/scripts/create-signing-key.mjs`
- Create: `release-signing-worker/test/create-signing-key.test.mjs`

**Interfaces:**
- Consumes: `CLOUDFLARE_ACCOUNT_ID`, `BACKCHANNEL_RELEASE_SIGNING_STORE_ID`, and captured `wrangler auth token --json`.
- Produces: stdout JSON containing only `key_id` and `public_key`.
- Sends: a Secrets Store create request for `ed25519-2026-07b` with `workers` scope.

- [ ] **Step 1: Write the failing ceremony test**

```javascript
const output = [];
let captured;
const fixturePair = await crypto.subtle.generateKey(
  "Ed25519", true, ["sign", "verify"]
);
await runCeremony({
  accountId: "account",
  storeId: "store",
  authToken: async () => "fixture-token",
  generateKeyPair: async () => fixturePair,
  fetchImpl: async (url, init) => {
    captured = { url, init };
    return new Response("{}", { status: 200 });
  },
  writeOutput: value => output.push(value),
});
assert.deepEqual(Object.keys(JSON.parse(output[0])).sort(),
                 ["key_id", "public_key"]);
assert.match(captured.url, /^https:/);
```

Assert the private fixture appears only in the captured HTTPS request body,
never stdout/stderr, argv, or a written file; assert non-HTTPS and non-2xx
responses fail without printing an API body.

- [ ] **Step 2: Run the ceremony test and confirm RED**

Run: `cd release-signing-worker; node --test test/create-signing-key.test.mjs`

Expected: module is missing.

- [ ] **Step 3: Implement the one-shot script**

```javascript
const pair = await crypto.subtle.generateKey("Ed25519", true, ["sign", "verify"]);
const privateBytes = new Uint8Array(
  await crypto.subtle.exportKey("pkcs8", pair.privateKey)
);
```

Capture `wrangler auth token --json` with `execFile` pipes, POST the unpadded
base64url PKCS#8 directly to the account Secrets Store API, print only the
public JSON after success, and best-effort zero mutable buffers in `finally`.

- [ ] **Step 4: Run all Worker tests and confirm GREEN**

Run: `cd release-signing-worker; npm test`

Expected: all tests pass and output contains no fixture private value.

- [ ] **Step 5: Commit**

```powershell
git add release-signing-worker/scripts release-signing-worker/test
git commit -m "feat: add in-memory signing key ceremony"
```

### Task 5: Remote PowerShell publisher and macOS contract

**Files:**
- Modify: `scripts/publish_release_platform.ps1`
- Modify: `scripts/tests/test_publish_release_platform.ps1`
- Modify: `.github/workflows/desktop-release.yml`
- Modify: `desktop/tests/test_release_contract.py`

**Interfaces:**
- Consumes: `-SigningMode Remote|Local`, default `Remote`.
- Remote consumes: `BACKCHANNEL_RELEASE_SIGNING_URL`, `CLOUDFLARE_ACCESS_CLIENT_ID`, and `CLOUDFLARE_ACCESS_CLIENT_SECRET`.
- Local consumes: existing private-key environment/file source only after explicit `Local`.

- [ ] **Step 1: Write failing transport and workflow tests**

```powershell
$signerCapture = Join-Path $temporary "signer-capture.json"
$clientId = "fixture-client-id"
$clientSecret = "fixture-client-secret"
$fixturePrivate = "fixture-private-value"
$output = & powershell -NoProfile -ExecutionPolicy Bypass -File $publisher `
    -Version $Version -Commit $Commit -PublishedAt $PublishedAt `
    -PlatformId windows-x64 -AssetPath (New-Asset) `
    -SigningMode Remote -Confirm:$false 2>&1
Assert-True ($LASTEXITCODE -eq 0) "Remote publisher failed"
$captured = Get-Content -Raw $signerCapture | ConvertFrom-Json
Assert-True ($captured.client_id -eq $clientId) "Wrong Access client ID"
Assert-True ($captured.client_secret -eq $clientSecret) "Wrong Access secret"
foreach ($secret in @($clientId, $clientSecret, $fixturePrivate)) {
    Assert-True (($output -join "`n") -notmatch [regex]::Escape($secret)) `
        "Publisher leaked a fixture secret"
}
```

Cover remote success, timeout, 401, malformed JSON, extra response field, wrong
key ID, invalid signature, and zero R2 calls on every failure. Keep one explicit
local-mode fixture test.

- [ ] **Step 2: Run the transport and contract tests and confirm RED**

Run: `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/tests/test_publish_release_platform.ps1`

Run: `C:/Users/Houle/.venvs/backchannel312/Scripts/python.exe -m unittest desktop.tests.test_release_contract`

Expected: missing remote mode and old macOS secret assertions fail.

- [ ] **Step 3: Implement remote signing before R2**

```powershell
$client.DefaultRequestHeaders.Add("CF-Access-Client-Id", $accessClientId)
$client.DefaultRequestHeaders.Add("CF-Access-Client-Secret", $accessClientSecret)
$response = $client.PostAsync($signingUri, $content).GetAwaiter().GetResult()
```

Require HTTPS except loopback tests, use a finite timeout, parse an exact
two-field response, compare the key ID, and call Python detached mode. Keep
local key loading inside the explicit local branch. Dispose HTTP and temporary
resources in `finally`.

- [ ] **Step 4: Change protected macOS publication to remote**

Replace the private-key secret with the endpoint and Access service-token
secrets, and pass `-SigningMode Remote`. Keep the build job credential-free.

- [ ] **Step 5: Run transport and contract tests and confirm GREEN**

Run: `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/tests/test_publish_release_platform.ps1`

Run: `C:/Users/Houle/.venvs/backchannel312/Scripts/python.exe -m unittest desktop.tests.test_release_contract desktop.tests.test_platform_release_manifest`

Expected: all tests pass.

- [ ] **Step 6: Commit**

```powershell
git add scripts/publish_release_platform.ps1 scripts/tests/test_publish_release_platform.ps1 .github/workflows/desktop-release.yml desktop/tests/test_release_contract.py
git commit -m "feat: publish releases through remote signer"
```

### Task 6: Operator documentation and stage-two gates

**Files:**
- Modify: `docs/releasing.md`
- Modify: `docs/superpowers/specs/2026-07-28-alp-173-remote-signing.md`
- Create: `docs/superpowers/plans/2026-07-28-alp-173-remote-signing.md`

**Interfaces:**
- Documents: stage-three ceremony, genesis trust-file replacement, remote env,
  future two-release rotation, and explicit future-emergency local mode.

- [ ] **Step 1: Update release operations**

Document that `v0.4.0` ships only `ed25519-2026-07b`, stage three runs the
ceremony before tagging, all production publishing is remote, the old private
file deletion is tracked on ALP-170, and the local mode has no stored key and
requires an approved emergency rotation.

- [ ] **Step 2: Run the complete stage-two gates**

```powershell
Push-Location release-signing-worker
npm test
npx wrangler deploy --dry-run --outdir (Join-Path $env:TEMP "alp173-worker-dry-run")
Pop-Location
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/tests/test_publish_release_platform.ps1
C:/Users/Houle/.venvs/backchannel312/Scripts/python.exe -m unittest desktop.tests.test_platform_release_manifest desktop.tests.test_release_contract
Push-Location backend
C:/Users/Houle/.venvs/backchannel312/Scripts/python.exe -m unittest discover -s tests
Pop-Location
git diff --check
```

Expected: Worker, transport, focused Python, release contract, and backend
suites pass with no errors.

- [ ] **Step 3: Inspect the entire diff for secret and scope violations**

Run: `git diff --check; git status --short; git diff --stat; rg -n "PRIVATE KEY|ed25519-2026-07b.*private" -- . ':!docs/superpowers/specs/*'`

Expected: no production private key, placeholder resource ID, R2 Worker
binding, production-key file change, or unrelated edit.

- [ ] **Step 4: Commit documentation and final stage-two state**

```powershell
git add docs/releasing.md docs/superpowers/specs/2026-07-28-alp-173-remote-signing.md docs/superpowers/plans/2026-07-28-alp-173-remote-signing.md
git commit -m "docs: define remote signing operations"
```

- [ ] **Step 5: Record and hand off**

Add a Linear comment with attribution, branch, commits, changed behavior, exact
gate counts/results, and explicit confirmation of no provisioning, ceremony,
production key, trust-file change, tag, push, or local production signing.
Send the Linear comment ID and branch tip to shepherd pane `w1:pP` for review.
