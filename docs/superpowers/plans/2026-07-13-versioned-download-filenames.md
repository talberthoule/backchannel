# Versioned Download Filenames Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Append the release version to every locally downloaded desktop archive without renaming immutable R2 objects or manifests.

**Architecture:** Keep the catalog and R2 object names unchanged. At the shared authenticated download response boundary, insert the already-validated manifest version before `.zip` or `.tar.gz` in the `Content-Disposition` filename; all full and ranged responses use that one header path.

**Tech Stack:** Cloudflare Workers, JavaScript, Node.js built-in test runner, Cloudflare R2 binding.

## Global Constraints

- Produce `Backchannel-windows-x64-vX.Y.Z.zip`, `Backchannel-macos-arm64-vX.Y.Z.zip`, and `Backchannel-linux-x64-vX.Y.Z.tar.gz` download names.
- Do not rename, migrate, re-upload, or mutate R2 objects, object metadata, release manifests, catalog responses, or portal display text.
- Preserve authorization, entitlements, streaming, range requests, conditional requests, cache headers, content types, ETags, and audit events.
- Use only the existing Worker response path and JavaScript standard library; add no dependency or abstraction.
- Use Cloudflare R2 only; do not invoke an AWS CLI, SDK, account, endpoint, or storage service.
- Preserve hold commit `57fc8d991b8101a2db5889df16ce5a26078baff2`.

---

### Task 1: Derive Versioned Attachment Names at the Response Boundary

**Files:**
- Modify: `docs-site/worker.test.js:1446-1527,1598-1635`
- Modify: `docs-site/worker.js:690-699,884-886`

**Interfaces:**
- Consumes: trusted `asset.filename`, trusted `manifest.version`, the existing `objectHeaders(...)` response-header builder, and the existing authenticated R2 download route.
- Produces: `Content-Disposition: attachment; filename="<asset-base>-<version><archive-extension>"` on full and ranged downloads.

- [ ] **Step 1: Write the failing Worker test**

Update the release fixture so one trusted asset can be selected without changing the existing default:

```js
const defaultReleaseAsset = {
  id: 'windows-x64',
  platform: 'Windows x64',
  filename: 'Backchannel-windows-x64.zip',
  content_type: 'application/zip',
};

function releaseManifest(version, size = 100, asset = defaultReleaseAsset) {
  return {
    version,
    published_at: version === 'v2.0.0' ? '2026-07-12T18:00:00Z' : '2026-06-01T18:00:00Z',
    commit: 'a'.repeat(40),
    assets: [{
      ...asset,
      key: `releases/${version}/${asset.filename}`,
      size,
      sha256: 'b'.repeat(64),
    }],
  };
}
```

Add this property after `malformed = false` in the `releaseBucket(...)` options:

```js
asset = defaultReleaseAsset,
```

Replace the fixture's manifest map with:

```js
const manifests = new Map([
  ['v1.0.0', releaseManifest('v1.0.0', 100, asset)],
  ['v2.0.0', releaseManifest('v2.0.0', 100, asset)],
]);
```

Replace `assetCalls(...)` with:

```js
function assetCalls(bucket, filename = defaultReleaseAsset.filename) {
  return bucket.calls.filter(({ operation, key }) => (
    operation === 'get' && key?.endsWith(filename)
  ));
}
```

Then add the behavior test:

```js
test('download filenames append version before archive extensions', async () => {
  const cases = [
    [{
      id: 'windows-x64', platform: 'Windows x64',
      filename: 'Backchannel-windows-x64.zip', content_type: 'application/zip',
    }, 'Backchannel-windows-x64-v1.0.0.zip'],
    [{
      id: 'macos-arm64', platform: 'macOS arm64',
      filename: 'Backchannel-macos-arm64.zip', content_type: 'application/zip',
    }, 'Backchannel-macos-arm64-v1.0.0.zip'],
    [{
      id: 'linux-x64', platform: 'Linux x64',
      filename: 'Backchannel-linux-x64.tar.gz', content_type: 'application/gzip',
    }, 'Backchannel-linux-x64-v1.0.0.tar.gz'],
  ];

  for (const [asset, expected] of cases) {
    const body = new ReadableStream();
    const bucket = releaseBucket({
      asset,
      object: async () => ({ body, size: 100, httpEtag: '"object-etag"' }),
    });
    const response = await workerModule.route(
      releaseGet(`/api/download/releases/v1.0.0/${asset.id}`),
      releaseBindings(bucket).env, undefined, downloadDependencies(),
    );
    assert.equal(response.status, 200, asset.id);
    assert.equal(response.headers.get('content-disposition'),
      `attachment; filename="${expected}"`, asset.id);
    assert.equal(response.body, body, asset.id);
    assert.equal(assetCalls(bucket, asset.filename).length, 1, asset.id);
  }
});
```

- [ ] **Step 2: Run the focused test and verify RED**

Run from `docs-site/`:

```powershell
node --test --test-name-pattern="download filenames append version" worker.test.js
```

Expected: FAIL because the header still returns the manifest filename without `-v1.0.0`.

- [ ] **Step 3: Implement the minimum response-only change**

Pass the manifest version into the existing shared header builder and use standard `String.prototype.replace`:

```js
function objectHeaders(asset, version, object, length, contentRange) {
  const headers = new Headers(DOWNLOAD_HEADERS);
  headers.set('accept-ranges', 'bytes');
  headers.set('content-disposition',
    `attachment; filename="${asset.filename.replace(/(\.tar\.gz|\.zip)$/, `-${version}$1`)}"`);
  headers.set('content-length', String(length));
  headers.set('content-type', asset.content_type);
  const etag = quotedEtag(object.httpEtag);
  if (etag) headers.set('etag', etag);
  if (contentRange) headers.set('content-range', contentRange);
  return headers;
}
```

Change the only caller:

```js
const headers = objectHeaders(asset, manifest.version, object, length, range?.contentRange);
```

- [ ] **Step 4: Run focused and complete verification**

Run from `docs-site/`:

```powershell
node --test --test-name-pattern="download filenames append version" worker.test.js
npm run test:release-access
npm run test:migration
npm run test:worker
npm run test:admin
npm run test:download
npm run test:site
npm run build
npx wrangler deploy --dry-run
```

Expected: focused test PASS; all docs-site tests PASS; build and dry-run deploy succeed without warnings or binding changes.

- [ ] **Step 5: Commit the verified behavior**

```powershell
git add -- docs-site/worker.js docs-site/worker.test.js
git diff --cached --check
git commit -m "feat: version downloaded release filenames"
```

Expected: one production file and one test file committed; no manifest, R2, UI, or dependency changes.

---

### Task 2: Deploy and Verify the Production Headers

**Files:**
- No file changes.

**Interfaces:**
- Consumes: the green `master` commit, the existing Site GitHub Actions workflow, the authenticated downloads portal, and current immutable R2 release objects.
- Produces: production attachment headers containing the requested version suffix for all three platform assets.

- [ ] **Step 1: Push the verified commit**

```powershell
git push origin master
```

Expected: `origin/master` advances to the versioned-filename commit and starts the existing Site workflow.

- [ ] **Step 2: Wait for the Site workflow and Cloudflare deployment**

Confirm the workflow for the pushed commit completes successfully and the new Worker version receives 100% production traffic. Do not manually upload or mutate any R2 object.

- [ ] **Step 3: Probe each authenticated download with a one-byte range**

In the signed-in downloads portal, issue same-origin requests without exposing session data:

```js
const cases = [
  ['windows-x64', 'Backchannel-windows-x64-v0.2.1.zip'],
  ['macos-arm64', 'Backchannel-macos-arm64-v0.2.1.zip'],
  ['linux-x64', 'Backchannel-linux-x64-v0.2.1.tar.gz'],
];

for (const [asset, filename] of cases) {
  const response = await fetch(`/api/download/releases/v0.2.1/${asset}`, {
    credentials: 'same-origin',
    headers: { Range: 'bytes=0-0' },
  });
  console.assert(response.status === 206, asset);
  console.assert(response.headers.get('content-range')?.startsWith('bytes 0-0/'), asset);
  console.assert(response.headers.get('content-disposition') ===
    `attachment; filename="${filename}"`, asset);
  await response.body?.cancel();
}
```

Expected: all three requests return `206`, preserve range semantics, and expose the exact versioned attachment filename.

- [ ] **Step 4: Confirm repository and rollout state**

```powershell
git status --short --branch
git merge-base --is-ancestor 57fc8d991b8101a2db5889df16ce5a26078baff2 origin/master
```

Expected: the worktree is clean and synchronized with `origin/master`; the hold commit remains an ancestor and is not reverted.
