import assert from 'node:assert/strict';
import test from 'node:test';

import worker, { handleInterest } from './worker.js';

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
