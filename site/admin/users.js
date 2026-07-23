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

function validIdentity(record, email) {
  return [
    record,
    record?.email === email,
    ['active', 'revoked'].includes(record?.state),
    typeof record?.source === 'string',
    validTime(record?.requested_at, false),
    validTime(record?.approved_at, false),
    record?.state === 'active' ? record?.revoked_at === null : validTime(record?.revoked_at, false),
  ].every(Boolean);
}

function validPassword(record) {
  if (record?.must_change_password === true) {
    return validTime(record.password_expires_at, false) && record.password_changed_at === null;
  }
  return record?.must_change_password === false
    && record.password_expires_at === null
    && validTime(record.password_changed_at, false);
}

function validSessions(record) {
  const count = record?.active_session_count;
  if (!Number.isInteger(count) || count < 0) return false;
  if (record.state !== 'active' && count !== 0) return false;
  return count === 0
    ? record.latest_session_expires_at === null
    : validTime(record.latest_session_expires_at, false);
}

function validUserRecord(record, email) {
  return [
    validIdentity(record, email),
    validPassword(record),
    validSessions(record),
    validTime(record?.password_expires_at),
    validTime(record?.password_changed_at),
    validTime(record?.revoked_at),
    validTime(record?.latest_session_expires_at),
  ].every(Boolean);
}

function preserves(record, current, fields) {
  return Boolean(record && current)
    && fields.every((field) => Object.is(record[field], current[field]));
}

function validResetResult(value, current) {
  const { item, credential } = value;
  return [
    item.state === 'active',
    item.revoked_at === null,
    item.must_change_password,
    item.password_changed_at === null,
    item.active_session_count === 0,
    item.latest_session_expires_at === null,
    credential,
    credential?.email === current.email,
    typeof credential?.password === 'string',
    credential?.password.length > 0,
    validTime(credential?.password_expires_at, false),
    credential?.password_expires_at === item.password_expires_at,
  ].every(Boolean);
}

function validSignOutResult({ item }, current) {
  return [
    preserves(item, current, [
      'state', 'revoked_at', 'must_change_password', 'password_expires_at', 'password_changed_at',
    ]),
    item.state === 'active',
    item.active_session_count === 0,
    item.latest_session_expires_at === null,
  ].every(Boolean);
}

function validRevokeResult({ item }, current) {
  return [
    preserves(item, current, [
      'must_change_password', 'password_expires_at', 'password_changed_at',
    ]),
    item.state === 'revoked',
    validTime(item.revoked_at, false),
    item.active_session_count === 0,
    item.latest_session_expires_at === null,
  ].every(Boolean);
}

function validReactivateResult({ item }, current) {
  return [
    preserves(item, current, [
      'must_change_password', 'password_expires_at', 'password_changed_at',
    ]),
    item.state === 'active',
    item.revoked_at === null,
    item.active_session_count === 0,
    item.latest_session_expires_at === null,
  ].every(Boolean);
}

const resultValidators = {
  reactivate: validReactivateResult,
  'reset-password': validResetResult,
  'sign-out': validSignOutResult,
  revoke: validRevokeResult,
};

function commandResult(action, value, current) {
  const validBase = [
    value?.ok === true,
    validUserRecord(value?.item, current?.email),
    preserves(value?.item, current, ['email', 'source', 'requested_at', 'approved_at']),
  ].every(Boolean);
  const validate = resultValidators[action];
  if (!validBase || !validate?.(value, current)) throw new Error('invalid response');
  return value;
}

const commandCopy = {
  'reset-password': {
    label: 'Reset password',
    description: ({ email }) => `Reset the password for ${email}? Active sessions will end and a one-time credential will be shown.`,
    success: ({ email }) => `Reset the password for ${email}.`,
  },
  'sign-out': {
    label: 'Sign out all sessions',
    description: ({ email }) => `Sign out all active sessions for ${email}?`,
    success: ({ email }) => `Signed out all sessions for ${email}.`,
  },
  revoke: {
    label: 'Revoke',
    description: ({ email }) => `Revoke access for ${email}? Sessions end immediately. Request and audit history remain.`,
    success: ({ email }) => `Revoked access for ${email}.`,
  },
  reactivate: {
    label: 'Reactivate',
    description: ({ email }) => `Reactivate access for ${email}? Existing credentials and release grants will become usable again.`,
    success: ({ email }) => `Reactivated access for ${email}.`,
  },
};

function showResetCredential(dialogs, value, returnFocus) {
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

function textOr(value, fallback) {
  return value || fallback;
}

function sessionCount(record) {
  return Number(record.active_session_count) || 0;
}

function disableCommandButtons(buttons) {
  for (const button of buttons) button.disabled = true;
}

function restoreCommandButtons(buttons) {
  for (const button of buttons) {
    if (button.isConnected) button.disabled = false;
  }
}

async function runUserCommand(context, record, action, button) {
    if (context.commandPending
      || (action === 'reactivate' ? record.state !== 'revoked' : record.state !== 'active')) return;
    const copy = commandCopy[action];
    const confirmed = await context.dialogs.confirm({
      title: copy.label,
      description: copy.description(record),
      label: copy.label,
      returnFocus: button,
    });
    if (!confirmed) return;

    context.commandPending = true;
    context.refreshGeneration += 1;
    context.shell.content.removeAttribute('aria-busy');
    const actionButtons = button.parentNode.querySelectorAll('button');
    disableCommandButtons(actionButtons);
    context.shell.status.textContent = `${copy.label} in progress for ${record.email}.`;
    try {
      const response = await jsonRequest(
        `${endpoint}/${action}`, 'POST', { email: record.email }, context.fetcher,
      );
      const current = context.items.find(({ email }) => email === record.email);
      const value = commandResult(action, response, current);
      context.items = replaceByEmail(context.items, value.item);
      context.selectedEmail = record.email;
      const returnFocus = renderUsers(context, action);
      context.shell.status.textContent = copy.success(record);
      if (action === 'reset-password') showResetCredential(context.dialogs, value, returnFocus);
    } catch {
      if (!button.isConnected) renderUsers(context, action);
      context.shell.status.textContent = `${copy.label} failed. Try again.`;
    } finally {
      context.commandPending = false;
      restoreCommandButtons(actionButtons);
    }
}

function showUsersState(context, message, retry = false) {
    const region = element('section', 'route-state', undefined, context.document);
    region.append(element('p', '', message, context.document));
    if (retry) {
      const button = element('button', 'secondary-button', 'Retry', context.document);
      button.type = 'button';
      button.addEventListener('click', () => refreshUsers(context));
      region.append(button);
    }
    context.shell.content.replaceChildren(region);
}

function showUserDetail(context, view, record, trigger, nextFocusAction) {
      const { document } = context;
      context.selectedEmail = record.email;
      const heading = element('h2', 'mono', textOr(record.email, 'Unknown email'), document);
      const identityTitle = element('h3', '', 'Identity', document);
      const identity = element('dl', 'detail-fields', undefined, document);
      identity.append(
        detailField('State', element('span', 'status-text', textOr(record.state, 'Unknown'), document), document),
        detailField('Source', element('span', '', textOr(record.source, 'Unknown'), document), document),
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
          'span', 'mono', formatCount(sessionCount(record)), document,
        ), document),
        detailField('Latest session expiry', timeNode(
          record.latest_session_expires_at, 'No active sessions', document,
        ), document),
      );
      const content = [view.back, heading, identityTitle, identity, securityTitle, security];
      const commandButtons = new Map();
      if (record.state === 'active') {
        const commandTitle = element('h3', '', 'Security commands', document);
        const actions = element('div', 'security-actions', undefined, document);
        const reset = element('button', 'primary-button', 'Reset password', document);
        reset.type = 'button';
        reset.addEventListener('click', () => runUserCommand(context, record, 'reset-password', reset));
        commandButtons.set('reset-password', reset);
        actions.append(reset);
        if (sessionCount(record) > 0) {
          const signOut = element('button', 'secondary-button', 'Sign out all sessions', document);
          signOut.type = 'button';
          signOut.addEventListener('click', () => runUserCommand(context, record, 'sign-out', signOut));
          commandButtons.set('sign-out', signOut);
          actions.append(signOut);
        }
        const revoke = element('button', 'danger-button', 'Revoke', document);
        revoke.type = 'button';
        revoke.addEventListener('click', () => runUserCommand(context, record, 'revoke', revoke));
        commandButtons.set('revoke', revoke);
        actions.append(revoke);
        content.push(commandTitle, actions);
      } else {
        const commandTitle = element('h3', '', 'Security commands', document);
        const actions = element('div', 'security-actions', undefined, document);
        const reactivate = element('button', 'primary-button', 'Reactivate', document);
        reactivate.type = 'button';
        reactivate.addEventListener('click', () => (
          runUserCommand(context, record, 'reactivate', reactivate)
        ));
        commandButtons.set('reactivate', reactivate);
        actions.append(reactivate);
        content.push(commandTitle, actions);
      }
      view.detailPane.replaceChildren(...content);
      view.controller.showDetail(trigger, heading);
      const focusTarget = commandButtons.get(nextFocusAction);
      focusTarget?.focus();
      return focusTarget || heading;
}

function matchesEmail({ email }, query) {
  return typeof email === 'string' && email.toLowerCase().includes(query);
}

function renderUserRows(context, view) {
      const query = view.search.value.trim().toLowerCase();
      const filtered = context.items.filter((record) => matchesEmail(record, query));
      view.triggers.clear();
      const rows = filtered.map((record) => {
        const row = element('tr', '', undefined, context.document);
        const select = element('button', 'row-select mono', record.email, context.document);
        select.type = 'button';
        select.addEventListener('click', () => showUserDetail(context, view, record, select));
        view.triggers.set(record.email, select);
        row.append(
          cell('Email', select, context.document),
          cell('Identity', element(
            'span', 'status-text', textOr(record.state, 'Unknown'), context.document,
          ), context.document),
          cell('Password', element('span', '', passwordState(record), context.document), context.document),
          cell('Sessions', element(
            'span', 'mono', formatCount(sessionCount(record)), context.document,
          ), context.document),
        );
        return row;
      });
      if (!rows.length) {
        const row = element('tr', 'state-row', undefined, context.document);
        const empty = element('td', '', 'No users match this email search.', context.document);
        empty.colSpan = 4;
        row.append(empty);
        rows.push(row);
      }
      view.body.replaceChildren(...rows);
      const count = filtered.length;
      view.searchStatus.textContent = count === 1
        ? '1 matching user.'
        : `${formatCount(count)} matching users.`;
      context.shell.count.textContent = formatCount(count);
      view.controller.showList();
}

function renderUsers(context, focusAction) {
    const { document, shell } = context;
    if (!context.items.length) {
      context.selectedEmail = null;
      showUsersState(context, 'No recipient users yet.');
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
    search.value = context.searchQuery;
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
    const view = {
      back,
      body,
      detailPane,
      search,
      searchStatus,
      triggers: new Map(),
    };
    view.controller = createListDetailController({
      root: workspace,
      list: listPane,
      detail: detailPane,
      heading: emptyHeading,
      back,
    });

    search.addEventListener('input', () => {
      context.searchQuery = search.value;
      renderUserRows(context, view);
    });
    renderUserRows(context, view);
    table.append(caption, head, body);
    tableWrap.append(table);
    listPane.append(listTitle, searchGroup, tableWrap);
    workspace.append(listPane, detailPane);
    shell.content.replaceChildren(workspace);

    const selected = context.items.find(({ email }) => email === context.selectedEmail);
    const selectedTrigger = view.triggers.get(context.selectedEmail);
    return selected && selectedTrigger
      ? showUserDetail(context, view, selected, selectedTrigger, focusAction)
      : null;
}

async function refreshUsers(context) {
    if (context.commandPending) return;
    const generation = ++context.refreshGeneration;
    context.shell.content.setAttribute('aria-busy', 'true');
    context.shell.count.textContent = '-';
    context.shell.status.textContent = 'Loading users.';
    showUsersState(context, 'Loading users.');
    try {
      const value = await jsonRequest(endpoint, undefined, undefined, context.fetcher);
      if (generation !== context.refreshGeneration) return;
      if (!Array.isArray(value.items)) throw new Error('invalid response');
      context.items = value.items;
      context.selectedEmail = null;
      context.searchQuery = '';
      renderUsers(context);
      context.shell.count.textContent = formatCount(context.items.length);
      context.shell.refreshed.replaceChildren(timeNode(
        new Date().toISOString(), 'Not yet', context.document,
      ));
      context.shell.status.textContent = context.items.length === 1
        ? 'Loaded 1 user.'
        : `Loaded ${formatCount(context.items.length)} users.`;
    } catch {
      if (generation !== context.refreshGeneration) return;
      context.items = [];
      context.selectedEmail = null;
      context.searchQuery = '';
      context.shell.count.textContent = '0';
      context.shell.status.textContent = 'Users could not be loaded.';
      showUsersState(context, 'Users could not be loaded. Try again.', true);
    } finally {
      if (generation === context.refreshGeneration) context.shell.content.removeAttribute('aria-busy');
    }
}

export function mount({ document, fetcher, shell, dialogs }) {
  const context = {
    commandPending: false,
    dialogs,
    document,
    fetcher,
    items: [],
    refreshGeneration: 0,
    searchQuery: '',
    selectedEmail: null,
    shell,
  };
  return { refresh: () => refreshUsers(context) };
}
