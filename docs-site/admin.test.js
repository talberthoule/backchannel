import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import {
  createDialogController,
  createListDetailController,
  element,
  jsonRequest,
  replaceByEmail,
  timeNode,
} from '../site/admin/admin-core.js';
import * as authorization from '../site/admin/authorization.js';
import * as earlyAccess from '../site/admin/early-access.js';
import * as users from '../site/admin/users.js';
import { createDocument, jsonResponse, textOf } from './admin-test-helpers.js';

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8');
const html = read('../site/admin/index.html');
const sharedCss = read('../site/style.css');
const adminCss = read('../site/admin/admin.css');
const css = `${sharedCss}\n${adminCss}`;
const bootstrapSource = read('../site/admin/admin.js');
const coreSource = read('../site/admin/admin-core.js');
const routeSources = [
  read('../site/admin/early-access.js'),
  read('../site/admin/users.js'),
  read('../site/admin/authorization.js'),
];
const config = JSON.parse(read('./wrangler.jsonc'));

function routeHarness() {
  const document = createDocument();
  const content = document.createElement('section');
  const count = document.createElement('span');
  const refreshed = document.createElement('time');
  const status = document.createElement('p');
  const shell = { content, count, refreshed, status };
  return { document, shell };
}

test('admin shell exposes protected native route navigation', () => {
  assert.match(html, /<html lang="en">/);
  assert.match(html, /class="skip-link"/);
  assert.equal((html.match(/<nav\b/g) || []).length, 1);
  assert.match(html, /href="\/early-access"/);
  assert.match(html, /href="\/users"/);
  assert.match(html, /href="\/authorization"/);
  assert.match(html, /<script[^>]+type="module"[^>]+src="\/admin\.js"/);
  assert.match(html, /id="route-title"/);
  assert.match(html, /id="route-content"/);
  assert.match(html, /id="result-count"/);
  assert.match(html, /id="last-refreshed"/);
  assert.match(html, /id="refresh"/);
  assert.match(html, /id="admin-status"[^>]+role="status"[^>]+aria-live="polite"/);
});

test('admin bootstrap is a small pathname module importer', () => {
  assert.match(bootstrapSource, /const routes = new Map\(\[\s*\['\/', '\.\/users\.js'\],\s*\['\/users', '\.\/users\.js'\],\s*\['\/early-access', '\.\/early-access\.js'\],\s*\['\/authorization', '\.\/authorization\.js'\],\s*\]\);/);
  assert.match(bootstrapSource, /location\.pathname/);
  assert.match(bootstrapSource, /import\(modulePath\)/);
  assert.doesNotMatch(bootstrapSource, /fetch\(['"]\/api\/admin/);
});

test('admin core uses safe ephemeral browser APIs', () => {
  const assets = [coreSource, html, ...routeSources].join('\n');
  assert.doesNotMatch(assets, /innerHTML|outerHTML|insertAdjacentHTML/);
  assert.doesNotMatch(assets, /localStorage|sessionStorage|document\.cookie|console\./);
  assert.match(coreSource, /navigator\.clipboard\.writeText/);
  assert.match(coreSource, /addEventListener\('pagehide'/);
  assert.doesNotMatch(coreSource, /Approve|Reject|Reset password|Sign out|Revoke|Save grants/);
});

test('admin core builds safe nodes and bounded JSON requests', async () => {
  const document = createDocument();
  const node = element('p', 'state', '<strong>plain</strong>', document);
  assert.equal(node.name, 'p');
  assert.equal(node.className, 'state');
  assert.equal(node.textContent, '<strong>plain</strong>');

  const calls = [];
  const value = await jsonRequest('/api/admin/users', undefined, undefined, async (path, init) => {
    calls.push({ path, init });
    return jsonResponse({ items: [] });
  });
  assert.deepEqual(value, { items: [] });
  assert.deepEqual(calls, [{
    path: '/api/admin/users',
    init: { method: 'GET', headers: { accept: 'application/json' }, cache: 'no-store' },
  }]);
  assert.deepEqual(
    replaceByEmail([{ email: 'a@example.com' }], { email: 'a@example.com', state: 'active' }),
    [{ email: 'a@example.com', state: 'active' }],
  );
  assert.deepEqual(replaceByEmail([], { email: 'a@example.com' }), []);
  assert.equal(timeNode(null, 'Not yet', document).textContent, 'Not yet');
});

test('shared dialog and list-detail controllers clear plaintext and restore focus', async () => {
  const ids = [
    'confirm-dialog', 'confirm-dialog-title', 'confirm-dialog-description',
    'confirm-cancel', 'confirm-submit', 'credential-dialog', 'credential-text',
    'credential-status', 'credential-copy', 'credential-save', 'credential-close',
  ];
  const document = createDocument(ids);
  const pageListeners = new Map();
  const trigger = document.createElement('button');
  const clipboard = [];
  const dialogs = createDialogController({
    document,
    navigator: { clipboard: { async writeText(value) { clipboard.push(value); } } },
    addEventListener(type, listener) { pageListeners.set(type, listener); },
    URL: { createObjectURL: () => 'blob:value', revokeObjectURL() {} },
    Blob,
  });
  dialogs.showCredential({ text: 'temporary secret', email: 'person@example.com', returnFocus: trigger });
  assert.equal(document.getElementById('credential-text').value, 'temporary secret');
  await document.getElementById('credential-copy').click();
  assert.deepEqual(clipboard, ['temporary secret']);
  await document.getElementById('credential-dialog').close();
  assert.equal(document.getElementById('credential-text').value, '');
  assert.equal(document.activeElement, trigger);
  dialogs.showCredential({ text: 'another secret', email: 'person@example.com' });
  pageListeners.get('pagehide')();
  assert.equal(document.getElementById('credential-text').value, '');

  const root = document.createElement('section');
  const list = document.createElement('div');
  const detail = document.createElement('div');
  const heading = document.createElement('h2');
  const back = document.createElement('button');
  const row = document.createElement('button');
  const controller = createListDetailController({ root, list, detail, heading, back });
  controller.showDetail(row);
  assert.equal(root.dataset.view, 'detail');
  assert.equal(document.activeElement, heading);
  await back.click();
  assert.equal(root.dataset.view, 'list');
  assert.equal(document.activeElement, row);
});

const routeCases = [
  ['Early access', earlyAccess, '/api/admin/interests', {
    email: 'request@example.com', status: 'interested', source: 'homepage',
    consent_version: '2026-07-11', consent_at: '2026-07-11 12:00:00',
    created_at: '2026-07-11 12:00:00', release_decision: 'pending',
  }],
  ['Users', users, '/api/admin/users', {
    email: 'person@example.com', state: 'active', source: 'homepage',
    requested_at: '2026-07-11 12:00:00', approved_at: '2026-07-11 12:05:00',
    must_change_password: true, password_expires_at: '2026-07-14 12:05:00',
    password_changed_at: null, revoked_at: null, active_session_count: 1,
    latest_session_expires_at: '2026-07-11 13:00:00',
  }],
  ['Authorization', authorization, '/api/admin/authorization', {
    email: 'person@example.com', account_state: 'active', include_latest: true,
    versions: ['v0.2.1'], updated_at: '2026-07-11 12:10:00',
  }],
];

for (const [name, module, endpoint, item] of routeCases) {
  test(`${name} route loads only its read endpoint and renders a no-selection state`, async () => {
    assert.equal(module.meta.title, name);
    const calls = [];
    const { document, shell } = routeHarness();
    const mounted = module.mount({
      document,
      shell,
      dialogs: {},
      fetcher: async (path, init) => {
        calls.push({ path, init });
        return jsonResponse({ items: [item] });
      },
    });
    assert.equal(typeof mounted.refresh, 'function');
    await mounted.refresh();
    assert.deepEqual(calls.map(({ path }) => path), [endpoint]);
    assert.match(textOf(shell.content), new RegExp(item.email.replace('.', '\\.')));
    assert.match(textOf(shell.content), /Select/i);
    assert.equal(shell.count.textContent, '1');
    assert.equal(shell.content.getAttribute('aria-busy'), null);
  });

  test(`${name} route renders empty and error states`, async () => {
    const { document, shell } = routeHarness();
    let fail = false;
    const mounted = module.mount({
      document,
      shell,
      dialogs: {},
      fetcher: async () => fail
        ? jsonResponse({ message: 'private detail' }, { ok: false })
        : jsonResponse({ items: [] }),
    });
    await mounted.refresh();
    assert.match(textOf(shell.content), /No /i);
    fail = true;
    await mounted.refresh();
    assert.match(textOf(shell.content), /could not be loaded/i);
    assert.match(textOf(shell.content), /Retry/);
  });
}

test('read-only routes select a row, render detail, and restore focus on Back', async () => {
  for (const [, module, endpoint, item] of routeCases) {
    const { document, shell } = routeHarness();
    const mounted = module.mount({
      document,
      shell,
      dialogs: {},
      fetcher: async (path) => {
        assert.equal(path, endpoint);
        return jsonResponse({ items: [item] });
      },
    });
    await mounted.refresh();
    const row = shell.content.querySelectorAll('.row-select')[0];
    await row.click();
    assert.equal(shell.content.querySelectorAll('.list-detail')[0].dataset.view, 'detail');
    assert.equal(document.activeElement.name, 'h2');
    assert.equal(document.activeElement.textContent, item.email);
    assert.match(textOf(shell.content), /Identity|Consent|Latest releases/);
    const back = shell.content.querySelectorAll('.back-button')[0];
    await back.click();
    assert.equal(shell.content.querySelectorAll('.list-detail')[0].dataset.view, 'list');
    assert.equal(document.activeElement, row);
  }
});

test('read-only routes expose loading while their owned GET is pending', async () => {
  for (const [, module, endpoint] of routeCases) {
    const { document, shell } = routeHarness();
    let resolveFetch;
    const calls = [];
    const mounted = module.mount({
      document,
      shell,
      dialogs: {},
      fetcher(path, init) {
        calls.push({ path, init });
        return new Promise((resolve) => { resolveFetch = resolve; });
      },
    });
    const pending = mounted.refresh();
    assert.equal(shell.content.getAttribute('aria-busy'), 'true');
    assert.match(textOf(shell.content), /Loading/);
    assert.deepEqual(calls.map(({ path }) => path), [endpoint]);
    resolveFetch(jsonResponse({ items: [] }));
    await pending;
    assert.equal(shell.content.getAttribute('aria-busy'), null);
  }
});

test('read-only route Retry performs a second owned GET', async () => {
  for (const [, module, endpoint] of routeCases) {
    const { document, shell } = routeHarness();
    const calls = [];
    const mounted = module.mount({
      document,
      shell,
      dialogs: {},
      fetcher: async (path, init) => {
        calls.push({ path, init });
        return calls.length === 1
          ? jsonResponse({}, { ok: false })
          : jsonResponse({ items: [] });
      },
    });
    await mounted.refresh();
    const retry = shell.content.querySelectorAll('button')[0];
    assert.equal(retry.textContent, 'Retry');
    await retry.click();
    assert.deepEqual(calls.map(({ path }) => path), [endpoint, endpoint]);
    assert.ok(calls.every(({ init }) => init.method === 'GET'));
    assert.match(textOf(shell.content), /No /i);
  }
});

test('Users and Authorization expose labelled case-insensitive email search', async () => {
  for (const [module, endpoint] of [
    [users, '/api/admin/users'],
    [authorization, '/api/admin/authorization'],
  ]) {
    const { document, shell } = routeHarness();
    const mounted = module.mount({
      document,
      shell,
      dialogs: {},
      fetcher: async (path) => {
        assert.equal(path, endpoint);
        return jsonResponse({ items: [
          { email: 'Alpha@Example.com', state: 'active', account_state: 'active', versions: [] },
          { email: 'beta@example.com', state: 'active', account_state: 'active', versions: [] },
        ] });
      },
    });
    await mounted.refresh();
    const search = shell.content.querySelectorAll('input')[0];
    assert.equal(search.getAttribute('aria-label'), 'Search by email');
    search.value = 'ALPHA@EXAMPLE';
    await search.dispatchEvent({ type: 'input' });
    assert.match(textOf(shell.content), /Alpha@Example\.com/);
    assert.doesNotMatch(textOf(shell.content), /beta@example\.com/);
  }
});

test('admin shell styles dense responsive list-detail without page overflow', () => {
  assert.match(css, /--accent:\s*#0d9488/);
  assert.match(adminCss, /grid-template-columns:\s*208px minmax\(0, 1fr\)/);
  assert.match(adminCss, /font-variant-numeric:\s*tabular-nums/);
  assert.match(adminCss, /min-height:\s*44px/);
  assert.match(adminCss, /@media \(max-width: 760px\)/);
  assert.match(adminCss, /@media \(max-width: 640px\)/);
  assert.match(adminCss, /@media \(prefers-color-scheme: dark\)/);
  assert.match(adminCss, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(adminCss, /@media \(forced-colors: active\)/);
  assert.match(adminCss, /dialog::backdrop/);
  assert.match(adminCss, /:focus-visible/);
  assert.doesNotMatch(adminCss, /animation\s*:/);
});

test('admin shell uses fluid intermediate tracks beside the fixed rail', () => {
  const listDetailRule = adminCss.match(/\.list-detail\s*\{([^}]*)\}/)?.[1] || '';
  const headerRule = adminCss.match(/\.route-header\s*\{([^}]*)\}/)?.[1] || '';
  assert.match(listDetailRule, /grid-template-columns:\s*minmax\(0, 3fr\) minmax\(0, 2fr\)/);
  assert.doesNotMatch(listDetailRule, /minmax\((?:360|280)px/);
  assert.match(headerRule, /flex-wrap:\s*wrap/);
  assert.match(css, /\.skip-link\s*\{[^}]*min-height:\s*44px/s);
});

test('private admin assets contain no identity or Access configuration', () => {
  const assets = [html, css, bootstrapSource, coreSource, ...routeSources].join('\n');
  assert.doesNotMatch(assets, /ADMIN_EMAIL|ACCESS_AUD|ACCESS_TEAM_DOMAIN|cloudflareaccess\.com/i);
});

test('Wrangler routes the complete private hostname', () => {
  assert.ok(config.routes.some((route) => (
    route.pattern === 'admin.backchannel.page' && route.custom_domain === true
  )));
});
