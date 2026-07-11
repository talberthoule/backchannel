# Private Interest Admin and Release Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Build a secure read-only admin page for D1 interest records and leave Backchannel ready to build its site, Docker images, and Linux/macOS/Windows desktop bundles.

**Architecture:** The existing Cloudflare Worker serves admin.backchannel.page, verifies every Cloudflare Access JWT and exact ADMIN_EMAIL match, and exposes one prepared D1 read endpoint. Static HTML, CSS, and JavaScript render the result without a framework. Existing desktop packaging gains one Linux matrix target while Docker remains source-built.

**Tech Stack:** Cloudflare Workers and D1, jose, HTML/CSS/vanilla JavaScript, Node test runner, PyInstaller, GitHub Actions, Docker Compose.

## Global Constraints

- admin.backchannel.page is the only hostname that serves the private page or read API.
- ADMIN_EMAIL, ACCESS_TEAM_DOMAIN, and ACCESS_AUD are Worker secrets and never enter Git.
- The API is read-only and returns only the eight existing interest_subscribers columns, newest first.
- Every private response is fail-closed, no-store, and free of subscriber/token/configuration logging.
- No status editing, export, search, pagination, passwords, roles, or second Worker.
- Linux ships as Backchannel-linux-x64.tar.gz; do not add MSI, DMG, DEB, RPM, signing, or a registry.
- Do not create a tag, push, deploy, publish artifacts, or change installer visibility.

---

### Task 1: Worker authorization and read-only D1 API

**Files:**
- Modify: docs-site/worker.test.js
- Modify: docs-site/worker.js
- Modify: docs-site/package.json
- Modify: docs-site/package-lock.json

**Interfaces:**
- Consumes: ADMIN_EMAIL, ACCESS_TEAM_DOMAIN, ACCESS_AUD, INTEREST_DB, ASSETS, and Cf-Access-Jwt-Assertion.
- Produces: route(request, env, verify), authorizeAdmin(request, env, verify), verifyAccessToken(token, env), and handleAdminInterests(request, env).

- [ ] **Step 1: Write failing route tests**

Add requests for https://admin.backchannel.page, complete fake bindings, and an injected verifier. Cover missing configuration, missing assertion, verifier rejection, wrong email, normalized exact email, newest-first SQL, D1 failure redaction, 405 with Allow: GET, private 404, public /admin denial, security headers, and explicit asset mapping.

Representative authorization assertion:

    const allowed = await route(
      adminRequest(),
      env,
      async () => ({ email: ' OWNER@EXAMPLE.COM ' }),
    );
    assert.equal(allowed.status, 200);
    assert.match(calls[0].sql, /ORDER BY created_at DESC/);
    assert.deepEqual(await allowed.json(), { items: records });

- [ ] **Step 2: Run RED**

From docs-site:

    node --test worker.test.js

Expected: failure because route and private-host behavior do not exist.

- [ ] **Step 3: Install the official JWT dependency**

From docs-site:

    npm install jose

Expected: jose appears under dependencies and in package-lock.json.

- [ ] **Step 4: Implement the security boundary**

Import createRemoteJWKSet and jwtVerify from jose. Define:

    const ADMIN_HOST = 'admin.backchannel.page';
    const ADMIN_API_PATH = '/api/admin/interests';
    const ADMIN_ASSETS = new Map([
      ['/', '/admin/index.html'],
      ['/index.html', '/admin/index.html'],
      ['/admin.css', '/admin/admin.css'],
      ['/admin.js', '/admin/admin.js'],
    ]);

verifyAccessToken must accept only a hostname ending in .cloudflareaccess.com, fetch that issuer's /cdn-cgi/access/certs JWKS, and call jwtVerify with the exact issuer and ACCESS_AUD.

authorizeAdmin must:

1. Return generic 503 when any Access setting is absent.
2. Return generic 401 when the assertion is absent or verification fails.
3. Normalize the payload email and ADMIN_EMAIL with trim and lowercase.
4. Return null only on exact equality; otherwise return generic 403.

route must handle the private hostname before public routes, authorize every private request, call handleAdminInterests for the exact API path, serve only ADMIN_ASSETS through ASSETS.fetch, and return private 404 otherwise. The public host must return 404 for /admin and /admin/*.

handleAdminInterests must allow only GET and execute this fixed prepared statement with all():

    SELECT email, status, source, consent_version, consent_at, created_at,
           invited_at, last_contacted_at
    FROM interest_subscribers
    ORDER BY created_at DESC

Private responses must set Cache-Control: no-store plus:

    Content-Security-Policy:
      default-src 'none'; script-src 'self'; style-src 'self';
      connect-src 'self'; img-src 'self'; base-uri 'none';
      form-action 'none'; frame-ancestors 'none'
    Referrer-Policy: no-referrer
    X-Content-Type-Options: nosniff
    X-Frame-Options: DENY

- [ ] **Step 5: Run GREEN**

    node --test worker.test.js

Expected: existing signup tests and new private-admin tests pass.

- [ ] **Step 6: Commit**

    git add docs-site/worker.js docs-site/worker.test.js docs-site/package.json docs-site/package-lock.json
    git commit -m "feat: secure private interest admin API"

---

### Task 2: Accessible private admin page and deployment route

**Files:**
- Create: site/admin/index.html
- Create: site/admin/admin.css
- Create: site/admin/admin.js
- Create: docs-site/admin.test.js
- Modify: docs-site/package.json
- Modify: docs-site/wrangler.jsonc

**Interfaces:**
- Consumes: GET /api/admin/interests returning an object with an items array.
- Produces: request-count, last-refreshed, admin-status, interest-rows, and refresh DOM hooks.

- [ ] **Step 1: Write failing static-page tests**

Use node:test and node:assert/strict to read the assets. Assert main, table, aria-live="polite", the Refresh button, the exact API fetch, no secret/configuration strings, and an admin.backchannel.page custom-domain route in wrangler.jsonc. Add:

    "test:admin": "node --test admin.test.js"

- [ ] **Step 2: Run RED**

    npm run test:admin

Expected: failure because site/admin/index.html does not exist.

- [ ] **Step 3: Create the page**

Create a semantic document with Backchannel branding, Early access heading, count, last-refreshed time, Refresh button, polite live status, and a table with Email, Status, Source, Requested, Consent, Invited, and Last contacted columns. Load only /admin.css and deferred /admin.js. Use no inline or third-party assets.

admin.js must:

- create cells with document.createElement and textContent;
- parse D1 UTC values by converting the space to T and adding Z;
- render null dates as an em dash using textContent;
- allowlist interested, invited, active, and unsubscribed status classes;
- clear stale rows before each request;
- fetch /api/admin/interests with cache: no-store and Accept: application/json;
- render loading, empty, success, and retryable error states;
- update count and last-refreshed only after success; and
- never use storage, cookies, or console output.

admin.css must use the existing teal accent, neutral surfaces, 4/8px spacing, tabular numbers, visible focus, sticky table headings, and native horizontal scrolling. Add no animation.

- [ ] **Step 4: Add the private custom domain**

Add this route beside the apex and www routes:

    { "pattern": "admin.backchannel.page", "custom_domain": true }

- [ ] **Step 5: Run page and build checks**

    npm run test:admin
    npm run test:worker
    npm run build

Expected: all pass and dist-site/admin contains index.html, admin.css, and admin.js.

- [ ] **Step 6: Commit**

    git add site/admin docs-site/admin.test.js docs-site/package.json docs-site/wrangler.jsonc
    git commit -m "feat: add private interest admin page"

---

### Task 3: Linux desktop bundle and three-platform release contract

**Files:**
- Modify: desktop/backchannel.spec
- Modify: desktop/launcher.py
- Modify: desktop/tests/test_launcher.py
- Create: desktop/tests/test_release_contract.py
- Modify: .github/workflows/desktop-release.yml
- Modify: docs/releasing.md

**Interfaces:**
- Consumes: the PyInstaller one-directory build and embedded PostgreSQL linux-amd64 download.
- Produces: Backchannel-linux-x64.tar.gz plus unchanged Windows and macOS assets.

- [ ] **Step 1: Write failing Linux checks**

test_release_contract.py must read the spec and workflow and assert all three exact asset names, pystray._xorg, an ubuntu-latest matrix job, and a Linux tar archive step. test_launcher.py must patch sys.platform to linux and subprocess.run, call _open_data_folder(Path('/tmp/data')), and require:

    subprocess.run(['xdg-open', '/tmp/data'], check=False)

- [ ] **Step 2: Run RED**

From desktop:

    python -m unittest discover -s tests

Expected: failures for missing Linux workflow, Xorg import, and xdg-open.

- [ ] **Step 3: Add minimum Linux support**

In desktop/backchannel.spec:

    else:
        hidden.append("pystray._xorg")

In launcher._open_data_folder:

    else:
        import subprocess
        subprocess.run(["xdg-open", str(data_dir)], check=False)

In the workflow matrix:

    - os: ubuntu-latest
      asset: Backchannel-linux-x64.tar.gz

Add a runner.os == 'Linux' step that executes:

    tar -C dist -czf Backchannel-linux-x64.tar.gz Backchannel

Keep workflow_dispatch non-publishing and the tag-only release condition unchanged.

- [ ] **Step 4: Update release documentation**

Name the Linux x64 tarball beside the existing exact Windows/macOS artifacts. State that it is portable rather than a package-manager installer. Add Linux to workflow and smoke-test descriptions. Do not alter v0.1.1 download links because that release has no Linux asset.

- [ ] **Step 5: Run GREEN and parse workflow YAML**

    python -m unittest discover -s tests
    python -c "import pathlib, yaml; yaml.safe_load(pathlib.Path('../.github/workflows/desktop-release.yml').read_text()); print('yaml ok')"

Expected: all desktop tests pass and output ends with yaml ok.

- [ ] **Step 6: Commit**

    git add desktop/backchannel.spec desktop/launcher.py desktop/tests/test_launcher.py desktop/tests/test_release_contract.py .github/workflows/desktop-release.yml docs/releasing.md
    git commit -m "ci: add Linux desktop bundle"

---

### Task 4: Operations documentation and full verification

**Files:**
- Modify: docs/deployment.md
- Modify: AGENTS.md
- Modify: CLAUDE.md

**Interfaces:**
- Consumes: Tasks 1-3.
- Produces: exact deployment steps and authoritative repository guidance.

- [ ] **Step 1: Document private deployment**

Add:

    cd docs-site
    npx wrangler secret put ADMIN_EMAIL
    npx wrangler secret put ACCESS_TEAM_DOMAIN
    npx wrangler secret put ACCESS_AUD

Describe one Cloudflare Access self-hosted application covering the complete admin.backchannel.page hostname, one exact-email Allow policy, how to copy its AUD tag, and the fail-closed requirement. Include no real identity or secret value.

- [ ] **Step 2: Update project snapshots**

Update AGENTS.md and CLAUDE.md so the site section names the private host and security boundary, and the release section names Docker plus Linux x64, macOS arm64, and Windows x64 outputs.

- [ ] **Step 3: Run focused site verification**

From docs-site:

    npm run test:worker
    npm run test:site
    npm run test:admin
    npm run build
    npm audit --omit=dev

Expected: tests/build pass and no production vulnerability is reported.

- [ ] **Step 4: Run application and packaging verification**

From the repository root:

    cd frontend
    npm ci
    npm run build
    cd ../backend
    python -m unittest discover -s tests
    cd ../desktop
    python -m unittest discover -s tests
    cd ..
    docker compose config --quiet
    docker compose build frontend backend

Expected: frontend, backend, and desktop checks pass; Compose is valid; both source-built images complete.

- [ ] **Step 5: Run finish checks**

    git diff --check
    C:/Users/thoule/.local/bin/sentrux.exe check .
    git status --short --branch

Expected: no whitespace errors, structural rules pass, and only intentional committed work remains.

- [ ] **Step 6: Commit operations documentation**

    git add docs/deployment.md AGENTS.md CLAUDE.md
    git commit -m "docs: operate private interest admin"

- [ ] **Step 7: Completion audit**

Inspect committed files and fresh command output for every requirement: private-host isolation, JWT verification, exact secret email, read-only D1 output, accessible states, no committed identity, Linux/macOS/Windows artifacts, Docker build success, and no publishing action. Keep the goal active if any evidence is missing.
