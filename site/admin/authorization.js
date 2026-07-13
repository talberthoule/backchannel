import {
  createListDetailController,
  element,
  formatCount,
  jsonRequest,
  replaceByEmail,
  timeNode,
} from './admin-core.js';

export const meta = {
  title: 'Authorization',
  description: 'Latest and historical release access policy.',
};

const endpoint = '/api/admin/authorization';
const catalogEndpoint = '/api/admin/releases';
const grantsEndpoint = '/api/admin/authorization/grants';
const versionPattern = /^(?=.{2,32}$)v(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$/;

function exactKeys(value, keys) {
  return value && typeof value === 'object' && !Array.isArray(value)
    && Object.keys(value).sort().join('\0') === [...keys].sort().join('\0');
}

function validTime(value) {
  return typeof value === 'string' && value.trim() && Number.isFinite(Date.parse(value));
}

function validVersions(versions) {
  return Array.isArray(versions) && versions.length <= 100
    && versions.every((version) => typeof version === 'string' && versionPattern.test(version))
    && new Set(versions).size === versions.length;
}

function validRecord(record, email = record?.email) {
  return exactKeys(record, ['email', 'account_state', 'include_latest', 'versions', 'updated_at'])
    && typeof record.email === 'string'
    && record.email.length > 0
    && record.email === email
    && ['active', 'revoked'].includes(record.account_state)
    && typeof record.include_latest === 'boolean'
    && validVersions(record.versions)
    && (record.include_latest || record.versions.length > 0)
    && validTime(record.updated_at);
}

function trustedCatalog(value) {
  if (!exactKeys(value, ['items', 'latest_version', 'available']) || value.available !== true
    || !versionPattern.test(value.latest_version) || !Array.isArray(value.items)) return null;
  const versions = new Set();
  for (const item of value.items) {
    if (!exactKeys(item, ['version', 'published_at']) || !versionPattern.test(item.version)
      || !validTime(item.published_at) || versions.has(item.version)) return null;
    versions.add(item.version);
  }
  return versions.has(value.latest_version) ? value : null;
}

function mutationItem(value, current, body) {
  if (!exactKeys(value, ['ok', 'item']) || value.ok !== true
    || !validRecord(value.item, current?.email)
    || value.item.account_state !== current.account_state
    || value.item.include_latest !== body.include_latest
    || value.item.versions.length !== body.versions.length
    || value.item.versions.some((version, index) => version !== body.versions[index])) {
    throw new Error('invalid response');
  }
  return value.item;
}

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
  let catalog = null;
  let selectedEmail = null;
  let searchQuery = '';
  let mutationPending = false;
  let refreshGeneration = 0;

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

  function render(focusSave = false) {
    if (!items.length) {
      selectedEmail = null;
      state('No release authorization policies yet.');
      return null;
    }
    const workspace = element('div', 'list-detail', undefined, document);
    const listPane = element('section', 'list-pane', undefined, document);
    const listTitle = element('h2', '', 'Authorization directory', document);
    const searchGroup = element('div', 'search-group', undefined, document);
    const searchLabel = element('label', '', 'Search by email', document);
    searchLabel.setAttribute('for', 'authorization-search');
    const search = element('input', 'search-input', undefined, document);
    search.type = 'search';
    search.value = searchQuery;
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

    function showDetail(record, trigger, nextFocusSave = false) {
      selectedEmail = record.email;
      const versions = versionsOf(record);
      const heading = element('h2', 'mono', record.email, document);
      const fields = element('dl', 'detail-fields', undefined, document);
      fields.append(
        detailField('Account state', element('span', 'status-text', record.account_state, document), document),
        detailField('Latest releases', element(
          'span', '', record.include_latest ? 'Enabled' : 'Disabled', document,
        ), document),
        detailField('Historical versions', element(
          'span', 'mono', versions.join(', ') || 'None', document,
        ), document),
        detailField('Policy updated', timeNode(record.updated_at, 'Not recorded', document), document),
      );
      const content = [back, heading, fields];
      let save = null;

      if (record.account_state !== 'active') {
        content.push(element(
          'p', 'grant-notice', 'Release grants cannot be changed for this account.', document,
        ));
      } else if (!catalog) {
        const title = element('h3', '', 'Release grants', document);
        const notice = element(
          'p', 'grant-notice', 'Release catalog could not be loaded. Current policy is unchanged.', document,
        );
        save = element('button', 'primary-button', 'Save grants', document);
        save.type = 'button';
        save.disabled = true;
        content.push(title, notice, save);
      } else {
        const title = element('h3', '', 'Release grants', document);
        const fieldset = element('fieldset', 'grant-options', undefined, document);
        fieldset.append(element('legend', '', 'Complete release access', document));
        const error = element('p', 'grant-error', '', document);
        error.setAttribute('id', 'grant-error');
        error.setAttribute('role', 'status');
        error.setAttribute('aria-live', 'polite');
        const latestLabel = element('label', 'grant-option', undefined, document);
        const latest = element('input', '', undefined, document);
        latest.type = 'checkbox';
        latest.setAttribute('name', 'include_latest');
        latest.checked = record.include_latest;
        latest.setAttribute('aria-describedby', 'grant-error');
        latestLabel.append(latest, element(
          'span', '', `Latest releases (${catalog.latest_version})`, document,
        ));
        fieldset.append(latestLabel);
        const versionInputs = catalog.items.map((release) => {
          const label = element('label', 'grant-option', undefined, document);
          const input = element('input', 'version-input', undefined, document);
          input.type = 'checkbox';
          input.setAttribute('name', 'versions');
          input.value = release.version;
          input.checked = versions.includes(release.version);
          input.setAttribute('aria-describedby', 'grant-error');
          label.append(input, element('span', 'mono', release.version, document));
          if (release.version === catalog.latest_version) {
            label.append(element('span', 'version-badge', 'Latest', document));
          }
          fieldset.append(label);
          return input;
        });
        const inputs = [latest, ...versionInputs];
        const clearError = () => {
          error.textContent = '';
          for (const input of inputs) input.removeAttribute('aria-invalid');
        };
        for (const input of inputs) input.addEventListener('change', clearError);
        save = element('button', 'primary-button', 'Save grants', document);
        save.type = 'button';
        save.disabled = mutationPending;
        for (const input of inputs) input.disabled = mutationPending;
        save.addEventListener('click', async () => {
          if (mutationPending || record.account_state !== 'active') return;
          const selectedVersions = versionInputs
            .filter(({ checked }) => checked)
            .map(({ value }) => value);
          if (!latest.checked && !selectedVersions.length) {
            error.textContent = 'Select Latest or at least one version.';
            for (const input of inputs) input.setAttribute('aria-invalid', 'true');
            latest.focus();
            return;
          }
          clearError();
          mutationPending = true;
          refreshGeneration += 1;
          shell.content.removeAttribute('aria-busy');
          save.disabled = true;
          for (const input of inputs) input.disabled = true;
          shell.status.textContent = `Saving release authorization for ${record.email}.`;
          const bodyValue = {
            email: record.email,
            include_latest: latest.checked,
            versions: selectedVersions,
          };
          let rerender = false;
          let status = 'Release authorization update failed. Try again.';
          try {
            const value = await jsonRequest(grantsEndpoint, 'PUT', bodyValue, fetcher);
            const current = items.find(({ email }) => email === record.email);
            items = replaceByEmail(items, mutationItem(value, current, bodyValue));
            selectedEmail = record.email;
            rerender = true;
            status = 'Release authorization updated.';
          } catch {
            rerender = !save.isConnected;
          } finally {
            mutationPending = false;
            if (rerender) render(true);
            else {
              save.disabled = false;
              for (const input of inputs) input.disabled = false;
            }
            shell.status.textContent = status;
          }
        });
        content.push(title, fieldset, error, save);
      }

      detailPane.replaceChildren(...content);
      controller.showDetail(trigger, heading);
      if (nextFocusSave && save && !save.disabled) save.focus();
      return save || heading;
    }

    const triggers = new Map();
    function renderRows() {
      const query = search.value.trim().toLowerCase();
      const filtered = items.filter(({ email }) => email.toLowerCase().includes(query));
      triggers.clear();
      const rows = filtered.map((record) => {
        const row = element('tr', '', undefined, document);
        const select = element('button', 'row-select mono', record.email, document);
        select.type = 'button';
        select.addEventListener('click', () => showDetail(record, select));
        triggers.set(record.email, select);
        row.append(
          cell('Email', select, document),
          cell('Account', element('span', 'status-text', record.account_state, document), document),
          cell('Latest', element(
            'span', '', record.include_latest ? 'Enabled' : 'Disabled', document,
          ), document),
          cell('Versions', element('span', 'mono', formatCount(versionsOf(record).length), document), document),
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
    return selected && selectedTrigger ? showDetail(selected, selectedTrigger, focusSave) : null;
  }

  async function refresh() {
    if (mutationPending) return;
    const generation = ++refreshGeneration;
    shell.content.setAttribute('aria-busy', 'true');
    shell.count.textContent = '-';
    shell.status.textContent = 'Loading authorization.';
    state('Loading authorization.');
    const authorizationRead = jsonRequest(endpoint, undefined, undefined, fetcher);
    const catalogRead = jsonRequest(catalogEndpoint, undefined, undefined, fetcher);
    const [authorizationResult, catalogResult] = await Promise.allSettled([
      authorizationRead,
      catalogRead,
    ]);
    try {
      if (generation !== refreshGeneration) return;
      if (authorizationResult.status !== 'fulfilled'
        || !exactKeys(authorizationResult.value, ['items'])
        || !Array.isArray(authorizationResult.value.items)
        || !authorizationResult.value.items.every((record) => validRecord(record))) {
        throw new Error('invalid response');
      }
      items = authorizationResult.value.items;
      catalog = catalogResult.status === 'fulfilled' ? trustedCatalog(catalogResult.value) : null;
      selectedEmail = null;
      searchQuery = '';
      render();
      shell.count.textContent = formatCount(items.length);
      shell.refreshed.replaceChildren(timeNode(new Date().toISOString(), 'Not yet', document));
      const loaded = items.length === 1
        ? 'Loaded 1 authorization policy.'
        : `Loaded ${formatCount(items.length)} authorization policies.`;
      shell.status.textContent = catalog ? loaded : `${loaded} Release catalog could not be loaded.`;
    } catch {
      if (generation !== refreshGeneration) return;
      items = [];
      catalog = null;
      selectedEmail = null;
      searchQuery = '';
      shell.count.textContent = '0';
      shell.status.textContent = 'Authorization could not be loaded.';
      state('Authorization could not be loaded. Try again.', true);
    } finally {
      if (generation === refreshGeneration) shell.content.removeAttribute('aria-busy');
    }
  }

  return { refresh };
}
