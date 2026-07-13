import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import { createDialogController } from '../site/admin/admin-core.js';
import * as users from '../site/admin/users.js';
import { createDocument, jsonResponse, textOf } from './admin-test-helpers.js';

const routeSource = readFileSync(new URL('../site/admin/users.js', import.meta.url), 'utf8');
const user = {
  email: 'Person@Example.com',
  state: 'active',
  source: 'homepage',
  requested_at: '2026-07-11T12:00:00.000Z',
  approved_at: '2026-07-11T12:05:00.000Z',
  must_change_password: false,
  password_expires_at: null,
  password_changed_at: '2026-07-12T12:00:00.000Z',
  revoked_at: null,
  active_session_count: 2,
  latest_session_expires_at: '2026-07-14T12:00:00.000Z',
};
const resetItem = {
  ...user,
  must_change_password: true,
  password_expires_at: '2026-07-16T12:00:00.000Z',
  password_changed_at: null,
  active_session_count: 0,
  latest_session_expires_at: null,
};
const credential = {
  email: user.email,
  password: 'generated-value',
  password_expires_at: resetItem.password_expires_at,
};
const expectedCredential = [
  'Backchannel desktop access',
  `Account: ${user.email}`,
  'Temporary password: generated-value',
  'Sign in: https://downloads.backchannel.page/',
  `Password expires: ${resetItem.password_expires_at}`,
].join('\n');

function deferred() {
  let resolve;
  const promise = new Promise((resolveValue) => { resolve = resolveValue; });
  return { promise, resolve };
}

function buttonNamed(root, label) {
  return root.querySelectorAll('button').find((button) => button.textContent === label);
}

function harness(respond) {
  const ids = [
    'confirm-dialog', 'confirm-dialog-title', 'confirm-dialog-description',
    'confirm-cancel', 'confirm-submit', 'credential-dialog', 'credential-text',
    'credential-status', 'credential-copy', 'credential-save', 'credential-close',
  ];
  const document = createDocument(ids);
  const shell = {
    content: document.createElement('section'),
    count: document.createElement('span'),
    refreshed: document.createElement('time'),
    status: document.createElement('p'),
  };
  document.body.append(shell.content, shell.count, shell.refreshed, shell.status);
  const dialogs = createDialogController({
    document,
    navigator: { clipboard: { async writeText() {} } },
    addEventListener() {},
    URL: { createObjectURL: () => 'blob:value', revokeObjectURL() {} },
    Blob,
  });
  const calls = [];
  const mounted = users.mount({
    document,
    shell,
    dialogs,
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
  return { calls, dialogs, document, mounted, shell };
}

async function openUser(route) {
  await route.mounted.refresh();
  await route.shell.content.querySelectorAll('.row-select')[0].click();
}

async function confirmCommand(route, label) {
  const pending = buttonNamed(route.shell.content, label).click();
  await route.document.getElementById('confirm-submit').click();
  await pending;
}

test('passwordState uses the exact permanent, expired, and temporary boundaries', () => {
  const now = new Date('2026-07-13T12:00:00.000Z');
  assert.equal(users.passwordState({ must_change_password: false }, now), 'Permanent');
  assert.equal(users.passwordState({
    must_change_password: true,
    password_expires_at: '2026-07-13T11:59:59.000Z',
  }, now), 'Expired');
  assert.equal(users.passwordState({
    must_change_password: true,
    password_expires_at: '2026-07-13T12:00:00.000Z',
  }, now), 'Expired');
  assert.equal(users.passwordState({
    must_change_password: true,
    password_expires_at: '2026-07-13T12:00:01.000Z',
  }, now), 'Temporary');
});

test('Users searches normalized email and owns complete identity and security detail', async () => {
  const route = harness(() => jsonResponse({ items: [
    user,
    { ...user, email: 'other@example.com' },
  ] }));
  await route.mounted.refresh();
  const search = route.shell.content.querySelectorAll('input')[0];
  search.value = '  PERSON@EXAMPLE  ';
  await search.dispatchEvent({ type: 'input' });
  assert.match(textOf(route.shell.content), /Person@Example\.com/);
  assert.doesNotMatch(textOf(route.shell.content), /other@example\.com/);

  const row = route.shell.content.querySelectorAll('.row-select')[0];
  await row.click();
  assert.equal(route.shell.content.querySelectorAll('.list-detail')[0].dataset.view, 'detail');
  assert.equal(route.document.activeElement.name, 'h2');
  assert.equal(route.document.activeElement.textContent, user.email);
  const pane = route.shell.content.querySelectorAll('.detail-pane')[0];
  const detail = textOf(pane);
  for (const label of [
    'Identity', 'State', 'Source', 'Requested', 'Approved', 'Revoked',
    'Security', 'Password', 'Temporary expiry', 'Password changed',
    'Active sessions', 'Latest session expiry',
  ]) assert.match(detail, new RegExp(label));
  const fields = pane.querySelectorAll('.detail-field');
  assert.equal(textOf(fields[0]), 'Stateactive');
  assert.equal(textOf(fields[1]), 'Sourcehomepage');
  assert.equal(textOf(fields[5]), 'PasswordPermanent');
  assert.equal(textOf(fields[8]), 'Active sessions2');
  assert.deepEqual(
    pane.querySelectorAll('time').map(({ dateTime }) => dateTime),
    [
      user.requested_at,
      user.approved_at,
      user.password_changed_at,
      user.latest_session_expires_at,
    ],
  );
  for (const label of ['Reset password', 'Sign out all sessions', 'Revoke']) {
    assert.ok(buttonNamed(route.shell.content, label), label);
  }
  assert.doesNotMatch(detail, /release|grant|authorization|reactivat/i);
  assert.doesNotMatch(routeSource, /authorization\/grants|include_latest|Save grants|Edit grants/i);

  await buttonNamed(route.shell.content, 'Back to users').click();
  assert.equal(route.shell.content.querySelectorAll('.list-detail')[0].dataset.view, 'list');
  assert.equal(route.document.activeElement, row);
});

test('Reset password posts only email, patches without refetch, and opens the one-time credential', async () => {
  const route = harness((call) => call.method === 'GET'
    ? jsonResponse({ items: [user] })
    : jsonResponse({ ok: true, item: resetItem, credential }));
  await openUser(route);
  const reset = buttonNamed(route.shell.content, 'Reset password');

  const cancelled = reset.click();
  await route.document.getElementById('confirm-cancel').click();
  await cancelled;
  assert.equal(route.calls.length, 1);
  assert.equal(route.document.activeElement, reset);

  await confirmCommand(route, 'Reset password');
  assert.deepEqual(route.calls[1], {
    path: '/api/admin/users/reset-password',
    method: 'POST',
    body: { email: user.email },
  });
  assert.equal(route.calls.length, 2);
  assert.equal(route.shell.content.querySelectorAll('.list-detail')[0].dataset.view, 'detail');
  assert.match(textOf(route.shell.content), /Temporary/);
  assert.match(textOf(route.shell.content), /No active sessions/);
  assert.equal(route.document.getElementById('credential-text').value, expectedCredential);
  assert.equal(route.document.getElementById('credential-dialog').open, true);
  assert.equal(reset.isConnected, false);

  const successor = buttonNamed(route.shell.content, 'Reset password');
  await route.document.getElementById('credential-close').click();
  assert.equal(route.document.activeElement, successor);
  assert.equal(successor.isConnected, true);
});

test('Sign out all sessions clears session metadata locally without changing identity', async () => {
  const signedOut = {
    ...user,
    active_session_count: 0,
    latest_session_expires_at: null,
  };
  const route = harness((call) => call.method === 'GET'
    ? jsonResponse({ items: [user] })
    : jsonResponse({ ok: true, item: signedOut }));
  await openUser(route);
  await confirmCommand(route, 'Sign out all sessions');

  assert.deepEqual(route.calls[1], {
    path: '/api/admin/users/sign-out',
    method: 'POST',
    body: { email: user.email },
  });
  assert.equal(route.calls.length, 2);
  assert.equal(route.shell.content.querySelectorAll('.list-detail')[0].dataset.view, 'detail');
  assert.match(textOf(route.shell.content), /No active sessions/);
  assert.equal(buttonNamed(route.shell.content, 'Sign out all sessions'), undefined);
  assert.equal(route.document.activeElement.isConnected, true);
  assert.equal(route.document.activeElement.name, 'h2');
});

test('Revoke explains the lifecycle, patches state, and exposes no reactivation path', async () => {
  const revoked = {
    ...user,
    state: 'revoked',
    revoked_at: '2026-07-13T12:30:00.000Z',
    active_session_count: 0,
    latest_session_expires_at: null,
  };
  const route = harness((call) => call.method === 'GET'
    ? jsonResponse({ items: [user] })
    : jsonResponse({ ok: true, item: revoked }));
  await openUser(route);
  const pending = buttonNamed(route.shell.content, 'Revoke').click();
  const description = route.document.getElementById('confirm-dialog-description').textContent;
  assert.match(description, /sessions end/i);
  assert.match(description, /request and audit history remain/i);
  await route.document.getElementById('confirm-submit').click();
  await pending;

  assert.deepEqual(route.calls[1], {
    path: '/api/admin/users/revoke',
    method: 'POST',
    body: { email: user.email },
  });
  assert.equal(route.calls.length, 2);
  const detail = textOf(route.shell.content.querySelectorAll('.detail-pane')[0]);
  assert.match(detail, /revoked/i);
  for (const command of ['Reset password', 'Sign out all sessions', 'Revoke', 'Reactivate']) {
    assert.equal(buttonNamed(route.shell.content, command), undefined);
  }
  assert.equal(route.shell.content.querySelectorAll('.list-detail')[0].dataset.view, 'detail');
  assert.equal(route.document.activeElement.isConnected, true);
});

test('one Users command runs at a time and failure restores every command', async () => {
  const response = deferred();
  const route = harness((call) => call.method === 'GET'
    ? jsonResponse({ items: [user] })
    : response.promise);
  await openUser(route);
  const reset = buttonNamed(route.shell.content, 'Reset password');
  const signOut = buttonNamed(route.shell.content, 'Sign out all sessions');
  const revoke = buttonNamed(route.shell.content, 'Revoke');

  const resetting = reset.click();
  await route.document.getElementById('confirm-submit').click();
  assert.equal(reset.disabled, true);
  assert.equal(signOut.disabled, true);
  assert.equal(revoke.disabled, true);
  await signOut.click();
  assert.equal(route.calls.length, 2);

  response.resolve(jsonResponse({}, { ok: false }));
  await resetting;
  assert.equal(reset.disabled, false);
  assert.equal(signOut.disabled, false);
  assert.equal(revoke.disabled, false);
  assert.match(route.shell.status.textContent, /failed/i);
  assert.equal(route.shell.content.querySelectorAll('.list-detail')[0].dataset.view, 'detail');
});

test('a command result wins when it completes before an older refresh', async () => {
  const staleRefresh = deferred();
  const commandResponse = deferred();
  let reads = 0;
  const route = harness((call) => {
    if (call.method === 'GET') return reads++ === 0
      ? jsonResponse({ items: [user] })
      : staleRefresh.promise;
    return commandResponse.promise;
  });
  await openUser(route);
  const resetting = buttonNamed(route.shell.content, 'Reset password').click();
  const refreshing = route.mounted.refresh();
  await route.document.getElementById('confirm-submit').click();

  commandResponse.resolve(jsonResponse({ ok: true, item: resetItem, credential }));
  await resetting;
  assert.match(route.shell.status.textContent, /Reset the password/);
  staleRefresh.resolve(jsonResponse({ items: [user] }));
  await refreshing;

  assert.equal(route.calls.length, 3);
  assert.match(route.shell.status.textContent, /Reset the password/);
  assert.match(textOf(route.shell.content), /Temporary/);
  assert.doesNotMatch(textOf(route.shell.content), /Permanent/);
  assert.equal(route.document.getElementById('credential-dialog').open, true);
});

test('an older refresh error cannot replace pending state when it completes before the command', async () => {
  const staleRefresh = deferred();
  const commandResponse = deferred();
  let reads = 0;
  const route = harness((call) => {
    if (call.method === 'GET') return reads++ === 0
      ? jsonResponse({ items: [user] })
      : staleRefresh.promise;
    return commandResponse.promise;
  });
  await openUser(route);
  const resetting = buttonNamed(route.shell.content, 'Reset password').click();
  const refreshing = route.mounted.refresh();
  await route.document.getElementById('confirm-submit').click();
  assert.match(route.shell.status.textContent, /in progress/);

  staleRefresh.resolve(jsonResponse({}, { ok: false }));
  await refreshing;
  assert.match(route.shell.status.textContent, /in progress/);
  assert.doesNotMatch(textOf(route.shell.content), /could not be loaded|Retry/);

  commandResponse.resolve(jsonResponse({ ok: true, item: resetItem, credential }));
  await resetting;
  assert.match(route.shell.status.textContent, /Reset the password/);
  assert.match(textOf(route.shell.content), /Temporary/);
});

test('Refresh performs no GET or rerender while a command is pending', async () => {
  const commandResponse = deferred();
  const route = harness((call) => call.method === 'GET'
    ? jsonResponse({ items: [user] })
    : commandResponse.promise);
  await openUser(route);
  const reset = buttonNamed(route.shell.content, 'Reset password');
  const resetting = reset.click();
  await route.document.getElementById('confirm-submit').click();
  const status = route.shell.status.textContent;

  await route.mounted.refresh();
  assert.equal(route.calls.length, 2);
  assert.equal(route.shell.status.textContent, status);
  assert.equal(reset.isConnected, true);
  assert.equal(reset.disabled, true);

  commandResponse.resolve(jsonResponse({ ok: true, item: resetItem, credential }));
  await resetting;
});

test('failed commands recover retained detail before stale refresh success or error completes', async () => {
  for (const staleFails of [false, true]) {
    const staleRefresh = deferred();
    let reads = 0;
    const route = harness((call) => {
      if (call.method === 'GET') return reads++ === 0
        ? jsonResponse({ items: [user] })
        : staleRefresh.promise;
      return jsonResponse({}, { ok: false });
    });
    await openUser(route);
    const oldReset = buttonNamed(route.shell.content, 'Reset password');
    const resetting = oldReset.click();
    const refreshing = route.mounted.refresh();
    await route.document.getElementById('confirm-submit').click();
    await resetting;

    assert.equal(route.calls.length, 3);
    assert.equal(oldReset.isConnected, false);
    assert.match(route.shell.status.textContent, /Reset password failed\. Try again\./);
    assert.equal(route.shell.content.querySelectorAll('.list-detail')[0].dataset.view, 'detail');
    const successor = buttonNamed(route.shell.content, 'Reset password');
    assert.equal(successor.isConnected, true);
    assert.equal(successor.disabled, false);
    assert.equal(route.document.activeElement, successor);
    assert.equal(
      route.shell.content.querySelectorAll('.row-select')[0].dataset.selected,
      'true',
    );

    staleRefresh.resolve(staleFails
      ? jsonResponse({}, { ok: false })
      : jsonResponse({ items: [{ ...user, source: 'stale' }] }));
    await refreshing;
    assert.match(route.shell.status.textContent, /Reset password failed\. Try again\./);
    assert.equal(route.shell.content.querySelectorAll('.list-detail')[0].dataset.view, 'detail');
    assert.equal(buttonNamed(route.shell.content, 'Reset password'), successor);
    assert.equal(route.document.activeElement, successor);
    assert.doesNotMatch(textOf(route.shell.content), /stale/);
  }
});

test('Reset accepts a matching parseable server expiry despite the client clock', async () => {
  const pastItem = {
    ...resetItem,
    password_expires_at: '2000-01-01T00:00:00.000Z',
  };
  const pastCredential = {
    ...credential,
    password_expires_at: pastItem.password_expires_at,
  };
  const route = harness((call) => call.method === 'GET'
    ? jsonResponse({ items: [user] })
    : jsonResponse({ ok: true, item: pastItem, credential: pastCredential }));
  await openUser(route);
  await confirmCommand(route, 'Reset password');

  assert.equal(route.calls.length, 2);
  assert.match(textOf(route.shell.content), /Expired/);
  assert.equal(route.document.getElementById('credential-dialog').open, true);
  assert.match(route.document.getElementById('credential-text').value, /2000-01-01T00:00:00\.000Z/);
});

test('malformed command success bodies do not patch state or expose credentials', async () => {
  const revoked = {
    ...user,
    state: 'revoked',
    revoked_at: '2026-07-13T12:30:00.000Z',
    active_session_count: 0,
    latest_session_expires_at: null,
  };
  const cases = [
    ['Reset password', { ok: false, item: resetItem, credential }],
    ['Reset password', { ok: true, item: { ...resetItem, email: 'other@example.com' }, credential }],
    ['Reset password', { ok: true, item: { ...resetItem, active_session_count: 1 }, credential }],
    ['Reset password', { ok: true, item: { ...resetItem, source: 'changed' }, credential }],
    ['Reset password', { ok: true, item: { ...resetItem, requested_at: '2026-07-10T12:00:00.000Z' }, credential }],
    ['Reset password', { ok: true, item: { ...resetItem, approved_at: '2026-07-10T12:00:00.000Z' }, credential }],
    ['Reset password', { ok: true, item: { ...resetItem, revoked_at: '2026-07-13T12:30:00.000Z' }, credential }],
    ['Reset password', { ok: true, item: { ...resetItem, password_changed_at: user.password_changed_at }, credential }],
    ['Reset password', { ok: true, item: resetItem, credential: { ...credential, password: '' } }],
    ['Reset password', { ok: true, item: resetItem, credential: { ...credential, password_expires_at: 'not-a-date' } }],
    ['Sign out all sessions', { ok: true, item: { ...user, active_session_count: 1 } }],
    ['Sign out all sessions', { ok: true, item: { ...user, active_session_count: 0 } }],
    ['Sign out all sessions', { ok: true, item: { ...user, state: 'revoked', active_session_count: 0 } }],
    ['Sign out all sessions', { ok: true, item: {
      ...user, must_change_password: true, password_expires_at: resetItem.password_expires_at,
      password_changed_at: null, active_session_count: 0, latest_session_expires_at: null,
    } }],
    ['Sign out all sessions', { ok: true, item: {
      ...user, source: 'changed', active_session_count: 0, latest_session_expires_at: null,
    } }],
    ['Revoke', { ok: true, item: { ...revoked, state: 'active' } }],
    ['Revoke', { ok: true, item: { ...revoked, revoked_at: null } }],
    ['Revoke', { ok: true, item: { ...revoked, source: 'changed' } }],
    ['Revoke', { ok: true, item: {
      ...revoked, must_change_password: true, password_expires_at: resetItem.password_expires_at,
      password_changed_at: null,
    } }],
  ];

  for (const [label, value] of cases) {
    const route = harness((call) => call.method === 'GET'
      ? jsonResponse({ items: [user] })
      : jsonResponse(value));
    await openUser(route);
    await confirmCommand(route, label);

    assert.equal(route.calls.length, 2, label);
    assert.equal(route.document.getElementById('credential-dialog').open, false, label);
    assert.match(route.shell.status.textContent, /failed/i, label);
    assert.match(textOf(route.shell.content), /Permanent/, label);
    assert.match(textOf(route.shell.content), /2/, label);
    for (const command of ['Reset password', 'Sign out all sessions', 'Revoke']) {
      assert.equal(buttonNamed(route.shell.content, command).disabled, false, `${label}: ${command}`);
    }
  }
});

test('revoked users expose identity and security history without any command path', async () => {
  const revoked = {
    ...user,
    state: 'revoked',
    revoked_at: '2026-07-13T12:30:00.000Z',
    active_session_count: 0,
    latest_session_expires_at: null,
  };
  const route = harness(() => jsonResponse({ items: [revoked] }));
  await openUser(route);
  const pane = route.shell.content.querySelectorAll('.detail-pane')[0];
  const detail = textOf(pane);
  assert.match(detail, /Identity/);
  assert.match(detail, /Security/);
  const fields = pane.querySelectorAll('.detail-field');
  assert.equal(textOf(fields[0]), 'Staterevoked');
  assert.equal(textOf(fields[1]), 'Sourcehomepage');
  assert.equal(textOf(fields[5]), 'PasswordPermanent');
  assert.equal(textOf(fields[8]), 'Active sessions0');
  assert.equal(textOf(fields[9]), 'Latest session expiryNo active sessions');
  assert.deepEqual(
    pane.querySelectorAll('time').map(({ dateTime }) => dateTime),
    [
      revoked.requested_at,
      revoked.approved_at,
      revoked.revoked_at,
      revoked.password_changed_at,
    ],
  );
  for (const command of ['Reset password', 'Sign out all sessions', 'Revoke', 'Reactivate']) {
    assert.equal(buttonNamed(route.shell.content, command), undefined);
  }
  assert.equal(route.calls.length, 1);
});
