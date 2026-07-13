# Cloudflare-native R2 Publisher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace every AWS CLI dependency in Backchannel release publication with one checked-in Node 24 client that calls Cloudflare R2's official S3-compatible API directly using Cloudflare-issued credentials.

**Architecture:** Add one dependency-free `scripts/r2-object.mjs` transport shared by GitHub Actions and the owner migration script. The client derives the Cloudflare endpoint from `CLOUDFLARE_ACCOUNT_ID`, implements the required SigV4 wire protocol with Node standard-library crypto, streams object bodies, and exposes stable JSON and exit-code contracts. Existing manifest generation, immutable version creation, compare-and-swap Latest updates, and readback verification remain unchanged.

**Tech Stack:** Node.js 24 standard library (`node:crypto`, `node:fs`, `node:stream/promises`), built-in Node test runner, PowerShell 5.1, Python `unittest`, GitHub Actions, Cloudflare R2 S3-compatible API.

## Global Constraints

- Target Backchannel only; do not touch AIEngine or any `Install-AIEngine` material.
- Send object requests only to `https://<CLOUDFLARE_ACCOUNT_ID>.r2.cloudflarestorage.com`; never install or invoke AWS CLI, an AWS SDK, Wrangler object commands, or an upload Worker.
- Read only `CLOUDFLARE_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, and `R2_SECRET_ACCESS_KEY`; these are Cloudflare-issued credentials. Never print credentials, authorization headers, canonical requests, response bodies, or signed URLs.
- The protocol literals `AWS4-HMAC-SHA256`, `AWS4`, `aws4_request`, and `x-amz-*` may appear inside `scripts/r2-object.mjs`, signer tests, and explanatory operations documentation because Cloudflare's S3-compatible wire protocol requires them. They must never identify an AWS tool, SDK, credential, endpoint, account, or service dependency.
- Use path-style object URLs, RFC 3986-encode every bucket/key segment, reject empty keys and `.`/`..` segments, and validate account IDs and bucket names before signing.
- Stream every upload twice: first into SHA-256, then from disk into `fetch` with exact `Content-Length`; never buffer a desktop bundle.
- A download writes to a unique sibling temporary file and renames it over the destination only after the full successful response; remove the temporary file on every failure.
- Preserve `Content-Type`, asset `Content-Disposition`, metadata `Cache-Control: no-store`, `If-None-Match`, and `If-Match` behavior.
- Exit `0` on success, `44` for HTTP 404, `42` for HTTP 412, `2` for CLI/configuration errors, and `1` for every other transport/HTTP failure. Nonzero stderr is one redacted compact JSON object containing only `error` and, when available, `status`.
- Successful stdout is one compact JSON object. `head` returns `{etag,contentLength,contentType}`; `get` returns `{etag,contentLength,contentType,output}`; `put` returns `{etag}`. Missing headers are represented as `null`, and `contentLength` is an integer or `null`.
- Preserve hold commit `57fc8d991b8101a2db5889df16ce5a26078baff2`; do not rebase or squash the rollout.
- Preserve the user's changes in the original checkout and the untracked `docs/admin-interest-workflow.html`.

---

### Task 1: Build the direct Cloudflare R2 object client with TDD

**Files:**
- Create: `scripts/r2-object.mjs`
- Create: `scripts/tests/r2-object.test.mjs`

**Interfaces:**
- Export: `EXIT_NOT_FOUND = 44`, `EXIT_PRECONDITION_FAILED = 42`, `EXIT_USAGE = 2`.
- Export: `buildObjectUrl(accountId, bucket, key) -> URL`.
- Export: `signRequest({method,url,headers,payloadHash,credentials,now}) -> Headers`.
- Export: `createR2Client({env,fetchImpl,now,fsImpl}) -> {head,get,put}`.
- Export: `main(argv, dependencies?) -> Promise<number>`; the module calls it only when executed directly.
- CLI:
  - `node scripts/r2-object.mjs head --bucket <bucket> --key <key>`
  - `node scripts/r2-object.mjs get --bucket <bucket> --key <key> --output <path>`
  - `node scripts/r2-object.mjs put --bucket <bucket> --key <key> --file <path> --content-type <type> [--content-disposition <value>] [--cache-control <value>] [--if-none-match '*'] [--if-match <etag>]`

- [ ] **Step 1: Add failing URL, signer, and CLI validation tests**

Create table-driven tests with fixed account ID `0123456789abcdef0123456789abcdef`, access key `R2TESTACCESS`, secret `r2-test-secret`, and clock `2026-07-12T15:04:05.000Z`. Require the exact Cloudflare host, path `/backchannel-desktop-releases/releases/v0.2.1/Backchannel%20macos.zip`, credential scope `20260712/auto/s3/aws4_request`, sorted signed headers, lowercase SHA-256 payload hashes, and deterministic Authorization output. Also require rejection of malformed account IDs, invalid bucket names, empty/relative key segments, conflicting conditions, missing operation flags, unknown flags, and absent credentials.

```js
test('buildObjectUrl cannot redirect credentials away from Cloudflare', () => {
  const url = buildObjectUrl(
    '0123456789abcdef0123456789abcdef',
    'backchannel-desktop-releases',
    'releases/v0.2.1/Backchannel macos.zip',
  );
  assert.equal(url.origin, 'https://0123456789abcdef0123456789abcdef.r2.cloudflarestorage.com');
  assert.equal(url.pathname, '/backchannel-desktop-releases/releases/v0.2.1/Backchannel%20macos.zip');
});

test('usage errors are distinct from R2 response failures', async () => {
  const stderr = [];
  assert.equal(await main(['head'], {env: CREDENTIALS, stderr: value => stderr.push(value)}), 2);
  assert.deepEqual(JSON.parse(stderr.join('')), {error: 'invalid arguments'});
});
```

- [ ] **Step 2: Run the new test and verify RED**

Run: `node --test scripts/tests/r2-object.test.mjs`

Expected: failure with `ERR_MODULE_NOT_FOUND` for `scripts/r2-object.mjs`.

- [ ] **Step 3: Implement URL construction and SigV4 signing**

Use `encodeURIComponent` plus RFC 3986 escaping for each path segment. Canonicalize lower-case trimmed headers, include `host`, `x-amz-content-sha256`, and `x-amz-date`, and derive the signing key through `AWS4${secret}` -> date -> `auto` -> `s3` -> `aws4_request`. Return a fresh `Headers` containing the Authorization value; never expose canonical/signing intermediates through the CLI.

- [ ] **Step 4: Add failing transport and streaming tests**

Inject `fetchImpl` and temporary files. Cover:

- HEAD normalization and signed Cloudflare-only URL.
- PUT headers for content type, disposition, cache control, exact length, `If-None-Match`, and `If-Match`.
- A multi-chunk file body whose `ReadableStream` is consumed by the fake fetch and matches source bytes.
- GET success preserving the old destination until completion, then atomically replacing it.
- GET stream failure leaving the old destination intact and no sibling temporary file.
- HTTP 404 -> 44, HTTP 412 -> 42, 403/500 -> 1, fetch rejection -> 1.
- Redacted errors containing no credential, Authorization, URL query, or response body text.

```js
test('HTTP status contracts are stable and redacted', async () => {
  for (const [status, expected] of [[404, 44], [412, 42], [403, 1]]) {
    const stderr = [];
    const code = await main(
      ['head', '--bucket', BUCKET, '--key', 'releases/latest.json'],
      {env: CREDENTIALS, fetchImpl: async () => new Response('sensitive vendor prose', {status}), stderr: value => stderr.push(value)},
    );
    assert.equal(code, expected);
    assert.doesNotMatch(stderr.join(''), /sensitive|R2TESTACCESS|r2-test-secret/);
  }
});
```

- [ ] **Step 5: Implement the minimal client and CLI**

Use `createReadStream` for hashing and upload, `Readable.fromWeb` plus `pipeline` for download, `randomUUID()` for the sibling temporary filename, and `rename` only after a complete successful pipeline. Set `duplex: 'half'` for streamed PUT requests. Parse `Content-Length` with a digits-only guard and normalize ETags without stripping their quotes.

- [ ] **Step 6: Run focused verification and commit Task 1**

Run:

```powershell
node --test scripts/tests/r2-object.test.mjs
node scripts/r2-object.mjs head
if ($LASTEXITCODE -ne 2) { throw "Expected usage exit 2" }
git diff --check
```

Expected: Node tests pass, the invalid invocation prints only `{"error":"invalid arguments"}` to stderr and exits 2, and the diff check is silent.

```powershell
git add scripts/r2-object.mjs scripts/tests/r2-object.test.mjs
git commit -m "feat: call Cloudflare R2 API directly"
```

### Task 2: Move the owner migration onto the shared client

**Files:**
- Modify: `scripts/migrate_releases_to_r2.ps1`
- Modify: `scripts/tests/test_migrate_releases_to_r2.ps1`
- Modify: `desktop/tests/test_release_contract.py`

**Interfaces:**
- Replace `Invoke-Aws` with `Invoke-R2([string[]]$Arguments)`.
- `Invoke-R2` runs `node $script:R2Client @Arguments`, captures combined output plus the true native exit code, restores both PowerShell error preferences, and parses JSON only after exit 0.
- `Get-RemoteLatest($Destination)` returns `{Exists,ETag}` and treats only exit 44 as absence.
- `Assert-R2Success($Result,$Action)` rejects every nonzero exit.

- [ ] **Step 1: Change the owner-migration contract tests first and verify RED**

Update `desktop/tests/test_release_contract.py` to require `scripts/r2-object.mjs` in the owner script, require the Cloudflare credential names there, and reject AWS CLI commands, `AWS_DEFAULT_REGION`, `AWS_ACCESS_KEY_ID`, and `Invoke-Aws` in the migration script. Preserve the existing workflow assertions unchanged until Task 3 changes the workflow and its contracts together. Update owner order assertions to locate `$existing = Invoke-R2` and ensure no `put` occurs before `ShouldProcess`.

Run: `python -m unittest desktop.tests.test_release_contract -v`

Expected: failures report the current owner-script AWS CLI configuration and `Invoke-Aws` calls; workflow assertions remain at their pre-Task-3 baseline.

- [ ] **Step 2: Adapt the PowerShell native-process harness and verify RED**

Replace the fake `aws.cmd` with a fake `node.cmd`. Have it ignore its first argument (the client path), emit compact success JSON with a quoted ETag for exit 0, emit redacted JSON and exit 44 for missing, and emit redacted JSON and exit 1 for access denied. Extract and dot-source `Invoke-R2`, `Assert-R2Success`, and `Get-RemoteLatest` from the parsed migration AST. Assert that missing is classified only by code 44, access denied fails closed, JSON is parsed on success, `$ErrorActionPreference` is restored, and no `NativeCommandError` text pollutes stderr.

Run: `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/tests/test_migrate_releases_to_r2.ps1`

Expected: failure because `Invoke-R2` does not exist.

- [ ] **Step 3: Replace every owner-script AWS call**

Set `$script:R2Client = Join-Path $repoRoot 'scripts/r2-object.mjs'` and fail if Node 24+ or the client file is absent. Keep all current validation and `ShouldProcess` placement. Translate calls exactly:

- manifest existence -> `head --bucket $script:Bucket --key $manifestKey`
- asset upload -> `put --bucket $script:Bucket --key $asset.key --file $source --content-type $asset.content_type --content-disposition "attachment; filename=\"$($asset.filename)\""`
- size verification -> `head`, then compare `.Data.contentLength`
- manifest creation -> `put --bucket $script:Bucket --key $manifestKey --file $manifestPath --content-type application/json --cache-control no-store --if-none-match *`
- Latest creation/replacement -> the same `put` shape for `releases/latest.json`, with either `--if-none-match *` or `--if-match $remoteLatest.ETag`
- manifest/latest reads -> `get --bucket $script:Bucket --key $key --output $destination`, taking ETag from `.Data.etag`
- Latest retry -> retry once only when `.Code -eq 42`

Delete endpoint construction, AWS environment aliases, vendor-prose regexes, `Invoke-Aws`, and every `s3`/`s3api` command.

- [ ] **Step 4: Run focused verification and commit Task 2**

Run:

```powershell
node --test scripts/tests/r2-object.test.mjs
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/tests/test_migrate_releases_to_r2.ps1
python -m unittest desktop.tests.test_release_contract -v
rg -n -i "(^|[&|;[:space:]])aws([[:space:]]|$)|AWS_DEFAULT_REGION|AWS_ACCESS_KEY_ID|Invoke-Aws" scripts/migrate_releases_to_r2.ps1
git diff --check
```

Expected: all tests pass; the migration-source search returns no executable AWS CLI call, AWS credential alias, or old adapter; diff check is silent.

```powershell
git add scripts/migrate_releases_to_r2.ps1 scripts/tests/test_migrate_releases_to_r2.ps1 desktop/tests/test_release_contract.py
git commit -m "refactor: migrate releases through Cloudflare R2 client"
```

### Task 3: Move GitHub publication onto the shared client and update operations

**Files:**
- Modify: `.github/workflows/desktop-release.yml`
- Modify: `desktop/tests/test_release_contract.py`
- Modify: `docs/releasing.md`
- Modify: `docs/deployment.md`
- Modify: `AGENTS.md`
- Modify: `CLAUDE.md`

**Interfaces:**
- The `publish` job installs Node 24 with `actions/setup-node@v4` and invokes only `node scripts/r2-object.mjs` for object I/O.
- Each R2 step receives only `CLOUDFLARE_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, and `R2_SECRET_ACCESS_KEY`; `R2_BUCKET` remains the production environment variable.
- Bash branches on exit 44 for absence and exit 42 for one Latest retry; it never parses vendor error prose.

- [ ] **Step 1: Extend workflow contracts and verify RED**

Require a Node 24 setup step in `publish`, at least one `head`, `get`, and `put` invocation through `scripts/r2-object.mjs`, asset `--content-disposition`, metadata `--cache-control no-store`, immutable `--if-none-match '*'`, Latest `--if-match`, explicit `44` absence handling, explicit `42` retry handling, and no AWS CLI command or AWS environment alias. Preserve the existing ordered publication steps and exact two manifest-helper calls.

Run: `python -m unittest desktop.tests.test_release_contract -v`

Expected: failures identify AWS CLI steps and missing direct-client commands.

- [ ] **Step 2: Replace workflow object calls without changing publication order**

Add `actions/setup-node@v4` with `node-version: 24` immediately after checkout in `publish`. Remove `R2_ENDPOINT`, AWS environment variables, AWS credential aliases, and all vendor-prose files/regexes. For expected absence use `set +e`, capture `$?`, restore `set -e`, and accept only 44. For successful GET capture the client's stdout JSON and parse `.etag` using Python's standard-library `json.load(sys.stdin)`. For HEAD size verification parse `.contentLength` the same way. Preserve `cmp` and helper revalidation after manifest readback. On Latest PUT, retry once only when the client exits 42; every other nonzero status fails immediately.

- [ ] **Step 3: Make the Cloudflare-only operating model explicit**

In `docs/releasing.md` and `docs/deployment.md`, describe the writer as Cloudflare R2 API token credentials with S3-compatible access key/secret fields. State that `scripts/r2-object.mjs` calls Cloudflare directly and that `AWS4-HMAC-SHA256`/`x-amz-*` are Cloudflare's required protocol field names, not AWS credentials or services. Add the focused client and PowerShell harness commands to the local release gate. In `AGENTS.md` and `CLAUDE.md`, identify the checked-in client as the sole release object transport and prohibit AWS CLI/SDK publication.

- [ ] **Step 4: Run the full amended source gate**

Run:

```powershell
node --test scripts/tests/r2-object.test.mjs
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/tests/test_migrate_releases_to_r2.ps1
python -m unittest desktop.tests.test_release_manifest desktop.tests.test_release_contract -v
cd docs-site
npm run test:release-access
npm run test:migration
npm run test:worker
npm run test:admin
npm run test:download
npm run test:site
npm run build
cd ..
rg -n -i '(^|[&|;[:space:]])aws([[:space:]]|$)|AWS_DEFAULT_REGION|AWS_ACCESS_KEY_ID|Invoke-Aws|@aws-sdk' .github/workflows/desktop-release.yml scripts/migrate_releases_to_r2.ps1 AGENTS.md CLAUDE.md
git diff --check
git status --short
```

Expected: all Node, PowerShell, Python, Worker, UI, and build gates pass; the scoped search returns no executable AWS CLI/SDK dependency, AWS credential alias, or old adapter while required Cloudflare protocol names remain allowed; only intended files are modified.

- [ ] **Step 5: Commit Task 3**

```powershell
git add .github/workflows/desktop-release.yml desktop/tests/test_release_contract.py docs/releasing.md docs/deployment.md AGENTS.md CLAUDE.md
git commit -m "ci: publish releases directly to Cloudflare R2"
```

### Task 4: Review, integrate, and resume the production gate

**Files:**
- Modify only if review exposes a defect, always after a failing regression test.

- [ ] **Step 1: Request a correctness and scope review**

Review the complete delta from `246402a` through Task 3 for signing correctness, streaming behavior, temp-file cleanup, secret redaction, 404/412 handling, PowerShell 5.1 exit-code behavior, workflow race safety, and absence of AWS tooling. Fix each confirmed defect with a failing test and a separate commit.

- [ ] **Step 2: Merge the amendment into the local rollout master**

Merge `agent/r2-release-access-impl` into the local rollout worktree with a merge commit. Verify both design commit `246402a` and hold commit `57fc8d991b8101a2db5889df16ce5a26078baff2` are ancestors. Do not squash or rebase.

- [ ] **Step 3: Re-run the complete rollout gate on the merged tree**

Repeat Task 3 Step 4 from the merged master worktree and verify a clean tree. Stop on any failure.

- [ ] **Step 4: Continue production acceptance without restarting completed provisioning**

Push merged `master`, wait for the Site workflow, and verify the deployed branch still contains the hold. Then run the historical migration in version order with the already-staged local assets and existing Cloudflare-issued `cloudflare-issues` R2 credentials. Verify every uploaded object's size/hash and each manifest before advancing Latest. Delete the temporary local credential file only after migration verification succeeds.

Continue the remaining approved release-access gate from its current state: Cloudflare Access activation/configuration, deployed PBKDF2 benchmark, live account/download acceptance, and finally the exact hold-commit revert for customer-link cutover. Any new billing activation or irreversible external action still requires its own explicit approval.

## Self-review record

- Spec coverage: direct Cloudflare endpoint, standard-library SigV4, all three object operations, stable JSON/exits, streaming PUT/GET, atomic destination replacement, conditional writes, PowerShell migration, workflow migration, redaction, and complete regression gates map to Tasks 1-4.
- Placeholder scan: no deferred TODO/TBD, pseudocode-only implementation step, or unresolved file name remains; angle-bracketed CLI operands are explicit interface notation.
- Conflict resolution: the user approved allowing Cloudflare-required `AWS4`/`x-amz-*` wire-protocol names in the client, signer tests, and explanatory docs while prohibiting AWS tools, SDKs, credentials, endpoints, accounts, and services; verification searches are scoped accordingly.
- Sequencing resolution: Task 2 changes only owner-migration contracts and implementation; workflow assertions and implementation move together in Task 3 so every task ends GREEN.
- Type consistency: `etag`, `contentLength`, `contentType`, `output`, exit 44, and exit 42 are identical across Node, PowerShell, Bash, and tests.
- Scope check: the amendment adds one transport file and one test file, replaces two callers, and updates their contracts/runbooks; it introduces no package, service, SDK, Worker, or storage provider.
- Planning decision: the existing release-access plan does not restart. Completed production provisioning remains valid; only the publication transport and its downstream verification are amended before the live catalog write.
