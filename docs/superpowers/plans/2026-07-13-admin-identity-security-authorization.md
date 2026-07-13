# Admin Identity, Security, and Authorization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the overloaded early-access admin row with protected Early access, Users identity/security, and Authorization modules while preserving release access and fixing two recipient security defects.

**Architecture:** Keep the existing Cloudflare Worker, D1 database, and static HTML/CSS/JavaScript stack. Add one authorization-policy table, route-specific admin read/mutation contracts, and a shared protected admin shell that loads three focused ES modules through native links and imports.

**Tech Stack:** Cloudflare Workers, D1/SQLite, R2, vanilla browser ES modules, HTML/CSS, Node.js built-in test runner, `node:sqlite`, Astro assembly, Sentrux.

## Global Constraints

- The sole admin operator remains external in Cloudflare Access and exact `ADMIN_EMAIL` authorization; do not add admin accounts or RBAC.
- Managed users are normalized-email recipients for `downloads.backchannel.page` and must originate from early-access requests.
- Early access owns Approve/Reject; Users owns identity, passwords, sessions, and revoke; Authorization owns Latest/version grants.
- Password/session commands must not render in Authorization, and grant commands must not render in Users or Early access.
- Keep the existing HTML/CSS/JavaScript stack; add no framework, component library, router, icon dependency, or runtime package.
- Keep emails in JSON bodies, never route paths, query strings, logs, or R2 keys.
- Every admin request must pass Access authorization before route dispatch, body parsing, or D1/R2 access.
- Admin mutations remain exact-origin JSON, strict UTF-8, and streamed to the existing 8 KiB bound.
- Preserve no-store/private headers, self-only CSP, safe DOM construction, ephemeral credential plaintext, dark mode, reduced motion, forced colors, and 44-pixel targets.
- Desktop navigation is a 208-pixel rail; it becomes route tabs below 760 pixels; list/detail becomes one pane below 640 pixels; verify at 320 CSS pixels.
- Approval atomically creates identity, default Latest policy, request decision, and audit event; it accepts no editable grants.
- Deployment documentation must freeze every admin mutation between migration 0003 and the matching Worker/assets deploy, then require zero missing policies and zero legacy/policy Latest mismatches before unfreezing.
- Do not reactivate revoked identities. Reset password must fail for revoked users.
- Do not deploy, apply remote migrations, or save a new Sentrux baseline in this implementation branch.

**Approved spec:** `docs/superpowers/specs/2026-07-13-admin-identity-security-authorization-design.md`

---

## File Structure

### Create

- `.ui-craft/tokens.md` - documents the existing token spine and admin layout constraints.
- `docs-site/migrations/0003_release_access_policies.sql` - moves active Latest authorization state out of account reads/writes.
- `docs-site/admin-test-helpers.js` - shared fake DOM/fetch helpers for route-module tests.
- `docs-site/admin-early-access.test.js` - request queue and approval/rejection behavior.
- `docs-site/admin-users.test.js` - identity/security list-detail and commands.
- `docs-site/admin-authorization.test.js` - grant list-detail and catalog degradation.
- `docs-site/admin-preview.mjs` - loopback-only static/mock API server for visual verification; never assembled or deployed.
- `docs-site/admin-preview.test.js` - verifies the preview stays loopback-only and outside deployed assets.
- `site/admin/admin-core.js` - shared safe DOM, fetch, format, dialog, and list-detail helpers.
- `site/admin/early-access.js` - Early access route.
- `site/admin/users.js` - Users identity/security route.
- `site/admin/authorization.js` - Authorization route.

### Modify

- `.ui-craft/brief.md` - append the private operator-console brief without replacing the public-site brief.
- `docs-site/migration.test.js` - execute and verify migration 0003.
- `docs-site/worker.js` - separated admin API, authorization-policy reads/writes, protected module assets, password non-reuse, and logout failure semantics.
- `docs-site/worker.test.js` - Worker/API/security and asset-isolation coverage.
- `docs-site/admin.test.js` - shared shell/core, security, and responsive contracts.
- `docs-site/package.json` - add the loopback admin-preview command only.
- `site/admin/index.html` - shared semantic admin shell and generic dialogs.
- `site/admin/admin.css` - rail, responsive route tabs, list/detail, states, and dialogs.
- `site/admin/admin.js` - pathname selection, route import, active navigation, Refresh wiring.
- `AGENTS.md` - document route ownership, policy table, endpoints, and verification.
- `CLAUDE.md` - mirror durable admin architecture and commands.
- `docs/README.md` - replace combined admin-mutation wording.
- `docs/deployment.md` - migration/deploy/smoke/rollback sequence.
- `docs/releasing.md` - cross-reference the admin migration deployment gate.

### Leave Unchanged

- `docs-site/assemble.mjs` already copies `site/` recursively.
- `docs-site/release-access.js` already supplies password verification and entitlement resolution.
- `site/downloads/downloads.js` already keeps the recipient on the current panel and shows a retryable error when logout fails.
- `docs-site/wrangler.jsonc` already disables public Worker URLs and protects the exact hosts.

---

### Task 1: Lock Design Memory and Separate Latest Policy Storage

**Files:**
- Create: `.ui-craft/tokens.md`
- Create: `docs-site/migrations/0003_release_access_policies.sql`
- Modify: `.ui-craft/brief.md`
- Modify: `docs-site/migration.test.js:6-15,31-184`

**Interfaces:**
- Consumes: existing `release_accounts.email`, `release_accounts.include_latest`, and `release_accounts.approved_at`.
- Produces: `release_access_policies(email, include_latest, updated_at)` for every existing release account.

- [ ] **Step 1: Append the approved admin brief and document existing tokens**

Append this section to `.ui-craft/brief.md`:

```markdown
## Surface: Private admin console (2026-07-13)

### Product purpose

Let the single authorized Backchannel operator review early-access requests,
manage recipient identity and security, and manage release authorization in
separate, predictable work areas.

### Primary user

One trusted operator working repeatedly with download-recipient accounts.
Recipient identity is normalized email; operator identity remains external in
Cloudflare Access.

### Principles

1. Separate request, identity/security, and authorization ownership.
2. Keep security state explicit and destructive actions deliberate.
3. Prefer dense scan-and-detail workflows over wide command tables.
4. Update the affected record immediately after a successful command.
5. Preserve privacy: no identity or credential persistence, URLs, or logs.

### Success metric

At desktop and 320 CSS pixels, the operator can approve a request, inspect a
user's identity/security state, reset credentials or sessions, and edit grants
without password and authorization commands sharing a surface.

### Out of scope

- Admin accounts, roles, permissions, organizations, or generic policy rules.
- Recipient reactivation, deletion, email changes, merge, or bulk operations.
- Audit export, saved filters, server-side search, or pagination.
- A frontend framework, component library, client router, or second Worker.
```

Create `.ui-craft/tokens.md` with the implemented values rather than a new theme:

```markdown
# Backchannel UI Tokens

## Primitive

- Color: existing light/dark values in `site/style.css`; teal is the only accent.
- Type: system UI for interface text; system monospace for email, dates, counts, and versions.
- Spacing: 4, 8, 12, 16, and 24 pixels.
- Radius: 6 pixels controls, 8 pixels bounded regions, 10 pixels dialogs.
- Elevation: existing layered `--shadow`; borders carry most grouping.
- Target: 44 pixels minimum interactive height.

## Semantic

- Ink, muted, paper, surface, border, accent, accent-strong, accent-soft, and danger reuse `site/style.css`.
- Success, warning, danger, and info reuse `site/admin/admin.css` status colors.
- Status always includes text; color is supplementary.

## Admin Components

- Navigation rail: 208 pixels desktop; route tabs below 760 pixels.
- List/detail: two panes desktop; one pane below 640 pixels.
- Minimum verification width: 320 CSS pixels with no page-level overflow.
- Motion: focus, hover, and immediate state changes only; no list/form animation.
```

- [ ] **Step 2: Write failing migration tests**

Add migration loading and a database-through-0002 helper to `migration.test.js`:

```js
const migration3 = readFileSync(
  new URL('./migrations/0003_release_access_policies.sql', import.meta.url),
  'utf8',
);

function databaseThrough2() {
  const db = new DatabaseSync(':memory:');
  db.exec('PRAGMA foreign_keys = ON');
  db.exec(migration1);
  db.exec(migration2);
  return db;
}

function database() {
  const db = databaseThrough2();
  db.exec(migration3);
  return db;
}
```

Add exact behavior tests:

```js
test('migration 0003 backfills release access policies without changing explicit grants', () => {
  const db = databaseThrough2();
  try {
    insertInterest(db, 'latest@example.com');
    insertAccount(db, 'latest@example.com');
    insertInterest(db, 'pinned@example.com');
    db.prepare(`
      INSERT INTO release_accounts
        (email, state, password_hash, password_salt, include_latest, approved_at)
      VALUES (?, 'active', 'hash', 'salt', 0, '2026-07-13 12:00:00')
    `).run('pinned@example.com');
    db.prepare(`
      INSERT INTO release_account_versions (email, version)
      VALUES ('pinned@example.com', 'v0.2.1')
    `).run();

    db.exec(migration3);

    assert.deepEqual(
      db.prepare(`SELECT email, include_latest FROM release_access_policies ORDER BY email`).all(),
      [
        { email: 'latest@example.com', include_latest: 1 },
        { email: 'pinned@example.com', include_latest: 0 },
      ],
    );
    assert.equal(db.prepare('SELECT count(*) AS count FROM release_account_versions').get().count, 1);
  } finally {
    db.close();
  }
});

test('release access policies enforce constraints and cascade with accounts', () => {
  const db = database();
  try {
    insertInterest(db);
    insertAccount(db);
    db.prepare(`
      INSERT INTO release_access_policies (email, include_latest)
      VALUES ('person@example.com', 1)
    `).run();
    assert.throws(
      () => db.exec(`UPDATE release_access_policies SET include_latest = 2`),
      /CHECK constraint failed/,
    );
    assert.throws(
      () => db.exec(`INSERT INTO release_access_policies (email) VALUES ('missing@example.com')`),
      /FOREIGN KEY constraint failed/,
    );
    db.exec(`DELETE FROM release_accounts WHERE email = 'person@example.com'`);
    assert.equal(db.prepare('SELECT count(*) AS count FROM release_access_policies').get().count, 0);
    assert.deepEqual(db.prepare('PRAGMA foreign_key_check').all(), []);
  } finally {
    db.close();
  }
});
```

- [ ] **Step 3: Run the focused test and confirm RED**

Run from `docs-site`:

```powershell
node --test --test-name-pattern='migration 0003|release access policies' migration.test.js
```

Expected: FAIL because `0003_release_access_policies.sql` does not exist.

- [ ] **Step 4: Add the additive migration**

Create `docs-site/migrations/0003_release_access_policies.sql`:

```sql
CREATE TABLE release_access_policies (
  email TEXT PRIMARY KEY COLLATE NOCASE,
  include_latest INTEGER NOT NULL DEFAULT 1
    CHECK (include_latest IN (0, 1)),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY (email) REFERENCES release_accounts(email) ON DELETE CASCADE
);

INSERT INTO release_access_policies (email, include_latest, updated_at)
SELECT email, include_latest, approved_at FROM release_accounts;
```

- [ ] **Step 5: Run migration tests and confirm GREEN**

```powershell
npm run test:migration
```

Expected: all migration tests pass with zero failures.

- [ ] **Step 6: Commit the design memory and policy migration**

```powershell
git add -- .ui-craft/brief.md .ui-craft/tokens.md docs-site/migrations/0003_release_access_policies.sql docs-site/migration.test.js
git commit -m "feat: separate release authorization policy"
```

---

### Task 2: Add Disjoint Admin Read Models and Recipient Policy Reads

**Files:**
- Modify: `docs-site/worker.test.js:323-469,925-959,1285-1337,1530-1605`
- Modify: `docs-site/worker.js:23-24,165-201,398-409,612-660,1251-1281`

**Interfaces:**
- Produces: `handleAdminUsers(request, env, dependencies) -> Response`.
- Produces: `handleAdminAuthorization(request, env) -> Response`.
- Produces: `findReleaseAuthorization(env, email) -> {include_latest, versions}|null`.
- Changes: `findDownloadSession()` returns authentication/security fields only; `releaseSession()` loads authorization separately.

- [ ] **Step 1: Write failing read-boundary tests**

Load migration 0003 beside the existing migration constants, apply it in
`sqliteD1()`, and add these exact real-SQLite fixtures:

```js
const policyMigration = readFileSync(
  new URL('./migrations/0003_release_access_policies.sql', import.meta.url), 'utf8',
);

// In sqliteD1(), immediately after releaseMigration:
database.exec(policyMigration);

function sqliteReleaseBindings() {
  const { database, binding } = sqliteD1();
  return {
    db: database,
    env: {
      ADMIN_EMAIL: 'owner@example.com',
      ACCESS_TEAM_DOMAIN: 'backchannel.cloudflareaccess.com',
      ACCESS_AUD: 'admin-audience',
      INTEREST_DB: binding,
      RELEASES: adminCatalogBucket(),
      ASSETS: { fetch: async () => new Response('private asset') },
    },
  };
}

function seedApprovedReleaseAccount(db, {
  email,
  includeLatest = 1,
  version,
  sessionExpiresAt,
}) {
  db.prepare(`
    INSERT INTO interest_subscribers
      (email, consent_version, release_decision, release_reviewed_at)
    VALUES (?, '2026-07-12', 'approved', '2026-07-12T12:00:00.000Z')
  `).run(email);
  db.prepare(`
    INSERT INTO release_accounts
      (email, state, password_hash, password_salt, must_change_password,
       password_expires_at, approved_at)
    VALUES (?, 'active', 'hash', 'salt', 1,
      '2026-07-15T12:00:00.000Z', '2026-07-12T12:00:00.000Z')
  `).run(email);
  db.prepare(`
    INSERT INTO release_access_policies (email, include_latest, updated_at)
    VALUES (?, ?, '2026-07-12T12:00:00.000Z')
  `).run(email, includeLatest);
  if (version) db.prepare(`
    INSERT INTO release_account_versions (email, version) VALUES (?, ?)
  `).run(email, version);
  if (sessionExpiresAt) db.prepare(`
    INSERT INTO release_sessions
      (token_hash, email, password_change_only, created_at, expires_at)
    VALUES ('seed-token', ?, 0, '2026-07-12T12:00:00.000Z', ?)
  `).run(email, sessionExpiresAt);
}
```

Then add a test that inserts one account, policy, explicit version, and active
session before calling all three endpoints:

```js
test('separated admin read endpoints return disjoint route-specific records', async (context) => {
  const env = sqliteReleaseBindings();
  context.after(() => env.db.close());
  seedApprovedReleaseAccount(env.db, {
    email: 'person@example.com',
    includeLatest: 1,
    version: 'v0.2.1',
    sessionExpiresAt: '2026-07-20T12:00:00.000Z',
  });
  const dependencies = { now: () => new Date('2026-07-13T12:00:00.000Z') };

  const interests = await workerModule.route(
    adminRequest('/api/admin/interests'), env.env, allowOwner, dependencies,
  );
  const users = await workerModule.route(
    adminRequest('/api/admin/users'), env.env, allowOwner, dependencies,
  );
  const authorization = await workerModule.route(
    adminRequest('/api/admin/authorization'), env.env, allowOwner, dependencies,
  );

  assert.deepEqual(Object.keys((await interests.json()).items[0]).sort(), [
    'consent_at', 'consent_version', 'created_at', 'email', 'invited_at',
    'last_contacted_at', 'release_decision', 'release_reviewed_at', 'source', 'status',
  ]);
  assert.deepEqual(Object.keys((await users.json()).items[0]).sort(), [
    'active_session_count', 'approved_at', 'email', 'latest_session_expires_at',
    'must_change_password', 'password_changed_at', 'password_expires_at',
    'requested_at', 'revoked_at', 'source', 'state',
  ]);
  assert.deepEqual(Object.keys((await authorization.json()).items[0]).sort(), [
    'account_state', 'email', 'include_latest', 'updated_at', 'versions',
  ]);
});
```

Add a route-order test using a D1 binding whose `prepare()` throws and a denied
Access verifier; assert no D1 call occurs for `/api/admin/users` or
`/api/admin/authorization`.

- [ ] **Step 2: Run focused read tests and confirm RED**

```powershell
node --test --test-name-pattern='separated admin read|admin read endpoints authorize' worker.test.js
```

Expected: FAIL because the new read routes do not exist and interests still contains account/grant fields.

- [ ] **Step 3: Implement route-specific read handlers**

Add constants:

```js
const ADMIN_INTERESTS_PATH = '/api/admin/interests';
const ADMIN_USERS_PATH = '/api/admin/users';
const ADMIN_AUTHORIZATION_PATH = '/api/admin/authorization';
const ADMIN_RELEASES_PATH = '/api/admin/releases';
```

Restrict the interest SELECT to the ten request fields asserted above. Add the
Users query with an injected timestamp:

```sql
SELECT a.email, a.state, i.source, i.created_at AS requested_at,
       a.approved_at, a.must_change_password, a.password_expires_at,
       a.password_changed_at, a.revoked_at,
       COALESCE((SELECT count(*) FROM release_sessions s
         WHERE s.email = a.email AND s.expires_at > ?), 0) AS active_session_count,
       (SELECT max(s.expires_at) FROM release_sessions s
         WHERE s.email = a.email AND s.expires_at > ?) AS latest_session_expires_at
FROM release_accounts a
JOIN interest_subscribers i ON i.email = a.email
ORDER BY a.approved_at DESC, a.email
```

Add the Authorization query:

```sql
SELECT a.email, a.state AS account_state, p.include_latest, p.updated_at,
       COALESCE((SELECT json_group_array(version)
         FROM release_account_versions WHERE email = a.email), '[]') AS versions
FROM release_accounts a
JOIN release_access_policies p ON p.email = a.email
ORDER BY a.email
```

Convert `must_change_password` and `include_latest` to booleans in JSON; parse
`versions` into an array; reject malformed rows with the existing generic 503.

- [ ] **Step 4: Separate recipient authentication from authorization reads**

Make `findDownloadSession()` select session/account/decision and current
password material, but no policy/version fields. Add:

```js
async function findReleaseAuthorization(env, email) {
  const record = await env.INTEREST_DB.prepare(`
    SELECT p.include_latest,
      COALESCE((SELECT json_group_array(version)
        FROM release_account_versions WHERE email = p.email), '[]') AS versions
    FROM release_access_policies p
    JOIN release_accounts a ON a.email = p.email
    WHERE p.email = ? AND a.state = 'active'
  `).bind(email).first();
  if (!record || ![0, 1].includes(record.include_latest)) return null;
  const versions = typeof record.versions === 'string' ? JSON.parse(record.versions) : [];
  return Array.isArray(versions) ? { include_latest: record.include_latest, versions } : null;
}
```

`releaseSession()` must call `findDownloadSession()` first, reject change-only
sessions, then call `findReleaseAuthorization()` and return its policy to
`resolveEntitlements()`.

- [ ] **Step 5: Run focused and entitlement tests**

```powershell
node --test --test-name-pattern='separated admin read|admin read endpoints authorize|recipient release listing|release APIs reject' worker.test.js
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit the read-boundary refactor**

```powershell
git add -- docs-site/worker.js docs-site/worker.test.js
git commit -m "refactor: separate admin read models"
```

---

### Task 3: Move Interest and User Mutations to Owned Routes

**Files:**
- Modify: `docs-site/worker.test.js:459-853`
- Modify: `docs-site/worker.js:25-31,278-308,324-409,447-540,1265-1281`

**Interfaces:**
- Produces: `POST /api/admin/interests/approve|reject`.
- Produces: `POST /api/admin/users/reset-password|sign-out|revoke`.
- Produces: approval `{ok, credential}`; reject/User mutations `{ok, item, credential?}`.
- Consumes: `release_access_policies` from Task 1 and user read shape from Task 2.

- [ ] **Step 1: Write failing mutation-ownership tests**

Add focused tests for exact bodies and outcomes:

```js
test('approval creates identity and default Latest policy without grant input', async (context) => {
  const bindings = sqliteReleaseBindings();
  context.after(() => bindings.db.close());
  bindings.db.prepare(`
    INSERT INTO interest_subscribers (email, consent_version)
    VALUES ('person@example.com', '2026-07-12')
  `).run();
  const response = await workerModule.route(
    adminJson('/api/admin/interests/approve', { email: ' Person@Example.com ' }),
    bindings.env,
    allowOwner,
    fixedDependencies,
  );
  const body = await response.json();
  assert.equal(response.status, 201);
  assert.deepEqual(Object.keys(body.credential).sort(), [
    'email', 'password', 'password_expires_at',
  ]);
  assert.deepEqual(bindings.db.prepare(`
    SELECT state, must_change_password FROM release_accounts WHERE email = ?
  `).get('person@example.com'), { state: 'active', must_change_password: 1 });
  assert.equal(bindings.db.prepare(`
    SELECT include_latest FROM release_access_policies WHERE email = ?
  `).get('person@example.com').include_latest, 1);
  assert.equal(bindings.db.prepare(`
    SELECT count(*) AS count FROM release_account_versions WHERE email = ?
  `).get('person@example.com').count, 0);
});

test('failed approval cannot backfill policy or emit an event', async (context) => {
  const bindings = sqliteReleaseBindings();
  context.after(() => bindings.db.close());
  bindings.db.exec(`
    INSERT INTO interest_subscribers
      (email, consent_version, release_decision, release_reviewed_at)
    VALUES
      ('person@example.com', '2026-07-12', 'approved', '2026-07-12T12:00:00.000Z');
    INSERT INTO release_accounts
      (email, state, password_hash, password_salt, approved_at)
    VALUES
      ('person@example.com', 'active', 'hash', 'salt', '2026-07-12T12:00:00.000Z');
  `);

  const response = await workerModule.route(
    adminJson('/api/admin/interests/approve', { email: 'person@example.com' }),
    bindings.env,
    allowOwner,
    fixedDependencies,
  );

  assert.equal(response.status, 409);
  assert.equal(bindings.db.prepare(`
    SELECT count(*) AS count FROM release_access_policies WHERE email = ?
  `).get('person@example.com').count, 0);
  assert.equal(bindings.db.prepare(`
    SELECT count(*) AS count FROM release_access_events WHERE email = ?
  `).get('person@example.com').count, 0);
});

test('sign-out deletes sessions without changing identity or authorization', async (context) => {
  const bindings = sqliteReleaseBindings();
  context.after(() => bindings.db.close());
  seedApprovedReleaseAccount(bindings.db, {
    email: 'person@example.com',
    includeLatest: 0,
    version: 'v0.2.1',
    sessionExpiresAt: '2026-07-20T12:00:00.000Z',
  });
  const accountBefore = bindings.db.prepare(`
    SELECT state, password_hash, password_salt FROM release_accounts WHERE email = ?
  `).get('person@example.com');
  const policyBefore = bindings.db.prepare(`
    SELECT include_latest FROM release_access_policies WHERE email = ?
  `).get('person@example.com');
  const response = await workerModule.route(
    adminJson('/api/admin/users/sign-out', { email: 'person@example.com' }),
    bindings.env,
    allowOwner,
    fixedDependencies,
  );
  assert.equal(response.status, 200);
  assert.equal(bindings.db.prepare(`
    SELECT count(*) AS count FROM release_sessions WHERE email = ?
  `).get('person@example.com').count, 0);
  assert.deepEqual(bindings.db.prepare(`
    SELECT state, password_hash, password_salt FROM release_accounts WHERE email = ?
  `).get('person@example.com'), accountBefore);
  assert.deepEqual(bindings.db.prepare(`
    SELECT include_latest FROM release_access_policies WHERE email = ?
  `).get('person@example.com'), policyBefore);
  assert.equal(bindings.db.prepare(`
    SELECT count(*) AS count FROM release_account_versions WHERE email = ?
  `).get('person@example.com').count, 1);
});
```

Also assert reset/revoke SQL never mentions policy/version tables, revoked
users cannot reset, and every successful non-approval mutation returns the
updated route-specific item.

- [ ] **Step 2: Run focused mutation tests and confirm RED**

```powershell
node --test --test-name-pattern='default Latest policy|interest and user mutations|sign-out|reset and revoke' worker.test.js
```

Expected: FAIL because the new routes and policy insert do not exist.

- [ ] **Step 3: Replace the overloaded route map**

Use an explicit method/action table:

```js
const ADMIN_MUTATIONS = new Map([
  ['/api/admin/interests/approve', ['POST', 'approve']],
  ['/api/admin/interests/reject', ['POST', 'reject']],
  ['/api/admin/users/reset-password', ['POST', 'reset']],
  ['/api/admin/users/sign-out', ['POST', 'sign-out']],
  ['/api/admin/users/revoke', ['POST', 'revoke']],
  ['/api/admin/authorization/grants', ['PUT', 'grants']],
]);
```

Dispatch every action explicitly. Do not retain a final fallback that assumes
unknown actions mean revoke.

- [ ] **Step 4: Make approval identity-only and add session sign-out**

Change `approve(env, email, dependencies, now)` so its batch includes:

```sql
INSERT INTO release_accounts
  (email, state, password_hash, password_salt, password_iterations,
   must_change_password, password_expires_at, approved_at)
SELECT ?, 'active', ?, ?, ?, 1, ?, ?
WHERE EXISTS (SELECT 1 FROM interest_subscribers
  WHERE email = ? AND release_decision = 'pending');

UPDATE interest_subscribers
SET status = 'active', release_decision = 'approved', release_reviewed_at = ?
WHERE email = ? AND release_decision = 'pending' AND changes() = 1
  AND EXISTS (SELECT 1 FROM release_accounts
    WHERE email = ? AND state = 'active' AND approved_at = ?);

INSERT INTO release_access_policies (email, include_latest, updated_at)
SELECT ?, 1, ? WHERE changes() = 1 AND EXISTS (
  SELECT 1 FROM release_accounts a
  JOIN interest_subscribers i ON i.email = a.email
  WHERE a.email = ? AND a.state = 'active' AND a.approved_at = ?
    AND i.release_decision = 'approved' AND i.release_reviewed_at = ?
);

INSERT INTO release_access_events (email, action, version, created_at)
SELECT ?, 'approval', NULL, ? WHERE changes() = 1 AND EXISTS (
  SELECT 1 FROM release_access_policies p
  JOIN interest_subscribers i ON i.email = p.email
  WHERE p.email = ? AND p.updated_at = ?
    AND i.release_decision = 'approved' AND i.release_reviewed_at = ?
);
```

The statement order and `changes() = 1` chain are required. Inspect all four
batch results and return a conflict unless each changed exactly one row; no
zero-change or repeated approval may backfill a policy or emit an event.
Return:

```js
privateJson(201, {
  ok: true,
  credential: { email, password, password_expires_at: expiresAt },
});
```

Add `signOutSessions(env, email, now)` with one batch: guarded session delete,
`session_sign_out` event, then load and return the updated user record. Reset
and revoke use only identity/session tables and return the Users read shape.
After a successful rejection, load and return the updated request-only
Interest record; approval remains the credential-only exception.

- [ ] **Step 5: Run all admin mutation tests**

```powershell
node --test --test-name-pattern='approval|rejection|sign-out|password reset|revocation|admin mutations' worker.test.js
```

Expected: selected tests pass; grant-route tests may remain red until Task 4.

- [ ] **Step 6: Commit owned interest/user commands**

```powershell
git add -- docs-site/worker.js docs-site/worker.test.js
git commit -m "refactor: separate admin identity commands"
```

---

### Task 4: Move Grant Replacement to Authorization Policy

**Files:**
- Modify: `docs-site/worker.test.js:552-637,753-775,908-959`
- Modify: `docs-site/worker.js:283-321,411-445,522-540`

**Interfaces:**
- Produces: `PUT /api/admin/authorization/grants`.
- Produces: `{ok:true,item:AuthorizationRecord}`.
- Removes: all `/api/admin/access/*` routes.

- [ ] **Step 1: Write failing policy-only grant tests**

Add assertions that grant replacement writes only policy/version/event tables,
revoked authorization remains readable but immutable, old routes return
private 404, and active Worker source has no account-Latest references:

```js
test('worker has no active release_accounts Latest references', () => {
  const source = readFileSync(new URL('./worker.js', import.meta.url), 'utf8');
  for (const forbidden of [
    /a\.include_latest/,
    /account\.include_latest/,
    /UPDATE release_accounts SET include_latest/i,
    /INSERT INTO release_accounts\s*\([^)]*\binclude_latest\b/i,
  ]) assert.doesNotMatch(source, forbidden);
});
```

- [ ] **Step 2: Run focused tests and confirm RED**

```powershell
node --test --test-name-pattern='authorization grant|revoked authorization|old overloaded|Latest references' worker.test.js
```

Expected: FAIL because grant replacement still updates `release_accounts` and old routes exist.

- [ ] **Step 3: Replace grants through policy and versions**

Keep existing entitlement validation and trusted-catalog checks. Build one
batch containing guarded version delete/inserts, then:

```sql
UPDATE release_access_policies
SET include_latest = ?, updated_at = ?
WHERE email = ? AND EXISTS
  (SELECT 1 FROM release_accounts WHERE email = ? AND state = 'active');

INSERT INTO release_access_events (email, action, version, created_at)
SELECT ?, 'grant_change', NULL, ? WHERE EXISTS
  (SELECT 1 FROM release_accounts WHERE email = ? AND state = 'active');
```

Return the updated Authorization record. Revoked users remain in the read
model but `PUT` returns generic 409.

- [ ] **Step 4: Remove old route aliases and account-Latest reads/writes**

Remove all `/api/admin/access/*` strings and all active SQL references to
`release_accounts.include_latest`. The legacy column remains only in migration
0002, migration 0003 backfill, migration tests, and approved documentation.

- [ ] **Step 5: Run Worker and migration suites**

```powershell
npm run test:worker
npm run test:migration
```

Expected: both suites pass with zero failures.

- [ ] **Step 6: Commit Authorization cutover**

```powershell
git add -- docs-site/worker.js docs-site/worker.test.js
git commit -m "refactor: isolate release authorization"
```

---

### Task 5: Reject Temporary-Password Reuse and Preserve Failed Logout Sessions

**Files:**
- Modify: `docs-site/worker.test.js:1336-1434`
- Modify: `docs-site/worker.js:612-630,1052-1155`

**Interfaces:**
- Consumes: existing `verifyPassword(password, record) -> Promise<boolean>`.
- Changes: password rotation rejects the current temporary credential before hashing or batching.
- Changes: logout clears the cookie only after successful server-session deletion.

- [ ] **Step 1: Write failing security regression tests**

Add:

```js
test('password change rejects reuse of the temporary credential without rotation', async () => {
  const token = await createSessionToken((length) => new Uint8Array(length).fill(12));
  let hashCalls = 0;
  let sessionCalls = 0;
  let batchCalls = 0;
  const bindings = downloadBindings({
    first: async () => ({
      email: 'person@example.com', state: 'active', password_change_only: 1,
      expires_at: '2026-07-13T12:30:00.000Z', password_hash: 'hash',
      password_salt: 'salt', password_iterations: 600000,
    }),
    batch: async (statements) => {
      batchCalls += 1;
      return statements.map(() => ({ success: true, meta: { changes: 1 } }));
    },
  });
  const response = await workerModule.route(
    downloadRequest('/api/download/password', { password: 'Temporary-Password1!' }, {
      headers: { cookie: `__Host-backchannel_release=${token.token}` },
    }),
    bindings.env,
    undefined,
    downloadDependencies({
      now: () => new Date('2026-07-13T12:00:00.000Z'),
      verifyPassword: async () => true,
      hashPassword: async () => { hashCalls += 1; },
      createSessionToken: async () => { sessionCalls += 1; },
    }),
  );
  assert.equal(response.status, 400);
  assert.equal(hashCalls, 0);
  assert.equal(sessionCalls, 0);
  assert.equal(batchCalls, 0);
  assert.equal(response.headers.has('set-cookie'), false);
});

test('logout D1 failure returns retryable error and preserves the cookie', async () => {
  const token = await createSessionToken((length) => new Uint8Array(length).fill(13));
  const bindings = downloadBindings({
    first: async () => ({
      email: 'person@example.com', state: 'active', password_change_only: 0,
      expires_at: '2026-07-20T12:00:00.000Z',
    }),
    batch: async () => { throw new Error('offline'); },
  });
  const response = await workerModule.route(
    downloadRequest('/api/download/logout', {}, {
      headers: { cookie: `__Host-backchannel_release=${token.token}` },
    }),
    bindings.env,
    undefined,
    downloadDependencies(),
  );
  assert.equal(response.status, 503);
  assert.equal(response.headers.has('set-cookie'), false);
});
```

- [ ] **Step 2: Run focused tests and confirm RED**

```powershell
node --test --test-name-pattern='password change rejects reuse|logout D1 failure' worker.test.js
```

Expected: FAIL because reuse is accepted and logout swallows D1 errors.

- [ ] **Step 3: Compare the proposed password before rotation**

Ensure `findDownloadSession()` supplies the current password hash, salt, and
iterations only to authenticated server code. In `handleDownloadPassword()`:

```js
const reused = await (dependencies.verifyPassword || verifyPassword)(password, {
  hash: account.password_hash,
  salt: account.password_salt,
  iterations: account.password_iterations,
});
if (reused) {
  return downloadJson(400, { ok: false, error: 'Choose a different password.' });
}
```

Run this before new hashing, token creation, or D1 batching. Successful tests
inject `verifyPassword: async () => false`.

- [ ] **Step 4: Fail logout closed on D1 errors**

Rules:

```text
Missing/invalid cookie -> 200 and clear cookie.
Valid cookie + successful delete -> 200 and clear cookie.
Valid cookie + any D1 lookup/delete/batch failure -> 503 and no Set-Cookie.
```

Remove the swallowed exception. Verify the presented-session delete result
before emitting success or a logout event.

- [ ] **Step 5: Run recipient security suites**

```powershell
npm run test:worker
npm run test:download
npm run test:release-access
```

Expected: all three suites pass.

- [ ] **Step 6: Commit security fixes**

```powershell
git add -- docs-site/worker.js docs-site/worker.test.js
git commit -m "fix: harden recipient credential security"
```

---

### Task 6: Build the Shared Admin Shell, Core, and Read-Only Routes

**Files:**
- Create: `docs-site/admin-test-helpers.js`
- Create: `site/admin/admin-core.js`
- Create: `site/admin/early-access.js`
- Create: `site/admin/users.js`
- Create: `site/admin/authorization.js`
- Modify: `docs-site/admin.test.js:1-208`
- Modify: `docs-site/worker.test.js:925-959,1034-1060,1873-1917`
- Modify: `docs-site/worker.js:32-38,1265-1281`
- Modify: `site/admin/index.html:1-124`
- Modify: `site/admin/admin.css:17-475`
- Modify: `site/admin/admin.js:1-356`

**Interfaces:**
- `admin-core.js` exports safe DOM/fetch/format/dialog/list-detail helpers.
- Every route module exports `meta` and `mount({document, fetcher, shell, dialogs})`.
- `mount()` returns `{refresh(): Promise<void>}`.

- [ ] **Step 1: Replace combined-page tests with failing shell/core contracts**

Create `admin-test-helpers.js` with a fake element that stores attributes,
listeners, focus, children, values, checked/disabled/open state, and can
dispatch events. Update `admin.test.js` to import production modules directly.

Assert:

```js
test('admin shell exposes protected native route navigation', () => {
  assert.match(html, /href="\/early-access"/);
  assert.match(html, /href="\/users"/);
  assert.match(html, /href="\/authorization"/);
  assert.match(html, /<script[^>]+type="module"[^>]+src="\/admin\.js"/);
  assert.match(html, /id="route-title"/);
  assert.match(html, /id="route-content"/);
});

test('admin core uses safe ephemeral browser APIs', () => {
  const assets = [coreSource, html].join('\n');
  assert.doesNotMatch(assets, /innerHTML|outerHTML|insertAdjacentHTML/);
  assert.doesNotMatch(assets, /localStorage|sessionStorage|document\.cookie|console\./);
  assert.match(coreSource, /navigator\.clipboard\.writeText/);
  assert.match(coreSource, /addEventListener\('pagehide'/);
});
```

Add Worker asset tests for all four page paths and all five JavaScript assets;
assert Access denial happens before `ASSETS.fetch()`.

- [ ] **Step 2: Run focused shell tests and confirm RED**

```powershell
node --test --test-name-pattern='admin shell|admin core|private host serves|page roots' admin.test.js worker.test.js
```

Expected: FAIL because the shell, modules, and protected mappings do not exist.

- [ ] **Step 3: Implement the core interfaces**

`admin-core.js` exports:

```js
export function element(name, className = '', text, documentValue = document) {
  const node = documentValue.createElement(name);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

export async function jsonRequest(path, method = 'GET', body, fetcher = fetch) {
  const init = { method, headers: { accept: 'application/json' }, cache: 'no-store' };
  if (body !== undefined) {
    init.headers['content-type'] = 'application/json';
    init.body = JSON.stringify(body);
  }
  const response = await fetcher(path, init);
  const value = await response.json();
  if (!response.ok) throw new Error('request failed');
  return value;
}

export function replaceByEmail(items, item) {
  const index = items.findIndex(({ email }) => email === item.email);
  return index < 0 ? items : items.with(index, item);
}
```

Also export `timeNode`, `createDialogController`, and
`createListDetailController` with the spec's focus and plaintext-clearing
behavior. The core has no route registry or business command labels.

- [ ] **Step 4: Replace HTML/CSS/bootstrap and add read-only route mounts**

The shell contains one semantic nav, shared header/count/Refresh/status,
content root, labelled confirm dialog, and credential dialog. Use
`<script type="module" src="/admin.js"></script>`.

`admin.js` uses this exact route map:

```js
const routes = new Map([
  ['/', './users.js'],
  ['/users', './users.js'],
  ['/early-access', './early-access.js'],
  ['/authorization', './authorization.js'],
]);
```

Each route module loads only its read endpoint and renders loading, empty,
error/Retry, list, and selection states. Users and Authorization provide
case-insensitive email search. No mutation command is added in this step.

CSS implements `grid-template-columns: 208px minmax(0, 1fr)`, route tabs at
760 pixels, labelled stacked table fields and one-pane list/detail at 640
pixels, 44-pixel targets, 320-pixel containment, dark mode, reduced motion,
and forced colors.

- [ ] **Step 5: Protect every page and module asset**

Map `/`, `/users`, `/early-access`, and `/authorization` to `/admin/`. Map
`/admin.js`, `/admin-core.js`, `/early-access.js`, `/users.js`,
`/authorization.js`, `/admin.css`, and `/style.css` to their static assets.
Unknown paths remain private no-store 404.

- [ ] **Step 6: Run shell, admin, and asset tests**

```powershell
npm run test:admin
node --test --test-name-pattern='private host serves|public host never|page roots|router isolates' worker.test.js
```

Expected: all selected tests pass.

- [ ] **Step 7: Commit the routed admin shell**

```powershell
git add -- docs-site/admin-test-helpers.js docs-site/admin.test.js docs-site/worker.js docs-site/worker.test.js site/admin/index.html site/admin/admin.css site/admin/admin.js site/admin/admin-core.js site/admin/early-access.js site/admin/users.js site/admin/authorization.js
git commit -m "feat: add modular admin shell"
```

---

### Task 7: Complete Early Access Decisions and One-Time Credentials

**Files:**
- Create: `docs-site/admin-early-access.test.js`
- Modify: `site/admin/early-access.js`
- Modify: `site/admin/admin-core.js`

**Interfaces:**
- Consumes: `GET /api/admin/interests` and `POST /api/admin/interests/approve|reject`.
- Produces: deterministic local request updates and the shared credential dialog.

- [ ] **Step 1: Write failing Early access tests**

Test that the route renders only request fields and Approve/Reject; posts only
`{email}`; Cancel performs no request; success updates the row without another
GET; credential text has no grants and clears on close/pagehide; password,
session, revoke, Latest, version, and grant copy is absent.

```js
assert.deepEqual(calls[1], {
  path: '/api/admin/interests/approve',
  method: 'POST',
  body: { email: 'person@example.com' },
});
assert.doesNotMatch(renderedText, /Reset password|Sign out|Revoke|Latest|version|grant/i);
```

- [ ] **Step 2: Run the focused test and confirm RED**

```powershell
node --test admin-early-access.test.js
```

Expected: FAIL because decision commands are not mounted.

- [ ] **Step 3: Implement approve/reject and credential handoff**

Approval uses the shared confirmation dialog and patches the known local row to
`status: 'active'`, `release_decision: 'approved'`, and the returned review
time if present. Reject consumes the returned `item`. Neither refetches.

Credential text is exactly:

```text
Backchannel desktop access
Account: recipient@example.com
Temporary password: generated-value
Sign in: https://downloads.backchannel.page/
Password expires: 2026-07-16T12:00:00.000Z
```

The dialog includes normal `/users` and `/authorization` links after Copy/Save
and restores focus to the originating Approve button after close.

- [ ] **Step 4: Run Early access and shared-admin tests**

```powershell
node --test admin-early-access.test.js admin.test.js
```

Expected: both files pass.

- [ ] **Step 5: Commit the request workflow**

```powershell
git add -- docs-site/admin-early-access.test.js site/admin/early-access.js site/admin/admin-core.js
git commit -m "feat: separate early access decisions"
```

---

### Task 8: Complete Users Identity and Security Management

**Files:**
- Create: `docs-site/admin-users.test.js`
- Modify: `site/admin/users.js`
- Modify: `site/admin/admin-core.js`
- Modify: `site/admin/admin.css`

**Interfaces:**
- Consumes: `GET /api/admin/users`.
- Consumes: `POST /api/admin/users/reset-password|sign-out|revoke`.
- Produces: searchable identity list, Identity/Security detail, immediate local updates.

- [ ] **Step 1: Write failing Users tests**

Cover normalized email search, list/detail selection, focus move/restore,
temporary/permanent/expired password boundary, session metadata, exact command
bodies, reset credential, sign-out, revoke, revoked command restrictions, and
absence of release/grant copy.

```js
assert.equal(passwordState({ must_change_password: false }, now), 'Permanent');
assert.equal(passwordState({
  must_change_password: true,
  password_expires_at: '2026-07-13T11:59:59.000Z',
}, now), 'Expired');
assert.equal(passwordState({
  must_change_password: true,
  password_expires_at: '2026-07-13T12:00:01.000Z',
}, now), 'Temporary');
```

- [ ] **Step 2: Run the focused test and confirm RED**

```powershell
node --test admin-users.test.js
```

Expected: FAIL because security commands and password-state behavior do not exist.

- [ ] **Step 3: Implement the Users directory and detail commands**

Export pure `passwordState(record, now)` plus `mount()`. Identity renders
email, source/request/approval, state, and revocation time. Security renders
password state/expiry/change, session count, and latest expiry.

Commands and bodies:

```js
jsonRequest('/api/admin/users/reset-password', 'POST', { email: selected.email }, fetcher);
jsonRequest('/api/admin/users/sign-out', 'POST', { email: selected.email }, fetcher);
jsonRequest('/api/admin/users/revoke', 'POST', { email: selected.email }, fetcher);
```

Patch `{item}` with `replaceByEmail()`, retain selection, rerender list/detail,
and announce success. Reset also opens the credential dialog. Revoked users
show no Reset command and no reactivation command.

- [ ] **Step 4: Verify responsive list/detail and security semantics**

At mobile width, selecting a row hides the list, reveals detail, moves focus
to its `h2`, and Back restores the row trigger. The revoke dialog states that
sessions end while request and audit history remain.

- [ ] **Step 5: Run Users and shared-admin tests**

```powershell
node --test admin-users.test.js admin.test.js
```

Expected: both files pass.

- [ ] **Step 6: Commit identity/security management**

```powershell
git add -- docs-site/admin-users.test.js site/admin/users.js site/admin/admin-core.js site/admin/admin.css
git commit -m "feat: add admin user security management"
```

---

### Task 9: Complete Authorization Management and Catalog Degradation

**Files:**
- Create: `docs-site/admin-authorization.test.js`
- Modify: `site/admin/authorization.js`
- Modify: `site/admin/admin.css`

**Interfaces:**
- Consumes: `GET /api/admin/authorization` and `GET /api/admin/releases` independently.
- Consumes: `PUT /api/admin/authorization/grants`.
- Produces: searchable grant list, focused complete-replacement editor, immediate local update.

- [ ] **Step 1: Write failing Authorization tests**

Cover independent parallel reads, Latest/version summary, revoked read-only
state, catalog failure preserving current policy, no guessed versions,
selection validation, exact full-replacement body, immediate update, and
absence of identity/security commands.

```js
assert.deepEqual(calls.find(({ path }) => path.endsWith('/grants')), {
  path: '/api/admin/authorization/grants',
  method: 'PUT',
  body: {
    email: 'person@example.com',
    include_latest: false,
    versions: ['v0.2.1'],
  },
});
assert.doesNotMatch(renderedText, /password|session|Approve|Reject|Revoke/i);
```

- [ ] **Step 2: Run the focused test and confirm RED**

```powershell
node --test admin-authorization.test.js
```

Expected: FAIL because the grant editor and degraded state do not exist.

- [ ] **Step 3: Implement complete grant replacement**

Load authorization and catalog independently. Render Latest toggle and trusted
historical checkboxes. Require Latest or one version while preserving valid
selection on error. Disable Save for revoked accounts or unavailable catalog.

On success, patch the returned item locally, retain selection, rerender the
directory/detail, and announce `Release authorization updated.` without
another GET.

- [ ] **Step 4: Run Authorization and shared-admin tests**

```powershell
node --test admin-authorization.test.js admin.test.js
```

Expected: both files pass.

- [ ] **Step 5: Commit Authorization management**

```powershell
git add -- docs-site/admin-authorization.test.js site/admin/authorization.js site/admin/admin.css
git commit -m "feat: add separate authorization management"
```

---

### Task 10: Update Durable Operations Docs and Run the Ship Gate

**Files:**
- Create: `docs-site/admin-preview.mjs`
- Create: `docs-site/admin-preview.test.js`
- Modify: `docs-site/package.json`
- Modify: `AGENTS.md:51-75`
- Modify: `CLAUDE.md:61-87`
- Modify: `docs/README.md:16-21`
- Modify: `docs/deployment.md:144-195,236-265`
- Modify: `docs/releasing.md:1-20`

**Interfaces:**
- Produces: `npm run preview:admin` on `http://127.0.0.1:4175` with deterministic fake recipients; it is not assembled into `dist-site`.
- Produces: durable migration, deployment, rollback, and verification instructions.

- [ ] **Step 1: Write a failing preview isolation test**

Add `admin-preview.test.js` that imports a `createAdminPreviewServer()` export,
starts on an ephemeral loopback port, requests `/users`,
`/api/admin/users`, and a module asset, and asserts the server address is
`127.0.0.1`. After `npm run build`, assert `dist-site/admin-preview.mjs` does
not exist.

- [ ] **Step 2: Implement the Node stdlib preview server**

Use only `node:http`, `node:fs/promises`, `node:path`, and `node:url`. Page
routes serve `site/admin/index.html`; asset routes serve the real source
files; API routes return deterministic `.example` identities for loaded,
revoked, temporary-password, and historical-grant states. Mutations return the
same route-specific shapes as the Worker and update in-memory fixture arrays.
Bind only `127.0.0.1` and export the server factory without starting on import.

Add to `package.json`:

```json
"preview:admin": "node admin-preview.mjs"
```

- [ ] **Step 3: Update durable documentation**

Document:

```text
Early access: request/consent plus approve/reject only.
Users: identity state, password reset, session sign-out, revoke.
Authorization: Latest and explicit versions only.
Policy storage: release_access_policies + release_account_versions.
Old /api/admin/access/* routes: removed.
Migration order: freeze admin mutations -> backup -> 0003 -> zero missing-policy
and Latest-mismatch counts -> Worker/assets together -> unfreeze -> smoke;
repeat the same guarded sequence in production.
Rollback: unsafe after first new policy mutation without forward fix or policy-to-legacy sync.
```

Include the exact parity queries from the approved spec. The freeze covers
approval, rejection, password reset, session sign-out, revoke, and grant
replacement while leaving recipient reads/downloads available.

Keep Access exact-email, sensitive logging, six focused npm scripts, aggregate
test, and build requirements in both agent instruction files. Link
`docs/releasing.md` to the deployment migration gate; do not rewrite unrelated
release publication steps.

- [ ] **Step 4: Run focused and aggregate verification**

From `docs-site`:

```powershell
npm run test:migration
npm run test:worker
npm run test:admin
npm run test:release-access
npm run test:download
npm run test:site
node --test *.test.js
npm run build
$assets = 'index.html','admin.css','admin.js','admin-core.js','early-access.js','users.js','authorization.js'
$assets | ForEach-Object {
  if (-not (Test-Path (Join-Path 'dist-site\admin' $_))) {
    throw "Missing assembled admin asset: $_"
  }
}
```

Expected: every suite passes, aggregate has zero failures, build succeeds, and
every required admin asset exists.

- [ ] **Step 5: Start the local admin preview and perform visual verification**

```powershell
npm run preview:admin
```

Use the browser at `http://127.0.0.1:4175/users`,
`/early-access`, and `/authorization`. Capture desktop and 320-pixel mobile
screenshots. Verify:

```text
nonblank page and correct active navigation
no overlap, clipping, or page-level horizontal scroll
loaded, empty, error, degraded-catalog, and revoked states
list/detail selection and mobile Back focus restoration
Approve/Reject, credential, Reset, Sign out, Revoke, and grant dialogs
keyboard-only operation and visible focus
dark mode, reduced motion, and forced colors
password/session commands absent from Authorization
grant commands absent from Users and Early access
```

Stop the preview process after screenshots and interaction checks.

- [ ] **Step 6: Run repository and structural checks**

From the repository root:

```powershell
git diff --check
C:/Users/thoule/.local/bin/sentrux.exe check .
C:/Users/thoule/.local/bin/sentrux.exe gate .
git status --short --branch --untracked-files=all
```

Expected: diff check clean; Sentrux check/gate pass without `gate --save`; only
intentional ALP-71 changes are present. The configured Sentrux executable was
missing during plan research: restore or correct the tool before this step,
and do not claim the structural gate if it remains unavailable.

- [ ] **Step 7: Commit docs and verification harness**

```powershell
git add -- docs-site/admin-preview.mjs docs-site/admin-preview.test.js docs-site/package.json AGENTS.md CLAUDE.md docs/README.md docs/deployment.md docs/releasing.md
git commit -m "docs: operate modular admin identity management"
```

- [ ] **Step 8: Update Linear ALP-71 with evidence**

Add one Linear comment containing the branch, implementation commits, exact
aggregate test count, build result, screenshot paths, Sentrux result, and any
rollout-only steps that remain. Do not mark ALP-71 complete until the original
objective's completion audit is green.

---

## Final Requirement Audit

Before claiming completion, map evidence to every item:

| Requirement | Evidence |
| --- | --- |
| Admin extends beyond early access | `/users` and `/authorization` protected route/asset tests plus desktop/mobile screenshots |
| Users and identity management | Users read/mutation Worker tests and `admin-users.test.js` |
| Security management | Reset, sign-out, revoke, password non-reuse, and logout failure tests |
| Authorization separate from identity | Migration 0003, disjoint response-key tests, policy-only SQL test, command-absence UI tests |
| Grants and password commands not co-located | `admin-users.test.js`, `admin-authorization.test.js`, and screenshots |
| Modular and ready for enhancements | Protected shared shell plus four focused ES modules; no combined admin script behavior |
| Dynamic and immediate | Route-specific `{item}` mutation tests and no-refetch UI tests |
| Secure admin boundary | Access-before-body/D1/assets, exact host isolation, safe DOM, no persistence/logging tests |
| Accessible/responsive | semantic/focus/dialog tests and 320-pixel/dark/reduced-motion/forced-colors visual checks |
| Documentation tracked | committed spec/plan/ops docs and ALP-71 comments with evidence |
| Migration cutover cannot lose policy writes | documented mutation freeze, zero-count parity queries, and atomic Worker/assets deployment sequence |
| Verification complete | all Node suites, production build, asset checks, Sentrux check/gate, clean diff/status |

If any evidence is missing, weak, or contradicted by current state, keep the
goal active and continue work rather than narrowing the definition of done.
