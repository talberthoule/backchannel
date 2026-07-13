import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { DatabaseSync } from 'node:sqlite';
import test from 'node:test';

import worker, { handleInterest } from './worker.js';
import * as workerModule from './worker.js';
import { createSessionToken } from './release-access.js';

const validVerification = {
  success: true,
  hostname: 'backchannel.page',
  action: 'interest',
};

function request(body = { email: 'Person@Example.com', token: 'token' }, init = {}) {
  return new Request('https://backchannel.page/api/interest', {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      origin: 'https://backchannel.page',
      ...init.headers,
    },
    body: JSON.stringify(body),
    ...init,
  });
}

function bindings({ run = async () => ({ success: true }) } = {}) {
  const calls = [];
  return {
    calls,
    env: {
      TURNSTILE_SECRET_KEY: 'worker-secret',
      INTEREST_DB: {
        prepare(sql) {
          return {
            bind(...values) {
              calls.push({ sql, values });
              return { run };
            },
          };
        },
      },
      ASSETS: { fetch: async () => new Response('asset') },
    },
  };
}

function verifier(payload = validVerification, status = 200) {
  return async () => new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

const interestRecord = {
  email: 'new@example.com',
  status: 'interested',
  source: 'homepage',
  consent_version: '2026-07-11',
  consent_at: '2026-07-11 12:00:00',
  created_at: '2026-07-11 12:00:00',
  invited_at: null,
  last_contacted_at: null,
  release_decision: 'pending',
  release_reviewed_at: null,
};

const interestMigration = readFileSync(
  new URL('./migrations/0001_interest_subscribers.sql', import.meta.url), 'utf8',
);
const releaseMigration = readFileSync(
  new URL('./migrations/0002_release_access.sql', import.meta.url), 'utf8',
);
const policyMigration = readFileSync(
  new URL('./migrations/0003_release_access_policies.sql', import.meta.url), 'utf8',
);

function sqliteD1() {
  const database = new DatabaseSync(':memory:');
  database.exec('PRAGMA foreign_keys = ON');
  database.exec(interestMigration);
  database.exec(releaseMigration);
  database.exec(policyMigration);
  const binding = {
    prepare(sql) {
      const prepared = database.prepare(sql);
      let values = [];
      const statementValue = {
        bind(...bound) { values = bound; return statementValue; },
        all() { return { results: prepared.all(...values) }; },
        first() { return prepared.get(...values); },
        run() {
          const result = prepared.run(...values);
          return { success: true, meta: { changes: Number(result.changes) } };
        },
      };
      return statementValue;
    },
    batch(statements) {
      database.exec('BEGIN IMMEDIATE');
      try {
        const results = statements.map((statementValue) => statementValue.run());
        database.exec('COMMIT');
        return results;
      } catch (error) {
        database.exec('ROLLBACK');
        throw error;
      }
    },
  };
  return { database, binding };
}

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

function adminReleaseManifest(version) {
  return {
    version,
    published_at: '2026-07-12T12:00:00Z',
    commit: 'a'.repeat(40),
    assets: [{
      id: 'windows-x64', platform: 'Windows x64', filename: 'Backchannel-windows-x64.zip',
      key: `releases/${version}/Backchannel-windows-x64.zip`, size: 1,
      sha256: 'b'.repeat(64), content_type: 'application/zip',
    }],
  };
}

function adminCatalogBucket(
  versions = ['v0.1.1', 'v0.2.0', 'v1.2.3'], latest = 'v1.2.3',
) {
  return {
    async list() {
      return {
        objects: versions.map((version) => ({ key: `releases/${version}/manifest.json` })),
      };
    },
    async get(key) {
      if (key === 'releases/latest.json') return { json: async () => ({ version: latest }) };
      const version = key.split('/')[1];
      return versions.includes(version) ? { json: async () => adminReleaseManifest(version) } : null;
    },
  };
}

function adminRequest(path = '/api/admin/interests', init = {}) {
  return new Request(`https://admin.backchannel.page${path}`, {
    method: 'GET',
    headers: { 'cf-access-jwt-assertion': 'access-token', ...init.headers },
    ...init,
  });
}

function adminBindings({
  all = async () => ({ results: [interestRecord] }),
  first = async () => ({ state: 'active', release_decision: 'approved' }),
  batch = async (statements) => statements.map(() => ({ success: true, meta: { changes: 1 } })),
  releases = adminCatalogBucket(),
  asset = async () => new Response('private asset', {
    headers: { 'content-type': 'text/html; charset=utf-8' },
  }),
} = {}) {
  const calls = [];
  const batchCalls = [];
  const assetRequests = [];
  return {
    calls,
    assetRequests,
    env: {
      ADMIN_EMAIL: 'owner@example.com',
      ACCESS_TEAM_DOMAIN: 'backchannel.cloudflareaccess.com',
      ACCESS_AUD: 'admin-audience',
      INTEREST_DB: {
        prepare(sql) {
          const call = { sql, values: [] };
          calls.push(call);
          const statement = {
            bind(...values) {
              call.values = values;
              return statement;
            },
            all,
            first,
          };
          return statement;
        },
        async batch(statements) {
          batchCalls.push(statements);
          return batch(statements);
        },
      },
      RELEASES: releases,
      ASSETS: {
        async fetch(assetRequest) {
          assetRequests.push(assetRequest);
          return asset(assetRequest);
        },
      },
    },
    batchCalls,
  };
}

const allowOwner = async () => ({ email: 'owner@example.com' });

test('exports an injectable request router', () => {
  assert.equal(typeof workerModule.route, 'function');
});

test('keeps the Worker execution context out of verifier injection', () => {
  assert.notEqual(worker.fetch, workerModule.route);
});

test('rejects methods other than POST', async () => {
  const { env, calls } = bindings();
  const response = await handleInterest(new Request(
    'https://backchannel.page/api/interest',
    { method: 'GET', headers: { origin: 'https://backchannel.page' } },
  ), env, verifier());
  assert.equal(response.status, 405);
  assert.equal(response.headers.get('allow'), 'POST');
  assert.equal(calls.length, 0);
});

test('rejects cross-origin submissions', async () => {
  const { env, calls } = bindings();
  const response = await handleInterest(request(undefined, {
    headers: { origin: 'https://attacker.example' },
  }), env, verifier());
  assert.equal(response.status, 403);
  assert.equal(calls.length, 0);
});

test('rejects invalid email before Turnstile or D1', async () => {
  const { env, calls } = bindings();
  let verifies = 0;
  const response = await handleInterest(
    request({ email: 'not-an-email', token: 'token' }),
    env,
    async () => { verifies += 1; return verifier()(); },
  );
  assert.equal(response.status, 400);
  assert.equal(verifies, 0);
  assert.equal(calls.length, 0);
});

test('rejects malformed and oversized bodies before Turnstile or D1', async () => {
  const { env, calls } = bindings();
  let verifies = 0;
  const fetcher = async () => { verifies += 1; return verifier()(); };
  const headers = { 'content-type': 'application/json', origin: 'https://backchannel.page' };

  const malformed = await handleInterest(new Request(
    'https://backchannel.page/api/interest',
    { method: 'POST', headers, body: '{' },
  ), env, fetcher);
  const oversized = await handleInterest(new Request(
    'https://backchannel.page/api/interest',
    { method: 'POST', headers, body: 'x'.repeat(4097) },
  ), env, fetcher);

  assert.equal(malformed.status, 400);
  assert.equal(oversized.status, 413);
  assert.equal(verifies, 0);
  assert.equal(calls.length, 0);
});

test('rejects failed, wrong-host, and wrong-action Turnstile results', async () => {
  for (const payload of [
    { success: false },
    { ...validVerification, hostname: 'example.com' },
    { ...validVerification, action: 'login' },
  ]) {
    const { env, calls } = bindings();
    const response = await handleInterest(request(), env, verifier(payload));
    assert.equal(response.status, 400);
    assert.equal(calls.length, 0);
  }
});

test('normalizes email and writes only consent metadata', async () => {
  const { env, calls } = bindings();
  const response = await handleInterest(request(), env, verifier());
  assert.equal(response.status, 200);
  assert.equal(response.headers.get('cache-control'), 'no-store');
  assert.deepEqual(calls[0].values, ['person@example.com', '2026-07-11']);
  assert.match(calls[0].sql, /ON CONFLICT\(email\) DO NOTHING/);
  assert.deepEqual(await response.json(), {
    ok: true,
    message: 'Thanks - your early-access request is saved.',
  });
});

test('returns the same success response when D1 reports a duplicate', async () => {
  const first = bindings({ run: async () => ({ success: true, meta: { changes: 1 } }) });
  const duplicate = bindings({ run: async () => ({ success: true, meta: { changes: 0 } }) });
  const firstResponse = await handleInterest(request(), first.env, verifier());
  const duplicateResponse = await handleInterest(request(), duplicate.env, verifier());
  assert.equal(await firstResponse.text(), await duplicateResponse.text());
});

test('returns retryable service errors without leaking details', async () => {
  const verifyFailure = await handleInterest(
    request(), bindings().env, async () => { throw new Error('upstream secret'); },
  );
  assert.equal(verifyFailure.status, 503);
  assert.doesNotMatch(await verifyFailure.text(), /secret/);

  const dbFailure = bindings({ run: async () => { throw new Error('database detail'); } });
  const dbResponse = await handleInterest(request(), dbFailure.env, verifier());
  assert.equal(dbResponse.status, 503);
  assert.doesNotMatch(await dbResponse.text(), /database detail/);
});

test('routes unknown API paths to JSON 404 instead of static assets', async () => {
  const response = await worker.fetch(
    new Request('https://backchannel.page/api/unknown'),
    bindings().env,
  );
  assert.equal(response.status, 404);
  assert.equal(response.headers.get('cache-control'), 'no-store');
});

test('validates Access JWTs against the configured Cloudflare issuer and audience', async () => {
  assert.equal(typeof workerModule.verifyAccessToken, 'function');
  const calls = {};
  const payload = await workerModule.verifyAccessToken(
    'signed-token',
    {
      ACCESS_TEAM_DOMAIN: 'Backchannel.CloudflareAccess.com ',
      ACCESS_AUD: 'admin-audience',
    },
    {
      createRemoteJWKSet(url) {
        calls.jwks = url.toString();
        return 'remote-keys';
      },
      async jwtVerify(token, keys, options) {
        calls.verify = { token, keys, options };
        return { payload: { email: 'owner@example.com' } };
      },
    },
  );

  assert.deepEqual(payload, { email: 'owner@example.com' });
  assert.equal(
    calls.jwks,
    'https://backchannel.cloudflareaccess.com/cdn-cgi/access/certs',
  );
  assert.deepEqual(calls.verify, {
    token: 'signed-token',
    keys: 'remote-keys',
    options: {
      issuer: 'https://backchannel.cloudflareaccess.com',
      audience: 'admin-audience',
    },
  });
});

test('rejects a non-Cloudflare Access issuer before fetching keys', async () => {
  assert.equal(typeof workerModule.verifyAccessToken, 'function');
  let fetched = false;
  await assert.rejects(() => workerModule.verifyAccessToken(
    'signed-token',
    { ACCESS_TEAM_DOMAIN: 'attacker.example', ACCESS_AUD: 'admin-audience' },
    {
      createRemoteJWKSet() { fetched = true; },
      async jwtVerify() { return { payload: {} }; },
    },
  ));
  assert.equal(fetched, false);
});

test('admin routes fail closed when Access configuration or assertion is missing', async () => {
  const { env } = adminBindings();
  let verified = false;
  const verify = async () => { verified = true; return { email: 'owner@example.com' }; };

  const unconfigured = await workerModule.route(
    adminRequest(),
    { INTEREST_DB: env.INTEREST_DB, ASSETS: env.ASSETS },
    verify,
  );
  const noAssertion = await workerModule.route(
    adminRequest(undefined, { headers: {} }),
    env,
    verify,
  );

  assert.equal(unconfigured.status, 503);
  assert.equal(noAssertion.status, 401);
  assert.equal(unconfigured.headers.get('cache-control'), 'no-store');
  assert.equal(noAssertion.headers.get('cache-control'), 'no-store');
  assert.equal(verified, false);
});

test('admin routes reject invalid assertions without leaking verifier details', async () => {
  const { env, calls } = adminBindings();
  const response = await workerModule.route(
    adminRequest(),
    env,
    async () => { throw new Error('token detail'); },
  );

  assert.equal(response.status, 401);
  assert.doesNotMatch(await response.text(), /token detail/);
  assert.equal(calls.length, 0);
});

test('admin routes allow only the normalized configured email', async () => {
  const deniedBindings = adminBindings();
  const denied = await workerModule.route(
    adminRequest(),
    deniedBindings.env,
    async () => ({ email: 'other@example.com' }),
  );
  assert.equal(denied.status, 403);
  assert.equal(deniedBindings.calls.length, 0);

  const allowedBindings = adminBindings();
  const allowed = await workerModule.route(
    adminRequest(),
    allowedBindings.env,
    async () => ({ email: ' OWNER@EXAMPLE.COM ' }),
  );
  assert.equal(allowed.status, 200);
  assert.deepEqual(await allowed.json(), { items: [interestRecord] });
});

test('admin API selects only consent records in newest-first order', async () => {
  const { env, calls } = adminBindings();
  const response = await workerModule.route(adminRequest(), env, allowOwner);

  assert.equal(response.status, 200);
  assert.equal(response.headers.get('cache-control'), 'no-store');
  assert.equal(calls.length, 1);
  assert.doesNotMatch(calls[0].sql, /SELECT\s+\*/i);
  for (const field of Object.keys(interestRecord)) assert.match(calls[0].sql, new RegExp(field));
  assert.match(calls[0].sql, /ORDER BY (?:i\.)?created_at DESC/);
});

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

  const interestItem = (await interests.json()).items[0];
  const userItem = (await users.json()).items[0];
  const authorizationItem = (await authorization.json()).items[0];

  assert.deepEqual(Object.keys(interestItem).sort(), [
    'consent_at', 'consent_version', 'created_at', 'email', 'invited_at',
    'last_contacted_at', 'release_decision', 'release_reviewed_at', 'source', 'status',
  ]);
  assert.deepEqual(Object.keys(userItem).sort(), [
    'active_session_count', 'approved_at', 'email', 'latest_session_expires_at',
    'must_change_password', 'password_changed_at', 'password_expires_at',
    'requested_at', 'revoked_at', 'source', 'state',
  ]);
  assert.equal(userItem.must_change_password, true);
  assert.deepEqual(Object.keys(authorizationItem).sort(), [
    'account_state', 'email', 'include_latest', 'updated_at', 'versions',
  ]);
  assert.equal(authorizationItem.include_latest, true);
  assert.deepEqual(authorizationItem.versions, ['v0.2.1']);
});

test('admin authorization rejects malformed versions rows generically', async () => {
  const { env } = adminBindings({
    all: async () => ({ results: [{
      email: 'person@example.com',
      account_state: 'active',
      include_latest: 1,
      updated_at: '2026-07-12T12:00:00.000Z',
      versions: ['v0.2.1'],
    }] }),
  });

  const response = await workerModule.route(
    adminRequest('/api/admin/authorization'), env, allowOwner,
  );

  assert.equal(response.status, 503);
  assert.deepEqual(await response.json(), {
    ok: false,
    message: 'Request could not be completed.',
  });
});

test('admin read endpoints authorize before D1 reads', async () => {
  let d1Calls = 0;
  const env = {
    ...adminBindings().env,
    INTEREST_DB: {
      prepare() {
        d1Calls += 1;
        throw new Error('D1 must not be reached');
      },
    },
  };
  const denyOwner = async () => ({ email: 'other@example.com' });

  for (const path of ['/api/admin/users', '/api/admin/authorization']) {
    const response = await workerModule.route(adminRequest(path), env, denyOwner);
    assert.equal(response.status, 403);
  }
  assert.equal(d1Calls, 0);
});

function adminJson(path, body, init = {}) {
  return adminRequest(path, {
    method: init.method || 'POST',
    headers: {
      'cf-access-jwt-assertion': 'access-token',
      origin: 'https://admin.backchannel.page',
      'content-type': 'application/json; charset=utf-8',
      ...init.headers,
    },
    body: typeof body === 'string' ? body : JSON.stringify(body),
  });
}

const fixedDependencies = {
  now: () => new Date('2026-07-12T12:00:00.000Z'),
  randomBytes: (length) => new Uint8Array(length),
};

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
  assert.deepEqual({ ...bindings.db.prepare(`
    SELECT state, must_change_password FROM release_accounts WHERE email = ?
  `).get('person@example.com') }, { state: 'active', must_change_password: 1 });
  assert.equal(bindings.db.prepare(`
    SELECT include_latest FROM release_access_policies WHERE email = ?
  `).get('person@example.com').include_latest, 1);
  assert.equal(bindings.db.prepare(`
    SELECT count(*) AS count FROM release_account_versions WHERE email = ?
  `).get('person@example.com').count, 0);
});

test('approval accepts exactly an email body', async () => {
  let r2Calls = 0;
  const bindings = adminBindings({
    releases: {
      async list() { r2Calls += 1; throw new Error('R2 must not be reached'); },
      async get() { r2Calls += 1; throw new Error('R2 must not be reached'); },
    },
  });
  const response = await workerModule.route(
    adminJson('/api/admin/interests/approve', {
      email: 'person@example.com',
      include_latest: true,
      versions: [],
    }),
    bindings.env,
    allowOwner,
    fixedDependencies,
  );

  assert.equal(response.status, 400);
  assert.deepEqual(await response.json(), { ok: false, message: 'Request is invalid.' });
  assert.equal(bindings.calls.length, 0);
  assert.equal(bindings.batchCalls.length, 0);
  assert.equal(r2Calls, 0);
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
  const body = await response.json();
  assert.equal(body.ok, true);
  assert.deepEqual(Object.keys(body.item).sort(), [
    'active_session_count', 'approved_at', 'email', 'latest_session_expires_at',
    'must_change_password', 'password_changed_at', 'password_expires_at',
    'requested_at', 'revoked_at', 'source', 'state',
  ]);
  assert.equal(body.item.active_session_count, 0);
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
  assert.equal(bindings.db.prepare(`
    SELECT count(*) AS count FROM release_access_events
    WHERE email = ? AND action = 'session_sign_out'
  `).get('person@example.com').count, 1);
});

test('admin authorization runs before mutation body parsing', async () => {
  const { env, calls } = adminBindings();
  const response = await workerModule.route(
    adminJson('/api/admin/interests/approve', '{'),
    env,
    async () => ({ email: 'other@example.com' }),
    fixedDependencies,
  );
  assert.equal(response.status, 403);
  assert.equal(calls.length, 0);
});

test('admin mutations enforce exact origin, JSON media type, and bounded bodies', async () => {
  const cases = [
    [adminJson('/api/admin/interests/reject', { email: 'person@example.com' }, {
      headers: { origin: 'https://attacker.example' },
    }), 403],
    [adminJson('/api/admin/interests/reject', { email: 'person@example.com' }, {
      headers: { 'content-type': 'text/plain' },
    }), 415],
    [adminJson('/api/admin/interests/reject', 'x'.repeat(8193)), 413],
  ];
  for (const [requestValue, expected] of cases) {
    const { env, calls } = adminBindings();
    const response = await workerModule.route(requestValue, env, allowOwner, fixedDependencies);
    assert.equal(response.status, expected);
    assert.equal(calls.length, 0);
    assert.equal(response.headers.get('cache-control'), 'no-store');
  }
});

test('approval normalizes input and creates a one-time credential without binding plaintext', async () => {
  const { env, calls, batchCalls } = adminBindings();
  const response = await workerModule.route(adminJson('/api/admin/interests/approve', {
    email: ' Person@Example.com ',
  }), env, allowOwner, fixedDependencies);

  assert.equal(response.status, 201);
  const { credential } = await response.json();
  assert.deepEqual({ ...credential, password: undefined }, {
    email: 'person@example.com',
    password: undefined,
    password_expires_at: '2026-07-15T12:00:00.000Z',
  });
  assert.equal(credential.password.length, 20);
  assert.equal(batchCalls.length, 1);
  const batchSql = calls.map(({ sql }) => sql);
  assert.match(batchSql[0], /INSERT INTO release_accounts[\s\S]+SELECT[\s\S]+WHERE EXISTS/i);
  assert.doesNotMatch(batchSql[0], /include_latest|release_account_versions/i);
  assert.match(batchSql[1], /UPDATE interest_subscribers[\s\S]+changes\(\)\s*=\s*1/i);
  assert.match(batchSql[2], /INSERT INTO release_access_policies[\s\S]+changes\(\)\s*=\s*1/i);
  assert.match(batchSql[3], /INSERT INTO release_access_events[\s\S]+changes\(\)\s*=\s*1/i);
  assert.equal(JSON.stringify(calls.map(({ values }) => values)).includes(credential.password), false);
  assert.ok(calls.flatMap(({ values }) => values).includes('person@example.com'));
});

test('approval fails generically when a concurrent account wins', async () => {
  const duplicate = adminBindings({
    batch: async () => { throw new Error('UNIQUE release_accounts.email'); },
  });
  const duplicateResponse = await workerModule.route(adminJson('/api/admin/interests/approve', {
    email: 'person@example.com',
  }), duplicate.env, allowOwner, fixedDependencies);
  assert.equal(duplicateResponse.status, 409);
  assert.doesNotMatch(await duplicateResponse.text(), /UNIQUE|person@example|password/i);
});

test('admin entitlement input requires a boolean and unique strict versions', async () => {
  const invalidBodies = [
    { email: 'person@example.com', include_latest: 'true', versions: [] },
    { email: 'person@example.com', include_latest: true, versions: ['1.2.3'] },
    { email: 'person@example.com', include_latest: true, versions: ['v1.2.3', 'v1.2.3'] },
  ];
  for (const body of invalidBodies) {
    const { env, calls } = adminBindings();
    const response = await workerModule.route(
      adminJson('/api/admin/authorization/grants', body, { method: 'PUT' }),
      env,
      allowOwner,
      fixedDependencies,
    );
    assert.equal(response.status, 400);
    assert.equal(calls.length, 0);
  }
});

test('admin entitlement input rejects more than 100 unique canonical versions', async () => {
  const { env, calls } = adminBindings();
  const versions = Array.from({ length: 101 }, (_, index) => `v1.2.${index}`);
  const response = await workerModule.route(adminJson('/api/admin/authorization/grants', {
    email: 'person@example.com', include_latest: true, versions,
  }, { method: 'PUT' }), env, allowOwner, fixedDependencies);
  assert.equal(new Set(versions).size, 101);
  assert.equal(response.status, 400);
  assert.equal(calls.length, 0);
});

test('admin entitlement input enforces the 32-character canonical version boundary', async () => {
  const accepted = `v${'1'.repeat(10)}.${'2'.repeat(9)}.${'3'.repeat(10)}`;
  const rejected = `${accepted}4`;
  assert.equal(accepted.length, 32);
  assert.equal(rejected.length, 33);

  const invalid = adminBindings();
  const response = await workerModule.route(adminJson('/api/admin/authorization/grants', {
    email: 'person@example.com', include_latest: true, versions: [rejected],
  }, { method: 'PUT' }), invalid.env, allowOwner, fixedDependencies);
  assert.equal(response.status, 400);
  assert.equal(invalid.calls.length, 0);
});

test('grant replacement validates the trusted catalog before D1 mutation', async () => {
  for (const [path, method] of [
    ['/api/admin/authorization/grants', 'PUT'],
  ]) {
    const unpublished = adminBindings({ releases: adminCatalogBucket(['v1.2.3']) });
    const unpublishedResponse = await workerModule.route(adminJson(path, {
      email: 'person@example.com', include_latest: false, versions: ['v9.9.9'],
    }, { method }), unpublished.env, allowOwner, fixedDependencies);
    assert.equal(unpublishedResponse.status, 409);
    assert.equal(unpublished.calls.length, 0);
    assert.equal(unpublished.batchCalls.length, 0);
    assert.doesNotMatch(await unpublishedResponse.text(), /v9\.9\.9|credential|manifest/i);

    const malformed = adminBindings({
      releases: {
        async list() { return { objects: [{ key: 'releases/v1.2.3/manifest.json' }] }; },
        async get() { return { json: async () => ({ private_key: 'secret' }) }; },
      },
    });
    const malformedResponse = await workerModule.route(adminJson(path, {
      email: 'person@example.com', include_latest: true, versions: [],
    }, { method }), malformed.env, allowOwner, fixedDependencies);
    assert.equal(malformedResponse.status, 503);
    assert.equal(malformed.calls.length, 0);
    assert.equal(malformed.batchCalls.length, 0);
    assert.doesNotMatch(await malformedResponse.text(), /secret|catalog|manifest/i);

    const noLatest = adminBindings({
      releases: {
        async list() { return { objects: [{ key: 'releases/v1.2.3/manifest.json' }] }; },
        async get(key) {
          return key.endsWith('latest.json') ? null : { json: async () => adminReleaseManifest('v1.2.3') };
        },
      },
    });
    const noLatestResponse = await workerModule.route(adminJson(path, {
      email: 'person@example.com', include_latest: true, versions: [],
    }, { method }), noLatest.env, allowOwner, fixedDependencies);
    assert.equal(noLatestResponse.status, 503);
    assert.equal(noLatest.calls.length, 0);
    assert.equal(noLatest.batchCalls.length, 0);
  }
});

test('interest and user mutations return a route-specific rejection item', async () => {
  const rejectedItem = {
    ...interestRecord,
    email: 'person@example.com',
    release_decision: 'rejected',
    release_reviewed_at: '2026-07-12T12:00:00.000Z',
  };
  const { env, calls, batchCalls } = adminBindings({ first: async () => rejectedItem });
  const response = await workerModule.route(adminJson('/api/admin/interests/reject', {
    email: ' Person@Example.com ',
  }), env, allowOwner, fixedDependencies);
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { ok: true, item: rejectedItem });
  assert.equal(batchCalls.length, 1);
  assert.equal(calls.length, 3);
  assert.match(calls[0].sql, /UPDATE interest_subscribers[\s\S]+release_decision/i);
  assert.match(calls[0].sql, /release_decision\s*=\s*'pending'/i);
  assert.match(calls[0].sql, /NOT EXISTS[\s\S]+release_accounts/i);
  assert.match(calls[1].sql, /rejection/);
  assert.match(calls[1].sql, /changes\(\)\s*=\s*1/i);
  assert.match(calls[1].sql, /release_decision\s*=\s*'rejected'/i);
  assert.match(calls[1].sql, /release_reviewed_at\s*=\s*\?/i);
  assert.match(calls[1].sql, /NOT EXISTS[\s\S]+release_accounts/i);
  assert.ok(calls[1].values.includes('2026-07-12T12:00:00.000Z'));

  const conflict = adminBindings({
    batch: async (statements) => statements.map(() => ({ success: true, meta: { changes: 0 } })),
  });
  const conflictResponse = await workerModule.route(adminJson('/api/admin/interests/reject', {
    email: 'person@example.com',
  }), conflict.env, allowOwner, fixedDependencies);
  assert.equal(conflictResponse.status, 409);
  assert.deepEqual(await conflictResponse.json(), {
    ok: false, message: 'Request could not be completed.',
  });
});

test('same-timestamp rejection retry cannot emit a second event in real SQLite', async (context) => {
  const { database, binding } = sqliteD1();
  context.after(() => database.close());
  database.prepare(`
    INSERT INTO interest_subscribers (email, consent_version)
    VALUES (?, '2026-07-12')
  `).run('person@example.com');
  const env = {
    ADMIN_EMAIL: 'owner@example.com',
    ACCESS_TEAM_DOMAIN: 'backchannel.cloudflareaccess.com',
    ACCESS_AUD: 'admin-audience',
    INTEREST_DB: binding,
  };
  const rejectRequest = () => adminJson('/api/admin/interests/reject', {
    email: 'person@example.com',
  });

  const accepted = await workerModule.route(
    rejectRequest(), env, allowOwner, fixedDependencies,
  );
  const retried = await workerModule.route(
    rejectRequest(), env, allowOwner, fixedDependencies,
  );

  assert.equal(accepted.status, 200);
  assert.equal(retried.status, 409);
  assert.equal(database.prepare(`
    SELECT count(*) AS count FROM release_access_events WHERE action = 'rejection'
  `).get().count, 1);
  assert.equal(database.prepare(`
    SELECT release_decision FROM interest_subscribers WHERE email = ?
  `).get('person@example.com').release_decision, 'rejected');
});

test('approved account and session survive a rejected-state race in real SQLite', async (context) => {
  const { database, binding } = sqliteD1();
  context.after(() => database.close());
  database.prepare(`
    INSERT INTO interest_subscribers (email, consent_version)
    VALUES (?, '2026-07-12')
  `).run('person@example.com');
  const env = {
    ADMIN_EMAIL: 'owner@example.com',
    ACCESS_TEAM_DOMAIN: 'backchannel.cloudflareaccess.com',
    ACCESS_AUD: 'admin-audience',
    INTEREST_DB: binding,
    RELEASES: adminCatalogBucket(['v1.2.3']),
  };

  const approval = await workerModule.route(adminJson('/api/admin/interests/approve', {
    email: 'person@example.com',
  }), env, allowOwner, fixedDependencies);
  assert.equal(approval.status, 201);
  const token = await createSessionToken((length) => new Uint8Array(length).fill(31));
  database.prepare(`
    INSERT INTO release_sessions
      (token_hash, email, password_change_only, created_at, expires_at)
    VALUES (?, 'person@example.com', 0, ?, ?)
  `).run(token.tokenHash, '2026-07-12T12:00:00.000Z', '2026-07-19T12:00:00.000Z');

  const rejection = await workerModule.route(adminJson('/api/admin/interests/reject', {
    email: 'person@example.com',
  }), env, allowOwner, fixedDependencies);
  assert.equal(rejection.status, 409);
  assert.equal(database.prepare(`
    SELECT release_decision FROM interest_subscribers WHERE email = ?
  `).get('person@example.com').release_decision, 'approved');

  const sessionRequest = () => downloadRequest('/api/download/session', undefined, {
    headers: { cookie: `__Host-backchannel_release=${token.token}` },
  });
  const coherent = await workerModule.route(
    sessionRequest(), env, undefined, downloadDependencies(),
  );
  assert.equal((await coherent.json()).authenticated, true);

  database.prepare(`
    UPDATE interest_subscribers SET release_decision = 'rejected' WHERE email = ?
  `).run('person@example.com');
  const inconsistent = await workerModule.route(
    sessionRequest(), env, undefined, downloadDependencies(),
  );
  assert.deepEqual(await inconsistent.json(), { authenticated: false });
});

test('grant replacement checks active state and batches delete, inserts, update, and event', async () => {
  const { env, calls, batchCalls } = adminBindings();
  const response = await workerModule.route(adminJson('/api/admin/authorization/grants', {
    email: 'person@example.com', include_latest: false, versions: ['v1.2.3'],
  }, { method: 'PUT' }), env, allowOwner, fixedDependencies);
  assert.equal(response.status, 200);
  assert.equal(batchCalls.length, 1);
  assert.match(calls[0].sql, /SELECT[\s\S]+release_accounts/i);
  assert.match(calls[1].sql, /DELETE FROM release_account_versions/i);
  assert.match(calls[1].sql, /EXISTS[\s\S]+state = 'active'/i);
  assert.match(calls[2].sql, /INSERT INTO release_account_versions/i);
  assert.match(calls[2].sql, /WHERE EXISTS[\s\S]+state = 'active'/i);
  assert.match(calls[3].sql, /UPDATE release_accounts/i);
  assert.match(calls[4].sql, /grant_change/);
  assert.match(calls[4].sql, /WHERE EXISTS[\s\S]+state = 'active'/i);

  const denied = adminBindings();
  const deniedResponse = await workerModule.route(adminJson('/api/admin/authorization/grants', {
    email: 'person@example.com', include_latest: false, versions: [],
  }, { method: 'PUT' }), denied.env, allowOwner, fixedDependencies);
  assert.equal(deniedResponse.status, 400);
  assert.equal(denied.calls.length, 0);
});

test('password reset requires its exact batch and audit event', async () => {
  const observed = {
    state: 'active', release_decision: 'approved',
    password_hash: 'observed-hash', password_salt: 'observed-salt',
    password_iterations: 600000, must_change_password: 0, password_expires_at: null,
  };
  const cases = [
    [
      { success: true, meta: { changes: 1 } },
      { success: true, meta: { changes: 0 } },
      { success: true, meta: { changes: 0 } },
    ],
    [
      { success: true, meta: { changes: 1 } },
      { success: true, meta: { changes: 0 } },
      { success: true, meta: { changes: 1 } },
      { success: true, meta: { changes: 1 } },
    ],
  ];

  for (const results of cases) {
    const bindings = adminBindings({
      first: async () => observed,
      batch: async () => results,
    });
    const response = await workerModule.route(
      adminJson('/api/admin/users/reset-password', { email: 'person@example.com' }),
      bindings.env,
      allowOwner,
      fixedDependencies,
    );
    const text = await response.text();

    assert.notEqual(response.status, 200);
    assert.doesNotMatch(text, /credential|password|person@example\.com/i);
  }
});

test('reset and revoke delete sessions atomically without reactivating accounts', async () => {
  const observed = {
    state: 'active', release_decision: 'approved',
    password_hash: 'observed-hash', password_salt: 'observed-salt',
    password_iterations: 600000, must_change_password: 0, password_expires_at: null,
  };
  const activeUser = {
    email: 'person@example.com', state: 'active', source: 'homepage',
    requested_at: '2026-07-12T11:00:00.000Z', approved_at: '2026-07-12T12:00:00.000Z',
    must_change_password: 1, password_expires_at: '2026-07-15T12:00:00.000Z',
    password_changed_at: null, revoked_at: null, active_session_count: 0,
    latest_session_expires_at: null,
  };
  let resetReads = 0;
  const reset = adminBindings({
    first: async () => (resetReads++ === 0 ? observed : activeUser),
  });
  const resetResponse = await workerModule.route(adminJson('/api/admin/users/reset-password', {
    email: 'person@example.com',
  }), reset.env, allowOwner, fixedDependencies);
  assert.equal(resetResponse.status, 200);
  const resetBody = await resetResponse.json();
  const resetCredential = resetBody.credential;
  assert.deepEqual(Object.keys(resetCredential).sort(), [
    'email', 'password', 'password_expires_at',
  ]);
  assert.deepEqual(resetBody.item, { ...activeUser, must_change_password: true });
  assert.equal(resetCredential.password.length, 20);
  assert.equal(reset.batchCalls.length, 1);
  for (const field of [
    'password_hash', 'password_salt', 'password_iterations',
    'must_change_password', 'password_expires_at',
  ]) assert.match(reset.calls[0].sql, new RegExp(field));
  assert.match(reset.calls[1].sql, /UPDATE release_accounts[\s\S]+must_change_password[\s\S]+password_changed_at/i);
  assert.match(reset.calls[1].sql, /release_decision = 'approved'/i);
  assert.match(reset.calls[1].sql, /password_hash\s*=\s*\?[\s\S]+password_salt\s*=\s*\?[\s\S]+password_iterations\s*=\s*\?[\s\S]+must_change_password\s*=\s*\?[\s\S]+password_expires_at IS \?/i);
  for (const value of ['observed-hash', 'observed-salt', 600000, 0, null]) {
    assert.ok(reset.calls[1].values.includes(value));
  }
  assert.doesNotMatch(reset.calls[1].sql, /SET\s+state\s*=/i);
  assert.match(reset.calls[2].sql, /DELETE FROM release_sessions/i);
  assert.match(reset.calls[3].sql, /password_reset/);
  const newHash = reset.calls[1].values[0];
  const newSalt = reset.calls[1].values[1];
  const newExpiry = reset.calls[1].values[3];
  for (const call of reset.calls.slice(2, 4)) {
    assert.match(call.sql, /EXISTS[\s\S]+state = 'active'/i);
    assert.match(call.sql, /release_decision = 'approved'/i);
    assert.match(call.sql, /password_hash = \?[\s\S]+password_salt = \?[\s\S]+password_expires_at = \?/i);
    assert.ok(call.values.includes(newHash));
    assert.ok(call.values.includes(newSalt));
    assert.ok(call.values.includes(newExpiry));
  }
  assert.equal(JSON.stringify(reset.calls).includes(resetCredential.password), false);
  assert.doesNotMatch(
    reset.calls.map(({ sql }) => sql).join('\n'),
    /release_access_policies|release_account_versions/i,
  );

  let resetAttempt = 0;
  const race = adminBindings({
    first: async () => observed,
    batch: async (statements) => {
      resetAttempt += 1;
      return statements.map((_, index) => ({
        success: true,
        meta: { changes: resetAttempt === 1 && (index === 0 || index === 2) ? 1 : 0 },
      }));
    },
  });
  const firstRace = await workerModule.route(adminJson('/api/admin/users/reset-password', {
    email: 'person@example.com',
  }), race.env, allowOwner, fixedDependencies);
  const secondRace = await workerModule.route(adminJson('/api/admin/users/reset-password', {
    email: 'person@example.com',
  }), race.env, allowOwner, fixedDependencies);
  assert.equal(firstRace.status, 200);
  assert.equal(secondRace.status, 409);
  assert.doesNotMatch(await secondRace.text(), /password|credential|person@example/i);

  const revokedReset = adminBindings({ first: async () => ({ state: 'revoked', release_decision: 'approved' }) });
  const revokedResetResponse = await workerModule.route(adminJson('/api/admin/users/reset-password', {
    email: 'person@example.com',
  }), revokedReset.env, allowOwner, fixedDependencies);
  assert.equal(revokedResetResponse.status, 409);
  assert.equal(revokedReset.batchCalls.length, 0);

  const revokedUser = { ...activeUser, state: 'revoked', revoked_at: fixedDependencies.now().toISOString() };
  const revoke = adminBindings({ first: async () => revokedUser });
  const revokeResponse = await workerModule.route(adminJson('/api/admin/users/revoke', {
    email: 'person@example.com',
  }), revoke.env, allowOwner, fixedDependencies);
  assert.equal(revokeResponse.status, 200);
  assert.deepEqual(await revokeResponse.json(), {
    ok: true,
    item: { ...revokedUser, must_change_password: true },
  });
  assert.equal(revoke.batchCalls.length, 1);
  assert.match(
    revoke.calls[0].sql,
    /UPDATE release_accounts[\s\S]+state\s*=\s*'revoked'[\s\S]+state\s*=\s*'active'/i,
  );
  assert.match(revoke.calls[1].sql, /revocation[\s\S]+changes\(\)\s*=\s*1/i);
  assert.match(revoke.calls[2].sql, /DELETE FROM release_sessions[\s\S]+changes\(\)\s*=\s*1/i);
  assert.doesNotMatch(
    revoke.calls.map(({ sql }) => sql).join('\n'),
    /release_access_policies|release_account_versions/i,
  );
});

test('admin release catalog returns summaries and bounded unavailable states', async () => {
  const releases = adminCatalogBucket(['v1.2.3']);
  const good = adminBindings({ releases });
  const response = await workerModule.route(adminRequest('/api/admin/releases'), good.env, allowOwner);
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), {
    items: [{ version: 'v1.2.3', published_at: '2026-07-12T12:00:00Z' }],
    latest_version: 'v1.2.3',
    available: true,
  });

  const unavailable = {
    items: [],
    latest_version: null,
    available: false,
    diagnostic: 'Release catalog is not ready.',
  };
  const empty = adminBindings({
    releases: { async list() { return { objects: [] }; }, async get() { return null; } },
  });
  const emptyResponse = await workerModule.route(
    adminRequest('/api/admin/releases'), empty.env, allowOwner,
  );
  assert.equal(emptyResponse.status, 200);
  assert.deepEqual(await emptyResponse.json(), unavailable);

  const malformed = adminBindings({
    releases: {
      async list() { return { objects: [{ key: 'releases/v1.2.3/manifest.json' }] }; },
      async get(key) {
        return { json: async () => key.endsWith('latest.json')
          ? { version: 'v1.2.3' } : { private_key: 'do-not-expose' } };
      },
    },
  });
  const malformedResponse = await workerModule.route(
    adminRequest('/api/admin/releases'), malformed.env, allowOwner,
  );
  assert.equal(malformedResponse.status, 200);
  const malformedText = await malformedResponse.text();
  assert.deepEqual(JSON.parse(malformedText), unavailable);
  assert.doesNotMatch(malformedText, /private_key|manifest-invalid/i);

  const bad = adminBindings({
    releases: { async list() { throw new Error('secret R2 key'); }, async get() { return null; } },
  });
  const failed = await workerModule.route(adminRequest('/api/admin/releases'), bad.env, allowOwner);
  assert.equal(failed.status, 503);
  assert.doesNotMatch(await failed.text(), /secret|catalog-unavailable|releases\//i);
});

test('admin API rejects mutations and redacts D1 failures', async () => {
  const methodBindings = adminBindings();
  const wrongMethod = await workerModule.route(
    adminRequest(undefined, { method: 'POST' }),
    methodBindings.env,
    allowOwner,
  );
  assert.equal(wrongMethod.status, 405);
  assert.equal(wrongMethod.headers.get('allow'), 'GET');
  assert.equal(methodBindings.calls.length, 0);

  const failureBindings = adminBindings({
    all: async () => { throw new Error('private database detail'); },
  });
  const failed = await workerModule.route(adminRequest(), failureBindings.env, allowOwner);
  assert.equal(failed.status, 503);
  assert.doesNotMatch(await failed.text(), /database detail/);
});

test('private host serves only mapped assets with security headers', async () => {
  const { env, assetRequests } = adminBindings();
  const page = await workerModule.route(adminRequest('/'), env, allowOwner);
  const sharedStyle = await workerModule.route(adminRequest('/style.css'), env, allowOwner);
  const script = await workerModule.route(adminRequest('/admin.js'), env, allowOwner);
  const missing = await workerModule.route(adminRequest('/not-found'), env, allowOwner);

  assert.equal(page.status, 200);
  assert.equal(sharedStyle.status, 200);
  assert.equal(script.status, 200);
  assert.equal(missing.status, 404);
  assert.deepEqual(
    assetRequests.map((assetRequest) => new URL(assetRequest.url).pathname),
    ['/admin/', '/style.css', '/admin/admin.js'],
  );
  assert.equal(page.headers.get('cache-control'), 'no-store');
  assert.match(page.headers.get('content-security-policy'), /frame-ancestors 'none'/);
  assert.equal(page.headers.get('referrer-policy'), 'no-referrer');
  assert.equal(page.headers.get('x-content-type-options'), 'nosniff');
  assert.equal(page.headers.get('x-frame-options'), 'DENY');
});

test('public host never serves private admin assets', async () => {
  const { env, assetRequests } = adminBindings();
  for (const path of ['/admin', '/admin/', '/admin/admin.js']) {
    const response = await workerModule.route(
      new Request(`https://backchannel.page${path}`),
      env,
      allowOwner,
    );
    assert.equal(response.status, 404);
    assert.equal(response.headers.get('cache-control'), 'no-store');
  }
  assert.equal(assetRequests.length, 0);
});

const DOWNLOAD_ORIGIN = 'https://downloads.backchannel.page';
const downloadNow = new Date('2026-07-12T12:00:00.000Z');

function downloadRequest(path, body, init = {}) {
  const method = init.method || (path.endsWith('/session') ? 'GET' : 'POST');
  const headers = method === 'GET' ? {} : {
    origin: DOWNLOAD_ORIGIN,
    'content-type': 'application/json; charset=utf-8',
  };
  return new Request(`${DOWNLOAD_ORIGIN}${path}`, {
    method,
    headers: { ...headers, ...init.headers },
    body: method === 'GET' ? undefined : (typeof body === 'string' ? body : JSON.stringify(body ?? {})),
  });
}

function downloadBindings({ first = async () => undefined, run, batch } = {}) {
  const calls = [];
  const batchCalls = [];
  const assetRequests = [];
  const defaultRun = async () => ({ success: true, meta: { changes: 1 } });
  return {
    calls,
    batchCalls,
    env: {
      TURNSTILE_SECRET: 'download-secret',
      INTEREST_DB: {
        prepare(sql) {
          const call = { sql, values: [] };
          calls.push(call);
          const prepared = {
            bind(...values) {
              call.values = values;
              return prepared;
            },
            async first(...values) {
              const record = await first(...values);
              return record && 'password_change_only' in record && !('release_decision' in record)
                ? { ...record, release_decision: 'approved' }
                : record;
            },
            run: run || defaultRun,
          };
          return prepared;
        },
        async batch(statements) {
          batchCalls.push(statements);
          return batch
            ? batch(statements)
            : statements.map(() => ({ success: true, meta: { changes: 1 } }));
        },
      },
      ASSETS: { fetch: async (requestValue) => {
        assetRequests.push(requestValue);
        return new Response('recipient asset');
      } },
    },
    assetRequests,
  };
}

function downloadDependencies(overrides = {}) {
  return {
    now: () => downloadNow,
    fetch: async () => new Response(JSON.stringify({
      success: true,
      hostname: 'downloads.backchannel.page',
      action: 'download_login',
    })),
    ...overrides,
  };
}

test('private page roots avoid Cloudflare index redirects', async () => {
  const cloudflareAsset = async (requestValue) => {
    const url = new URL(requestValue.url);
    if (url.pathname.endsWith('/index.html')) {
      url.pathname = url.pathname.slice(0, -'index.html'.length);
      return Response.redirect(url, 307);
    }
    return new Response('private asset');
  };
  const admin = adminBindings({ asset: cloudflareAsset });
  const download = downloadBindings();
  download.env.ASSETS.fetch = async (requestValue) => {
    download.assetRequests.push(requestValue);
    return cloudflareAsset(requestValue);
  };

  const adminPage = await workerModule.route(adminRequest('/'), admin.env, allowOwner);
  const downloadPage = await workerModule.route(
    downloadRequest('/', undefined, { method: 'GET' }),
    download.env,
  );

  assert.equal(adminPage.status, 200);
  assert.equal(downloadPage.status, 200);
  assert.equal(new URL(admin.assetRequests[0].url).pathname, '/admin/');
  assert.equal(new URL(download.assetRequests[0].url).pathname, '/downloads/');
});

const approvedAccount = {
  email: 'person@example.com',
  state: 'active',
  release_decision: 'approved',
  password_hash: 'hash',
  password_salt: 'salt',
  password_iterations: 600000,
  must_change_password: 1,
  password_expires_at: '2026-07-12T12:30:00.000Z',
};

test('recipient host serves only mapped assets with distinct private headers', async () => {
  const bindingsValue = downloadBindings();
  const paths = ['/', '/index.html', '/downloads.js', '/downloads.css'];
  const responses = [];
  for (const path of paths) {
    responses.push(await workerModule.route(downloadRequest(path, undefined, { method: 'GET' }), bindingsValue.env));
  }
  const missing = await workerModule.route(
    downloadRequest('/not-found', undefined, { method: 'GET' }),
    bindingsValue.env,
  );
  const admin = adminBindings();
  const adminPage = await workerModule.route(adminRequest('/'), admin.env, allowOwner);

  assert.ok(responses.every((response) => response.status === 200));
  assert.deepEqual(
    bindingsValue.assetRequests.map((requestValue) => new URL(requestValue.url).pathname),
    ['/downloads/', '/downloads/', '/downloads/downloads.js', '/downloads/downloads.css'],
  );
  const expectedCsp = "default-src 'self'; script-src 'self' https://challenges.cloudflare.com; frame-src https://challenges.cloudflare.com; connect-src 'self'; style-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'";
  for (const response of [...responses, missing]) {
    assert.equal(response.headers.get('content-security-policy'), expectedCsp);
    assert.equal(response.headers.get('cache-control'), 'private, no-store');
    assert.equal(response.headers.get('referrer-policy'), 'no-referrer');
    assert.equal(response.headers.get('x-content-type-options'), 'nosniff');
    assert.match(response.headers.get('permissions-policy'), /camera=\(\)/);
  }
  assert.equal(missing.status, 404);
  assert.notEqual(adminPage.headers.get('content-security-policy'), expectedCsp);
});

test('recipient host keeps unknown paths private and mutations enforce request boundaries', async () => {
  const missing = downloadBindings();
  for (const path of ['/unknown', '/api/download/unknown']) {
    const response = await workerModule.route(
      downloadRequest(path, undefined, { method: 'GET' }),
      missing.env,
    );
    assert.equal(response.status, 404);
    assert.equal(response.headers.get('cache-control'), 'private, no-store');
    assert.equal(response.headers.get('x-frame-options'), 'DENY');
  }
  assert.equal(missing.calls.length, 0);

  const cases = [
    [downloadRequest('/api/download/login', {
      email: 'person@example.com', password: 'temporary', turnstile_token: 'token',
    }, { headers: { origin: 'https://attacker.example' } }), 403],
    [downloadRequest('/api/download/login', {
      email: 'person@example.com', password: 'temporary', turnstile_token: 'token',
    }, { headers: { 'content-type': 'text/plain' } }), 415],
    [downloadRequest('/api/download/login', 'x'.repeat(8193)), 413],
  ];
  for (const [requestValue, expected] of cases) {
    const bindingsValue = downloadBindings();
    const response = await workerModule.route(
      requestValue,
      bindingsValue.env,
      undefined,
      downloadDependencies(),
    );
    assert.equal(response.status, expected);
    assert.equal(bindingsValue.calls.length, 0);
  }
});

test('recipient login requires exact Turnstile hostname and action', async () => {
  const bodies = [];
  for (const verification of [
    { success: true, hostname: 'backchannel.page', action: 'download_login' },
    { success: true, hostname: 'downloads.backchannel.page', action: 'interest' },
  ]) {
    const bindingsValue = downloadBindings();
    const response = await workerModule.route(downloadRequest('/api/download/login', {
      email: ' Person@Example.com ', password: 'temporary', turnstile_token: 'challenge',
    }), bindingsValue.env, undefined, downloadDependencies({
      async fetch(url, init) {
        bodies.push({ url, init });
        return new Response(JSON.stringify(verification));
      },
    }));
    assert.equal(response.status, 401);
    assert.deepEqual(await response.json(), { ok: false, error: 'Unable to sign in.' });
    assert.equal(bindingsValue.calls.length, 0);
  }
  assert.equal(bodies.length, 2);
  assert.equal(bodies[0].url, 'https://challenges.cloudflare.com/turnstile/v0/siteverify');
  assert.equal(bodies[0].init.body.get('secret'), 'download-secret');
  assert.equal(bodies[0].init.body.get('response'), 'challenge');
});

test('recipient login performs one password verification for every account state', async () => {
  const cases = [
    undefined,
    { ...approvedAccount, state: 'revoked' },
    { ...approvedAccount, release_decision: 'pending' },
    { ...approvedAccount, release_decision: 'rejected' },
    { ...approvedAccount, password_hash: 'malformed' },
    { ...approvedAccount, password_expires_at: '2026-07-12T11:59:59.000Z' },
    approvedAccount,
  ];
  const bodies = [];
  for (const [index, account] of cases.entries()) {
    let derivations = 0;
    const bindingsValue = downloadBindings({ first: async () => account });
    const response = await workerModule.route(downloadRequest('/api/download/login', {
      email: ' Person@Example.com ', password: 'wrong', turnstile_token: 'challenge',
    }), bindingsValue.env, undefined, downloadDependencies({
      async verifyPassword(password, record) {
        derivations += 1;
        assert.equal(password, 'wrong');
        if (index === 0) assert.equal(record, undefined);
        return index !== 4 && index !== 6;
      },
    }));
    assert.equal(derivations, 1);
    bodies.push({ status: response.status, body: await response.json() });
  }
  assert.deepEqual(new Set(bodies.map(({ status }) => status)), new Set([401]));
  assert.deepEqual(new Set(bodies.map(({ body }) => JSON.stringify(body))), new Set([
    JSON.stringify({ ok: false, error: 'Unable to sign in.' }),
  ]));
});

test('recipient login denies unknown and malformed accounts generically', async () => {
  for (const account of [undefined, { ...approvedAccount, password_hash: 'malformed' }]) {
    const bindingsValue = downloadBindings({ first: async () => account });
    const response = await workerModule.route(downloadRequest('/api/download/login', {
      email: 'person@example.com', password: 'wrong', turnstile_token: 'challenge',
    }), bindingsValue.env, undefined, downloadDependencies());
    assert.equal(response.status, 401);
    assert.deepEqual(await response.json(), { ok: false, error: 'Unable to sign in.' });
  }
});

test('temporary login stores only a token hash and caps the change session expiry', async () => {
  for (const [passwordExpires, expectedExpires, maxAge] of [
    ['2026-07-12T12:10:00.000Z', '2026-07-12T12:10:00.000Z', 600],
    ['2026-07-12T13:00:00.000Z', '2026-07-12T12:30:00.000Z', 1800],
  ]) {
    const bindingsValue = downloadBindings({
      first: async () => ({ ...approvedAccount, password_expires_at: passwordExpires }),
    });
    const response = await workerModule.route(downloadRequest('/api/download/login', {
      email: ' Person@Example.com ', password: 'temporary', turnstile_token: 'challenge',
    }), bindingsValue.env, undefined, downloadDependencies({
      verifyPassword: async () => true,
      createSessionToken: async () => ({ token: 'raw-token', tokenHash: 'stored-token-hash' }),
    }));
    assert.equal(response.status, 200);
    assert.equal(response.headers.get('set-cookie'),
      `__Host-backchannel_release=raw-token; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age=${maxAge}`);
    assert.equal(bindingsValue.batchCalls.length, 1);
    const serialized = JSON.stringify(bindingsValue.calls);
    assert.match(bindingsValue.calls[1].sql,
      /INSERT INTO release_sessions[\s\S]+SELECT[\s\S]+WHERE EXISTS[\s\S]+state = 'active'[\s\S]+release_decision = 'approved'/i);
    assert.deepEqual(bindingsValue.calls[1].values, [
      'stored-token-hash', 'person@example.com', 1,
      '2026-07-12T12:00:00.000Z', expectedExpires, 'person@example.com',
      'hash', 'salt', 600000, 1, passwordExpires, 1, '2026-07-12T12:00:00.000Z',
    ]);
    assert.match(bindingsValue.calls[2].sql, /login_success/i);
    assert.equal(serialized.includes('raw-token'), false);
  }
});

test('permanent login creates a seven-day normal session', async () => {
  const bindingsValue = downloadBindings({
    first: async () => ({ ...approvedAccount, must_change_password: 0, password_expires_at: null }),
  });
  const response = await workerModule.route(downloadRequest('/api/download/login', {
    email: 'person@example.com', password: 'permanent password', turnstile_token: 'challenge',
  }), bindingsValue.env, undefined, downloadDependencies({
    verifyPassword: async () => true,
    createSessionToken: async () => ({ token: 'raw-token', tokenHash: 'stored-token-hash' }),
  }));
  assert.equal(response.status, 200);
  assert.match(response.headers.get('set-cookie'), /Max-Age=604800$/);
  assert.deepEqual(bindingsValue.calls[1].values, [
    'stored-token-hash', 'person@example.com', 0,
    '2026-07-12T12:00:00.000Z', '2026-07-19T12:00:00.000Z', 'person@example.com',
    'hash', 'salt', 600000, 0, null, 0, '2026-07-12T12:00:00.000Z',
  ]);
});

test('login rejects a concurrent credential reset without storing a session or cookie', async () => {
  const bindingsValue = downloadBindings({
    first: async () => approvedAccount,
    batch: async (statements) => statements.map(() => ({ success: true, meta: { changes: 0 } })),
  });
  const response = await workerModule.route(downloadRequest('/api/download/login', {
    email: 'person@example.com', password: 'temporary', turnstile_token: 'challenge',
  }), bindingsValue.env, undefined, downloadDependencies({
    verifyPassword: async () => true,
    createSessionToken: async () => ({ token: 'stale-raw-token', tokenHash: 'stale-token-hash' }),
  }));

  assert.equal(response.status, 401);
  assert.deepEqual(await response.json(), { ok: false, error: 'Unable to sign in.' });
  assert.equal(response.headers.get('set-cookie'), null);
  assert.equal(bindingsValue.batchCalls.length, 1);
  assert.match(bindingsValue.calls[1].sql,
    /password_hash = \?[\s\S]+password_salt = \?[\s\S]+password_iterations = \?[\s\S]+must_change_password = \?[\s\S]+password_expires_at IS \?[\s\S]+password_expires_at > \?/i);
  assert.deepEqual(bindingsValue.calls[1].values, [
    'stale-token-hash', 'person@example.com', 1,
    '2026-07-12T12:00:00.000Z', '2026-07-12T12:30:00.000Z',
    'person@example.com', 'hash', 'salt', 600000, 1,
    '2026-07-12T12:30:00.000Z', 1, '2026-07-12T12:00:00.000Z',
  ]);
  assert.match(bindingsValue.calls[2].sql,
    /login_success[\s\S]+WHERE EXISTS[\s\S]+release_sessions[\s\S]+token_hash = \?/i);
});

test('session status hashes only the named cookie and rechecks session and account state', async () => {
  const token = await createSessionToken((length) => new Uint8Array(length).fill(7));
  const bindingsValue = downloadBindings({
    first: async () => ({
      email: 'person@example.com', state: 'active', password_change_only: 1,
      expires_at: '2026-07-12T12:30:00.000Z',
    }),
  });
  const response = await workerModule.route(downloadRequest('/api/download/session', undefined, {
    headers: { cookie: `other=ignored; __Host-backchannel_release=${token.token}` },
  }), bindingsValue.env, undefined, downloadDependencies());
  assert.deepEqual(await response.json(), {
    authenticated: true,
    must_change_password: true,
    email: 'person@example.com',
  });
  assert.match(bindingsValue.calls[0].sql, /release_sessions[\s\S]+release_accounts/i);
  assert.match(bindingsValue.calls[0].sql, /interest_subscribers/i);
  assert.match(bindingsValue.calls[0].sql, /release_decision\s*=\s*'approved'/i);
  assert.match(bindingsValue.calls[0].sql, /expires_at/i);
  assert.match(bindingsValue.calls[0].sql, /state/i);
  assert.equal(bindingsValue.calls[0].values[0], token.tokenHash);

  const invalid = downloadBindings();
  const invalidResponse = await workerModule.route(downloadRequest('/api/download/session', undefined, {
    headers: { cookie: `__Host-backchannel_release=${token.token}` },
  }), invalid.env, undefined, downloadDependencies());
  assert.deepEqual(await invalidResponse.json(), { authenticated: false });
  assert.equal(invalidResponse.headers.get('set-cookie'),
    '__Host-backchannel_release=; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age=0');

  const malformed = downloadBindings({ first: async () => ({
    email: 'person@example.com', state: 'active', password_change_only: 0,
    expires_at: 'not-a-time',
  }) });
  const malformedResponse = await workerModule.route(downloadRequest('/api/download/session', undefined, {
    headers: { cookie: `__Host-backchannel_release=${token.token}` },
  }), malformed.env, undefined, downloadDependencies());
  assert.deepEqual(await malformedResponse.json(), { authenticated: false });

  const inconsistent = downloadBindings({ first: async () => ({
    email: 'person@example.com', state: 'active', release_decision: 'rejected',
    password_change_only: 0, expires_at: '2026-07-19T12:00:00.000Z',
  }) });
  const inconsistentResponse = await workerModule.route(downloadRequest('/api/download/session', undefined, {
    headers: { cookie: `__Host-backchannel_release=${token.token}` },
  }), inconsistent.env, undefined, downloadDependencies());
  assert.deepEqual(await inconsistentResponse.json(), { authenticated: false });
});

test('password change requires a change-only session and rotates it atomically', async () => {
  const token = await createSessionToken((length) => new Uint8Array(length).fill(8));
  const normal = downloadBindings({ first: async () => ({
    email: 'person@example.com', state: 'active', password_change_only: 0,
    expires_at: '2026-07-19T12:00:00.000Z',
  }) });
  const denied = await workerModule.route(downloadRequest('/api/download/password', {
    password: 'long enough password',
  }, { headers: { cookie: `__Host-backchannel_release=${token.token}` } }),
  normal.env, undefined, downloadDependencies());
  assert.equal(denied.status, 401);
  assert.equal(normal.batchCalls.length, 0);

  const short = downloadBindings();
  const shortResponse = await workerModule.route(downloadRequest('/api/download/password', {
    password: '1234567890123',
  }), short.env, undefined, downloadDependencies());
  assert.equal(shortResponse.status, 400);
  assert.equal(short.calls.length, 0);

  const bindingsValue = downloadBindings({ first: async () => ({
    email: 'person@example.com', state: 'active', password_change_only: 1,
    expires_at: '2026-07-12T12:30:00.000Z',
  }) });
  const response = await workerModule.route(downloadRequest('/api/download/password', {
    password: 'a new permanent password',
  }, { headers: { cookie: `__Host-backchannel_release=${token.token}` } }),
  bindingsValue.env, undefined, downloadDependencies({
    hashPassword: async () => ({ hash: 'new-hash', salt: 'new-salt', iterations: 600000 }),
    createSessionToken: async () => ({ token: 'new-raw-token', tokenHash: 'new-token-hash' }),
  }));
  assert.equal(response.status, 200);
  assert.equal(bindingsValue.batchCalls.length, 1);
  assert.match(bindingsValue.calls[1].sql, /UPDATE release_accounts[\s\S]+must_change_password\s*=\s*0/i);
  assert.match(bindingsValue.calls[2].sql, /DELETE FROM release_sessions[\s\S]+email/i);
  assert.match(bindingsValue.calls[3].sql, /INSERT INTO release_sessions/i);
  assert.match(bindingsValue.calls[4].sql, /password_change/i);
  assert.equal(JSON.stringify(bindingsValue.calls).includes('new-raw-token'), false);
  assert.equal(response.headers.get('set-cookie'),
    '__Host-backchannel_release=new-raw-token; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age=604800');
});

test('password change makes every write conditional on the exact presented session', async () => {
  const token = await createSessionToken((length) => new Uint8Array(length).fill(10));
  const bindingsValue = downloadBindings({
    first: async () => ({
      email: 'person@example.com', state: 'active', password_change_only: 1,
      expires_at: '2026-07-12T12:30:00.000Z',
    }),
    batch: async (statements) => statements.map(() => ({ success: true, meta: { changes: 0 } })),
  });
  const response = await workerModule.route(downloadRequest('/api/download/password', {
    password: 'a new permanent password',
  }, { headers: { cookie: `__Host-backchannel_release=${token.token}` } }),
  bindingsValue.env, undefined, downloadDependencies({
    hashPassword: async () => ({ hash: 'new-hash', salt: 'new-salt', iterations: 600000 }),
    createSessionToken: async () => ({ token: 'new-raw-token', tokenHash: 'new-token-hash' }),
  }));

  assert.equal(response.status, 401);
  assert.equal(response.headers.get('set-cookie'), null);
  assert.equal(bindingsValue.batchCalls.length, 1);
  assert.match(bindingsValue.calls[1].sql,
    /UPDATE release_accounts[\s\S]+WHERE[\s\S]+state = 'active'[\s\S]+EXISTS[\s\S]+release_sessions[\s\S]+token_hash = \?[\s\S]+password_change_only = 1[\s\S]+expires_at > \?/i);
  assert.ok(bindingsValue.calls[1].values.includes(token.tokenHash));
  for (const call of bindingsValue.calls.slice(2, 5)) {
    assert.match(call.sql,
      /EXISTS[\s\S]+password_hash = \?[\s\S]+password_salt = \?[\s\S]+password_changed_at = \?/i);
    assert.ok(call.values.includes('new-hash'));
    assert.ok(call.values.includes('new-salt'));
    assert.ok(call.values.includes('2026-07-12T12:00:00.000Z'));
  }
});

test('logout deletes only the presented session and always clears the cookie', async () => {
  const token = await createSessionToken((length) => new Uint8Array(length).fill(9));
  const bindingsValue = downloadBindings({ first: async () => ({
    email: 'person@example.com', state: 'active', password_change_only: 0,
    expires_at: '2026-07-19T12:00:00.000Z',
  }) });
  const response = await workerModule.route(downloadRequest('/api/download/logout', {}, {
    headers: { cookie: `__Host-backchannel_release=${token.token}` },
  }), bindingsValue.env, undefined, downloadDependencies());
  assert.deepEqual(await response.json(), { ok: true });
  assert.equal(bindingsValue.batchCalls.length, 1);
  assert.match(bindingsValue.calls[1].sql, /DELETE FROM release_sessions WHERE token_hash = \?/i);
  assert.deepEqual(bindingsValue.calls[1].values, [token.tokenHash]);
  assert.match(bindingsValue.calls[2].sql, /logout/i);
  assert.equal(response.headers.get('set-cookie'),
    '__Host-backchannel_release=; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age=0');

  const invalid = downloadBindings();
  const invalidResponse = await workerModule.route(downloadRequest('/api/download/logout', {}, {
    headers: { cookie: '__Host-backchannel_release=invalid' },
  }), invalid.env, undefined, downloadDependencies());
  assert.deepEqual(await invalidResponse.json(), { ok: true });
  assert.equal(invalidResponse.headers.get('set-cookie'),
    '__Host-backchannel_release=; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age=0');
});

const releaseToken = await createSessionToken((length) => new Uint8Array(length).fill(11));
const releaseSession = {
  email: 'person@example.com',
  state: 'active',
  password_change_only: 0,
  expires_at: '2026-07-19T12:00:00.000Z',
  include_latest: 1,
  versions: JSON.stringify(['v1.0.0', 'v2.0.0', 'v1.0.0']),
};

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

function releaseBucket({
  object = async () => null,
  metadata = {
    size: 100,
    httpEtag: '"object-etag"',
    uploaded: new Date('2026-07-12T12:00:00.900Z'),
  },
  malformed = false,
  asset = defaultReleaseAsset,
} = {}) {
  const calls = [];
  const manifests = new Map([
    ['v1.0.0', releaseManifest('v1.0.0', 100, asset)],
    ['v2.0.0', releaseManifest('v2.0.0', 100, asset)],
  ]);
  return {
    calls,
    async list(options) {
      calls.push({ operation: 'list', options });
      return {
        objects: [
          ...[...manifests].map(([version]) => ({ key: `releases/${version}/manifest.json` })),
          ...(malformed ? [{ key: 'releases/v3.0.0/manifest.json' }] : []),
        ],
        truncated: false,
      };
    },
    async get(key, options) {
      calls.push({ operation: 'get', key, options });
      if (key === 'releases/latest.json') return { json: async () => ({ version: 'v2.0.0' }) };
      const manifest = /^releases\/(v[0-9.]+)\/manifest\.json$/.exec(key);
      if (manifest) return {
        json: async () => malformed && manifest[1] === 'v3.0.0'
          ? { version: 'not-valid' }
          : structuredClone(manifests.get(manifest[1])),
      };
      return object(key, options);
    },
    async head(key) {
      calls.push({ operation: 'head', key });
      return metadata;
    },
  };
}

function releaseGet(path, headers = {}) {
  return downloadRequest(path, undefined, {
    method: 'GET',
    headers: {
      cookie: `__Host-backchannel_release=${releaseToken.token}`,
      ...headers,
    },
  });
}

function releaseBindings(bucket, session = releaseSession) {
  const result = downloadBindings({ first: async () => session });
  if (bucket) result.env.RELEASES = bucket;
  return result;
}

function assetCalls(bucket, filename = defaultReleaseAsset.filename) {
  return bucket.calls.filter(({ operation, key }) => (
    operation === 'get' && key?.endsWith(filename)
  ));
}

test('recipient release listing resolves Latest plus explicit grants without leaking R2 metadata', async () => {
  const bucket = releaseBucket({ malformed: true });
  const bindingsValue = releaseBindings(bucket);
  const response = await workerModule.route(
    releaseGet('/api/download/releases'), bindingsValue.env, undefined, downloadDependencies(),
  );

  assert.equal(response.status, 200);
  const body = await response.json();
  assert.equal(body.latest_version, 'v2.0.0');
  assert.deepEqual(body.items.map(({ version }) => version), ['v2.0.0', 'v1.0.0']);
  assert.deepEqual(Object.keys(body.items[0]), ['version', 'published_at', 'assets']);
  assert.deepEqual(Object.keys(body.items[0].assets[0]),
    ['id', 'platform', 'filename', 'size', 'sha256']);
  assert.doesNotMatch(JSON.stringify(body), /releases\/|content_type|commit/);
});

test('release APIs reject invalid sessions and paths before catalog or object access', async () => {
  const invalidSessions = [
    null,
    { ...releaseSession, state: 'revoked' },
    { ...releaseSession, password_change_only: 1 },
    { ...releaseSession, expires_at: '2026-07-12T11:59:59.000Z' },
  ];
  for (const session of invalidSessions) {
    const bucket = releaseBucket();
    const response = await workerModule.route(
      releaseGet('/api/download/releases'), releaseBindings(bucket, session).env,
      undefined, downloadDependencies(),
    );
    assert.equal(response.status, 404);
    assert.equal(bucket.calls.length, 0);
  }

  for (const path of [
    '/api/download/releases/1.0.0/windows-x64',
    '/api/download/releases/v01.0.0/windows-x64',
    '/api/download/releases/v1.0.0/Windows-x64',
    '/api/download/releases/v1.0.0/Backchannel-windows-x64.zip',
    '/api/download/releases/v1.0.0/windows-x64/extra',
    '/api/download/releases/v1.0.0%2Fwindows-x64',
    '/api/download/releases/v1.0.0/windows%2Fx64',
  ]) {
    const bucket = releaseBucket();
    const response = await workerModule.route(
      releaseGet(path), releaseBindings(bucket).env, undefined, downloadDependencies(),
    );
    assert.equal(response.status, 404, path);
    assert.equal(bucket.calls.length, 0, path);
  }
});

test('unauthorized versions and missing asset IDs are indistinguishable private 404s', async () => {
  const responses = [];
  for (const path of [
    '/api/download/releases/v3.0.0/windows-x64',
    '/api/download/releases/v1.0.0/linux-x64',
  ]) {
    const bucket = releaseBucket();
    responses.push(await workerModule.route(
      releaseGet(path), releaseBindings(bucket).env, undefined, downloadDependencies(),
    ));
    assert.equal(assetCalls(bucket).length, 0);
  }
  assert.deepEqual(responses.map(({ status }) => status), [404, 404]);
  assert.deepEqual(await responses[0].json(), await responses[1].json());
  assert.equal(responses[0].headers.get('cache-control'), 'private, no-store');
});

test('authorized downloads stream full and ranged R2 bodies with exact headers and safe events', async () => {
  const cases = [
    [undefined, 200, 100, null],
    ['bytes=10-19', 206, 10, 'bytes 10-19/100'],
    ['bytes=25-', 206, 75, 'bytes 25-99/100'],
    ['bytes=-10', 206, 10, 'bytes 90-99/100'],
    ['bytes=7-7', 206, 1, 'bytes 7-7/100'],
  ];
  for (const [range, status, length, contentRange] of cases) {
    const body = new ReadableStream();
    const bucket = releaseBucket({ object: async () => ({
      body, size: 100, httpEtag: '"object-etag"',
    }) });
    const bindingsValue = releaseBindings(bucket);
    const response = await workerModule.route(
      releaseGet('/api/download/releases/v1.0.0/windows-x64', range ? { range } : {}),
      bindingsValue.env, undefined, downloadDependencies(),
    );
    assert.equal(response.status, status, range);
    assert.equal(response.body, body, range);
    assert.equal(response.headers.get('content-length'), String(length));
    assert.equal(response.headers.get('content-range'), contentRange);
    assert.equal(response.headers.get('content-type'), 'application/zip');
    assert.equal(response.headers.get('content-disposition'),
      'attachment; filename="Backchannel-windows-x64-v1.0.0.zip"');
    assert.equal(response.headers.get('etag'), '"object-etag"');
    assert.equal(response.headers.get('accept-ranges'), 'bytes');
    assert.equal(response.headers.get('cache-control'), 'private, no-store');
    const call = assetCalls(bucket)[0];
    assert.equal(call.options.range.get('range'), range || null);
    assert.equal(call.options.onlyIf.get('range'), range || null);
    const event = bindingsValue.calls.find(({ sql }) => /download_start/.test(sql));
    assert.deepEqual(event.values, [
      'person@example.com', 'v1.0.0', '2026-07-12T12:00:00.000Z',
    ]);
    assert.doesNotMatch(JSON.stringify(event), /windows-x64|object-etag|Backchannel/);
  }
});

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

test('ranges and conditional absence map to 304, 412, and 416 with defined precedence', async () => {
  for (const range of ['', 'bytes=0-1,5-6', 'bytes=100-', 'items=0-1']) {
    const bucket = releaseBucket();
    const bindingsValue = releaseBindings(bucket);
    const response = await workerModule.route(
      releaseGet('/api/download/releases/v1.0.0/windows-x64', { range }),
      bindingsValue.env, undefined, downloadDependencies(),
    );
    assert.equal(response.status, 416, range);
    assert.equal(response.body, null);
    assert.equal(response.headers.get('content-range'), 'bytes */100');
    assert.equal(assetCalls(bucket).length, 0);
    assert.equal(bindingsValue.calls.some(({ sql }) => /download_start/.test(sql)), false);
  }

  const conditions = [
    [{ 'if-none-match': '"object-etag"', range: 'bytes=0-9' }, 304],
    [{ 'if-modified-since': 'Sun, 12 Jul 2026 13:00:00 GMT' }, 304],
    [{ 'if-match': '"old"', range: 'bytes=0-9' }, 412],
    [{ 'if-unmodified-since': 'Sun, 12 Jul 2026 11:59:59 GMT' }, 412],
    [{ 'if-match': '"old"', 'if-none-match': '"object-etag"', range: 'bytes=0-9' }, 412],
  ];
  for (const [headers, status] of conditions) {
    const bucket = releaseBucket({ object: async () => ({
      size: 100,
      httpEtag: '"object-etag"',
      uploaded: new Date('2026-07-12T12:00:00.900Z'),
    }) });
    const bindingsValue = releaseBindings(bucket);
    const response = await workerModule.route(
      releaseGet('/api/download/releases/v1.0.0/windows-x64', headers),
      bindingsValue.env, undefined, downloadDependencies(),
    );
    assert.equal(response.status, status, JSON.stringify(headers));
    assert.equal(response.body, null);
    assert.equal(response.headers.get('content-length'), null);
    assert.equal(bucket.calls.filter(({ operation }) => operation === 'head').length, 1);
    assert.equal(assetCalls(bucket).length, 0);
    assert.equal(bindingsValue.calls.some(({ sql }) => /download_start/.test(sql)), false);
  }
});

test('GET preconditions use object metadata in RFC order before Range parsing', async () => {
  const cases = [
    ['If-Match mismatch beats multi-range', {
      'if-match': '"other"', range: 'bytes=0-1,5-6',
    }, 412],
    ['If-Match uses strong comparison', {
      'if-match': 'W/"object-etag"', range: 'bytes=100-',
    }, 412],
    ['If-Match lists preserve commas inside quoted tags', {
      'if-match': '"tag,with,comma", "object-etag"', range: 'bytes=100-',
    }, 416],
    ['If-Match wildcard passes for an existing object', {
      'if-match': '*', range: 'bytes=100-',
    }, 416],
    ['If-Unmodified-Since failure beats invalid range', {
      'if-unmodified-since': 'Sun, 12 Jul 2026 11:59:59 GMT', range: 'invalid',
    }, 412],
    ['If-Unmodified-Since is ignored when If-Match is present', {
      'if-match': '"object-etag"',
      'if-unmodified-since': 'Sun, 12 Jul 2026 11:59:59 GMT',
      range: 'invalid',
    }, 416],
    ['invalid If-Unmodified-Since is ignored', {
      'if-unmodified-since': '0', range: 'invalid',
    }, 416],
    ['If-None-Match uses weak comparison before Range', {
      'if-none-match': 'W/"object-etag"', range: 'bytes=0-1,5-6',
    }, 304],
    ['If-None-Match wildcard matches an existing object', {
      'if-none-match': '*', range: 'bytes=100-',
    }, 304],
    ['If-None-Match suppresses If-Modified-Since when it does not match', {
      'if-none-match': '"other"',
      'if-modified-since': 'Sun, 12 Jul 2026 13:00:00 GMT',
      range: 'bytes=100-',
    }, 416],
    ['If-Modified-Since compares at HTTP second precision', {
      'if-modified-since': 'Sun, 12 Jul 2026 12:00:00 GMT', range: 'bytes=100-',
    }, 304],
    ['invalid If-Modified-Since is ignored', {
      'if-modified-since': '9999', range: 'bytes=100-',
    }, 416],
    ['If-Match pass plus If-None-Match match returns actual 304', {
      'if-match': '"object-etag"',
      'if-none-match': '"object-etag"',
      range: 'bytes=100-',
    }, 304],
    ['If-Match failure wins over matching If-None-Match', {
      'if-match': '"other"',
      'if-none-match': '"object-etag"',
      range: 'bytes=100-',
    }, 412],
  ];

  for (const [name, headers, expected] of cases) {
    const bucket = releaseBucket();
    const bindingsValue = releaseBindings(bucket);
    const response = await workerModule.route(
      releaseGet('/api/download/releases/v1.0.0/windows-x64', headers),
      bindingsValue.env, undefined, downloadDependencies(),
    );
    assert.equal(response.status, expected, name);
    assert.equal(bucket.calls.filter(({ operation }) => operation === 'head').length, 1, name);
    assert.equal(assetCalls(bucket).length, 0, `${name}: must not call get`);
    assert.equal(response.body, null, name);
    assert.equal(bindingsValue.calls.some(({ sql }) => /download_start/.test(sql)), false, name);
  }
});

test('legacy HTTP dates honor RFC850 rollover and asctime semantics before Range', async () => {
  const cases = [
    ['RFC850 most-recent-past year fails If-Unmodified-Since',
      'if-unmodified-since', 'Sunday, 06-Nov-94 08:49:37 GMT',
      '1995-01-01T00:00:00.000Z', 412],
    ['RFC850 exactly fifty years ahead is not rolled back',
      'if-unmodified-since', 'Sunday, 12-Jul-76 12:00:00 GMT',
      '2100-01-01T00:00:00.000Z', 412],
    ['asctime not-modified returns 304',
      'if-modified-since', 'Sun Jul 12 13:00:00 2026',
      '2026-07-12T12:00:00.900Z', 304],
    ['impossible RFC850 date is ignored',
      'if-unmodified-since', 'Monday, 31-Feb-25 12:00:00 GMT',
      '2026-07-12T12:00:00.900Z', 416],
    ['RFC850 lookalike without GMT is ignored',
      'if-unmodified-since', 'Saturday, 12-Jul-25 12:00:00 UTC',
      '2026-07-12T12:00:00.900Z', 416],
    ['malformed asctime spacing is ignored',
      'if-modified-since', 'Sun Jul 6 13:00:00 2026',
      '2026-07-12T12:00:00.900Z', 416],
  ];

  for (const [name, header, value, uploaded, expected] of cases) {
    const bucket = releaseBucket({ metadata: {
      size: 100, httpEtag: '"object-etag"', uploaded: new Date(uploaded),
    } });
    const bindingsValue = releaseBindings(bucket);
    const response = await workerModule.route(
      releaseGet('/api/download/releases/v1.0.0/windows-x64', {
        [header]: value, range: 'bytes=0-1,5-6',
      }),
      bindingsValue.env, undefined, downloadDependencies(),
    );
    assert.equal(response.status, expected, name);
    assert.equal(bucket.calls.filter(({ operation }) => operation === 'head').length, 1, name);
    assert.equal(assetCalls(bucket).length, 0, name);
  }
});

test('legacy HTTP dates are reevaluated on bodyless conditional get results', async () => {
  const cases = [
    ['RFC850 fallback returns 412', 'if-unmodified-since',
      'Sunday, 12-Jul-26 13:00:00 GMT',
      '2026-07-12T12:00:00.000Z', '2026-07-12T14:00:00.000Z', 412],
    ['asctime fallback returns 304', 'if-modified-since',
      'Sun Jul 12 13:00:00 2026',
      '2026-07-12T14:00:00.000Z', '2026-07-12T12:00:00.000Z', 304],
  ];

  for (const [name, header, value, headUploaded, getUploaded, expected] of cases) {
    const bucket = releaseBucket({
      metadata: {
        size: 100, httpEtag: '"object-etag"', uploaded: new Date(headUploaded),
      },
      object: async () => ({
        size: 100, httpEtag: '"object-etag"', uploaded: new Date(getUploaded),
      }),
    });
    const bindingsValue = releaseBindings(bucket);
    const response = await workerModule.route(
      releaseGet('/api/download/releases/v1.0.0/windows-x64', {
        [header]: value, range: 'bytes=0-9',
      }),
      bindingsValue.env, undefined, downloadDependencies(),
    );
    assert.equal(response.status, expected, name);
    assert.equal(assetCalls(bucket).length, 1, name);
    assert.equal(response.body, null, name);
    assert.equal(bindingsValue.calls.some(({ sql }) => /download_start/.test(sql)), false, name);
  }
});

test('missing bindings and missing authorized objects fail generically without download events', async () => {
  const noBinding = releaseBindings();
  const absentBucket = releaseBucket({ metadata: null });
  const absent = releaseBindings(absentBucket);
  const responses = [
    await workerModule.route(releaseGet('/api/download/releases'), noBinding.env,
      undefined, downloadDependencies()),
    await workerModule.route(releaseGet('/api/download/releases/v1.0.0/windows-x64'), absent.env,
      undefined, downloadDependencies()),
  ];
  assert.deepEqual(responses.map(({ status }) => status), [503, 503]);
  assert.equal(absent.calls.some(({ sql }) => /download_start/.test(sql)), false);
});

test('router isolates every hostname before API and static dispatch', async () => {
  const assets = [];
  const env = {
    ...downloadBindings().env,
    ADMIN_EMAIL: 'owner@example.com',
    ACCESS_TEAM_DOMAIN: 'backchannel.cloudflareaccess.com',
    ACCESS_AUD: 'admin-audience',
    ASSETS: { async fetch(requestValue) {
      assets.push(requestValue.url);
      return new Response('asset');
    } },
  };

  const redirect = await workerModule.route(
    new Request('https://www.backchannel.page/docs/?q=1'), env, allowOwner,
  );
  assert.equal(redirect.status, 301);
  assert.equal(redirect.headers.get('location'), 'https://backchannel.page/docs/?q=1');

  for (const host of [
    'www.attacker.example', 'backchannel-site.workers.dev',
    'preview.backchannel-site.workers.dev', 'unknown.backchannel.page',
  ]) {
    const response = await workerModule.route(new Request(`https://${host}/api/interest`), env,
      async () => { throw new Error('unknown hosts must not authorize'); });
    assert.equal(response.status, 404, host);
    assert.equal(response.headers.get('cache-control'), 'no-store');
  }

  const isolated = [
    new Request('https://backchannel.page/%61dmin/admin.js'),
    new Request('https://backchannel.page/downloads/downloads.js'),
    new Request('https://downloads.backchannel.page/admin.js'),
    new Request('https://downloads.backchannel.page/api%2Fdownload%2Freleases'),
    adminRequest('/downloads.js'),
  ];
  for (const requestValue of isolated) {
    const response = await workerModule.route(requestValue, env, allowOwner);
    assert.equal(response.status, 404, requestValue.url);
  }
  assert.equal(assets.length, 0);
});
