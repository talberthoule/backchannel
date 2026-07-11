import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

function read(url) {
  try {
    return readFileSync(url, 'utf8');
  } catch {
    return '';
  }
}

const html = read(new URL('../site/admin/index.html', import.meta.url));
const sharedCss = read(new URL('../site/style.css', import.meta.url));
const adminCss = read(new URL('../site/admin/admin.css', import.meta.url));
const css = `${sharedCss}\n${adminCss}`;
const script = read(new URL('../site/admin/admin.js', import.meta.url));
const config = JSON.parse(readFileSync(new URL('./wrangler.jsonc', import.meta.url), 'utf8'));

test('private admin page has an accessible table and explicit states', () => {
  assert.match(html, /<html lang="en">/);
  assert.match(html, /class="skip-link"/);
  assert.match(html, /<main id="main"/);
  assert.match(html, /<h1[^>]*>Early access<\/h1>/);
  assert.match(html, /id="request-count"/);
  assert.match(html, /id="last-refreshed"/);
  assert.match(html, /<button[^>]+id="refresh"[^>]+type="button"/);
  assert.match(html, /id="admin-status"[^>]+role="status"[^>]+aria-live="polite"/);
  assert.match(html, /<table[^>]+id="interest-table"/);
  assert.match(html, /<caption>/);
  assert.match(html, /<th scope="col">Email<\/th>/);
  assert.match(html, /id="interest-rows"/);
});

test('private admin page uses CSP-compatible local assets and safe DOM rendering', () => {
  assert.match(html, /href="\/style\.css"/);
  assert.match(html, /href="\/admin\.css"/);
  assert.match(html, /src="\/admin\.js"/);
  assert.doesNotMatch(html, /<style[\s>]/);
  assert.doesNotMatch(html, /<script(?![^>]+src=)/);
  assert.match(script, /fetch\('\/api\/admin\/interests'/);
  assert.match(script, /document\.createElement/);
  assert.match(script, /\.textContent\s*=/);
  assert.match(script, /emailCell\.title\s*=\s*record\.email/);
  assert.doesNotMatch(script, /innerHTML|outerHTML|insertAdjacentHTML/);
  assert.doesNotMatch(script, /localStorage|sessionStorage|document\.cookie|console\./);
});

test('private admin page styles dense responsive data without hiding overflow', () => {
  assert.match(css, /--accent:\s*#0d9488/);
  assert.match(css, /font-variant-numeric:\s*tabular-nums/);
  assert.match(css, /\.table-scroll[\s\S]*overflow-x:\s*auto/);
  assert.match(css, /thead th[\s\S]*position:\s*sticky/);
  assert.match(css, /:focus-visible/);
  assert.match(css, /min-height:\s*44px/);
  assert.match(css, /@media \(hover: hover\) and \(pointer: fine\)/);
  assert.match(css, /@media \(prefers-color-scheme: dark\)/);
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)/);
});

test('private admin assets contain no identity or Access configuration', () => {
  const assets = [html, css, script].join('\n');
  assert.doesNotMatch(
    assets,
    /ADMIN_EMAIL|ACCESS_AUD|ACCESS_TEAM_DOMAIN|cloudflareaccess\.com/i,
  );
});

test('Wrangler routes the complete private hostname', () => {
  assert.ok(config.routes.some((route) => (
    route.pattern === 'admin.backchannel.page' && route.custom_domain === true
  )));
});
