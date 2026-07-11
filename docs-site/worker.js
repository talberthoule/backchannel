import { createRemoteJWKSet, jwtVerify } from 'jose';

const API_PATH = '/api/interest';
const ADMIN_HOST = 'admin.backchannel.page';
const ADMIN_API_PATH = '/api/admin/interests';
const ADMIN_ASSETS = new Map([
  ['/', '/admin/index.html'],
  ['/index.html', '/admin/index.html'],
  ['/admin.css', '/admin/admin.css'],
  ['/admin.js', '/admin/admin.js'],
]);
const CONSENT_VERSION = '2026-07-11';
const MAX_BODY_BYTES = 4096;
const SITEVERIFY_URL = 'https://challenges.cloudflare.com/turnstile/v0/siteverify';
const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
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
      SELECT email, status, source, consent_version, consent_at, created_at,
             invited_at, last_contacted_at
      FROM interest_subscribers
      ORDER BY created_at DESC
    `).all();
    return privateJson(200, { items: result.results || [] });
  } catch {
    return privateJson(503, {
      ok: false,
      message: 'Access requests could not be loaded.',
    });
  }
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

export async function route(request, env, verify = verifyAccessToken) {
  const url = new URL(request.url);
  if (url.hostname.startsWith('www.')) {
    url.hostname = url.hostname.slice(4);
    return Response.redirect(url.toString(), 301);
  }
  if (url.hostname === ADMIN_HOST) {
    const denied = await authorizeAdmin(request, env, verify);
    if (denied) return denied;
    if (url.pathname === ADMIN_API_PATH) {
      return handleAdminInterests(request, env);
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
