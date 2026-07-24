// Edge response policy for the deployed Worker: canonical-scheme
// enforcement, robots isolation for the auth-gated hostnames, baseline
// security headers, and browser caching for assets that are immutable
// (hashed) or slow-moving (fonts, screenshots).

export const HSTS_VALUE = 'max-age=31536000; includeSubDomains';

// 301 to the canonical https apex when the request arrived on plain HTTP or
// the www host; null when the URL is already canonical.
export function canonicalRedirect(url, { wwwHost, publicHost }) {
  if (url.protocol !== 'http:' && url.hostname !== wwwHost) return null;
  url.protocol = 'https:';
  if (url.hostname === wwwHost) url.hostname = publicHost;
  return new Response(null, {
    status: 301,
    headers: { Location: url.toString(), 'Strict-Transport-Security': HSTS_VALUE },
  });
}

function cacheControlFor(pathname) {
  if (pathname.startsWith('/docs/_astro/')) return 'public, max-age=31536000, immutable';
  if (pathname.startsWith('/assets/fonts/')) return 'public, max-age=2592000';
  if (pathname.startsWith('/assets/')) return 'public, max-age=86400';
  return null;
}

export function applyEdgePolicy(url, response, { adminHost, downloadHost }) {
  // Worker assets emit temporary (307) trailing-slash redirects; permanence
  // consolidates canonicalization signals for crawlers.
  const slashRedirect = response.status === 307 || response.status === 308;
  const headers = new Headers(response.headers);
  if (!headers.has('strict-transport-security')) {
    headers.set('Strict-Transport-Security', HSTS_VALUE);
  }
  if (url.hostname === downloadHost || url.hostname === adminHost) {
    headers.set('X-Robots-Tag', 'noindex, nofollow');
  } else {
    if (!headers.has('x-content-type-options')) headers.set('X-Content-Type-Options', 'nosniff');
    if (!headers.has('referrer-policy')) headers.set('Referrer-Policy', 'strict-origin-when-cross-origin');
    const cache = response.ok ? cacheControlFor(url.pathname) : null;
    if (cache) headers.set('Cache-Control', cache);
  }
  return new Response(slashRedirect ? null : response.body, {
    status: slashRedirect ? 301 : response.status,
    headers,
  });
}
