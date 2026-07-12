import assert from 'node:assert/strict';
import test from 'node:test';

import worker, { handleInterest } from './worker.js';
import * as workerModule from './worker.js';

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
  account_state: null,
  include_latest: null,
  versions: [],
};

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
  releases,
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

test('admin authorization runs before mutation body parsing', async () => {
  const { env, calls } = adminBindings();
  const response = await workerModule.route(
    adminJson('/api/admin/access/approve', '{'),
    env,
    async () => ({ email: 'other@example.com' }),
    fixedDependencies,
  );
  assert.equal(response.status, 403);
  assert.equal(calls.length, 0);
});

test('admin mutations enforce exact origin, JSON media type, and bounded bodies', async () => {
  const cases = [
    [adminJson('/api/admin/access/reject', { email: 'person@example.com' }, {
      headers: { origin: 'https://attacker.example' },
    }), 403],
    [adminJson('/api/admin/access/reject', { email: 'person@example.com' }, {
      headers: { 'content-type': 'text/plain' },
    }), 415],
    [adminJson('/api/admin/access/reject', 'x'.repeat(8193)), 413],
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
  const response = await workerModule.route(adminJson('/api/admin/access/approve', {
    email: ' Person@Example.com ',
    include_latest: true,
    versions: ['v0.2.0', 'v0.1.1'],
  }), env, allowOwner, fixedDependencies);

  assert.equal(response.status, 201);
  const { credential } = await response.json();
  assert.deepEqual({ ...credential, password: undefined }, {
    email: 'person@example.com',
    password: undefined,
    password_expires_at: '2026-07-15T12:00:00.000Z',
    include_latest: true,
    versions: ['v0.2.0', 'v0.1.1'],
  });
  assert.equal(credential.password.length, 20);
  assert.equal(batchCalls.length, 1);
  const batchSql = calls.map(({ sql }) => sql);
  assert.match(batchSql[0], /INSERT INTO release_accounts[\s\S]+SELECT[\s\S]+WHERE EXISTS/i);
  assert.match(batchSql[1], /INSERT INTO release_account_versions/i);
  assert.match(batchSql[2], /INSERT INTO release_account_versions/i);
  for (const grantSql of batchSql.slice(1, 3)) {
    assert.match(grantSql, /INSERT INTO release_account_versions[\s\S]+SELECT[\s\S]+WHERE EXISTS/i);
    assert.match(grantSql, /release_accounts[\s\S]+state = 'active'/i);
    assert.match(grantSql, /interest_subscribers/i);
  }
  assert.match(batchSql[3], /UPDATE interest_subscribers/i);
  assert.match(batchSql[4], /INSERT INTO release_access_events/i);
  assert.match(batchSql[4], /WHERE EXISTS[\s\S]+release_accounts/i);
  assert.equal(JSON.stringify(calls.map(({ values }) => values)).includes(credential.password), false);
  assert.ok(calls.flatMap(({ values }) => values).includes('person@example.com'));
});

test('approval with explicit versions cannot create orphan grants when interest is absent', async () => {
  const absent = adminBindings({
    batch: async (statements) => statements.map((_, index) => ({
      success: true,
      meta: { changes: index === 0 ? 0 : 1 },
    })),
  });
  const absentResponse = await workerModule.route(adminJson('/api/admin/access/approve', {
    email: 'missing@example.com', include_latest: true, versions: ['v1.2.3'],
  }), absent.env, allowOwner, fixedDependencies);
  assert.ok([404, 409].includes(absentResponse.status));
  assert.doesNotMatch(await absentResponse.text(), /missing@example|password/i);
  assert.match(absent.calls[1].sql, /INSERT INTO release_account_versions[\s\S]+WHERE EXISTS/i);
  assert.match(absent.calls[1].sql, /release_accounts[\s\S]+interest_subscribers/i);
});

test('approval fails generically when a concurrent account wins', async () => {
  const duplicate = adminBindings({
    batch: async () => { throw new Error('UNIQUE release_accounts.email'); },
  });
  const duplicateResponse = await workerModule.route(adminJson('/api/admin/access/approve', {
    email: 'person@example.com', include_latest: true, versions: [],
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
      adminJson('/api/admin/access/approve', body), env, allowOwner, fixedDependencies,
    );
    assert.equal(response.status, 400);
    assert.equal(calls.length, 0);
  }
});

test('admin entitlement input rejects more than 100 unique canonical versions', async () => {
  const { env, calls } = adminBindings();
  const versions = Array.from({ length: 101 }, (_, index) => `v1.2.${index}`);
  const response = await workerModule.route(adminJson('/api/admin/access/approve', {
    email: 'person@example.com', include_latest: true, versions,
  }), env, allowOwner, fixedDependencies);
  assert.equal(new Set(versions).size, 101);
  assert.equal(response.status, 400);
  assert.equal(calls.length, 0);
});

test('rejection preserves consent and never creates an account', async () => {
  const { env, calls, batchCalls } = adminBindings();
  const response = await workerModule.route(adminJson('/api/admin/access/reject', {
    email: ' Person@Example.com ',
  }), env, allowOwner, fixedDependencies);
  assert.equal(response.status, 200);
  assert.equal(batchCalls.length, 1);
  assert.equal(calls.length, 2);
  assert.match(calls[0].sql, /UPDATE interest_subscribers[\s\S]+release_decision/i);
  assert.doesNotMatch(calls.map(({ sql }) => sql).join('\n'), /release_accounts/);
  assert.match(calls[1].sql, /rejection/);
});

test('grant replacement checks active state and batches delete, inserts, update, and event', async () => {
  const { env, calls, batchCalls } = adminBindings();
  const response = await workerModule.route(adminJson('/api/admin/access/grants', {
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
  const deniedResponse = await workerModule.route(adminJson('/api/admin/access/grants', {
    email: 'person@example.com', include_latest: false, versions: [],
  }, { method: 'PUT' }), denied.env, allowOwner, fixedDependencies);
  assert.equal(deniedResponse.status, 400);
  assert.equal(denied.calls.length, 0);
});

test('password reset and revocation delete sessions atomically without reactivating accounts', async () => {
  const reset = adminBindings();
  const resetResponse = await workerModule.route(adminJson('/api/admin/access/reset-password', {
    email: 'person@example.com',
  }), reset.env, allowOwner, fixedDependencies);
  assert.equal(resetResponse.status, 200);
  const resetCredential = (await resetResponse.json()).credential;
  assert.equal(resetCredential.password.length, 20);
  assert.equal(reset.batchCalls.length, 1);
  assert.match(reset.calls[1].sql, /UPDATE release_accounts[\s\S]+must_change_password[\s\S]+password_changed_at/i);
  assert.match(reset.calls[1].sql, /release_decision = 'approved'/i);
  assert.doesNotMatch(reset.calls[1].sql, /SET\s+state\s*=/i);
  assert.match(reset.calls[2].sql, /DELETE FROM release_sessions/i);
  assert.match(reset.calls[3].sql, /password_reset/);
  assert.match(reset.calls[3].sql, /WHERE EXISTS[\s\S]+state = 'active'/i);
  assert.match(reset.calls[3].sql, /release_decision = 'approved'/i);
  assert.equal(JSON.stringify(reset.calls).includes(resetCredential.password), false);

  const revokedReset = adminBindings({ first: async () => ({ state: 'revoked', release_decision: 'approved' }) });
  const revokedResetResponse = await workerModule.route(adminJson('/api/admin/access/reset-password', {
    email: 'person@example.com',
  }), revokedReset.env, allowOwner, fixedDependencies);
  assert.equal(revokedResetResponse.status, 409);
  assert.equal(revokedReset.batchCalls.length, 0);

  const revoke = adminBindings();
  const revokeResponse = await workerModule.route(adminJson('/api/admin/access/revoke', {
    email: 'person@example.com',
  }), revoke.env, allowOwner, fixedDependencies);
  assert.equal(revokeResponse.status, 200);
  assert.equal(revoke.batchCalls.length, 1);
  assert.match(revoke.calls[0].sql, /UPDATE release_accounts[\s\S]+state\s*=\s*'revoked'/i);
  assert.match(revoke.calls[1].sql, /DELETE FROM release_sessions/i);
  assert.match(revoke.calls[2].sql, /revocation/);
});

test('admin release catalog returns summaries and keeps diagnostics generic', async () => {
  const manifest = {
    version: 'v1.2.3',
    published_at: '2026-07-12T12:00:00Z',
    commit: 'a'.repeat(40),
    assets: [{
      id: 'windows-x64', platform: 'Windows x64', filename: 'Backchannel-windows-x64.zip',
      key: 'releases/v1.2.3/Backchannel-windows-x64.zip', size: 1,
      sha256: 'b'.repeat(64), content_type: 'application/zip',
    }],
  };
  const releases = {
    async list() { return { objects: [{ key: 'releases/v1.2.3/manifest.json' }] }; },
    async get(key) {
      return { json: async () => key.endsWith('latest.json') ? { version: 'v1.2.3' } : manifest };
    },
  };
  const good = adminBindings({ releases });
  const response = await workerModule.route(adminRequest('/api/admin/releases'), good.env, allowOwner);
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), {
    items: [{ version: 'v1.2.3', published_at: '2026-07-12T12:00:00Z' }],
    latest_version: 'v1.2.3',
  });

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
    ['/admin/index.html', '/style.css', '/admin/admin.js'],
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
