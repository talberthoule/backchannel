const API_PATH = '/api/interest';
const CONSENT_VERSION = '2026-07-11';
const MAX_BODY_BYTES = 4096;
const SITEVERIFY_URL = 'https://challenges.cloudflare.com/turnstile/v0/siteverify';
const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

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

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.hostname.startsWith('www.')) {
      url.hostname = url.hostname.slice(4);
      return Response.redirect(url.toString(), 301);
    }
    if (url.pathname === API_PATH) return handleInterest(request, env);
    if (url.pathname.startsWith('/api/')) {
      return json(404, { ok: false, message: 'Not found.' });
    }
    return env.ASSETS.fetch(request);
  },
};
