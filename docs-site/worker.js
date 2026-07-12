import { createRemoteJWKSet, jwtVerify } from 'jose';
import {
  CHANGE_SESSION_TTL_SECONDS,
  PASSWORD_ITERATIONS,
  SESSION_COOKIE,
  SESSION_TTL_SECONDS,
  TEMPORARY_PASSWORD_TTL_SECONDS,
  createSessionToken,
  generateTemporaryPassword,
  hashPassword,
  loadReleaseCatalog,
  verifyPassword,
} from './release-access.js';

const API_PATH = '/api/interest';
const ADMIN_HOST = 'admin.backchannel.page';
const DOWNLOAD_HOST = 'downloads.backchannel.page';
const ADMIN_API_PATH = '/api/admin/interests';
const ADMIN_RELEASES_PATH = '/api/admin/releases';
const ADMIN_MUTATIONS = new Map([
  ['/api/admin/access/approve', ['POST', 'approve']],
  ['/api/admin/access/reject', ['POST', 'reject']],
  ['/api/admin/access/grants', ['PUT', 'grants']],
  ['/api/admin/access/reset-password', ['POST', 'reset']],
  ['/api/admin/access/revoke', ['POST', 'revoke']],
]);
const ADMIN_ASSETS = new Map([
  ['/', '/admin/index.html'],
  ['/index.html', '/admin/index.html'],
  ['/style.css', '/style.css'],
  ['/admin.css', '/admin/admin.css'],
  ['/admin.js', '/admin/admin.js'],
]);
const CONSENT_VERSION = '2026-07-11';
const MAX_BODY_BYTES = 4096;
const MAX_ADMIN_BODY_BYTES = 8192;
const MAX_DOWNLOAD_BODY_BYTES = 8192;
const SITEVERIFY_URL = 'https://challenges.cloudflare.com/turnstile/v0/siteverify';
const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const VERSION = /^v[0-9]+\.[0-9]+\.[0-9]+$/;
const ACCESS_HOST = /^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.cloudflareaccess\.com$/;
const PRIVATE_HEADERS = {
  'cache-control': 'no-store',
  'content-security-policy': "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
  'referrer-policy': 'no-referrer',
  'x-content-type-options': 'nosniff',
  'x-frame-options': 'DENY',
};
const accessKeySets = new Map();

function json(status, body, headers = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      'cache-control': 'no-store',
      'content-type': 'application/json; charset=utf-8',
      ...headers,
    },
  });
}

function serviceUnavailable() {
  return json(503, {
    ok: false,
    message: "We couldn't save this right now. Please try again.",
  });
}

function privateJson(status, body, headers = {}) {
  return json(status, body, { ...PRIVATE_HEADERS, ...headers });
}

function secureAsset(response) {
  const headers = new Headers(response.headers);
  for (const [name, value] of Object.entries(PRIVATE_HEADERS)) headers.set(name, value);
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}

export async function verifyAccessToken(
  token,
  env,
  dependencies = { createRemoteJWKSet, jwtVerify },
) {
  const host = String(env.ACCESS_TEAM_DOMAIN || '').trim().toLowerCase();
  if (!ACCESS_HOST.test(host)) throw new Error('invalid Access issuer');
  const issuer = `https://${host}`;
  let keys;
  if (dependencies.createRemoteJWKSet === createRemoteJWKSet) {
    keys = accessKeySets.get(issuer);
    if (!keys) {
      keys = createRemoteJWKSet(new URL(`${issuer}/cdn-cgi/access/certs`));
      accessKeySets.set(issuer, keys);
    }
  } else {
    keys = dependencies.createRemoteJWKSet(
      new URL(`${issuer}/cdn-cgi/access/certs`),
    );
  }
  const { payload } = await dependencies.jwtVerify(token, keys, {
    issuer,
    audience: env.ACCESS_AUD,
  });
  return payload;
}

export async function authorizeAdmin(request, env, verify = verifyAccessToken) {
  if (
    typeof env.ADMIN_EMAIL !== 'string' ||
    !EMAIL.test(env.ADMIN_EMAIL.trim()) ||
    typeof env.ACCESS_TEAM_DOMAIN !== 'string' ||
    !env.ACCESS_TEAM_DOMAIN.trim() ||
    typeof env.ACCESS_AUD !== 'string' ||
    !env.ACCESS_AUD.trim()
  ) {
    return privateJson(503, { ok: false, message: 'Admin is unavailable.' });
  }

  const token = request.headers.get('cf-access-jwt-assertion');
  if (!token) return privateJson(401, { ok: false, message: 'Unauthorized.' });

  let payload;
  try {
    payload = await verify(token, env);
  } catch {
    return privateJson(401, { ok: false, message: 'Unauthorized.' });
  }

  const actual = typeof payload.email === 'string'
    ? payload.email.trim().toLowerCase()
    : '';
  const expected = env.ADMIN_EMAIL.trim().toLowerCase();
  return actual === expected
    ? null
    : privateJson(403, { ok: false, message: 'Forbidden.' });
}

export async function handleAdminInterests(request, env) {
  if (request.method !== 'GET') {
    return privateJson(
      405,
      { ok: false, message: 'Method not allowed.' },
      { allow: 'GET' },
    );
  }
  if (!env.INTEREST_DB) {
    return privateJson(503, { ok: false, message: 'Admin is unavailable.' });
  }
  try {
    const result = await env.INTEREST_DB.prepare(`
      SELECT i.email, i.status, i.source, i.consent_version, i.consent_at, i.created_at,
             i.invited_at, i.last_contacted_at, i.release_decision,
             i.release_reviewed_at, a.state AS account_state, a.include_latest,
             COALESCE((SELECT json_group_array(version)
               FROM release_account_versions WHERE email = i.email), '[]') AS versions
      FROM interest_subscribers i
      LEFT JOIN release_accounts a ON a.email = i.email
      ORDER BY i.created_at DESC
    `).all();
    const items = (result.results || []).map((record) => {
      let versions = record.versions;
      if (typeof versions === 'string') {
        try { versions = JSON.parse(versions); } catch { versions = []; }
      }
      return { ...record, versions: Array.isArray(versions) ? versions : [] };
    });
    return privateJson(200, { items });
  } catch {
    return privateJson(503, {
      ok: false,
      message: 'Access requests could not be loaded.',
    });
  }
}

export async function handleAdminReleases(request, env) {
  if (request.method !== 'GET') {
    return privateJson(405, { ok: false, message: 'Method not allowed.' }, { allow: 'GET' });
  }
  if (!env.RELEASES) return privateJson(503, { ok: false, message: 'Admin is unavailable.' });
  try {
    const catalog = await loadReleaseCatalog(env.RELEASES);
    if (catalog.diagnostics.length || !catalog.latestVersion) throw new Error('catalog unavailable');
    const items = [...catalog.manifests.values()]
      .map(({ version, published_at }) => ({ version, published_at }))
      .sort((left, right) => right.published_at.localeCompare(left.published_at));
    return privateJson(200, { items, latest_version: catalog.latestVersion });
  } catch {
    return privateJson(503, { ok: false, message: 'Release catalog could not be loaded.' });
  }
}

async function readAdminBody(
  request,
  host = ADMIN_HOST,
  maxBytes = MAX_ADMIN_BODY_BYTES,
) {
  if (request.headers.get('origin') !== `https://${host}`) {
    return { response: privateJson(403, { ok: false, message: 'Request origin is not allowed.' }) };
  }
  const contentType = request.headers.get('content-type') || '';
  const [mediaType, ...parameters] = contentType.split(';').map((part) => part.trim());
  if (mediaType.toLowerCase() !== 'application/json'
    || parameters.some((part) => !/^charset\s*=\s*['"]?utf-8['"]?$/i.test(part))) {
    return { response: privateJson(415, { ok: false, message: 'Request must be JSON.' }) };
  }
  const declaredLength = Number(request.headers.get('content-length') || 0);
  if (declaredLength > maxBytes) {
    return { response: privateJson(413, { ok: false, message: 'Request is too large.' }) };
  }
  const reader = request.body?.getReader();
  if (!reader) return { response: privateJson(400, { ok: false, message: 'Request is not valid JSON.' }) };
  const chunks = [];
  let length = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      length += value.byteLength;
      if (length > maxBytes) {
        await reader.cancel();
        return { response: privateJson(413, { ok: false, message: 'Request is too large.' }) };
      }
      chunks.push(value);
    }
    const bytes = new Uint8Array(length);
    let offset = 0;
    for (const chunk of chunks) {
      bytes.set(chunk, offset);
      offset += chunk.byteLength;
    }
    const body = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes));
    if (!body || typeof body !== 'object' || Array.isArray(body)) throw new TypeError();
    return { body };
  } catch {
    return { response: privateJson(400, { ok: false, message: 'Request is not valid JSON.' }) };
  }
}

function emailFrom(body) {
  const email = typeof body.email === 'string' ? body.email.trim().toLowerCase() : '';
  return email && email.length <= 254 && EMAIL.test(email) ? email : null;
}

function entitlementsFrom(body) {
  if (typeof body.include_latest !== 'boolean' || !Array.isArray(body.versions)
    || body.versions.length > 100 || body.versions.some((version) => (
      typeof version !== 'string' || !VERSION.test(version)
    )) || new Set(body.versions).size !== body.versions.length
    || (!body.include_latest && body.versions.length === 0)) return null;
  return { includeLatest: body.include_latest, versions: body.versions };
}

function dbError(status = 503) {
  return privateJson(status, { ok: false, message: 'Request could not be completed.' });
}

function statement(env, sql, ...values) {
  return env.INTEREST_DB.prepare(sql).bind(...values);
}

function credential(email, password, expiresAt, includeLatest, versions) {
  return {
    email,
    password,
    password_expires_at: expiresAt,
    include_latest: includeLatest,
    versions,
  };
}

async function approve(env, email, access, dependencies, now) {
  const randomBytes = dependencies.randomBytes
    || ((length) => globalThis.crypto.getRandomValues(new Uint8Array(length)));
  const password = generateTemporaryPassword(randomBytes);
  const hashed = await hashPassword(password, { salt: randomBytes(16) });
  const expiresAt = new Date(Date.parse(now) + TEMPORARY_PASSWORD_TTL_SECONDS * 1000).toISOString();
  const statements = [statement(env, `
    INSERT INTO release_accounts
      (email, state, password_hash, password_salt, password_iterations,
       must_change_password, password_expires_at, include_latest, approved_at)
    SELECT ?, 'active', ?, ?, ?, 1, ?, ?, ?
    WHERE EXISTS (SELECT 1 FROM interest_subscribers WHERE email = ?)
  `, email, hashed.hash, hashed.salt, PASSWORD_ITERATIONS, expiresAt,
  access.includeLatest ? 1 : 0, now, email)];
  for (const version of access.versions) {
    statements.push(statement(env, `
      INSERT INTO release_account_versions (email, version, granted_at)
      SELECT ?, ?, ? WHERE EXISTS (
        SELECT 1 FROM release_accounts a
        JOIN interest_subscribers i ON i.email = a.email
        WHERE a.email = ? AND a.state = 'active'
      )
    `, email, version, now, email));
  }
  statements.push(
    statement(env, `
      UPDATE interest_subscribers
      SET status = 'active', release_decision = 'approved', release_reviewed_at = ?
      WHERE email = ? AND EXISTS
        (SELECT 1 FROM release_accounts WHERE email = ?)
    `, now, email, email),
    statement(env, `
      INSERT INTO release_access_events (email, action, version, created_at)
      SELECT ?, 'approval', NULL, ?
      WHERE EXISTS (SELECT 1 FROM release_accounts WHERE email = ?)
    `, email, now, email),
  );
  try {
    const results = await env.INTEREST_DB.batch(statements);
    if ((results[0]?.meta?.changes ?? 0) !== 1) return dbError(409);
  } catch (error) {
    return dbError(/UNIQUE[\s\S]*release_accounts|FOREIGN KEY/i.test(String(error)) ? 409 : 503);
  }
  return privateJson(201, {
    ok: true,
    credential: credential(email, password, expiresAt, access.includeLatest, access.versions),
  });
}

async function reject(env, email, now) {
  try {
    const results = await env.INTEREST_DB.batch([
      statement(env, `
        UPDATE interest_subscribers
        SET release_decision = 'rejected', release_reviewed_at = ? WHERE email = ?
      `, now, email),
      statement(env, `
        INSERT INTO release_access_events (email, action, version, created_at)
        SELECT ?, 'rejection', NULL, ?
        WHERE EXISTS (SELECT 1 FROM interest_subscribers WHERE email = ?)
      `, email, now, email),
    ]);
    return (results[0]?.meta?.changes ?? 0) === 1
      ? privateJson(200, { ok: true })
      : dbError(404);
  } catch {
    return dbError();
  }
}

async function activeAccount(env, email, withVersions = false) {
  return env.INTEREST_DB.prepare(`
    SELECT a.state, i.release_decision, a.include_latest${withVersions ? `,
      COALESCE((SELECT json_group_array(version) FROM release_account_versions
        WHERE email = a.email), '[]') AS versions` : ''}
    FROM release_accounts a
    JOIN interest_subscribers i ON i.email = a.email
    WHERE a.email = ?
  `).bind(email).first();
}

async function replaceGrants(env, email, access, now) {
  let account;
  try { account = await activeAccount(env, email); } catch { return dbError(); }
  if (account?.state !== 'active') return dbError(409);
  const statements = [statement(env, `
    DELETE FROM release_account_versions WHERE email = ? AND EXISTS
      (SELECT 1 FROM release_accounts WHERE email = ? AND state = 'active')
  `, email, email)];
  for (const version of access.versions) {
    statements.push(statement(env, `
      INSERT INTO release_account_versions (email, version, granted_at)
      SELECT ?, ?, ? WHERE EXISTS
        (SELECT 1 FROM release_accounts WHERE email = ? AND state = 'active')
    `, email, version, now, email));
  }
  statements.push(
    statement(env, `
      UPDATE release_accounts SET include_latest = ? WHERE email = ? AND state = 'active'
    `, access.includeLatest ? 1 : 0, email),
    statement(env, `
      INSERT INTO release_access_events (email, action, version, created_at)
      SELECT ?, 'grant_change', NULL, ? WHERE EXISTS
        (SELECT 1 FROM release_accounts WHERE email = ? AND state = 'active')
    `, email, now, email),
  );
  try {
    const results = await env.INTEREST_DB.batch(statements);
    const updateIndex = statements.length - 2;
    return (results[updateIndex]?.meta?.changes ?? 0) === 1
      ? privateJson(200, { ok: true })
      : dbError(409);
  } catch {
    return dbError();
  }
}

async function resetPassword(env, email, dependencies, now) {
  let account;
  try { account = await activeAccount(env, email, true); } catch { return dbError(); }
  if (account?.state !== 'active' || account.release_decision !== 'approved') return dbError(409);
  let versions = account.versions;
  if (typeof versions === 'string') {
    try { versions = JSON.parse(versions); } catch { versions = []; }
  }
  if (!Array.isArray(versions)) versions = [];
  const randomBytes = dependencies.randomBytes
    || ((length) => globalThis.crypto.getRandomValues(new Uint8Array(length)));
  const password = generateTemporaryPassword(randomBytes);
  const hashed = await hashPassword(password, { salt: randomBytes(16) });
  const expiresAt = new Date(Date.parse(now) + TEMPORARY_PASSWORD_TTL_SECONDS * 1000).toISOString();
  try {
    const results = await env.INTEREST_DB.batch([
      statement(env, `
        UPDATE release_accounts SET password_hash = ?, password_salt = ?,
          password_iterations = ?, password_expires_at = ?, must_change_password = 1,
          password_changed_at = NULL
        WHERE email = ? AND state = 'active' AND EXISTS
          (SELECT 1 FROM interest_subscribers WHERE email = ?
            AND release_decision = 'approved')
      `, hashed.hash, hashed.salt, PASSWORD_ITERATIONS, expiresAt, email, email),
      statement(env, `
        DELETE FROM release_sessions WHERE email = ? AND EXISTS
          (SELECT 1 FROM release_accounts a JOIN interest_subscribers i ON i.email = a.email
            WHERE a.email = ? AND a.state = 'active' AND i.release_decision = 'approved')
      `, email, email),
      statement(env, `
        INSERT INTO release_access_events (email, action, version, created_at)
        SELECT ?, 'password_reset', NULL, ? WHERE EXISTS
          (SELECT 1 FROM release_accounts a JOIN interest_subscribers i ON i.email = a.email
            WHERE a.email = ? AND a.state = 'active' AND i.release_decision = 'approved')
      `, email, now, email),
    ]);
    if ((results[0]?.meta?.changes ?? 0) !== 1) return dbError(409);
  } catch {
    return dbError();
  }
  return privateJson(200, {
    ok: true,
    credential: credential(email, password, expiresAt, account.include_latest === 1, versions),
  });
}

async function revoke(env, email, now) {
  try {
    const results = await env.INTEREST_DB.batch([
      statement(env, `
        UPDATE release_accounts SET state = 'revoked', revoked_at = ? WHERE email = ?
      `, now, email),
      statement(env, 'DELETE FROM release_sessions WHERE email = ?', email),
      statement(env, `
        INSERT INTO release_access_events (email, action, version, created_at)
        SELECT ?, 'revocation', NULL, ?
        WHERE EXISTS (SELECT 1 FROM release_accounts WHERE email = ?)
      `, email, now, email),
    ]);
    return (results[0]?.meta?.changes ?? 0) === 1
      ? privateJson(200, { ok: true })
      : dbError(404);
  } catch {
    return dbError();
  }
}

export async function handleAdminMutation(request, env, action, dependencies = {}) {
  if (!env.INTEREST_DB) return privateJson(503, { ok: false, message: 'Admin is unavailable.' });
  const parsed = await readAdminBody(request);
  if (parsed.response) return parsed.response;
  const email = emailFrom(parsed.body);
  if (!email) return privateJson(400, { ok: false, message: 'Request is invalid.' });
  const now = (dependencies.now ? dependencies.now() : new Date()).toISOString();
  if (action === 'approve' || action === 'grants') {
    const access = entitlementsFrom(parsed.body);
    if (!access) return privateJson(400, { ok: false, message: 'Request is invalid.' });
    return action === 'approve'
      ? approve(env, email, access, dependencies, now)
      : replaceGrants(env, email, access, now);
  }
  if (action === 'reject') return reject(env, email, now);
  if (action === 'reset') return resetPassword(env, email, dependencies, now);
  return revoke(env, email, now);
}

async function handleAdminAsset(request, env, assetPath) {
  if (request.method !== 'GET') {
    return privateJson(
      405,
      { ok: false, message: 'Method not allowed.' },
      { allow: 'GET' },
    );
  }
  if (!env.ASSETS) {
    return privateJson(503, { ok: false, message: 'Admin is unavailable.' });
  }
  const assetUrl = new URL(request.url);
  assetUrl.pathname = assetPath;
  assetUrl.search = '';
  try {
    return secureAsset(await env.ASSETS.fetch(new Request(assetUrl, request)));
  } catch {
    return privateJson(503, { ok: false, message: 'Admin is unavailable.' });
  }
}

function sessionCookie(token, maxAge) {
  return `${SESSION_COOKIE}=${token}; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age=${maxAge}`;
}

function clearSessionCookie() {
  return sessionCookie('', 0);
}

function signInDenied() {
  return privateJson(401, { ok: false, error: 'Unable to sign in.' });
}

function downloadUnavailable() {
  return privateJson(503, { ok: false, error: 'Request could not be completed.' });
}

function downloadNow(dependencies) {
  return dependencies.now ? dependencies.now() : new Date();
}

function rawSessionToken(request) {
  const prefix = `${SESSION_COOKIE}=`;
  const cookie = (request.headers.get('cookie') || '')
    .split(';')
    .map((part) => part.trim())
    .find((part) => part.startsWith(prefix));
  return cookie ? cookie.slice(prefix.length) : null;
}

async function tokenHashFromRequest(request) {
  const token = rawSessionToken(request);
  if (!token || !/^[A-Za-z0-9_-]{43}$/.test(token)) return null;
  try {
    const bytes = Uint8Array.from(
      atob(`${token.replaceAll('-', '+').replaceAll('_', '/')}=`),
      (character) => character.charCodeAt(0),
    );
    if (bytes.length !== 32) return null;
    const digest = new Uint8Array(await globalThis.crypto.subtle.digest('SHA-256', bytes));
    return btoa(String.fromCharCode(...digest))
      .replaceAll('+', '-')
      .replaceAll('/', '_')
      .replace(/=+$/, '');
  } catch {
    return null;
  }
}

async function findDownloadSession(env, tokenHash, now) {
  if (!tokenHash) return null;
  const account = await env.INTEREST_DB.prepare(`
    SELECT s.email, s.password_change_only, s.expires_at, a.state
    FROM release_sessions s
    JOIN release_accounts a ON a.email = s.email
    WHERE s.token_hash = ? AND s.expires_at > ? AND a.state = 'active'
  `).bind(tokenHash, now.toISOString()).first();
  const expiresAt = Date.parse(account?.expires_at);
  if (!account || account.state !== 'active'
    || ![0, 1].includes(account.password_change_only)
    || typeof account.email !== 'string'
    || !Number.isFinite(expiresAt) || expiresAt <= now.getTime()) return null;
  return account;
}

async function readDownloadBody(request) {
  return readAdminBody(request, DOWNLOAD_HOST, MAX_DOWNLOAD_BODY_BYTES);
}

async function handleDownloadLogin(request, env, dependencies) {
  const parsed = await readDownloadBody(request);
  if (parsed.response) return parsed.response;
  const email = emailFrom(parsed.body);
  const password = typeof parsed.body.password === 'string' ? parsed.body.password : '';
  const turnstileToken = typeof parsed.body.turnstile_token === 'string'
    ? parsed.body.turnstile_token
    : '';
  if (!email || password.length < 1 || password.length > 128
    || turnstileToken.length < 1 || turnstileToken.length > 2048) {
    return privateJson(400, { ok: false, error: 'Request is invalid.' });
  }
  if (!env.INTEREST_DB || typeof env.TURNSTILE_SECRET !== 'string'
    || !env.TURNSTILE_SECRET) return downloadUnavailable();

  let verification;
  try {
    const form = new FormData();
    form.set('secret', env.TURNSTILE_SECRET);
    form.set('response', turnstileToken);
    const response = await (dependencies.fetch || fetch)(SITEVERIFY_URL, {
      method: 'POST',
      body: form,
    });
    if (!response.ok) return downloadUnavailable();
    verification = await response.json();
  } catch {
    return downloadUnavailable();
  }
  if (verification?.success !== true || verification.hostname !== DOWNLOAD_HOST
    || verification.action !== 'download_login') return signInDenied();

  let account;
  try {
    account = await env.INTEREST_DB.prepare(`
      SELECT a.email, a.state, a.password_hash, a.password_salt, a.password_iterations,
             a.must_change_password, a.password_expires_at, i.release_decision
      FROM release_accounts a
      JOIN interest_subscribers i ON i.email = a.email
      WHERE a.email = ?
    `).bind(email).first();
  } catch {
    return downloadUnavailable();
  }

  const verify = dependencies.verifyPassword || verifyPassword;
  let passwordMatches = false;
  try {
    passwordMatches = await verify(password, account ? {
      hash: account.password_hash,
      salt: account.password_salt,
      iterations: account.password_iterations,
    } : undefined);
  } catch {
    return downloadUnavailable();
  }
  const now = downloadNow(dependencies);
  const temporary = account?.must_change_password === 1;
  const permanent = account?.must_change_password === 0;
  const temporaryExpiry = Date.parse(account?.password_expires_at);
  if (!passwordMatches || account?.state !== 'active'
    || account?.release_decision !== 'approved' || (!temporary && !permanent)
    || (temporary && (!Number.isFinite(temporaryExpiry) || temporaryExpiry <= now.getTime()))) {
    return signInDenied();
  }

  const expiresAt = new Date(temporary
    ? Math.min(now.getTime() + CHANGE_SESSION_TTL_SECONDS * 1000, temporaryExpiry)
    : now.getTime() + SESSION_TTL_SECONDS * 1000);
  const maxAge = Math.floor((expiresAt.getTime() - now.getTime()) / 1000);
  if (maxAge <= 0) return signInDenied();
  let session;
  try {
    session = await (dependencies.createSessionToken || createSessionToken)(
      dependencies.randomBytes,
    );
    const results = await env.INTEREST_DB.batch([
      statement(env, `
        INSERT INTO release_sessions
          (token_hash, email, password_change_only, created_at, expires_at)
        SELECT ?, ?, ?, ?, ? WHERE EXISTS (
          SELECT 1 FROM release_accounts a
          JOIN interest_subscribers i ON i.email = a.email
          WHERE a.email = ? AND a.state = 'active' AND i.release_decision = 'approved'
        )
      `, session.tokenHash, email, temporary ? 1 : 0, now.toISOString(),
      expiresAt.toISOString(), email),
      statement(env, `
        INSERT INTO release_access_events (email, action, version, created_at)
        SELECT ?, 'login_success', NULL, ? WHERE EXISTS
          (SELECT 1 FROM release_sessions WHERE token_hash = ?)
      `, email, now.toISOString(), session.tokenHash),
    ]);
    if ((results[0]?.meta?.changes ?? 0) !== 1) return downloadUnavailable();
  } catch {
    return downloadUnavailable();
  }
  return privateJson(200, { ok: true, must_change_password: temporary }, {
    'set-cookie': sessionCookie(session.token, maxAge),
  });
}

async function handleDownloadSession(request, env, dependencies) {
  if (!env.INTEREST_DB) return downloadUnavailable();
  try {
    const account = await findDownloadSession(
      env,
      await tokenHashFromRequest(request),
      downloadNow(dependencies),
    );
    if (!account) return privateJson(200, { authenticated: false }, {
      'set-cookie': clearSessionCookie(),
    });
    return privateJson(200, {
      authenticated: true,
      must_change_password: account.password_change_only === 1,
      email: account.email.trim().toLowerCase(),
    });
  } catch {
    return downloadUnavailable();
  }
}

async function handleDownloadPassword(request, env, dependencies) {
  const parsed = await readDownloadBody(request);
  if (parsed.response) return parsed.response;
  const password = typeof parsed.body.password === 'string' ? parsed.body.password : '';
  if (password.length < 14 || password.length > 128) {
    return privateJson(400, { ok: false, error: 'Request is invalid.' });
  }
  if (!env.INTEREST_DB) return downloadUnavailable();
  const now = downloadNow(dependencies);
  let account;
  try {
    account = await findDownloadSession(env, await tokenHashFromRequest(request), now);
  } catch {
    return downloadUnavailable();
  }
  if (!account || account.password_change_only !== 1) {
    return privateJson(401, { ok: false, error: 'Unable to change password.' });
  }

  const randomBytes = dependencies.randomBytes
    || ((length) => globalThis.crypto.getRandomValues(new Uint8Array(length)));
  let hashed;
  let session;
  try {
    hashed = await (dependencies.hashPassword || hashPassword)(password, {
      salt: randomBytes(16),
      iterations: PASSWORD_ITERATIONS,
    });
    session = await (dependencies.createSessionToken || createSessionToken)(randomBytes);
    const expiresAt = new Date(now.getTime() + SESSION_TTL_SECONDS * 1000).toISOString();
    const results = await env.INTEREST_DB.batch([
      statement(env, `
        UPDATE release_accounts SET password_hash = ?, password_salt = ?,
          password_iterations = ?, must_change_password = 0, password_expires_at = NULL,
          password_changed_at = ?
        WHERE email = ? AND state = 'active'
      `, hashed.hash, hashed.salt, PASSWORD_ITERATIONS, now.toISOString(), account.email),
      statement(env, 'DELETE FROM release_sessions WHERE email = ?', account.email),
      statement(env, `
        INSERT INTO release_sessions
          (token_hash, email, password_change_only, created_at, expires_at)
        SELECT ?, ?, 0, ?, ? WHERE EXISTS
          (SELECT 1 FROM release_accounts WHERE email = ? AND state = 'active')
      `, session.tokenHash, account.email, now.toISOString(), expiresAt, account.email),
      statement(env, `
        INSERT INTO release_access_events (email, action, version, created_at)
        SELECT ?, 'password_change', NULL, ? WHERE EXISTS
          (SELECT 1 FROM release_accounts WHERE email = ? AND state = 'active')
      `, account.email, now.toISOString(), account.email),
    ]);
    if ((results[0]?.meta?.changes ?? 0) !== 1
      || (results[2]?.meta?.changes ?? 0) !== 1) return downloadUnavailable();
  } catch {
    return downloadUnavailable();
  }
  return privateJson(200, { ok: true }, {
    'set-cookie': sessionCookie(session.token, SESSION_TTL_SECONDS),
  });
}

async function handleDownloadLogout(request, env, dependencies) {
  const parsed = await readDownloadBody(request);
  if (parsed.response) return parsed.response;
  const now = downloadNow(dependencies);
  const tokenHash = await tokenHashFromRequest(request);
  if (env.INTEREST_DB && tokenHash) {
    try {
      const account = await findDownloadSession(env, tokenHash, now);
      if (account) {
        await env.INTEREST_DB.batch([
          statement(env, 'DELETE FROM release_sessions WHERE token_hash = ?', tokenHash),
          statement(env, `
            INSERT INTO release_access_events (email, action, version, created_at)
            VALUES (?, 'logout', NULL, ?)
          `, account.email, now.toISOString()),
        ]);
      } else {
        await statement(env, 'DELETE FROM release_sessions WHERE token_hash = ?', tokenHash).run();
      }
    } catch {
      // Clearing the browser cookie is still a successful local logout.
    }
  }
  return privateJson(200, { ok: true }, { 'set-cookie': clearSessionCookie() });
}

async function handleDownloadRequest(request, env, dependencies) {
  const routes = new Map([
    ['/api/download/login', ['POST', handleDownloadLogin]],
    ['/api/download/session', ['GET', handleDownloadSession]],
    ['/api/download/password', ['POST', handleDownloadPassword]],
    ['/api/download/logout', ['POST', handleDownloadLogout]],
  ]);
  const routeValue = routes.get(new URL(request.url).pathname);
  if (!routeValue) return privateJson(404, { ok: false, error: 'Not found.' });
  if (request.method !== routeValue[0]) {
    return privateJson(405, { ok: false, error: 'Method not allowed.' }, { allow: routeValue[0] });
  }
  return routeValue[1](request, env, dependencies);
}

export async function handleInterest(request, env, fetcher = fetch) {
  if (request.method !== 'POST') {
    return json(405, { ok: false, message: 'Method not allowed.' }, { allow: 'POST' });
  }

  const requestUrl = new URL(request.url);
  if (request.headers.get('origin') !== requestUrl.origin) {
    return json(403, { ok: false, message: 'Request origin is not allowed.' });
  }

  const declaredLength = Number(request.headers.get('content-length') || 0);
  if (declaredLength > MAX_BODY_BYTES) {
    return json(413, { ok: false, message: 'Request is too large.' });
  }

  let raw;
  let body;
  try {
    raw = await request.text();
    if (new TextEncoder().encode(raw).byteLength > MAX_BODY_BYTES) {
      return json(413, { ok: false, message: 'Request is too large.' });
    }
    body = JSON.parse(raw);
  } catch {
    return json(400, { ok: false, message: 'Request is not valid JSON.' });
  }

  const email = typeof body.email === 'string' ? body.email.trim().toLowerCase() : '';
  const token = typeof body.token === 'string' ? body.token : '';
  if (!email || email.length > 254 || !EMAIL.test(email)) {
    return json(400, { ok: false, message: 'Enter a valid email address.' });
  }
  if (!token || token.length > 2048) {
    return json(400, { ok: false, message: 'Verification expired. Please try again.' });
  }
  if (!env.TURNSTILE_SECRET_KEY || !env.INTEREST_DB) return serviceUnavailable();

  let verification;
  try {
    const form = new FormData();
    form.set('secret', env.TURNSTILE_SECRET_KEY);
    form.set('response', token);
    const response = await fetcher(SITEVERIFY_URL, { method: 'POST', body: form });
    if (!response.ok) return serviceUnavailable();
    verification = await response.json();
  } catch {
    return serviceUnavailable();
  }

  if (
    verification.success !== true ||
    verification.hostname !== requestUrl.hostname ||
    verification.action !== 'interest'
  ) {
    return json(400, { ok: false, message: 'Verification expired. Please try again.' });
  }

  try {
    await env.INTEREST_DB.prepare(`
      INSERT INTO interest_subscribers (email, status, source, consent_version)
      VALUES (?, 'interested', 'homepage', ?)
      ON CONFLICT(email) DO NOTHING
    `).bind(email, CONSENT_VERSION).run();
  } catch {
    return serviceUnavailable();
  }

  return json(200, {
    ok: true,
    message: 'Thanks - your early-access request is saved.',
  });
}

export async function route(request, env, verify = verifyAccessToken, dependencies = {}) {
  const url = new URL(request.url);
  if (url.hostname.startsWith('www.')) {
    url.hostname = url.hostname.slice(4);
    return Response.redirect(url.toString(), 301);
  }
  if (url.hostname === DOWNLOAD_HOST) return handleDownloadRequest(request, env, dependencies);
  if (url.hostname === ADMIN_HOST) {
    const denied = await authorizeAdmin(request, env, verify);
    if (denied) return denied;
    if (url.pathname === ADMIN_API_PATH) {
      return handleAdminInterests(request, env);
    }
    if (url.pathname === ADMIN_RELEASES_PATH) return handleAdminReleases(request, env);
    const mutation = ADMIN_MUTATIONS.get(url.pathname);
    if (mutation) {
      if (request.method !== mutation[0]) {
        return privateJson(405, { ok: false, message: 'Method not allowed.' }, { allow: mutation[0] });
      }
      return handleAdminMutation(request, env, mutation[1], dependencies);
    }
    const assetPath = ADMIN_ASSETS.get(url.pathname);
    if (assetPath) return handleAdminAsset(request, env, assetPath);
    return privateJson(404, { ok: false, message: 'Not found.' });
  }
  if (url.pathname === '/admin' || url.pathname.startsWith('/admin/')) {
    return json(404, { ok: false, message: 'Not found.' });
  }
  if (url.pathname === API_PATH) return handleInterest(request, env);
  if (url.pathname.startsWith('/api/')) {
    return json(404, { ok: false, message: 'Not found.' });
  }
  return env.ASSETS.fetch(request);
}

export default {
  async fetch(request, env) {
    return route(request, env);
  },
};
