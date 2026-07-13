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

export function mount({ document, fetcher, shell, dialogs }) {
  let items = [];
  let decisionPending = false;

  async function decide(record, action, button) {
    if (decisionPending) return;
    const verb = action === 'approve' ? 'Approve' : 'Reject';
    const confirmed = await dialogs.confirm({
      title: `${verb} early-access request`,
      description: `${verb} the request from ${record.email}?`,
      label: verb,
      returnFocus: button,
    });
    if (!confirmed) return;

    decisionPending = true;
    const actionButtons = button.parentNode.querySelectorAll('button');
    for (const actionButton of actionButtons) actionButton.disabled = true;
    shell.status.textContent = `${action === 'approve' ? 'Approving' : 'Rejecting'} ${record.email}.`;
    try {
      const value = await jsonRequest(
        `${endpoint}/${action}`, 'POST', { email: record.email }, fetcher,
      );
      if (value.ok !== true) throw new Error('invalid response');
      if (action === 'reject') {
        if (!value.item || value.item.email !== record.email
          || value.item.release_decision !== 'rejected') throw new Error('invalid response');
        items = replaceByEmail(items, value.item);
        const returnFocus = render(record.email);
        shell.status.textContent = `Rejected the request from ${record.email}.`;
        returnFocus?.focus();
        return;
      }

      const credential = value.credential;
      if (!credential || credential.email !== record.email
        || typeof credential.password !== 'string'
        || !credential.password.length
        || typeof credential.password_expires_at !== 'string'
        || !credential.password_expires_at.trim()
        || !Number.isFinite(Date.parse(credential.password_expires_at))) {
        throw new Error('invalid response');
      }
      const reviewedAt = value.item?.release_reviewed_at;
      items = replaceByEmail(items, {
        ...record,
        status: 'active',
        release_decision: 'approved',
        ...(typeof reviewedAt === 'string' ? { release_reviewed_at: reviewedAt } : {}),
      });
      const returnFocus = render(record.email);
      shell.status.textContent = `Approved the request from ${record.email}.`;
      dialogs.showCredential({
        text: [
          'Backchannel desktop access',
          `Account: ${credential.email}`,
          `Temporary password: ${credential.password}`,
          'Sign in: https://downloads.backchannel.page/',
          `Password expires: ${credential.password_expires_at}`,
        ].join('\n'),
        email: credential.email,
        returnFocus,
      });
    } catch {
      shell.status.textContent = `${verb} failed. Try again.`;
    } finally {
      decisionPending = false;
      for (const actionButton of actionButtons) actionButton.disabled = false;
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

  function render(focusEmail) {
    if (!items.length) {
      state('No early-access requests yet.');
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
    const controller = createListDetailController({
      root: workspace,
      list: listPane,
      detail: detailPane,
      heading: emptyHeading,
      back,
    });

    function showDetail(record, trigger) {
      const heading = element('h2', 'mono', record.email || 'Unknown email', document);
      const fields = element('dl', 'detail-fields', undefined, document);
      fields.append(
        detailField('Interest status', element('span', '', record.status || 'Unknown', document), document),
        detailField('Source', element('span', '', record.source || 'Unknown', document), document),
        detailField('Requested', timeNode(record.created_at, 'Not recorded', document), document),
        detailField('Consent', timeNode(record.consent_at, 'Not recorded', document), document),
        detailField('Consent version', element(
          'span', 'mono', record.consent_version || 'Unknown', document,
        ), document),
        detailField('Decision', element(
          'span', '', record.release_decision || 'pending', document,
        ), document),
      );
      const content = [back, heading, fields];
      if (record.release_decision === 'pending') {
        const actionTitle = element('h3', '', 'Decision', document);
        const actions = element('div', 'dialog-actions', undefined, document);
        const approve = element('button', 'primary-button', 'Approve', document);
        approve.type = 'button';
        approve.addEventListener('click', () => decide(record, 'approve', approve));
        const reject = element('button', 'secondary-button', 'Reject', document);
        reject.type = 'button';
        reject.addEventListener('click', () => decide(record, 'reject', reject));
        actions.append(approve, reject);
        content.push(actionTitle, actions);
      }
      detailPane.replaceChildren(...content);
      controller.showDetail(trigger, heading);
    }

    let focusTarget = null;
    for (const record of items) {
      const row = element('tr', '', undefined, document);
      const select = element('button', 'row-select mono', record.email || 'Unknown email', document);
      select.type = 'button';
      select.addEventListener('click', () => showDetail(record, select));
      if (record.email === focusEmail) focusTarget = select;
      row.append(
        cell('Email', select, document),
        cell('Status', element('span', 'status-text', record.status || 'Unknown', document), document),
        cell('Source', element('span', '', record.source || 'Unknown', document), document),
        cell('Requested', timeNode(record.created_at, 'Not recorded', document), document),
        cell('Decision', element(
          'span', 'status-text', record.release_decision || 'pending', document,
        ), document),
      );
      body.append(row);
    }
    table.append(caption, head, body);
    tableWrap.append(table);
    listPane.append(listTitle, tableWrap);
    workspace.append(listPane, detailPane);
    shell.content.replaceChildren(workspace);
    return focusTarget;
  }

  async function refresh() {
    shell.content.setAttribute('aria-busy', 'true');
    shell.count.textContent = '-';
    shell.status.textContent = 'Loading early-access requests.';
    state('Loading early-access requests.');
    try {
      const value = await jsonRequest(endpoint, undefined, undefined, fetcher);
      if (!Array.isArray(value.items)) throw new Error('invalid response');
      items = value.items;
      render();
      shell.count.textContent = formatCount(items.length);
      shell.refreshed.replaceChildren(timeNode(new Date().toISOString(), 'Not yet', document));
      shell.status.textContent = items.length === 1
        ? 'Loaded 1 early-access request.'
        : `Loaded ${formatCount(items.length)} early-access requests.`;
    } catch {
      items = [];
      shell.count.textContent = '0';
      shell.status.textContent = 'Early-access requests could not be loaded.';
      state('Early-access requests could not be loaded. Try again.', true);
    } finally {
      shell.content.removeAttribute('aria-busy');
    }
  }

  return { refresh };
}
