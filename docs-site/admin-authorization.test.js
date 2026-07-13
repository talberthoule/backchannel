import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import * as authorization from '../site/admin/authorization.js';
import { createDocument, jsonResponse, textOf } from './admin-test-helpers.js';

const routeSource = readFileSync(new URL('../site/admin/authorization.js', import.meta.url), 'utf8');
const policy = {
  email: 'Person@Example.com',
  account_state: 'active',
  include_latest: true,
  versions: ['v0.2.1'],
  updated_at: '2026-07-12T12:00:00.000Z',
};
const catalog = {
  items: [
    { version: 'v0.3.0', published_at: '2026-07-13T12:00:00.000Z' },
    { version: 'v0.2.1', published_at: '2026-07-12T12:00:00.000Z' },
  ],
  latest_version: 'v0.3.0',
  available: true,
};

function deferred() {
  let resolve;
  const promise = new Promise((resolveValue) => { resolve = resolveValue; });
  return { promise, resolve };
}

function nextTurn() {
  return new Promise((resolve) => setImmediate(resolve));
}

function buttonNamed(root, label) {
  return root.querySelectorAll('button').find((button) => button.textContent === label);
}

function latestInput(root) {
  return root.querySelectorAll('input').find((input) => input.getAttribute('name') === 'include_latest');
}

function versionInput(root, version) {
  return root.querySelectorAll('input').find((input) => input.value === version);
}

function harness(respond) {
  const document = createDocument();
  const shell = {
    content: document.createElement('section'),
    count: document.createElement('span'),
    refreshed: document.createElement('time'),
    status: document.createElement('p'),
  };
  document.body.append(shell.content, shell.count, shell.refreshed, shell.status);
  const calls = [];
  const mounted = authorization.mount({
    document,
    shell,
    dialogs: {},
    fetcher: async (path, init) => {
      const call = {
        path,
        method: init.method,
        body: init.body === undefined ? undefined : JSON.parse(init.body),
      };
      calls.push(call);
      return respond(call);
    },
  });
  return { calls, document, mounted, shell };
}

function standardResponse(call, nextPolicy = policy) {
  if (call.path === '/api/admin/authorization') return jsonResponse({ items: [nextPolicy] });
  if (call.path === '/api/admin/releases') return jsonResponse(catalog);
  return jsonResponse({ ok: true, item: nextPolicy });
}

async function openPolicy(route) {
  await route.mounted.refresh();
  await route.shell.content.querySelectorAll('.row-select')[0].click();
}

test('Authorization launches its policy and trusted catalog reads independently in parallel', async () => {
  const reads = {
    '/api/admin/authorization': deferred(),
    '/api/admin/releases': deferred(),
  };
  const route = harness(({ path }) => reads[path].promise);
  const refreshing = route.mounted.refresh();

  assert.deepEqual(route.calls, [
    { path: '/api/admin/authorization', method: 'GET', body: undefined },
    { path: '/api/admin/releases', method: 'GET', body: undefined },
  ]);
  assert.equal(route.shell.content.getAttribute('aria-busy'), 'true');
  reads['/api/admin/releases'].resolve(jsonResponse(catalog));
  reads['/api/admin/authorization'].resolve(jsonResponse({ items: [policy] }));
  await refreshing;

  assert.equal(route.shell.content.getAttribute('aria-busy'), null);
  assert.equal(route.shell.count.textContent, '1');
});

test('policy renders while the independent catalog read remains pending', async () => {
  const authorizationRead = deferred();
  const catalogRead = deferred();
  const route = harness(({ path }) => path === '/api/admin/authorization'
    ? authorizationRead.promise
    : catalogRead.promise);
  const refreshing = route.mounted.refresh();

  authorizationRead.resolve(jsonResponse({ items: [policy] }));
  await nextTurn();

  assert.equal(route.shell.count.textContent, '1');
  assert.match(textOf(route.shell.content), /Person@Example\.com/);
  assert.match(route.shell.status.textContent, /catalog is loading/i);
  const row = route.shell.content.querySelectorAll('.row-select')[0];
  await row.click();
  assert.match(textOf(route.shell.content), /catalog is loading/i);
  assert.equal(buttonNamed(route.shell.content, 'Save grants').disabled, true);
  assert.equal(route.shell.content.querySelectorAll('.version-input').length, 0);
  assert.equal(route.calls.filter(({ path }) => path === '/api/admin/authorization').length, 1);

  catalogRead.resolve(jsonResponse(catalog));
  await refreshing;

  assert.equal(route.shell.content.querySelectorAll('.list-detail')[0].dataset.view, 'detail');
  assert.equal(buttonNamed(route.shell.content, 'Save grants').disabled, false);
  assert.deepEqual(
    route.shell.content.querySelectorAll('.version-input').map(({ value }) => value),
    ['v0.3.0', 'v0.2.1'],
  );
  assert.equal(route.calls.filter(({ path }) => path === '/api/admin/authorization').length, 1);
});

test('Authorization searches normalized email and restores row focus from complete policy detail', async () => {
  const other = { ...policy, email: 'other@example.com', versions: [] };
  const route = harness(({ path }) => path === '/api/admin/authorization'
    ? jsonResponse({ items: [policy, other] })
    : jsonResponse(catalog));
  await route.mounted.refresh();
  const search = route.shell.content.querySelectorAll('input')[0];
  search.value = '  PERSON@EXAMPLE  ';
  await search.dispatchEvent({ type: 'input' });
  assert.match(textOf(route.shell.content), /Person@Example\.com/);
  assert.doesNotMatch(textOf(route.shell.content), /other@example\.com/);

  const row = route.shell.content.querySelectorAll('.row-select')[0];
  await row.click();
  const pane = route.shell.content.querySelectorAll('.detail-pane')[0];
  assert.equal(route.shell.content.querySelectorAll('.list-detail')[0].dataset.view, 'detail');
  assert.equal(route.document.activeElement.textContent, policy.email);
  for (const label of [
    'Account state', 'Latest releases', 'Historical versions', 'Policy updated', 'Release grants',
  ]) assert.match(textOf(pane), new RegExp(label));
  assert.match(textOf(pane), /Enabled/);
  assert.match(textOf(pane), /v0\.2\.1/);

  await buttonNamed(route.shell.content, 'Back to authorization').click();
  assert.equal(route.shell.content.querySelectorAll('.list-detail')[0].dataset.view, 'list');
  assert.equal(route.document.activeElement, row);
});

test('grant editor uses only trusted catalog checkboxes and labels the current Latest release', async () => {
  const route = harness((call) => standardResponse(call));
  await openPolicy(route);

  assert.equal(latestInput(route.shell.content).checked, true);
  assert.deepEqual(
    route.shell.content.querySelectorAll('.version-input').map(({ value }) => value),
    ['v0.3.0', 'v0.2.1'],
  );
  assert.equal(versionInput(route.shell.content, 'v0.2.1').checked, true);
  assert.match(textOf(route.shell.content), /v0\.3\.0.*Latest/);
  assert.doesNotMatch(routeSource, /type\s*=\s*['"]text['"]|version-entry|manual version/i);
});

test('selection validation retains the form and requires Latest or one trusted version', async () => {
  const route = harness((call) => standardResponse(call));
  await openPolicy(route);
  const latest = latestInput(route.shell.content);
  const pinned = versionInput(route.shell.content, 'v0.2.1');
  latest.checked = false;
  pinned.checked = false;

  await buttonNamed(route.shell.content, 'Save grants').click();

  assert.equal(route.calls.length, 2);
  assert.equal(latest.checked, false);
  assert.equal(pinned.checked, false);
  assert.equal(latest.getAttribute('aria-invalid'), 'true');
  assert.match(textOf(route.shell.content), /Select Latest or at least one version/);
  assert.equal(route.document.activeElement, latest);
});

test('Save sends the exact full replacement and patches the returned policy without a refetch', async () => {
  const updated = {
    ...policy,
    include_latest: false,
    updated_at: '2026-07-13T13:00:00.000Z',
  };
  const route = harness((call) => call.method === 'PUT'
    ? jsonResponse({ ok: true, item: updated })
    : standardResponse(call));
  await openPolicy(route);
  latestInput(route.shell.content).checked = false;

  await buttonNamed(route.shell.content, 'Save grants').click();

  assert.deepEqual(route.calls[2], {
    path: '/api/admin/authorization/grants',
    method: 'PUT',
    body: {
      email: policy.email,
      include_latest: false,
      versions: ['v0.2.1'],
    },
  });
  assert.equal(route.calls.length, 3);
  assert.equal(route.shell.content.querySelectorAll('.list-detail')[0].dataset.view, 'detail');
  assert.match(textOf(route.shell.content), /Latest releasesDisabled/);
  assert.equal(latestInput(route.shell.content).checked, false);
  assert.equal(route.shell.status.textContent, 'Release authorization updated.');
  assert.equal(route.document.activeElement, buttonNamed(route.shell.content, 'Save grants'));
});

test('Save accepts the same unique version set in server order', async () => {
  const updated = {
    ...policy,
    include_latest: false,
    versions: ['v0.2.1', 'v0.3.0'],
    updated_at: '2026-07-13T13:00:00.000Z',
  };
  const route = harness((call) => call.method === 'PUT'
    ? jsonResponse({ ok: true, item: updated })
    : standardResponse(call));
  await openPolicy(route);
  latestInput(route.shell.content).checked = false;
  versionInput(route.shell.content, 'v0.3.0').checked = true;

  await buttonNamed(route.shell.content, 'Save grants').click();

  assert.deepEqual(route.calls[2].body.versions, ['v0.3.0', 'v0.2.1']);
  assert.equal(route.shell.status.textContent, 'Release authorization updated.');
  assert.match(textOf(route.shell.content), /Historical versionsv0\.2\.1, v0\.3\.0/);
  assert.equal(versionInput(route.shell.content, 'v0.3.0').checked, true);
  assert.equal(versionInput(route.shell.content, 'v0.2.1').checked, true);
});

test('malformed grant successes cannot change unowned fields or patch local policy', async () => {
  const validUpdated = {
    ...policy,
    include_latest: false,
    updated_at: '2026-07-13T13:00:00.000Z',
  };
  const cases = [
    { ok: false, item: validUpdated },
    { ok: true, item: { ...validUpdated, email: 'other@example.com' } },
    { ok: true, item: { ...validUpdated, account_state: 'revoked' } },
    { ok: true, item: { ...validUpdated, include_latest: true } },
    { ok: true, item: { ...validUpdated, versions: [] } },
    { ok: true, item: { ...validUpdated, updated_at: 'not-a-date' } },
    { ok: true, item: { ...validUpdated, source: 'homepage' } },
    { ok: true, item: validUpdated, credential: 'not-owned' },
  ];

  for (const value of cases) {
    const route = harness((call) => call.method === 'PUT'
      ? jsonResponse(value)
      : standardResponse(call));
    await openPolicy(route);
    latestInput(route.shell.content).checked = false;
    await buttonNamed(route.shell.content, 'Save grants').click();

    assert.equal(route.calls.length, 3);
    assert.match(route.shell.status.textContent, /failed/i);
    assert.match(textOf(route.shell.content), /Latest releasesEnabled/);
    assert.equal(buttonNamed(route.shell.content, 'Save grants').disabled, false);
  }
});

test('a grant mutation wins both completion orders against stale refresh success and failure', async () => {
  for (const staleFails of [false, true]) {
    const staleAuthorization = deferred();
    const staleCatalog = deferred();
    let refreshes = 0;
    const updated = {
      ...policy,
      include_latest: false,
      updated_at: '2026-07-13T13:00:00.000Z',
    };
    const route = harness((call) => {
      if (call.method === 'PUT') return jsonResponse({ ok: true, item: updated });
      if (call.path === '/api/admin/authorization') return refreshes++ === 0
        ? jsonResponse({ items: [policy] })
        : staleAuthorization.promise;
      if (refreshes === 1) return jsonResponse(catalog);
      return staleCatalog.promise;
    });
    await openPolicy(route);
    const oldSave = buttonNamed(route.shell.content, 'Save grants');
    latestInput(route.shell.content).checked = false;
    const refreshing = route.mounted.refresh();
    assert.equal(oldSave.isConnected, false);
    await oldSave.click();

    assert.match(textOf(route.shell.content), /Latest releasesDisabled/);
    assert.equal(route.shell.status.textContent, 'Release authorization updated.');
    staleAuthorization.resolve(staleFails
      ? jsonResponse({}, { ok: false })
      : jsonResponse({ items: [{ ...policy, versions: ['v9.9.9'] }] }));
    staleCatalog.resolve(staleFails ? jsonResponse({}, { ok: false }) : jsonResponse(catalog));
    await refreshing;
    assert.match(textOf(route.shell.content), /Latest releasesDisabled/);
    assert.doesNotMatch(textOf(route.shell.content), /v9\.9\.9/);
    assert.equal(route.shell.status.textContent, 'Release authorization updated.');
  }
});

test('failed grants recover retained detail after an invalidated refresh detaches the editor', async () => {
  const staleAuthorization = deferred();
  const staleCatalog = deferred();
  let reads = 0;
  const route = harness((call) => {
    if (call.method === 'PUT') return jsonResponse({}, { ok: false });
    if (call.path === '/api/admin/authorization') return reads++ === 0
      ? jsonResponse({ items: [policy] })
      : staleAuthorization.promise;
    return reads === 1 ? jsonResponse(catalog) : staleCatalog.promise;
  });
  await openPolicy(route);
  const oldSave = buttonNamed(route.shell.content, 'Save grants');
  const refreshing = route.mounted.refresh();
  await oldSave.click();

  assert.equal(oldSave.isConnected, false);
  assert.equal(route.shell.content.querySelectorAll('.list-detail')[0].dataset.view, 'detail');
  assert.match(route.shell.status.textContent, /failed/i);
  assert.equal(route.document.activeElement, buttonNamed(route.shell.content, 'Save grants'));
  staleAuthorization.resolve(jsonResponse({ items: [{ ...policy, versions: ['v9.9.9'] }] }));
  staleCatalog.resolve(jsonResponse(catalog));
  await refreshing;
  assert.doesNotMatch(textOf(route.shell.content), /v9\.9\.9/);
  assert.match(route.shell.status.textContent, /failed/i);
});

test('detached failed grants recover the submitted valid draft selection', async () => {
  const staleAuthorization = deferred();
  const staleCatalog = deferred();
  let reads = 0;
  const route = harness((call) => {
    if (call.method === 'PUT') return jsonResponse({}, { ok: false });
    if (call.path === '/api/admin/authorization') return reads++ === 0
      ? jsonResponse({ items: [policy] })
      : staleAuthorization.promise;
    return reads === 1 ? jsonResponse(catalog) : staleCatalog.promise;
  });
  await openPolicy(route);
  const oldSave = buttonNamed(route.shell.content, 'Save grants');
  latestInput(route.shell.content).checked = false;
  versionInput(route.shell.content, 'v0.2.1').checked = false;
  versionInput(route.shell.content, 'v0.3.0').checked = true;
  const refreshing = route.mounted.refresh();
  await oldSave.click();

  assert.deepEqual(route.calls[4].body, {
    email: policy.email,
    include_latest: false,
    versions: ['v0.3.0'],
  });
  assert.equal(latestInput(route.shell.content).checked, false);
  assert.equal(versionInput(route.shell.content, 'v0.2.1').checked, false);
  assert.equal(versionInput(route.shell.content, 'v0.3.0').checked, true);
  assert.equal(route.document.activeElement, buttonNamed(route.shell.content, 'Save grants'));

  staleAuthorization.resolve(jsonResponse({ items: [{ ...policy, versions: ['v9.9.9'] }] }));
  staleCatalog.resolve(jsonResponse(catalog));
  await refreshing;
  assert.equal(latestInput(route.shell.content).checked, false);
  assert.equal(versionInput(route.shell.content, 'v0.2.1').checked, false);
  assert.equal(versionInput(route.shell.content, 'v0.3.0').checked, true);
  assert.match(route.shell.status.textContent, /failed/i);
});

test('one route lock disables the editor and prevents refresh or duplicate mutation in flight', async () => {
  const update = deferred();
  const updated = {
    ...policy,
    include_latest: false,
    updated_at: '2026-07-13T13:00:00.000Z',
  };
  const route = harness((call) => call.method === 'PUT' ? update.promise : standardResponse(call));
  await openPolicy(route);
  latestInput(route.shell.content).checked = false;
  const save = buttonNamed(route.shell.content, 'Save grants');
  const saving = save.click();

  assert.equal(save.disabled, true);
  assert.ok([
    latestInput(route.shell.content),
    ...route.shell.content.querySelectorAll('.version-input'),
  ].every(({ disabled }) => disabled));
  await save.click();
  await route.mounted.refresh();
  assert.equal(route.calls.length, 3);
  update.resolve(jsonResponse({ ok: true, item: updated }));
  await saving;
  assert.equal(buttonNamed(route.shell.content, 'Save grants').disabled, false);
});

test('revoked policies are history-only and expose no grant mutation', async () => {
  const revoked = { ...policy, account_state: 'revoked' };
  const route = harness((call) => standardResponse(call, revoked));
  await openPolicy(route);

  assert.match(textOf(route.shell.content), /Account staterevoked/);
  assert.match(textOf(route.shell.content), /cannot be changed/);
  assert.equal(buttonNamed(route.shell.content, 'Save grants'), undefined);
  assert.equal(route.shell.content.querySelectorAll('.grant-option').length, 0);
  assert.equal(route.calls.length, 2);
});

test('catalog failure preserves current policy, disables mutation, and never guesses versions', async () => {
  const current = { ...policy, versions: ['v8.8.8'] };
  const route = harness((call) => call.path === '/api/admin/authorization'
    ? jsonResponse({ items: [current] })
    : jsonResponse({}, { ok: false }));
  await openPolicy(route);

  assert.match(textOf(route.shell.content), /v8\.8\.8/);
  assert.match(textOf(route.shell.content), /catalog could not be loaded/i);
  assert.equal(buttonNamed(route.shell.content, 'Save grants').disabled, true);
  assert.equal(route.shell.content.querySelectorAll('.version-input').length, 0);
  await buttonNamed(route.shell.content, 'Save grants').click();
  assert.equal(route.calls.length, 2);
});

test('malformed catalog items degrade grants without clearing loaded policy', async () => {
  const route = harness((call) => call.path === '/api/admin/authorization'
    ? jsonResponse({ items: [policy] })
    : jsonResponse({ items: {}, latest_version: 'v0.3.0', available: true }));
  await route.mounted.refresh();

  assert.equal(route.shell.content.querySelectorAll('.row-select').length, 1);
  assert.match(route.shell.status.textContent, /catalog could not be loaded/i);
  await route.shell.content.querySelectorAll('.row-select')[0].click();
  assert.match(textOf(route.shell.content), /v0\.2\.1/);
  assert.equal(buttonNamed(route.shell.content, 'Save grants').disabled, true);
});

test('Authorization owns grants only and renders no identity lifecycle commands', async () => {
  const route = harness((call) => standardResponse(call));
  await openPolicy(route);
  const rendered = textOf(route.shell.content);
  assert.doesNotMatch(rendered, /password|session|Approve|Reject|Revoke/i);
  for (const command of [
    'Reset password', 'Sign out all sessions', 'Approve', 'Reject', 'Revoke',
  ]) assert.equal(buttonNamed(route.shell.content, command), undefined);
  assert.doesNotMatch(routeSource, /reset-password|sign-out|users\/revoke|interests\/approve|interests\/reject/i);
});
