import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import { createDialogController } from '../site/admin/admin-core.js';
import * as earlyAccess from '../site/admin/early-access.js';
import { createDocument, jsonResponse, textOf } from './admin-test-helpers.js';

const html = readFileSync(new URL('../site/admin/index.html', import.meta.url), 'utf8');
const routeSource = readFileSync(new URL('../site/admin/early-access.js', import.meta.url), 'utf8');
const request = {
  email: 'person@example.com',
  status: 'interested',
  source: 'homepage',
  consent_version: '2026-07-11',
  consent_at: '2026-07-13T12:00:00.000Z',
  created_at: '2026-07-13T12:00:00.000Z',
  release_decision: 'pending',
  release_reviewed_at: null,
};
const credential = {
  email: 'person@example.com',
  password: 'generated-value',
  password_expires_at: '2026-07-16T12:00:00.000Z',
};
const expectedCredential = [
  'Backchannel desktop access',
  'Account: person@example.com',
  'Temporary password: generated-value',
  'Sign in: https://downloads.backchannel.page/',
  'Password expires: 2026-07-16T12:00:00.000Z',
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
  const createdAnchors = [];
  const createElement = document.createElement.bind(document);
  document.createElement = (name) => {
    const node = createElement(name);
    if (name === 'a') createdAnchors.push(node);
    return node;
  };
  const shell = {
    content: document.createElement('section'),
    count: document.createElement('span'),
    refreshed: document.createElement('time'),
    status: document.createElement('p'),
  };
  document.body.append(shell.content, shell.count, shell.refreshed, shell.status);
  const calls = [];
  const clipboard = [];
  const saved = [];
  const pageListeners = new Map();
  const dialogs = createDialogController({
    document,
    navigator: { clipboard: { async writeText(value) { clipboard.push(value); } } },
    addEventListener(type, listener) { pageListeners.set(type, listener); },
    URL: {
      createObjectURL(blob) { saved.push(blob); return 'blob:credential'; },
      revokeObjectURL() {},
    },
    Blob,
  });
  const mounted = earlyAccess.mount({
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
  return {
    calls, clipboard, createdAnchors, dialogs, document, mounted, pageListeners, saved, shell,
  };
}

async function openRequest(route) {
  await route.mounted.refresh();
  await route.shell.content.querySelectorAll('.row-select')[0].click();
}

test('Early access renders request review and no identity, security, or grant commands', async () => {
  const route = harness(() => jsonResponse({ items: [request] }));
  await openRequest(route);

  const renderedText = textOf(route.shell.content);
  assert.match(renderedText, /Interest status/);
  assert.match(renderedText, /Source/);
  assert.match(renderedText, /Requested/);
  assert.match(renderedText, /Consent/);
  assert.match(renderedText, /Consent version/);
  assert.match(renderedText, /Decision/);
  assert.deepEqual(
    route.shell.content.querySelectorAll('button').map(({ textContent }) => textContent),
    ['person@example.com', 'Back to requests', 'Approve', 'Reject'],
  );
  assert.doesNotMatch(renderedText, /Reset password|Sign out|Revoke|Latest|Save grants|Edit grants/i);
  assert.doesNotMatch(routeSource, /reset-password|sign-out|revoke|authorization\/grants/i);
});

test('Approve Cancel sends nothing, then posts only email and patches without refetch', async () => {
  const route = harness((call) => call.method === 'GET'
    ? jsonResponse({ items: [request] })
    : jsonResponse({ ok: true, credential }));
  await openRequest(route);
  const approve = buttonNamed(route.shell.content, 'Approve');

  const cancelled = approve.click();
  assert.equal(route.document.getElementById('confirm-dialog').open, true);
  await route.document.getElementById('confirm-cancel').click();
  await cancelled;
  assert.equal(route.calls.length, 1);
  assert.equal(route.document.activeElement, approve);

  const approved = approve.click();
  await route.document.getElementById('confirm-submit').click();
  await approved;
  assert.deepEqual(route.calls[1], {
    path: '/api/admin/interests/approve',
    method: 'POST',
    body: { email: 'person@example.com' },
  });
  assert.equal(route.calls.length, 2);
  assert.match(textOf(route.shell.content), /active/);
  assert.match(textOf(route.shell.content), /approved/);
  assert.match(route.shell.status.textContent, /approved/i);

  const successor = route.shell.content.querySelectorAll('.row-select')[0];
  assert.notEqual(successor, approve);
  assert.equal(approve.isConnected, false);
  assert.equal(successor.isConnected, true);

  const credentialText = route.document.getElementById('credential-text');
  assert.equal(credentialText.value, expectedCredential);
  assert.doesNotMatch(credentialText.value, /Latest|version|grant/i);
  await route.document.getElementById('credential-copy').click();
  assert.deepEqual(route.clipboard, [expectedCredential]);
  await route.document.getElementById('credential-save').click();
  assert.equal(await route.saved[0].text(), expectedCredential);
  assert.equal(
    route.createdAnchors[0].download,
    'backchannel-access-person-example-com.txt',
  );
  await route.document.getElementById('credential-close').click();
  assert.equal(credentialText.value, '');
  assert.equal(route.document.activeElement, successor);

  route.dialogs.showCredential({ text: 'temporary secret', email: request.email });
  route.pageListeners.get('pagehide')();
  assert.equal(credentialText.value, '');
});

test('Reject posts only email, consumes the returned item, and does not refetch', async () => {
  const rejected = {
    ...request,
    release_decision: 'rejected',
    release_reviewed_at: '2026-07-13T12:10:00.000Z',
  };
  const route = harness((call) => call.method === 'GET'
    ? jsonResponse({ items: [request] })
    : jsonResponse({ ok: true, item: rejected }));
  await openRequest(route);
  const reject = buttonNamed(route.shell.content, 'Reject');
  const pending = reject.click();
  await route.document.getElementById('confirm-submit').click();
  await pending;

  assert.deepEqual(route.calls[1], {
    path: '/api/admin/interests/reject',
    method: 'POST',
    body: { email: 'person@example.com' },
  });
  assert.equal(route.calls.length, 2);
  assert.match(textOf(route.shell.content), /rejected/);
  assert.match(route.shell.status.textContent, /rejected/i);
});

test('one decision runs at a time and a failed request restores both actions', async () => {
  const response = deferred();
  let mutations = 0;
  const route = harness((call) => {
    if (call.method === 'GET') return jsonResponse({ items: [request] });
    mutations += 1;
    return mutations === 1
      ? response.promise
      : jsonResponse({
        ok: true,
        item: { ...request, release_decision: 'rejected' },
      });
  });
  await openRequest(route);
  const approve = buttonNamed(route.shell.content, 'Approve');
  const reject = buttonNamed(route.shell.content, 'Reject');

  const approving = approve.click();
  await route.document.getElementById('confirm-submit').click();
  assert.equal(approve.disabled, true);
  assert.equal(reject.disabled, true);

  const opposing = reject.dispatchEvent({ type: 'click' });
  if (route.document.getElementById('confirm-dialog').open) {
    await route.document.getElementById('confirm-submit').click();
  }
  await opposing;
  assert.equal(route.calls.length, 2);

  response.resolve(jsonResponse({}, { ok: false }));
  await approving;
  assert.equal(approve.disabled, false);
  assert.equal(reject.disabled, false);
  assert.match(route.shell.status.textContent, /failed/i);
});

test('malformed success bodies preserve pending state and expose no credential', async () => {
  const rejected = {
    ...request,
    release_decision: 'rejected',
    release_reviewed_at: '2026-07-13T12:10:00.000Z',
  };
  const cases = [
    ['approve', { ok: false, credential }],
    ['approve', { ok: true, credential: { ...credential, email: 'other@example.com' } }],
    ['approve', { ok: true, credential: { ...credential, password: '' } }],
    ['approve', { ok: true, credential: { ...credential, password_expires_at: 'not-a-date' } }],
    ['reject', { ok: false, item: rejected }],
    ['reject', { ok: true, item: { ...request, release_decision: 'pending' } }],
    ['reject', { ok: true, item: { ...rejected, email: 'other@example.com' } }],
  ];

  for (const [action, response] of cases) {
    const route = harness((call) => call.method === 'GET'
      ? jsonResponse({ items: [request] })
      : jsonResponse(response));
    await openRequest(route);
    const pending = buttonNamed(route.shell.content, action === 'approve' ? 'Approve' : 'Reject').click();
    await route.document.getElementById('confirm-submit').click();
    await pending;

    assert.equal(route.calls.length, 2, `${action} must not refetch`);
    assert.equal(route.document.getElementById('credential-dialog').open, false, action);
    assert.match(route.shell.status.textContent, /failed/i, action);
    assert.match(textOf(route.shell.content), /interested/i, action);
    assert.match(textOf(route.shell.content), /pending/i, action);
    assert.equal(buttonNamed(route.shell.content, 'Approve').disabled, false, action);
    assert.equal(buttonNamed(route.shell.content, 'Reject').disabled, false, action);
  }
});

test('credential actions precede plain Users and Authorization route links', () => {
  assert.match(html, /id="credential-copy"[\s\S]+id="credential-save"[\s\S]+href="\/users"[\s\S]+href="\/authorization"/);
  assert.doesNotMatch(html, /credential-links[\s\S]*<button/);
});
