const numberFormatter = new Intl.NumberFormat();
const dateFormatter = new Intl.DateTimeFormat(undefined, {
  dateStyle: 'medium',
  timeStyle: 'short',
});

export function element(name, className = '', text, documentValue = document) {
  const node = documentValue.createElement(name);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

export async function jsonRequest(path, method = 'GET', body, fetcher = fetch) {
  const init = { method, headers: { accept: 'application/json' }, cache: 'no-store' };
  if (body !== undefined) {
    init.headers['content-type'] = 'application/json';
    init.body = JSON.stringify(body);
  }
  const response = await fetcher(path, init);
  const value = await response.json();
  if (!response.ok) throw new Error('request failed');
  return value;
}

export function replaceByEmail(items, item) {
  const index = items.findIndex(({ email }) => email === item.email);
  return index < 0 ? items : items.with(index, item);
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

export function timeNode(value, fallback = 'Not yet', documentValue = document) {
  const parsed = parseUtc(value);
  if (!parsed) return element('span', '', fallback, documentValue);
  const time = element('time', '', dateFormatter.format(parsed.date), documentValue);
  time.dateTime = parsed.date.toISOString();
  time.title = parsed.source + ' UTC';
  return time;
}

export function formatCount(value) {
  return numberFormatter.format(value);
}

export function createDialogController({
  document = globalThis.document,
  navigator = globalThis.navigator,
  addEventListener = globalThis.addEventListener
    ? globalThis.addEventListener.bind(globalThis)
    : () => {},
  URL = globalThis.URL,
  Blob = globalThis.Blob,
} = {}) {
  const confirmDialog = document.getElementById('confirm-dialog');
  const confirmTitle = document.getElementById('confirm-dialog-title');
  const confirmDescription = document.getElementById('confirm-dialog-description');
  const confirmCancel = document.getElementById('confirm-cancel');
  const confirmSubmit = document.getElementById('confirm-submit');
  const credentialDialog = document.getElementById('credential-dialog');
  const credentialText = document.getElementById('credential-text');
  const credentialStatus = document.getElementById('credential-status');
  const credentialCopy = document.getElementById('credential-copy');
  const credentialSave = document.getElementById('credential-save');
  const credentialClose = document.getElementById('credential-close');
  let confirmResolve = null;
  let confirmReturnFocus = null;
  let credentialReturnFocus = null;
  let activeCredentialText = '';

  function settleConfirmation(value) {
    const resolve = confirmResolve;
    confirmResolve = null;
    resolve?.(value);
    if (confirmDialog.open) confirmDialog.close(value ? 'confirm' : 'cancel');
  }

  function confirm({ title, description, label = 'Confirm', returnFocus } = {}) {
    confirmTitle.textContent = title || 'Confirm action';
    confirmDescription.textContent = description || '';
    confirmSubmit.textContent = label;
    confirmReturnFocus = returnFocus || null;
    confirmDialog.showModal();
    confirmSubmit.focus();
    return new Promise((resolve) => { confirmResolve = resolve; });
  }

  confirmCancel.addEventListener('click', () => settleConfirmation(false));
  confirmSubmit.addEventListener('click', () => settleConfirmation(true));
  confirmDialog.addEventListener('cancel', (event) => {
    event.preventDefault();
    settleConfirmation(false);
  });
  confirmDialog.addEventListener('close', () => {
    if (confirmResolve) settleConfirmation(false);
    confirmReturnFocus?.focus();
    confirmReturnFocus = null;
  });

  function clearCredential() {
    activeCredentialText = '';
    credentialText.value = '';
    credentialDialog.dataset.email = '';
    credentialStatus.textContent = '';
  }

  function showCredential({ text, email, returnFocus } = {}) {
    activeCredentialText = text || '';
    credentialText.value = activeCredentialText;
    credentialDialog.dataset.email = email || '';
    credentialStatus.textContent = '';
    credentialReturnFocus = returnFocus || null;
    credentialDialog.showModal();
    credentialText.focus();
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
  credentialDialog.addEventListener('close', () => {
    credentialReturnFocus?.focus();
    credentialReturnFocus = null;
  });
  addEventListener('pagehide', clearCredential);

  return { confirm, showCredential, clearCredential };
}

export function createListDetailController({ root, list, detail, heading, back }) {
  let returnFocus = null;
  let activeHeading = heading;

  function showList() {
    root.dataset.view = 'list';
    returnFocus?.focus();
  }

  function showDetail(trigger, nextHeading = heading) {
    if (returnFocus) delete returnFocus.dataset.selected;
    returnFocus = trigger || null;
    if (returnFocus) returnFocus.dataset.selected = 'true';
    activeHeading = nextHeading || heading;
    root.dataset.view = 'detail';
    activeHeading.setAttribute('tabindex', '-1');
    activeHeading.focus();
  }

  back.addEventListener('click', showList);
  showList();
  return { showDetail, showList };
}
