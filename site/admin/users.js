import {
  createListDetailController,
  element,
  formatCount,
  jsonRequest,
  replaceByEmail,
  timeNode,
} from './admin-core.js';

export const meta = {
  title: 'Users',
  description: 'Recipient identity and security state.',
};

const endpoint = '/api/admin/users';

export function passwordState(record, now = Date.now()) {
  if (!record.must_change_password) return 'Permanent';
  const expires = Date.parse(record.password_expires_at);
  const current = new Date(now).getTime();
  return Number.isFinite(expires) && Number.isFinite(current) && expires <= current
    ? 'Expired'
    : 'Temporary';
}

function validTime(value, nullable = true) {
  return (nullable && value === null)
    || (typeof value === 'string' && value.trim() && Number.isFinite(Date.parse(value)));
}

function validUserRecord(record, email) {
  return record && record.email === email
    && ['active', 'revoked'].includes(record.state)
    && typeof record.source === 'string'
    && validTime(record.requested_at, false)
    && validTime(record.approved_at, false)
    && typeof record.must_change_password === 'boolean'
    && validTime(record.password_expires_at)
    && validTime(record.password_changed_at)
    && validTime(record.revoked_at)
    && Number.isInteger(record.active_session_count)
    && record.active_session_count >= 0
    && validTime(record.latest_session_expires_at);
}

function commandResult(action, value, email) {
  if (value?.ok !== true || !validUserRecord(value.item, email)) throw new Error('invalid response');
  const { item } = value;
  if (action === 'reset-password') {
    const credential = value.credential;
    if (item.state !== 'active' || !item.must_change_password
      || item.active_session_count !== 0 || item.latest_session_expires_at !== null
      || !credential || credential.email !== email
      || typeof credential.password !== 'string' || !credential.password.length
      || !validTime(credential.password_expires_at, false)
      || credential.password_expires_at !== item.password_expires_at) throw new Error('invalid response');
  } else if (action === 'sign-out') {
    if (item.state !== 'active' || item.active_session_count !== 0
      || item.latest_session_expires_at !== null) throw new Error('invalid response');
  } else if (item.state !== 'revoked' || !validTime(item.revoked_at, false)
    || item.active_session_count !== 0 || item.latest_session_expires_at !== null) {
    throw new Error('invalid response');
  }
  return value;
}

function cell(label, content, document) {
  const node = element('td', '', undefined, document);
  node.setAttribute('data-label', label);
  node.append(content);
  return node;
}

function detailField(label, content, document) {
  const group = element('div', 'detail-field', undefined, document);
  const value = element('dd', '', undefined, document);
  value.append(content);
  group.append(element('dt', '', label, document), value);
  return group;
}

export function mount({ document, fetcher, shell, dialogs }) {
  let items = [];
  let selectedEmail = null;
  let searchQuery = '';
  let commandPending = false;

  async function runCommand(record, action, button) {
    if (commandPending || record.state !== 'active') return;
    const label = action === 'reset-password'
      ? 'Reset password'
      : action === 'sign-out' ? 'Sign out all sessions' : 'Revoke';
    const description = action === 'reset-password'
      ? `Reset the password for ${record.email}? Active sessions will end and a one-time credential will be shown.`
      : action === 'sign-out'
        ? `Sign out all active sessions for ${record.email}?`
        : `Revoke access for ${record.email}? Sessions end immediately. Request and audit history remain.`;
    const confirmed = await dialogs.confirm({
      title: label,
      description,
      label,
      returnFocus: button,
    });
    if (!confirmed) return;

    commandPending = true;
    const actionButtons = button.parentNode.querySelectorAll('button');
    for (const actionButton of actionButtons) actionButton.disabled = true;
    shell.status.textContent = `${label} in progress for ${record.email}.`;
    try {
      const value = commandResult(action, await jsonRequest(
        `${endpoint}/${action}`, 'POST', { email: record.email }, fetcher,
      ), record.email);
      items = replaceByEmail(items, value.item);
      selectedEmail = record.email;
      const returnFocus = render(action);
      shell.status.textContent = action === 'reset-password'
        ? `Reset the password for ${record.email}.`
        : action === 'sign-out'
          ? `Signed out all sessions for ${record.email}.`
          : `Revoked access for ${record.email}.`;
      if (action === 'reset-password') {
        dialogs.showCredential({
          text: [
            'Backchannel desktop access',
            `Account: ${value.credential.email}`,
            `Temporary password: ${value.credential.password}`,
            'Sign in: https://downloads.backchannel.page/',
            `Password expires: ${value.credential.password_expires_at}`,
          ].join('\n'),
          email: value.credential.email,
          returnFocus,
        });
      }
    } catch {
      shell.status.textContent = `${label} failed. Try again.`;
    } finally {
      commandPending = false;
      for (const actionButton of actionButtons) {
        if (actionButton.isConnected) actionButton.disabled = false;
      }
    }
  }

  function state(message, retry = false) {
    const region = element('section', 'route-state', undefined, document);
    region.append(element('p', '', message, document));
    if (retry) {
      const button = element('button', 'secondary-button', 'Retry', document);
      button.type = 'button';
      button.addEventListener('click', refresh);
      region.append(button);
    }
    shell.content.replaceChildren(region);
  }

  function render(focusAction) {
    if (!items.length) {
      selectedEmail = null;
      state('No recipient users yet.');
      return null;
    }
    const workspace = element('div', 'list-detail', undefined, document);
    const listPane = element('section', 'list-pane', undefined, document);
    const listTitle = element('h2', '', 'User directory', document);
    const searchGroup = element('div', 'search-group', undefined, document);
    const searchLabel = element('label', '', 'Search by email', document);
    searchLabel.setAttribute('for', 'user-search');
    const search = element('input', 'search-input', undefined, document);
    search.type = 'search';
    search.value = searchQuery;
    search.setAttribute('id', 'user-search');
    search.setAttribute('aria-label', 'Search by email');
    const searchStatus = element('p', 'search-status', '', document);
    searchStatus.setAttribute('role', 'status');
    searchStatus.setAttribute('aria-live', 'polite');
    searchGroup.append(searchLabel, search, searchStatus);
    const tableWrap = element('div', 'table-wrap', undefined, document);
    const table = element('table', 'data-table', undefined, document);
    const caption = element('caption', '', 'Recipient identity and security directory', document);
    const head = element('thead', '', undefined, document);
    const headRow = element('tr', '', undefined, document);
    for (const label of ['Email', 'Identity', 'Password', 'Sessions']) {
      const heading = element('th', '', label, document);
      heading.setAttribute('scope', 'col');
      headRow.append(heading);
    }
    head.append(headRow);
    const body = element('tbody', '', undefined, document);
    const detailPane = element('section', 'detail-pane', undefined, document);
    const back = element('button', 'back-button', 'Back to users', document);
    back.type = 'button';
    const emptyHeading = element('h2', '', 'Select a user', document);
    detailPane.append(back, emptyHeading, element(
      'p', 'detail-empty', 'Choose a user to inspect identity and security state.', document,
    ));
    const controller = createListDetailController({
      root: workspace,
      list: listPane,
      detail: detailPane,
      heading: emptyHeading,
      back,
    });

    function showDetail(record, trigger, nextFocusAction) {
      selectedEmail = record.email;
      const heading = element('h2', 'mono', record.email || 'Unknown email', document);
      const identityTitle = element('h3', '', 'Identity', document);
      const identity = element('dl', 'detail-fields', undefined, document);
      identity.append(
        detailField('State', element('span', 'status-text', record.state || 'Unknown', document), document),
        detailField('Source', element('span', '', record.source || 'Unknown', document), document),
        detailField('Requested', timeNode(record.requested_at, 'Not recorded', document), document),
        detailField('Approved', timeNode(record.approved_at, 'Not recorded', document), document),
        detailField('Revoked', timeNode(record.revoked_at, 'Not revoked', document), document),
      );
      const securityTitle = element('h3', '', 'Security', document);
      const security = element('dl', 'detail-fields', undefined, document);
      security.append(
        detailField('Password', element('span', '', passwordState(record), document), document),
        detailField('Temporary expiry', timeNode(record.password_expires_at, 'Not applicable', document), document),
        detailField('Password changed', timeNode(record.password_changed_at, 'Not yet', document), document),
        detailField('Active sessions', element(
          'span', 'mono', formatCount(Number(record.active_session_count) || 0), document,
        ), document),
        detailField('Latest session expiry', timeNode(
          record.latest_session_expires_at, 'No active sessions', document,
        ), document),
      );
      const content = [back, heading, identityTitle, identity, securityTitle, security];
      const commandButtons = new Map();
      if (record.state === 'active') {
        const commandTitle = element('h3', '', 'Security commands', document);
        const actions = element('div', 'security-actions', undefined, document);
        const reset = element('button', 'primary-button', 'Reset password', document);
        reset.type = 'button';
        reset.addEventListener('click', () => runCommand(record, 'reset-password', reset));
        commandButtons.set('reset-password', reset);
        actions.append(reset);
        if ((Number(record.active_session_count) || 0) > 0) {
          const signOut = element('button', 'secondary-button', 'Sign out all sessions', document);
          signOut.type = 'button';
          signOut.addEventListener('click', () => runCommand(record, 'sign-out', signOut));
          commandButtons.set('sign-out', signOut);
          actions.append(signOut);
        }
        const revoke = element('button', 'danger-button', 'Revoke', document);
        revoke.type = 'button';
        revoke.addEventListener('click', () => runCommand(record, 'revoke', revoke));
        commandButtons.set('revoke', revoke);
        actions.append(revoke);
        content.push(commandTitle, actions);
      }
      detailPane.replaceChildren(...content);
      controller.showDetail(trigger, heading);
      const focusTarget = commandButtons.get(nextFocusAction);
      focusTarget?.focus();
      return focusTarget || heading;
    }

    const triggers = new Map();
    function renderRows() {
      const query = search.value.trim().toLowerCase();
      const filtered = items.filter(({ email }) => (
        typeof email === 'string' && email.toLowerCase().includes(query)
      ));
      triggers.clear();
      const rows = filtered.map((record) => {
        const row = element('tr', '', undefined, document);
        const select = element('button', 'row-select mono', record.email, document);
        select.type = 'button';
        select.addEventListener('click', () => showDetail(record, select));
        triggers.set(record.email, select);
        row.append(
          cell('Email', select, document),
          cell('Identity', element('span', 'status-text', record.state || 'Unknown', document), document),
          cell('Password', element('span', '', passwordState(record), document), document),
          cell('Sessions', element(
            'span', 'mono', formatCount(Number(record.active_session_count) || 0), document,
          ), document),
        );
        return row;
      });
      if (!rows.length) {
        const row = element('tr', 'state-row', undefined, document);
        const empty = element('td', '', 'No users match this email search.', document);
        empty.colSpan = 4;
        row.append(empty);
        rows.push(row);
      }
      body.replaceChildren(...rows);
      const count = filtered.length;
      searchStatus.textContent = count === 1 ? '1 matching user.' : `${formatCount(count)} matching users.`;
      shell.count.textContent = formatCount(count);
      controller.showList();
    }

    search.addEventListener('input', () => {
      searchQuery = search.value;
      renderRows();
    });
    renderRows();
    table.append(caption, head, body);
    tableWrap.append(table);
    listPane.append(listTitle, searchGroup, tableWrap);
    workspace.append(listPane, detailPane);
    shell.content.replaceChildren(workspace);

    const selected = items.find(({ email }) => email === selectedEmail);
    const selectedTrigger = triggers.get(selectedEmail);
    return selected && selectedTrigger ? showDetail(selected, selectedTrigger, focusAction) : null;
  }

  async function refresh() {
    shell.content.setAttribute('aria-busy', 'true');
    shell.count.textContent = '-';
    shell.status.textContent = 'Loading users.';
    state('Loading users.');
    try {
      const value = await jsonRequest(endpoint, undefined, undefined, fetcher);
      if (!Array.isArray(value.items)) throw new Error('invalid response');
      items = value.items;
      selectedEmail = null;
      searchQuery = '';
      render();
      shell.count.textContent = formatCount(items.length);
      shell.refreshed.replaceChildren(timeNode(new Date().toISOString(), 'Not yet', document));
      shell.status.textContent = items.length === 1
        ? 'Loaded 1 user.'
        : `Loaded ${formatCount(items.length)} users.`;
    } catch {
      items = [];
      selectedEmail = null;
      searchQuery = '';
      shell.count.textContent = '0';
      shell.status.textContent = 'Users could not be loaded.';
      state('Users could not be loaded. Try again.', true);
    } finally {
      shell.content.removeAttribute('aria-busy');
    }
  }

  return { refresh };
}
