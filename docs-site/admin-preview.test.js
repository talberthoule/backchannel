import assert from 'node:assert/strict';
import { access } from 'node:fs/promises';
import { once } from 'node:events';
import test from 'node:test';

import { createAdminPreviewServer, listenAdminPreview } from './admin-preview.mjs';

async function startPreview() {
  const server = createAdminPreviewServer();
  assert.equal(server.listening, false);
  listenAdminPreview(server, 0);
  await once(server, 'listening');
  const address = server.address();
  assert.equal(address.address, '127.0.0.1');
  return {
    server,
    url: `http://127.0.0.1:${address.port}`,
  };
}

async function requestJson(url, path, options) {
  const response = await fetch(`${url}${path}`, options);
  return { response, value: await response.json() };
}

function json(method, body) {
  return {
    method,
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  };
}

test('admin preview serves protected page routes and real source assets on loopback', async (t) => {
  const { server, url } = await startPreview();
  t.after(() => server.close());

  const page = await fetch(`${url}/users`);
  assert.equal(page.status, 200);
  assert.match(page.headers.get('content-type'), /^text\/html/);
  assert.match(await page.text(), /<script type="module" src="\/admin\.js"><\/script>/);

  const module = await fetch(`${url}/users.js`);
  assert.equal(module.status, 200);
  assert.match(module.headers.get('content-type'), /^text\/javascript/);
  assert.match(await module.text(), /const endpoint = '\/api\/admin\/users'/);

  const unknown = await fetch(`${url}/admin-preview.mjs`);
  assert.equal(unknown.status, 404);
});

test('admin preview exposes deterministic separated route fixtures', async (t) => {
  const { server, url } = await startPreview();
  t.after(() => server.close());

  const interests = await requestJson(url, '/api/admin/interests');
  assert.equal(interests.response.status, 200);
  assert.ok(interests.value.items.some(({ email, release_decision }) => (
    email.endsWith('@preview.example') && release_decision === 'pending'
  )));

  const users = await requestJson(url, '/api/admin/users');
  assert.equal(users.response.status, 200);
  assert.ok(users.value.items.every(({ email }) => email.endsWith('@preview.example')));
  assert.ok(users.value.items.some(({ state }) => state === 'revoked'));
  assert.ok(users.value.items.some(({ must_change_password }) => must_change_password));

  const authorization = await requestJson(url, '/api/admin/authorization');
  assert.equal(authorization.response.status, 200);
  assert.ok(authorization.value.items.every(({ email }) => email.endsWith('@preview.example')));
  assert.ok(authorization.value.items.some(({ include_latest, versions }) => (
    !include_latest && versions.length > 0
  )));

  const releases = await requestJson(url, '/api/admin/releases');
  assert.equal(releases.response.status, 200);
  assert.deepEqual(Object.keys(releases.value).sort(), ['available', 'items', 'latest_version']);
  assert.equal(releases.value.available, true);
});

test('admin preview mutations match Worker shapes and update in-memory fixtures', async (t) => {
  const { server, url } = await startPreview();
  t.after(() => server.close());

  const pendingEmail = 'pending@preview.example';
  const approve = await requestJson(
    url,
    '/api/admin/interests/approve',
    json('POST', { email: pendingEmail }),
  );
  assert.equal(approve.response.status, 201);
  assert.deepEqual(Object.keys(approve.value).sort(), ['credential', 'ok']);
  assert.equal(approve.value.credential.email, pendingEmail);

  const usersAfterApprove = await requestJson(url, '/api/admin/users');
  assert.ok(usersAfterApprove.value.items.some(({ email }) => email === pendingEmail));
  const authorizationAfterApprove = await requestJson(url, '/api/admin/authorization');
  assert.ok(authorizationAfterApprove.value.items.some(({ email, include_latest }) => (
    email === pendingEmail && include_latest
  )));

  const reject = await requestJson(
    url,
    '/api/admin/interests/reject',
    json('POST', { email: 'reject@preview.example' }),
  );
  assert.equal(reject.response.status, 200);
  assert.deepEqual(Object.keys(reject.value).sort(), ['item', 'ok']);
  assert.equal(reject.value.item.release_decision, 'rejected');
  const interestsAfterReject = await requestJson(url, '/api/admin/interests');
  assert.deepEqual(
    interestsAfterReject.value.items.find(({ email }) => email === reject.value.item.email),
    reject.value.item,
    'reject persists to the next interests read',
  );

  const reset = await requestJson(
    url,
    '/api/admin/users/reset-password',
    json('POST', { email: 'loaded@preview.example' }),
  );
  assert.equal(reset.response.status, 200);
  assert.deepEqual(Object.keys(reset.value).sort(), ['credential', 'item', 'ok']);
  assert.equal(reset.value.item.must_change_password, true);
  assert.equal(reset.value.item.active_session_count, 0);
  const usersAfterReset = await requestJson(url, '/api/admin/users');
  assert.deepEqual(
    usersAfterReset.value.items.find(({ email }) => email === reset.value.item.email),
    reset.value.item,
    'password reset persists to the next users read',
  );

  const signOut = await requestJson(
    url,
    '/api/admin/users/sign-out',
    json('POST', { email: 'temporary@preview.example' }),
  );
  assert.equal(signOut.response.status, 200);
  assert.deepEqual(Object.keys(signOut.value).sort(), ['item', 'ok']);
  assert.equal(signOut.value.item.active_session_count, 0);
  const usersAfterSignOut = await requestJson(url, '/api/admin/users');
  assert.deepEqual(
    usersAfterSignOut.value.items.find(({ email }) => email === signOut.value.item.email),
    signOut.value.item,
    'session sign-out persists to the next users read',
  );

  const revoke = await requestJson(
    url,
    '/api/admin/users/revoke',
    json('POST', { email: 'historical@preview.example' }),
  );
  assert.equal(revoke.response.status, 200);
  assert.deepEqual(Object.keys(revoke.value).sort(), ['item', 'ok']);
  assert.equal(revoke.value.item.state, 'revoked');
  const authorizationAfterRevoke = await requestJson(url, '/api/admin/authorization');
  assert.equal(
    authorizationAfterRevoke.value.items.find(({ email }) => email === revoke.value.item.email)
      .account_state,
    'revoked',
  );

  const grants = await requestJson(
    url,
    '/api/admin/authorization/grants',
    json('PUT', {
      email: 'loaded@preview.example',
      include_latest: false,
      versions: ['v0.2.0'],
    }),
  );
  assert.equal(grants.response.status, 200);
  assert.deepEqual(Object.keys(grants.value).sort(), ['item', 'ok']);
  assert.equal(grants.value.item.include_latest, false);
  assert.deepEqual(grants.value.item.versions, ['v0.2.0']);
  const authorizationAfterGrants = await requestJson(url, '/api/admin/authorization');
  assert.deepEqual(
    authorizationAfterGrants.value.items.find(({ email }) => email === grants.value.item.email),
    grants.value.item,
    'grant replacement persists to the next authorization read',
  );
});

test('admin preview source is not assembled into dist-site', async () => {
  await assert.rejects(
    access(new URL('./dist-site/admin-preview.mjs', import.meta.url)),
    { code: 'ENOENT' },
  );
});
