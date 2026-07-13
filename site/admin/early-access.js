import {
  createListDetailController,
  element,
  formatCount,
  jsonRequest,
  replaceByEmail,
  timeNode,
} from './admin-core.js';

export const meta = {
  title: 'Early access',
  description: 'Request and consent review for the private desktop preview.',
};

const endpoint = '/api/admin/interests';

const decisionCopy = {
  approve: {
    verb: 'Approve',
    progress: 'Approving',
    success: 'Approved',
  },
  reject: {
    verb: 'Reject',
    progress: 'Rejecting',
    success: 'Rejected',
  },
};

function validCredential(credential, email) {
  return [
    credential,
    credential?.email === email,
    typeof credential?.password === 'string',
    credential?.password.length > 0,
    typeof credential?.password_expires_at === 'string',
    credential?.password_expires_at.trim(),
    Number.isFinite(Date.parse(credential?.password_expires_at)),
  ].every(Boolean);
}

function credentialText(credential) {
  return [
    'Backchannel desktop access',
    `Account: ${credential.email}`,
    `Temporary password: ${credential.password}`,
    'Sign in: https://downloads.backchannel.page/',
    `Password expires: ${credential.password_expires_at}`,
  ].join('\n');
}

function cell(label, content, document) {
  const node = element('td', '', undefined, document);
  node.setAttribute('data-label', label);
  node.append(content);
  return node;
}

function detailField(label, content, document) {
  const group = element('div', 'detail-field', undefined, document);
  group.append(element('dt', '', label, document), element('dd', '', undefined, document));
  group.children[1].append(content);
  return group;
}

function textOr(value, fallback) {
  return value || fallback;
}

function applyRejection(context, value, record) {
    const valid = [
      value.item,
      value.item?.email === record.email,
      value.item?.release_decision === 'rejected',
    ].every(Boolean);
    if (!valid) throw new Error('invalid response');
    context.items = replaceByEmail(context.items, value.item);
    const returnFocus = renderEarlyAccess(context, record.email);
    return () => returnFocus?.focus();
}

function applyApproval(context, value, record) {
    const { credential } = value;
    if (!validCredential(credential, record.email)) throw new Error('invalid response');
    const reviewedAt = value.item?.release_reviewed_at;
    context.items = replaceByEmail(context.items, {
      ...record,
      status: 'active',
      release_decision: 'approved',
      ...(typeof reviewedAt === 'string' ? { release_reviewed_at: reviewedAt } : {}),
    });
    const returnFocus = renderEarlyAccess(context, record.email);
    return () => context.dialogs.showCredential({
      text: credentialText(credential),
      email: credential.email,
      returnFocus,
    });
}

const decisionHandlers = {
  approve: applyApproval,
  reject: applyRejection,
};

async function decideEarlyAccess(context, record, action, button) {
    if (context.decisionPending) return;
    const copy = decisionCopy[action];
    const confirmed = await context.dialogs.confirm({
      title: `${copy.verb} early-access request`,
      description: `${copy.verb} the request from ${record.email}?`,
      label: copy.verb,
      returnFocus: button,
    });
    if (!confirmed) return;

    context.decisionPending = true;
    const actionButtons = button.parentNode.querySelectorAll('button');
    for (const actionButton of actionButtons) actionButton.disabled = true;
    context.shell.status.textContent = `${copy.progress} ${record.email}.`;
    try {
      const value = await jsonRequest(
        `${endpoint}/${action}`, 'POST', { email: record.email }, context.fetcher,
      );
      if (value.ok !== true) throw new Error('invalid response');
      const complete = decisionHandlers[action](context, value, record);
      context.shell.status.textContent = `${copy.success} the request from ${record.email}.`;
      complete();
    } catch {
      context.shell.status.textContent = `${copy.verb} failed. Try again.`;
    } finally {
      context.decisionPending = false;
      for (const actionButton of actionButtons) actionButton.disabled = false;
    }
}

function showEarlyAccessState(context, message, retry = false) {
    const region = element('section', 'route-state', undefined, context.document);
    region.append(element('p', '', message, context.document));
    if (retry) {
      const button = element('button', 'secondary-button', 'Retry', context.document);
      button.type = 'button';
      button.addEventListener('click', () => refreshEarlyAccess(context));
      region.append(button);
    }
    context.shell.content.replaceChildren(region);
}

function showEarlyAccessDetail(context, view, record, trigger) {
      const { document } = context;
      const heading = element('h2', 'mono', textOr(record.email, 'Unknown email'), document);
      const fields = element('dl', 'detail-fields', undefined, document);
      fields.append(
        detailField('Interest status', element(
          'span', '', textOr(record.status, 'Unknown'), document,
        ), document),
        detailField('Source', element('span', '', textOr(record.source, 'Unknown'), document), document),
        detailField('Requested', timeNode(record.created_at, 'Not recorded', document), document),
        detailField('Consent', timeNode(record.consent_at, 'Not recorded', document), document),
        detailField('Consent version', element(
          'span', 'mono', textOr(record.consent_version, 'Unknown'), document,
        ), document),
        detailField('Decision', element(
          'span', '', textOr(record.release_decision, 'pending'), document,
        ), document),
      );
      const content = [view.back, heading, fields];
      if (record.release_decision === 'pending') {
        const actionTitle = element('h3', '', 'Decision', document);
        const actions = element('div', 'dialog-actions', undefined, document);
        const approve = element('button', 'primary-button', 'Approve', document);
        approve.type = 'button';
        approve.addEventListener('click', () => decideEarlyAccess(context, record, 'approve', approve));
        const reject = element('button', 'secondary-button', 'Reject', document);
        reject.type = 'button';
        reject.addEventListener('click', () => decideEarlyAccess(context, record, 'reject', reject));
        actions.append(approve, reject);
        content.push(actionTitle, actions);
      }
      view.detailPane.replaceChildren(...content);
      view.controller.showDetail(trigger, heading);
}

function renderEarlyAccessRows(context, view, focusEmail) {
    let focusTarget = null;
    for (const record of context.items) {
      const row = element('tr', '', undefined, context.document);
      const select = element(
        'button', 'row-select mono', textOr(record.email, 'Unknown email'), context.document,
      );
      select.type = 'button';
      select.addEventListener('click', () => showEarlyAccessDetail(context, view, record, select));
      if (record.email === focusEmail) focusTarget = select;
      row.append(
        cell('Email', select, context.document),
        cell('Status', element(
          'span', 'status-text', textOr(record.status, 'Unknown'), context.document,
        ), context.document),
        cell('Source', element(
          'span', '', textOr(record.source, 'Unknown'), context.document,
        ), context.document),
        cell('Requested', timeNode(record.created_at, 'Not recorded', context.document), context.document),
        cell('Decision', element(
          'span', 'status-text', textOr(record.release_decision, 'pending'), context.document,
        ), context.document),
      );
      view.body.append(row);
    }
    return focusTarget;
}

function renderEarlyAccess(context, focusEmail) {
    const { document, shell } = context;
    if (!context.items.length) {
      showEarlyAccessState(context, 'No early-access requests yet.');
      return null;
    }
    const workspace = element('div', 'list-detail', undefined, document);
    const listPane = element('section', 'list-pane', undefined, document);
    const listTitle = element('h2', '', 'Requests', document);
    const tableWrap = element('div', 'table-wrap', undefined, document);
    const table = element('table', 'data-table', undefined, document);
    const caption = element('caption', '', 'Early-access requests, newest first', document);
    const head = element('thead', '', undefined, document);
    const headRow = element('tr', '', undefined, document);
    for (const label of ['Email', 'Status', 'Source', 'Requested', 'Decision']) {
      const heading = element('th', '', label, document);
      heading.setAttribute('scope', 'col');
      headRow.append(heading);
    }
    head.append(headRow);
    const body = element('tbody', '', undefined, document);
    const detailPane = element('section', 'detail-pane', undefined, document);
    const back = element('button', 'back-button', 'Back to requests', document);
    back.type = 'button';
    const emptyHeading = element('h2', '', 'Select a request', document);
    detailPane.append(back, emptyHeading, element(
      'p', 'detail-empty', 'Choose a request to inspect its consent record.', document,
    ));
    const view = { back, body, detailPane };
    view.controller = createListDetailController({
      root: workspace,
      list: listPane,
      detail: detailPane,
      heading: emptyHeading,
      back,
    });
    const focusTarget = renderEarlyAccessRows(context, view, focusEmail);
    table.append(caption, head, body);
    tableWrap.append(table);
    listPane.append(listTitle, tableWrap);
    workspace.append(listPane, detailPane);
    shell.content.replaceChildren(workspace);
    return focusTarget;
}

async function refreshEarlyAccess(context) {
    context.shell.content.setAttribute('aria-busy', 'true');
    context.shell.count.textContent = '-';
    context.shell.status.textContent = 'Loading early-access requests.';
    showEarlyAccessState(context, 'Loading early-access requests.');
    try {
      const value = await jsonRequest(endpoint, undefined, undefined, context.fetcher);
      if (!Array.isArray(value.items)) throw new Error('invalid response');
      context.items = value.items;
      renderEarlyAccess(context);
      context.shell.count.textContent = formatCount(context.items.length);
      context.shell.refreshed.replaceChildren(timeNode(
        new Date().toISOString(), 'Not yet', context.document,
      ));
      context.shell.status.textContent = context.items.length === 1
        ? 'Loaded 1 early-access request.'
        : `Loaded ${formatCount(context.items.length)} early-access requests.`;
    } catch {
      context.items = [];
      context.shell.count.textContent = '0';
      context.shell.status.textContent = 'Early-access requests could not be loaded.';
      showEarlyAccessState(context, 'Early-access requests could not be loaded. Try again.', true);
    } finally {
      context.shell.content.removeAttribute('aria-busy');
    }
}

export function mount({ document, fetcher, shell, dialogs }) {
  const context = {
    decisionPending: false,
    dialogs,
    document,
    fetcher,
    items: [],
    shell,
  };
  return { refresh: () => refreshEarlyAccess(context) };
}
