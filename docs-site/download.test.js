import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import test from 'node:test';

const read = (path) => existsSync(new URL(path, import.meta.url))
  ? readFileSync(new URL(path, import.meta.url), 'utf8')
  : '';
const html = read('../site/downloads/index.html');
const script = read('../site/downloads/downloads.js');
const css = read('../site/downloads/downloads.css');
const packageJson = JSON.parse(read('./package.json'));

test('recipient page uses local assets and the exact Turnstile login action', () => {
  assert.match(html, /href="\/downloads\.css"/);
  assert.match(html, /src="\/downloads\.js"\s+defer/);
  assert.match(html, /src="https:\/\/challenges\.cloudflare\.com\/turnstile\/v0\/api\.js"\s+defer/);
  assert.match(html, /class="cf-turnstile"[^>]*data-sitekey="[^"]+"[^>]*data-action="download_login"/s);
  assert.doesNotMatch(html, /<(?:script|style)(?![^>]*\bsrc=|[^>]*\bhref=)[^>]*>\s*\S/i);
});

test('recipient page exposes labelled controls and three exclusive panels', () => {
  for (const id of ['email', 'password', 'new-password']) {
    assert.match(html, new RegExp(`<label[^>]+for="${id}"`));
    assert.match(html, new RegExp(`<input[^>]+id="${id}"`));
  }
  assert.match(html, /id="new-password"[^>]*minlength="14"[^>]*maxlength="128"/);
  for (const panel of ['login-panel', 'change-panel', 'releases-panel']) {
    assert.match(html, new RegExp(`<section[^>]+id="${panel}"[^>]+hidden`));
  }
  assert.match(html, /releases will load/i);
  assert.ok((html.match(/role="alert"/g) || []).length >= 2);
  assert.match(html, /type="submit"[^>]*>\s*Sign in/i);
  assert.match(html, /type="submit"[^>]*>\s*Change password/i);
  assert.ok((html.match(/>\s*Log out\s*</gi) || []).length >= 2);
});

test('recipient script implements session, login, password, and logout requests safely', () => {
  for (const path of ['session', 'login', 'password', 'logout']) {
    assert.match(script, new RegExp(`fetch\\(['"]\\/api\\/download\\/${path}['"]`));
  }
  assert.match(script, /credentials:\s*['"]same-origin['"]/);
  assert.match(script, /JSON\.stringify\(\{\s*email:\s*email\.value,\s*password:\s*password\.value,\s*turnstile_token:/s);
  assert.match(script, /JSON\.stringify\(\{\s*password\s*\}\)/);
  assert.match(script, /JSON\.stringify\(\{\s*\}\)/);
  assert.match(script, /turnstile\??\.getResponse/);
  assert.match(script, /turnstile\??\.reset/);
  assert.match(script, /\.disabled\s*=\s*true/);
  assert.match(script, /\.disabled\s*=\s*false/);
  assert.match(script, /\.focus\(\)/);
  assert.match(script, /password\.value\s*=\s*['"]/);
  assert.doesNotMatch(script, /innerHTML|outerHTML|insertAdjacentHTML/);
  assert.doesNotMatch(script, /localStorage|sessionStorage|document\.cookie|console\./);
});

test('recipient styles are accessible and resilient at 320px', () => {
  assert.match(css, /:focus-visible/);
  assert.match(css, /@media\s*\(prefers-reduced-motion:\s*reduce\)/);
  assert.match(css, /max-width:\s*320px|@media\s*\(max-width:\s*\d+px\)/);
  assert.match(css, /overflow-x:\s*hidden/);
  assert.match(css, /min-height:\s*44px/);
  assert.match(css, /max-width:\s*100%/);
});

test('download contract is runnable and static assets contain no secrets', () => {
  assert.equal(packageJson.scripts?.['test:download'], 'node --test download.test.js');
  assert.doesNotMatch(`${html}\n${script}\n${css}`, /ADMIN_EMAIL|ACCESS_AUD|TURNSTILE_SECRET|owner@example\.com|cloudflareaccess\.com/i);
});
