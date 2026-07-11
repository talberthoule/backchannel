'use strict';

const rows = document.getElementById('interest-rows');
const table = document.getElementById('interest-table');
const refresh = document.getElementById('refresh');
const requestCount = document.getElementById('request-count');
const lastRefreshed = document.getElementById('last-refreshed');
const status = document.getElementById('admin-status');
const numberFormatter = new Intl.NumberFormat();
const dateFormatter = new Intl.DateTimeFormat(undefined, {
  dateStyle: 'medium',
  timeStyle: 'short',
});
const statusClasses = new Set([
  'interested',
  'invited',
  'active',
  'unsubscribed',
]);

function element(name, className, text) {
  const node = document.createElement(name);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function messageRow(message) {
  const row = element('tr', 'state-row');
  const cell = element('td', '', message);
  cell.colSpan = 7;
  row.append(cell);
  return row;
}

function parseUtc(value) {
  if (typeof value !== 'string' || !value.trim()) return null;
  const source = value.trim();
  const zoned = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(source)
    ? source
    : source.replace(' ', 'T') + 'Z';
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
  const label = known
    ? normalized.charAt(0).toUpperCase() + normalized.slice(1)
    : 'Unknown';
  const cell = element('td');
  const indicator = element(
    'span',
    'status' + (known ? ' status-' + normalized : ''),
  );
  indicator.append(
    element('span', 'status-dot'),
    document.createTextNode(label),
  );
  cell.append(indicator);
  return cell;
}

function consentCell(record) {
  const cell = element('td', 'date');
  const content = element('span', 'consent');
  content.append(timeNode(record.consent_at, 'Not recorded'));
  content.append(element(
    'span',
    'cell-meta',
    record.consent_version ? 'Version ' + record.consent_version : 'Version unknown',
  ));
  cell.append(content);
  return cell;
}

function recordRow(record) {
  const row = document.createElement('tr');
  const emailCell = element('td', 'email', record.email || '—');
  if (record.email) emailCell.title = record.email;
  row.append(
    emailCell,
    statusCell(record.status),
    element('td', 'source', record.source || '—'),
    dateCell(record.created_at, 'Not recorded'),
    consentCell(record),
    dateCell(record.invited_at, 'Not yet'),
    dateCell(record.last_contacted_at, 'Not yet'),
  );
  return row;
}

function render(records) {
  if (records.length === 0) {
    rows.replaceChildren(messageRow('No access requests yet.'));
    return;
  }
  rows.replaceChildren(...records.map(recordRow));
}

function setStatus(message) {
  status.textContent = message;
}

async function load() {
  refresh.disabled = true;
  table.setAttribute('aria-busy', 'true');
  requestCount.textContent = '—';
  setStatus('Loading access requests…');
  rows.replaceChildren(messageRow('Loading access requests…'));

  try {
    const response = await fetch('/api/admin/interests', {
      headers: { accept: 'application/json' },
      cache: 'no-store',
    });
    if (!response.ok) throw new Error('request failed');
    const body = await response.json();
    if (!Array.isArray(body.items)) throw new Error('invalid response');

    render(body.items);
    requestCount.textContent = numberFormatter.format(body.items.length);
    const now = new Date();
    lastRefreshed.textContent = dateFormatter.format(now);
    lastRefreshed.dateTime = now.toISOString();
    setStatus(body.items.length === 1
      ? 'Loaded 1 access request.'
      : 'Loaded ' + numberFormatter.format(body.items.length) + ' access requests.');
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
