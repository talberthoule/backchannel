import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { runInNewContext } from 'node:vm';

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

class TestElement {
  constructor(name = 'div') {
    this.name = name;
    this.children = [];
    this.dataset = {};
    this.textContent = '';
    this.value = '';
    this.checked = false;
    this.disabled = false;
    this.open = false;
  }

  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
  addEventListener() {}
  setAttribute(name, value) { this[name] = value; }
  removeAttribute(name) { delete this[name]; }
  querySelectorAll() { return []; }
  showModal() { this.open = true; }
  close() { this.open = false; }
  focus() {}
  click() {}
  remove() {}
  get childElementCount() { return this.children.filter((child) => child instanceof TestElement).length; }
}

function textOf(node) {
  if (typeof node === 'string') return node;
  return (node?.textContent || '') + (node?.children || []).map(textOf).join('');
}

async function runAdmin(fetch) {
  const elements = new Map();
  const document = {
    body: new TestElement('body'),
    createElement: (name) => new TestElement(name),
    createTextNode: (value) => String(value),
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, new TestElement());
      return elements.get(id);
    },
  };
  const executable = script.replace(
    /refresh\.addEventListener\('click', load\);\s*load\(\);\s*$/,
    'globalThis.__admin = { load, actionCell };',
  );
  assert.notEqual(executable, script);
  const context = {
    Blob, Date, Intl, Set, URL, document, fetch,
    navigator: { clipboard: { async writeText() {} } },
    window: { confirm: () => true },
    addEventListener() {},
  };
  runInNewContext(executable, context);
  await context.__admin.load();
  return { ...context.__admin, elements };
}

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
  for (const heading of ['Decision', 'Account', 'Release access', 'Actions']) {
    assert.match(html, new RegExp(`<th scope="col">${heading}<\\/th>`));
  }
});

test('admin actions use labelled native dialogs with cancellable focus-safe controls', () => {
  assert.match(html, /<dialog[^>]+id="access-dialog"[^>]+aria-labelledby="access-dialog-title"/);
  assert.match(html, /<dialog[^>]+id="credential-dialog"[^>]+aria-labelledby="credential-dialog-title"/);
  assert.match(html, /<label[^>]*>[\s\S]*Latest[\s\S]*<input[^>]+id="include-latest"[^>]+type="checkbox"[^>]+checked/);
  assert.match(html, /<textarea[^>]+id="credential-text"[^>]+readonly/);
  assert.match(html, /<button[^>]+id="access-cancel"[^>]+type="button"[^>]*>Cancel<\/button>/);
  assert.match(script, /\.showModal\(\)/);
  assert.match(script, /\.focus\(\)/);
  assert.match(script, /\.returnValue|addEventListener\('cancel'/);
});

test('credential copy and save retain plaintext in one variable and clear it promptly', () => {
  assert.equal((script.match(/let activeCredentialText\s*=\s*''/g) || []).length, 1);
  assert.match(script, /navigator\.clipboard\.writeText\(activeCredentialText\)/);
  assert.match(script, /new Blob\(\[activeCredentialText\],\s*\{\s*type:\s*'text\/plain;charset=utf-8'\s*\}\)/);
  assert.match(script, /URL\.createObjectURL/);
  assert.match(script, /URL\.revokeObjectURL/);
  assert.match(script, /backchannel-access-/);
  assert.match(script, /replace\(\/\[\^a-z0-9\]\+\/gi,\s*'-'\)/);
  assert.match(script, /credentialDialog\.addEventListener\('close',\s*clearCredential\)/);
  assert.match(script, /addEventListener\('pagehide',\s*clearCredential\)/);
  assert.match(script, /credentialText\.value\s*=\s*''/);
  assert.match(script, /activeCredentialText\s*=\s*''/);
  assert.match(html, /id="credential-status"[^>]+role="status"[^>]+aria-live="polite"/);
});

test('admin loads releases and interests and renders row actions with safe DOM APIs', () => {
  assert.match(script, /fetch\('\/api\/admin\/releases'/);
  assert.match(script, /fetch\('\/api\/admin\/interests'/);
  for (const action of ['Approve', 'Reject', 'Edit grants', 'Reset password', 'Revoke']) {
    assert.match(script, new RegExp(action));
  }
  assert.doesNotMatch(script, /innerHTML|outerHTML|insertAdjacentHTML/);
});

test('admin renders interests independently when the release catalog is unavailable', async () => {
  const calls = [];
  const admin = await runAdmin(async (path) => {
    calls.push(path);
    if (path === '/api/admin/releases') {
      return { ok: false, async json() { return { ok: false }; } };
    }
    return {
      ok: true,
      async json() {
        return { items: [{
          email: 'person@example.com', status: 'interested', source: 'homepage',
          consent_version: '2026-07-11', consent_at: '2026-07-11 12:00:00',
          created_at: '2026-07-11 12:00:00', invited_at: null, last_contacted_at: null,
          release_decision: 'pending', account_state: null, include_latest: null, versions: [],
        }] };
      },
    };
  });

  assert.deepEqual(calls.sort(), ['/api/admin/interests', '/api/admin/releases']);
  const rowsText = textOf(admin.elements.get('interest-rows'));
  assert.match(rowsText, /person@example\.com/);
  assert.match(rowsText, /Reject/);
  assert.doesNotMatch(rowsText, /Approve/);
  assert.match(admin.elements.get('admin-status').textContent, /Release catalog is not ready\./);

  const activeActions = textOf(admin.actionCell({
    email: 'active@example.com', account_state: 'active', release_decision: 'approved',
  }));
  assert.match(activeActions, /Reset password/);
  assert.match(activeActions, /Revoke/);
  assert.doesNotMatch(activeActions, /Edit grants/);
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
  assert.match(css, /dialog::backdrop/);
  assert.match(css, /\.row-actions[\s\S]*flex-wrap:\s*wrap/);
  assert.match(css, /textarea[\s\S]*min-height:/);
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
