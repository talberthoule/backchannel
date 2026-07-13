import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = dirname(fileURLToPath(import.meta.url));
const site = join(root, '..', 'site');
const now = '2026-07-13T15:00:00.000Z';
const passwordExpiry = '2026-07-16T15:00:00.000Z';
const assets = new Map([
  ['/', ['admin/index.html', 'text/html; charset=utf-8']],
  ['/users', ['admin/index.html', 'text/html; charset=utf-8']],
  ['/early-access', ['admin/index.html', 'text/html; charset=utf-8']],
  ['/authorization', ['admin/index.html', 'text/html; charset=utf-8']],
  ['/style.css', ['style.css', 'text/css; charset=utf-8']],
  ['/admin.css', ['admin/admin.css', 'text/css; charset=utf-8']],
  ['/admin.js', ['admin/admin.js', 'text/javascript; charset=utf-8']],
  ['/admin-core.js', ['admin/admin-core.js', 'text/javascript; charset=utf-8']],
  ['/early-access.js', ['admin/early-access.js', 'text/javascript; charset=utf-8']],
  ['/users.js', ['admin/users.js', 'text/javascript; charset=utf-8']],
  ['/authorization.js', ['admin/authorization.js', 'text/javascript; charset=utf-8']],
]);

function createFixtures() {
  const interest = (email, decision = 'approved') => ({
    email,
    status: decision === 'approved' ? 'active' : 'subscribed',
    source: 'admin-preview',
    consent_version: '2026-07-11',
    consent_at: '2026-07-12T14:00:00.000Z',
    created_at: '2026-07-12T14:00:00.000Z',
    invited_at: null,
    last_contacted_at: null,
    release_decision: decision,
    release_reviewed_at: decision === 'pending' ? null : '2026-07-12T15:00:00.000Z',
  });
  const user = (email, fields = {}) => ({
    email,
    state: 'active',
    source: 'admin-preview',
    requested_at: '2026-07-12T14:00:00.000Z',
    approved_at: '2026-07-12T15:00:00.000Z',
    must_change_password: false,
    password_expires_at: null,
    password_changed_at: '2026-07-12T16:00:00.000Z',
    revoked_at: null,
    active_session_count: 0,
    latest_session_expires_at: null,
    ...fields,
  });
  return {
    interests: [
      interest('pending@preview.example', 'pending'),
      interest('reject@preview.example', 'pending'),
      ...['loaded', 'temporary', 'revoked', 'historical']
        .map((name) => interest(`${name}@preview.example`)),
    ],
    users: [
      user('loaded@preview.example', {
        active_session_count: 2,
        latest_session_expires_at: '2026-07-13T16:00:00.000Z',
      }),
      user('temporary@preview.example', {
        must_change_password: true,
        password_expires_at: passwordExpiry,
        password_changed_at: null,
        active_session_count: 1,
        latest_session_expires_at: '2026-07-13T16:00:00.000Z',
      }),
      user('revoked@preview.example', {
        state: 'revoked',
        revoked_at: '2026-07-13T14:00:00.000Z',
      }),
      user('historical@preview.example'),
    ],
    authorization: [
      {
        email: 'loaded@preview.example',
        account_state: 'active',
        include_latest: true,
        versions: [],
        updated_at: now,
      },
      {
        email: 'temporary@preview.example',
        account_state: 'active',
        include_latest: true,
        versions: ['v0.2.1'],
        updated_at: now,
      },
      {
        email: 'revoked@preview.example',
        account_state: 'revoked',
        include_latest: false,
        versions: ['v0.1.1'],
        updated_at: now,
      },
      {
        email: 'historical@preview.example',
        account_state: 'active',
        include_latest: false,
        versions: ['v0.2.0'],
        updated_at: now,
      },
    ],
    releases: {
      items: [
        { version: 'v0.2.1', published_at: '2026-07-11T12:00:00.000Z' },
        { version: 'v0.2.0', published_at: '2026-07-10T12:00:00.000Z' },
        { version: 'v0.1.1', published_at: '2026-07-09T12:00:00.000Z' },
      ],
      latest_version: 'v0.2.1',
      available: true,
    },
  };
}

function sendJson(response, status, value) {
  response.writeHead(status, {
    'cache-control': 'no-store',
    'content-type': 'application/json; charset=utf-8',
  });
  response.end(JSON.stringify(value));
}

function fail(response, status = 400) {
  sendJson(response, status, { ok: false, message: 'Request could not be completed.' });
}

async function readBody(request) {
  let body = '';
  for await (const chunk of request) {
    body += chunk;
    if (body.length > 8192) throw new Error('body too large');
  }
  const value = JSON.parse(body);
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('invalid body');
  return value;
}

function replace(items, item) {
  const index = items.findIndex(({ email }) => email === item.email);
  if (index < 0) return false;
  items[index] = item;
  return true;
}

async function mutate(request, response, path, fixtures) {
  let body;
  try {
    body = await readBody(request);
  } catch {
    fail(response);
    return;
  }
  const email = typeof body.email === 'string' ? body.email.trim().toLowerCase() : '';
  if (!email.endsWith('@preview.example')) {
    fail(response);
    return;
  }

  if (path === '/api/admin/interests/approve' && request.method === 'POST') {
    const item = fixtures.interests.find((entry) => (
      entry.email === email && entry.release_decision === 'pending'
    ));
    if (!item) return fail(response, 409);
    Object.assign(item, { status: 'active', release_decision: 'approved', release_reviewed_at: now });
    fixtures.users.push({
      email,
      state: 'active',
      source: item.source,
      requested_at: item.created_at,
      approved_at: now,
      must_change_password: true,
      password_expires_at: passwordExpiry,
      password_changed_at: null,
      revoked_at: null,
      active_session_count: 0,
      latest_session_expires_at: null,
    });
    fixtures.authorization.push({
      email,
      account_state: 'active',
      include_latest: true,
      versions: [],
      updated_at: now,
    });
    sendJson(response, 201, {
      ok: true,
      credential: { email, password: 'not-a-real-password', password_expires_at: passwordExpiry },
    });
    return;
  }

  if (path === '/api/admin/interests/reject' && request.method === 'POST') {
    const item = fixtures.interests.find((entry) => (
      entry.email === email && entry.release_decision === 'pending'
    ));
    if (!item) return fail(response, 409);
    const updated = { ...item, release_decision: 'rejected', release_reviewed_at: now };
    replace(fixtures.interests, updated);
    sendJson(response, 200, { ok: true, item: updated });
    return;
  }

  const user = fixtures.users.find((entry) => entry.email === email);
  if (path === '/api/admin/users/reset-password' && request.method === 'POST') {
    if (!user || user.state !== 'active') return fail(response, 409);
    const item = {
      ...user,
      must_change_password: true,
      password_expires_at: passwordExpiry,
      password_changed_at: null,
      active_session_count: 0,
      latest_session_expires_at: null,
    };
    replace(fixtures.users, item);
    sendJson(response, 200, {
      ok: true,
      item,
      credential: { email, password: 'not-a-real-password', password_expires_at: passwordExpiry },
    });
    return;
  }

  if (path === '/api/admin/users/sign-out' && request.method === 'POST') {
    if (!user || user.state !== 'active' || user.active_session_count < 1) return fail(response, 409);
    const item = { ...user, active_session_count: 0, latest_session_expires_at: null };
    replace(fixtures.users, item);
    sendJson(response, 200, { ok: true, item });
    return;
  }

  if (path === '/api/admin/users/revoke' && request.method === 'POST') {
    if (!user || user.state !== 'active') return fail(response, 409);
    const item = {
      ...user,
      state: 'revoked',
      revoked_at: now,
      active_session_count: 0,
      latest_session_expires_at: null,
    };
    replace(fixtures.users, item);
    const authorization = fixtures.authorization.find((entry) => entry.email === email);
    if (authorization) replace(fixtures.authorization, { ...authorization, account_state: 'revoked' });
    sendJson(response, 200, { ok: true, item });
    return;
  }

  if (path === '/api/admin/authorization/grants' && request.method === 'PUT') {
    const authorization = fixtures.authorization.find((entry) => entry.email === email);
    const versions = body.versions;
    if (!authorization || authorization.account_state !== 'active'
      || typeof body.include_latest !== 'boolean' || !Array.isArray(versions)
      || (!body.include_latest && versions.length === 0)
      || versions.some((version) => !fixtures.releases.items.some((item) => item.version === version))) {
      return fail(response, 409);
    }
    const item = {
      ...authorization,
      include_latest: body.include_latest,
      versions: [...versions],
      updated_at: now,
    };
    replace(fixtures.authorization, item);
    sendJson(response, 200, { ok: true, item });
    return;
  }

  fail(response, 404);
}

export function createAdminPreviewServer() {
  const fixtures = createFixtures();
  return createServer(async (request, response) => {
    const path = new URL(request.url, 'http://127.0.0.1').pathname;
    if (request.method === 'GET' && path === '/api/admin/interests') {
      return sendJson(response, 200, { items: fixtures.interests });
    }
    if (request.method === 'GET' && path === '/api/admin/users') {
      return sendJson(response, 200, { items: fixtures.users });
    }
    if (request.method === 'GET' && path === '/api/admin/authorization') {
      return sendJson(response, 200, { items: fixtures.authorization });
    }
    if (request.method === 'GET' && path === '/api/admin/releases') {
      return sendJson(response, 200, fixtures.releases);
    }
    if (path.startsWith('/api/admin/')) return mutate(request, response, path, fixtures);

    const asset = request.method === 'GET' ? assets.get(path) : null;
    if (!asset) return fail(response, 404);
    try {
      const bytes = await readFile(join(site, asset[0]));
      response.writeHead(200, { 'cache-control': 'no-store', 'content-type': asset[1] });
      response.end(bytes);
    } catch {
      fail(response, 404);
    }
  });
}

if (process.argv[1] && pathToFileURL(process.argv[1]).href === import.meta.url) {
  createAdminPreviewServer().listen(4175, '127.0.0.1', () => {
    console.log('Admin preview: http://127.0.0.1:4175/users');
  });
}
