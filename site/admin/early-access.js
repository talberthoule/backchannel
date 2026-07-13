import {
  createListDetailController,
  element,
  formatCount,
  jsonRequest,
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

  function render() {
    if (!items.length) {
      state('No early-access requests yet.');
      return;
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
      detailPane.replaceChildren(back, heading, fields);
      controller.showDetail(trigger, heading);
    }

    for (const record of items) {
      const row = element('tr', '', undefined, document);
      const select = element('button', 'row-select mono', record.email || 'Unknown email', document);
      select.type = 'button';
      select.addEventListener('click', () => showDetail(record, select));
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
