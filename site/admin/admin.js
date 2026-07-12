'use strict';

const rows = document.getElementById('interest-rows');
const table = document.getElementById('interest-table');
const refresh = document.getElementById('refresh');
const requestCount = document.getElementById('request-count');
const lastRefreshed = document.getElementById('last-refreshed');
const status = document.getElementById('admin-status');
const accessDialog = document.getElementById('access-dialog');
const accessForm = document.getElementById('access-form');
const accessTitle = document.getElementById('access-dialog-title');
const accessAccount = document.getElementById('access-account');
const includeLatest = document.getElementById('include-latest');
const versionOptions = document.getElementById('version-options');
const accessStatus = document.getElementById('access-status');
const accessCancel = document.getElementById('access-cancel');
const accessSubmit = document.getElementById('access-submit');
const credentialDialog = document.getElementById('credential-dialog');
const credentialText = document.getElementById('credential-text');
const credentialStatus = document.getElementById('credential-status');
const credentialCopy = document.getElementById('credential-copy');
const credentialSave = document.getElementById('credential-save');
const credentialClose = document.getElementById('credential-close');
const numberFormatter = new Intl.NumberFormat();
const dateFormatter = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' });
const statusClasses = new Set(['interested', 'invited', 'active', 'unsubscribed']);
let releases = [];
let selectedRecord = null;
let dialogMode = 'approve';
let returnFocus = null;
let activeCredentialText = '';

function element(name, className, text) {
  const node = document.createElement(name);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function messageRow(message) {
  const row = element('tr', 'state-row');
  const cell = element('td', '', message);
  cell.colSpan = 11;
  row.append(cell);
  return row;
}

function parseUtc(value) {
  if (typeof value !== 'string' || !value.trim()) return null;
  const source = value.trim();
  const zoned = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(source) ? source : source.replace(' ', 'T') + 'Z';
  const date = new Date(zoned);
  return Number.isNaN(date.getTime()) ? null : { date, source };
}

function timeNode(value, fallback = 'Not yet') {
  const parsed = parseUtc(value);
  if (!parsed) return element('span', '', fallback);
  const time = element('time', '', dateFormatter.format(parsed.date));
  time.dateTime = parsed.date.toISOString();
  time.title = parsed.source + ' UTC';
  return time;
}

function dateCell(value, fallback) {
  const cell = element('td', 'date');
  cell.append(timeNode(value, fallback));
  return cell;
}

function statusCell(value) {
  const normalized = typeof value === 'string' ? value.trim().toLowerCase() : '';
  const known = statusClasses.has(normalized);
  const label = known ? normalized.charAt(0).toUpperCase() + normalized.slice(1) : 'Unknown';
  const cell = element('td');
  const indicator = element('span', 'status' + (known ? ' status-' + normalized : ''));
  indicator.append(element('span', 'status-dot'), document.createTextNode(label));
  cell.append(indicator);
  return cell;
}

function consentCell(record) {
  const cell = element('td', 'date');
  const content = element('span', 'consent');
  content.append(timeNode(record.consent_at, 'Not recorded'));
  content.append(element('span', 'cell-meta', record.consent_version
    ? 'Version ' + record.consent_version : 'Version unknown'));
  cell.append(content);
  return cell;
}

function entitlementCell(record) {
  const labels = record.include_latest === 1 || record.include_latest === true ? ['Latest'] : [];
  labels.push(...(Array.isArray(record.versions) ? record.versions : []));
  return element('td', 'entitlements', labels.join(', ') || 'None');
}

function actionButton(label, record, action) {
  const button = element('button', 'row-action', label);
  button.type = 'button';
  button.setAttribute('aria-label', label + ' for ' + record.email);
  button.addEventListener('click', () => action(record, button));
  return button;
}

function actionCell(record) {
  const cell = element('td');
  const actions = element('div', 'row-actions');
  if (!record.account_state) {
    actions.append(
      actionButton('Approve', record, (item, button) => openAccess(item, 'approve', button)),
      actionButton('Reject', record, (item, button) => runSimple(item, 'reject', button)),
    );
  } else if (record.account_state === 'active') {
    actions.append(
      actionButton('Edit grants', record, (item, button) => openAccess(item, 'grants', button)),
      actionButton('Reset password', record, (item, button) => runSimple(item, 'reset-password', button)),
      actionButton('Revoke', record, (item, button) => runSimple(item, 'revoke', button)),
    );
  }
  if (!actions.childElementCount) actions.append(element('span', 'cell-meta', 'No actions'));
  cell.append(actions);
  return cell;
}

function recordRow(record) {
  const row = document.createElement('tr');
  const emailCell = element('td', 'email', record.email || '—');
  if (record.email) emailCell.title = record.email;
  row.append(
    emailCell, statusCell(record.status), element('td', 'source', record.source || '—'),
    dateCell(record.created_at, 'Not recorded'), consentCell(record),
    dateCell(record.invited_at, 'Not yet'), dateCell(record.last_contacted_at, 'Not yet'),
    element('td', '', record.release_decision || 'pending'),
    element('td', '', record.account_state || 'No account'),
    entitlementCell(record), actionCell(record),
  );
  return row;
}

function render(records) {
  rows.replaceChildren(...(records.length ? records.map(recordRow) : [messageRow('No access requests yet.')]));
}

function setStatus(message) { status.textContent = message; }

async function jsonRequest(path, method, body) {
  const response = await fetch(path, {
    method,
    headers: { 'content-type': 'application/json', accept: 'application/json' },
    body: JSON.stringify(body),
    cache: 'no-store',
  });
  const value = await response.json();
  if (!response.ok) throw new Error('request failed');
  return value;
}

function releaseCheckbox(release, checked) {
  const label = element('label', 'check-row');
  const input = document.createElement('input');
  input.type = 'checkbox';
  input.name = 'version';
  input.value = release.version;
  input.checked = checked;
  label.append(input, document.createTextNode(release.version));
  return label;
}

function openAccess(record, mode, button) {
  selectedRecord = record;
  dialogMode = mode;
  returnFocus = button;
  const existing = new Set(Array.isArray(record.versions) ? record.versions : []);
  accessTitle.textContent = mode === 'approve' ? 'Approve release access' : 'Edit release grants';
  accessSubmit.textContent = mode === 'approve' ? 'Approve access' : 'Save grants';
  accessAccount.textContent = record.email;
  includeLatest.checked = mode === 'approve' ? true
    : record.include_latest === 1 || record.include_latest === true;
  versionOptions.replaceChildren(...releases
    .filter((release) => release.version !== releases.latestVersion)
    .map((release) => releaseCheckbox(release, existing.has(release.version))));
  accessStatus.textContent = '';
  accessDialog.showModal();
  includeLatest.focus();
}

function showCredential(value) {
  const credential = value.credential;
  const releaseAccess = [credential.include_latest ? 'Latest' : '', ...credential.versions]
    .filter(Boolean).join(', ');
  activeCredentialText = [
    'Backchannel desktop access',
    'Account: ' + credential.email,
    'Temporary password: ' + credential.password,
    'Sign in: https://downloads.backchannel.page/',
    'Password expires: ' + credential.password_expires_at,
    'Release access: ' + releaseAccess,
  ].join('\n');
  credentialDialog.dataset.email = credential.email;
  credentialText.value = activeCredentialText;
  credentialStatus.textContent = '';
  credentialDialog.showModal();
  credentialText.focus();
}

async function runSimple(record, action, button) {
  if ((action === 'reject' || action === 'revoke')
    && !window.confirm((action === 'reject' ? 'Reject' : 'Revoke') + ' this account?')) return;
  button.disabled = true;
  try {
    const value = await jsonRequest('/api/admin/access/' + action, 'POST', { email: record.email });
    returnFocus = button;
    if (value.credential) showCredential(value);
    else setStatus('Account updated. Refresh to load the new state.');
  } catch {
    setStatus('The account action could not be completed. Try again.');
  } finally {
    button.disabled = false;
  }
}

accessForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const versions = [...versionOptions.querySelectorAll('input:checked')].map((input) => input.value);
  if (!includeLatest.checked && versions.length === 0) {
    accessStatus.textContent = 'Select Latest or at least one historical release.';
    return;
  }
  accessSubmit.disabled = true;
  accessStatus.textContent = 'Saving…';
  try {
    const value = await jsonRequest(
      '/api/admin/access/' + (dialogMode === 'approve' ? 'approve' : 'grants'),
      dialogMode === 'approve' ? 'POST' : 'PUT',
      { email: selectedRecord.email, include_latest: includeLatest.checked, versions },
    );
    accessDialog.close('saved');
    if (value.credential) showCredential(value);
    else setStatus('Release access updated. Refresh to load the new state.');
  } catch {
    accessStatus.textContent = 'Release access could not be saved. Try again.';
  } finally {
    accessSubmit.disabled = false;
  }
});

accessCancel.addEventListener('click', () => accessDialog.close('cancel'));
accessDialog.addEventListener('cancel', () => { accessDialog.returnValue = 'cancel'; });
accessDialog.addEventListener('close', () => {
  selectedRecord = null;
  if (!credentialDialog.open) returnFocus?.focus();
});

function clearCredential() {
  activeCredentialText = '';
  credentialText.value = '';
  credentialDialog.dataset.email = '';
  credentialStatus.textContent = '';
}

credentialCopy.addEventListener('click', async () => {
  try {
    await navigator.clipboard.writeText(activeCredentialText);
    credentialStatus.textContent = 'Credential copied.';
  } catch {
    credentialStatus.textContent = 'Copy failed. Use Save or select the credential text.';
  }
});

credentialSave.addEventListener('click', () => {
  const blob = new Blob([activeCredentialText], { type: 'text/plain;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  const safeEmail = credentialDialog.dataset.email
    .replace(/[^a-z0-9]+/gi, '-').replace(/^-+|-+$/g, '').toLowerCase();
  anchor.href = url;
  anchor.download = 'backchannel-access-' + safeEmail + '.txt';
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
});

credentialClose.addEventListener('click', () => credentialDialog.close());
credentialDialog.addEventListener('close', clearCredential);
credentialDialog.addEventListener('close', () => returnFocus?.focus());
addEventListener('pagehide', clearCredential);

async function load() {
  refresh.disabled = true;
  table.setAttribute('aria-busy', 'true');
  requestCount.textContent = '—';
  setStatus('Loading access requests…');
  rows.replaceChildren(messageRow('Loading access requests…'));
  try {
    const [releaseResponse, interestResponse] = await Promise.all([
      fetch('/api/admin/releases', { headers: { accept: 'application/json' }, cache: 'no-store' }),
      fetch('/api/admin/interests', { headers: { accept: 'application/json' }, cache: 'no-store' }),
    ]);
    if (!releaseResponse.ok || !interestResponse.ok) throw new Error('request failed');
    const [releaseBody, interestBody] = await Promise.all([
      releaseResponse.json(), interestResponse.json(),
    ]);
    if (!Array.isArray(releaseBody.items) || !Array.isArray(interestBody.items)) {
      throw new Error('invalid response');
    }
    releases = releaseBody.items;
    releases.latestVersion = releaseBody.latest_version;
    render(interestBody.items);
    requestCount.textContent = numberFormatter.format(interestBody.items.length);
    const now = new Date();
    lastRefreshed.textContent = dateFormatter.format(now);
    lastRefreshed.dateTime = now.toISOString();
    setStatus(interestBody.items.length === 1 ? 'Loaded 1 access request.'
      : 'Loaded ' + numberFormatter.format(interestBody.items.length) + ' access requests.');
  } catch {
    rows.replaceChildren(messageRow('Access requests could not be loaded.'));
    setStatus('Access requests could not be loaded. Try Refresh.');
  } finally {
    refresh.disabled = false;
    table.removeAttribute('aria-busy');
  }
}

refresh.addEventListener('click', load);
load();
