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

function approvePreview(response, fixtures, email) {
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
  return sendJson(response, 201, {
    ok: true,
    credential: { email, password: 'not-a-real-password', password_expires_at: passwordExpiry },
  });
}

function rejectPreview(response, fixtures, email) {
  const item = fixtures.interests.find((entry) => (
    entry.email === email && entry.release_decision === 'pending'
  ));
  if (!item) return fail(response, 409);
  const updated = { ...item, release_decision: 'rejected', release_reviewed_at: now };
  replace(fixtures.interests, updated);
  return sendJson(response, 200, { ok: true, item: updated });
}

function resetPreviewPassword(response, fixtures, email) {
  const user = fixtures.users.find((entry) => entry.email === email);
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
  return sendJson(response, 200, {
    ok: true,
    item,
    credential: { email, password: 'not-a-real-password', password_expires_at: passwordExpiry },
  });
}

function signOutPreview(response, fixtures, email) {
  const user = fixtures.users.find((entry) => entry.email === email);
  const valid = [user, user?.state === 'active', user?.active_session_count > 0].every(Boolean);
  if (!valid) return fail(response, 409);
  const item = { ...user, active_session_count: 0, latest_session_expires_at: null };
  replace(fixtures.users, item);
  return sendJson(response, 200, { ok: true, item });
}

function revokePreview(response, fixtures, email) {
  const user = fixtures.users.find((entry) => entry.email === email);
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
  return sendJson(response, 200, { ok: true, item });
}

function reactivatePreview(response, fixtures, email) {
  const user = fixtures.users.find((entry) => entry.email === email);
  if (!user || user.state !== 'revoked') return fail(response, 409);
  const item = { ...user, state: 'active', revoked_at: null };
  replace(fixtures.users, item);
  const authorization = fixtures.authorization.find((entry) => entry.email === email);
  if (authorization) replace(fixtures.authorization, { ...authorization, account_state: 'active' });
  return sendJson(response, 200, { ok: true, item });
}

function replacePreviewGrants(response, fixtures, email, body) {
  const authorization = fixtures.authorization.find((entry) => entry.email === email);
  const versions = body.versions;
  const validBase = [
    authorization,
    authorization?.account_state === 'active',
    typeof body.include_latest === 'boolean',
    Array.isArray(versions),
  ].every(Boolean);
  if (!validBase) return fail(response, 409);
  if (!body.include_latest && versions.length === 0) return fail(response, 409);
  const available = new Set(fixtures.releases.items.map(({ version }) => version));
  if (!versions.every((version) => available.has(version))) return fail(response, 409);
  const item = {
    ...authorization,
    include_latest: body.include_latest,
    versions: [...versions],
    updated_at: now,
  };
  replace(fixtures.authorization, item);
  return sendJson(response, 200, { ok: true, item });
}

const mutationRoutes = {
  'POST /api/admin/interests/approve': approvePreview,
  'POST /api/admin/interests/reject': rejectPreview,
  'POST /api/admin/users/reset-password': resetPreviewPassword,
  'POST /api/admin/users/sign-out': signOutPreview,
  'POST /api/admin/users/revoke': revokePreview,
  'POST /api/admin/users/reactivate': reactivatePreview,
  'PUT /api/admin/authorization/grants': replacePreviewGrants,
};

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
  const handler = mutationRoutes[`${request.method} ${path}`];
  return handler ? handler(response, fixtures, email, body) : fail(response, 404);
}

const adminReads = {
  '/api/admin/interests': (fixtures) => ({ items: fixtures.interests }),
  '/api/admin/users': (fixtures) => ({ items: fixtures.users }),
  '/api/admin/authorization': (fixtures) => ({ items: fixtures.authorization }),
  '/api/admin/releases': (fixtures) => fixtures.releases,
};

function sendAdminRead(request, response, path, fixtures) {
  if (request.method !== 'GET') return false;
  const read = adminReads[path];
  if (!read) return false;
  sendJson(response, 200, read(fixtures));
  return true;
}

async function sendAsset(request, response, path) {
  const asset = request.method === 'GET' ? assets.get(path) : null;
  if (!asset) return fail(response, 404);
  try {
    const bytes = await readFile(join(site, asset[0]));
    response.writeHead(200, { 'cache-control': 'no-store', 'content-type': asset[1] });
    return response.end(bytes);
  } catch {
    return fail(response, 404);
  }
}

export function createAdminPreviewServer() {
  const fixtures = createFixtures();
  return createServer(async (request, response) => {
    const path = new URL(request.url, 'http://127.0.0.1').pathname;
    if (sendAdminRead(request, response, path, fixtures)) return;
    if (path.startsWith('/api/admin/')) return mutate(request, response, path, fixtures);
    return sendAsset(request, response, path);
  });
}

export function listenAdminPreview(server, port, onListening) {
  return server.listen(port, '127.0.0.1', onListening);
}

if (process.argv[1] && pathToFileURL(process.argv[1]).href === import.meta.url) {
  listenAdminPreview(createAdminPreviewServer(), 4175, () => {
    console.log('Admin preview: http://127.0.0.1:4175/users');
  });
}
