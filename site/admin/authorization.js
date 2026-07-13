import {
  createListDetailController,
  element,
  formatCount,
  jsonRequest,
  timeNode,
} from './admin-core.js';

export const meta = {
  title: 'Authorization',
  description: 'Latest and historical release access policy.',
};

const endpoint = '/api/admin/authorization';

function versionsOf(record) {
  return Array.isArray(record.versions) ? record.versions : [];
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
      state('No release authorization policies yet.');
      return;
    }
    const workspace = element('div', 'list-detail', undefined, document);
    const listPane = element('section', 'list-pane', undefined, document);
    const listTitle = element('h2', '', 'Authorization directory', document);
    const searchGroup = element('div', 'search-group', undefined, document);
    const searchLabel = element('label', '', 'Search by email', document);
    searchLabel.setAttribute('for', 'authorization-search');
    const search = element('input', 'search-input', undefined, document);
    search.type = 'search';
    search.setAttribute('id', 'authorization-search');
    search.setAttribute('aria-label', 'Search by email');
    const searchStatus = element('p', 'search-status', '', document);
    searchStatus.setAttribute('role', 'status');
    searchStatus.setAttribute('aria-live', 'polite');
    searchGroup.append(searchLabel, search, searchStatus);
    const tableWrap = element('div', 'table-wrap', undefined, document);
    const table = element('table', 'data-table', undefined, document);
    const caption = element('caption', '', 'Release authorization directory', document);
    const head = element('thead', '', undefined, document);
    const headRow = element('tr', '', undefined, document);
    for (const label of ['Email', 'Account', 'Latest', 'Versions']) {
      const heading = element('th', '', label, document);
      heading.setAttribute('scope', 'col');
      headRow.append(heading);
    }
    head.append(headRow);
    const body = element('tbody', '', undefined, document);
    const detailPane = element('section', 'detail-pane', undefined, document);
    const back = element('button', 'back-button', 'Back to authorization', document);
    back.type = 'button';
    const emptyHeading = element('h2', '', 'Select a user', document);
    detailPane.append(back, emptyHeading, element(
      'p', 'detail-empty', 'Choose a user to inspect release authorization.', document,
    ));
    const controller = createListDetailController({
      root: workspace,
      list: listPane,
      detail: detailPane,
      heading: emptyHeading,
      back,
    });

    function showDetail(record, trigger) {
      const versions = versionsOf(record);
      const heading = element('h2', 'mono', record.email || 'Unknown email', document);
      const fields = element('dl', 'detail-fields', undefined, document);
      fields.append(
        detailField('Account state', element(
          'span', 'status-text', record.account_state || 'Unknown', document,
        ), document),
        detailField('Latest releases', element(
          'span', '', record.include_latest ? 'Enabled' : 'Disabled', document,
        ), document),
        detailField('Historical versions', element(
          'span', 'mono', versions.join(', ') || 'None', document,
        ), document),
        detailField('Policy updated', timeNode(record.updated_at, 'Not recorded', document), document),
      );
      detailPane.replaceChildren(back, heading, fields);
      controller.showDetail(trigger, heading);
    }

    function renderRows() {
      const query = search.value.trim().toLowerCase();
      const filtered = items.filter(({ email }) => (
        typeof email === 'string' && email.toLowerCase().includes(query)
      ));
      const rows = filtered.map((record) => {
        const row = element('tr', '', undefined, document);
        const select = element('button', 'row-select mono', record.email, document);
        select.type = 'button';
        select.addEventListener('click', () => showDetail(record, select));
        row.append(
          cell('Email', select, document),
          cell('Account', element(
            'span', 'status-text', record.account_state || 'Unknown', document,
          ), document),
          cell('Latest', element(
            'span', '', record.include_latest ? 'Enabled' : 'Disabled', document,
          ), document),
          cell('Versions', element(
            'span', 'mono', formatCount(versionsOf(record).length), document,
          ), document),
        );
        return row;
      });
      if (!rows.length) {
        const row = element('tr', 'state-row', undefined, document);
        const empty = element('td', '', 'No policies match this email search.', document);
        empty.colSpan = 4;
        row.append(empty);
        rows.push(row);
      }
      body.replaceChildren(...rows);
      const count = filtered.length;
      searchStatus.textContent = count === 1 ? '1 matching policy.' : `${formatCount(count)} matching policies.`;
      shell.count.textContent = formatCount(count);
      controller.showList();
    }

    search.addEventListener('input', renderRows);
    renderRows();
    table.append(caption, head, body);
    tableWrap.append(table);
    listPane.append(listTitle, searchGroup, tableWrap);
    workspace.append(listPane, detailPane);
    shell.content.replaceChildren(workspace);
  }

  async function refresh() {
    shell.content.setAttribute('aria-busy', 'true');
    shell.count.textContent = '-';
    shell.status.textContent = 'Loading authorization.';
    state('Loading authorization.');
    try {
      const value = await jsonRequest(endpoint, undefined, undefined, fetcher);
      if (!Array.isArray(value.items)) throw new Error('invalid response');
      items = value.items;
      render();
      shell.count.textContent = formatCount(items.length);
      shell.refreshed.replaceChildren(timeNode(new Date().toISOString(), 'Not yet', document));
      shell.status.textContent = items.length === 1
        ? 'Loaded 1 authorization policy.'
        : `Loaded ${formatCount(items.length)} authorization policies.`;
    } catch {
      items = [];
      shell.count.textContent = '0';
      shell.status.textContent = 'Authorization could not be loaded.';
      state('Authorization could not be loaded. Try again.', true);
    } finally {
      shell.content.removeAttribute('aria-busy');
    }
  }

  return { refresh };
}
