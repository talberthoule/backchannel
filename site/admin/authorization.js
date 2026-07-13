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
  return [
    exactKeys(record, ['email', 'account_state', 'include_latest', 'versions', 'updated_at']),
    typeof record?.email === 'string',
    record?.email.length > 0,
    record?.email === email,
    ['active', 'revoked'].includes(record?.account_state),
    typeof record?.include_latest === 'boolean',
    validVersions(record?.versions),
    record?.include_latest || record?.versions?.length > 0,
    validTime(record?.updated_at),
  ].every(Boolean);
}

function validCatalogItem(item) {
  return [
    exactKeys(item, ['version', 'published_at']),
    versionPattern.test(item?.version),
    validTime(item?.published_at),
  ].every(Boolean);
}

function validCatalogItems(items) {
  return Array.isArray(items) && items.every(validCatalogItem);
}

function trustedCatalog(value) {
  const items = value?.items;
  const valid = [
    exactKeys(value, ['items', 'latest_version', 'available']),
    value?.available === true,
    versionPattern.test(value?.latest_version),
    validCatalogItems(items),
  ].every(Boolean);
  if (!valid) return null;
  const versions = items.map(({ version }) => version);
  if (new Set(versions).size !== versions.length) return null;
  return versions.includes(value.latest_version) ? value : null;
}

function mutationItem(value, current, body) {
  const submittedVersions = new Set(body.versions);
  if (!exactKeys(value, ['ok', 'item']) || value.ok !== true
    || !validRecord(value.item, current?.email)
    || value.item.account_state !== current.account_state
    || value.item.include_latest !== body.include_latest
    || value.item.versions.length !== body.versions.length
    || value.item.versions.some((version) => !submittedVersions.has(version))) {
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

function authorizationFields(record, document) {
  const versions = versionsOf(record);
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
  return fields;
}

function settle(read) {
  return read.then(
    (value) => ({ status: 'fulfilled', value }),
    () => ({ status: 'rejected' }),
  );
}

function trustedAuthorizationItems(result) {
  const value = result?.value;
  const valid = [
    result?.status === 'fulfilled',
    exactKeys(value, ['items']),
    Array.isArray(value?.items),
    value?.items?.every((record) => validRecord(record)),
  ].every(Boolean);
  if (!valid) throw new Error('invalid response');
  return value.items;
}

function trustedCatalogResult(result) {
  if (result?.status !== 'fulfilled') return null;
  return trustedCatalog(result.value);
}

function setInputsDisabled(inputs, disabled) {
  for (const input of inputs) input.disabled = disabled;
}

function clearGrantError(error, inputs) {
  error.textContent = '';
  for (const input of inputs) input.removeAttribute('aria-invalid');
}

function showGrantError(error, inputs, focusTarget) {
  error.textContent = 'Select Latest or at least one version.';
  for (const input of inputs) input.setAttribute('aria-invalid', 'true');
  focusTarget.focus();
}

function focusSaveButton(save, requested) {
  if (requested && save && !save.disabled) save.focus();
}

function showAuthorizationState(context, message, retry = false) {
    const region = element('section', 'route-state', undefined, context.document);
    region.append(element('p', '', message, context.document));
    if (retry) {
      const button = element('button', 'secondary-button', 'Retry', context.document);
      button.type = 'button';
      button.addEventListener('click', () => refreshAuthorization(context));
      region.append(button);
    }
    context.shell.content.replaceChildren(region);
}

function unavailableGrantEditor(context) {
      const title = element('h3', '', 'Release grants', context.document);
      const message = context.catalogPending
        ? 'Release catalog is loading. Grant changes are disabled.'
        : 'Release catalog could not be loaded. Current policy is unchanged.';
      const notice = element('p', 'grant-notice', message, context.document);
      const save = element('button', 'primary-button', 'Save grants', context.document);
      save.type = 'button';
      save.disabled = true;
      return { content: [title, notice, save], save };
}

function createVersionInput(context, fieldset, release, selectedVersions) {
      const label = element('label', 'grant-option', undefined, context.document);
      const input = element('input', 'version-input', undefined, context.document);
      input.type = 'checkbox';
      input.setAttribute('name', 'versions');
      input.value = release.version;
      input.checked = selectedVersions.includes(release.version);
      input.setAttribute('aria-describedby', 'grant-error');
      label.append(input, element('span', 'mono', release.version, context.document));
      if (release.version === context.catalog.latest_version) {
        label.append(element('span', 'version-badge', 'Latest', context.document));
      }
      fieldset.append(label);
      return input;
}

async function saveGrants(context, record, form) {
        if (context.mutationPending || record.account_state !== 'active') return;
        const selectedVersions = form.versionInputs
          .filter(({ checked }) => checked)
          .map(({ value }) => value);
        if (!form.latest.checked && selectedVersions.length === 0) {
          showGrantError(form.error, form.inputs, form.latest);
          return;
        }
        clearGrantError(form.error, form.inputs);
        context.mutationPending = true;
        context.refreshGeneration += 1;
        context.shell.content.removeAttribute('aria-busy');
        form.save.disabled = true;
        setInputsDisabled(form.inputs, true);
        context.shell.status.textContent = `Saving release authorization for ${record.email}.`;
        const bodyValue = {
          email: record.email,
          include_latest: form.latest.checked,
          versions: selectedVersions,
        };
        let rerender = false;
        let recoveryDraft = null;
        let status = 'Release authorization update failed. Try again.';
        try {
          const value = await jsonRequest(grantsEndpoint, 'PUT', bodyValue, context.fetcher);
          const current = context.items.find(({ email }) => email === record.email);
          context.items = replaceByEmail(context.items, mutationItem(value, current, bodyValue));
          context.selectedEmail = record.email;
          rerender = true;
          status = 'Release authorization updated.';
        } catch {
          rerender = !form.save.isConnected;
          if (rerender) recoveryDraft = bodyValue;
        } finally {
          context.mutationPending = false;
          if (rerender) renderAuthorization(context, true, recoveryDraft);
          else {
            form.save.disabled = false;
            setInputsDisabled(form.inputs, false);
          }
          context.shell.status.textContent = status;
        }
}

function catalogGrantEditor(context, record, versions, draft) {
      const { document } = context;
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
      const selectedDraft = draft?.email === record.email ? draft : null;
      latest.checked = selectedDraft ? selectedDraft.include_latest : record.include_latest;
      latest.setAttribute('aria-describedby', 'grant-error');
      latestLabel.append(latest, element(
        'span', '', `Latest releases (${context.catalog.latest_version})`, document,
      ));
      fieldset.append(latestLabel);
      const selectedVersions = selectedDraft?.versions || versions;
      const versionInputs = context.catalog.items.map((release) => (
        createVersionInput(context, fieldset, release, selectedVersions)
      ));
      const inputs = [latest, ...versionInputs];
      const clearError = () => clearGrantError(error, inputs);
      for (const input of inputs) input.addEventListener('change', clearError);
      const save = element('button', 'primary-button', 'Save grants', document);
      save.type = 'button';
      save.disabled = context.mutationPending;
      setInputsDisabled(inputs, context.mutationPending);
      const form = { error, inputs, latest, save, versionInputs };
      save.addEventListener('click', () => saveGrants(context, record, form));
      return { content: [title, fieldset, error, save], save };
}

function grantEditor(context, record, versions, draft) {
      if (record.account_state !== 'active') {
        return {
          content: [element(
            'p', 'grant-notice', 'Release grants cannot be changed for this account.', context.document,
          )],
          save: null,
        };
      }
      if (!context.catalog) return unavailableGrantEditor(context);
      return catalogGrantEditor(context, record, versions, draft);
}

function showAuthorizationDetail(context, view, record, trigger, nextFocusSave = false, draft = null) {
      context.selectedEmail = record.email;
      const heading = element('h2', 'mono', record.email, context.document);
      const editor = grantEditor(context, record, versionsOf(record), draft);
      view.detailPane.replaceChildren(
        view.back, heading, authorizationFields(record, context.document), ...editor.content,
      );
      view.controller.showDetail(trigger, heading);
      focusSaveButton(editor.save, nextFocusSave);
      return editor.save || heading;
}

function authorizationRow(context, view, record) {
        const row = element('tr', '', undefined, context.document);
        const select = element('button', 'row-select mono', record.email, context.document);
        select.type = 'button';
        select.addEventListener('click', () => showAuthorizationDetail(context, view, record, select));
        view.triggers.set(record.email, select);
        row.append(
          cell('Email', select, context.document),
          cell('Account', element(
            'span', 'status-text', record.account_state, context.document,
          ), context.document),
          cell('Latest', element(
            'span', '', record.include_latest ? 'Enabled' : 'Disabled', context.document,
          ), context.document),
          cell('Versions', element(
            'span', 'mono', formatCount(versionsOf(record).length), context.document,
          ), context.document),
        );
        return row;
}

function renderAuthorizationRows(context, view) {
      const query = view.search.value.trim().toLowerCase();
      const filtered = context.items.filter(({ email }) => email.toLowerCase().includes(query));
      view.triggers.clear();
      const rows = filtered.map((record) => authorizationRow(context, view, record));
      if (!rows.length) {
        const row = element('tr', 'state-row', undefined, context.document);
        const empty = element('td', '', 'No policies match this email search.', context.document);
        empty.colSpan = 4;
        row.append(empty);
        rows.push(row);
      }
      view.body.replaceChildren(...rows);
      const count = filtered.length;
      view.searchStatus.textContent = count === 1
        ? '1 matching policy.'
        : `${formatCount(count)} matching policies.`;
      context.shell.count.textContent = formatCount(count);
      view.controller.showList();
}

function renderAuthorization(context, focusSave = false, draft = null) {
    const { document, shell } = context;
    if (!context.items.length) {
      context.selectedEmail = null;
      showAuthorizationState(context, 'No release authorization policies yet.');
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
    search.value = context.searchQuery;
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
      renderAuthorizationRows(context, view);
    });
    renderAuthorizationRows(context, view);
    table.append(caption, head, body);
    tableWrap.append(table);
    listPane.append(listTitle, searchGroup, tableWrap);
    workspace.append(listPane, detailPane);
    shell.content.replaceChildren(workspace);

    const selected = context.items.find(({ email }) => email === context.selectedEmail);
    const selectedTrigger = view.triggers.get(context.selectedEmail);
    return selected && selectedTrigger
      ? showAuthorizationDetail(context, view, selected, selectedTrigger, focusSave, draft)
      : null;
}

function showAuthorizationLoaded(context, result) {
    context.items = trustedAuthorizationItems(result);
    context.catalog = null;
    context.catalogPending = true;
    context.selectedEmail = null;
    context.searchQuery = '';
    renderAuthorization(context);
    context.shell.count.textContent = formatCount(context.items.length);
    context.shell.refreshed.replaceChildren(timeNode(
      new Date().toISOString(), 'Not yet', context.document,
    ));
    const loaded = context.items.length === 1
      ? 'Loaded 1 authorization policy.'
      : `Loaded ${formatCount(context.items.length)} authorization policies.`;
    context.shell.status.textContent = `${loaded} Release catalog is loading.`;
    return loaded;
}

function showCatalogLoaded(context, result, loaded) {
    context.catalogPending = false;
    context.catalog = trustedCatalogResult(result);
    renderAuthorization(context);
    context.shell.status.textContent = context.catalog
      ? loaded
      : `${loaded} Release catalog could not be loaded.`;
}

function showAuthorizationError(context) {
    context.items = [];
    context.catalog = null;
    context.catalogPending = false;
    context.selectedEmail = null;
    context.searchQuery = '';
    context.shell.count.textContent = '0';
    context.shell.status.textContent = 'Authorization could not be loaded.';
    showAuthorizationState(context, 'Authorization could not be loaded. Try again.', true);
}

async function refreshAuthorization(context) {
    if (context.mutationPending) return;
    const generation = ++context.refreshGeneration;
    context.shell.content.setAttribute('aria-busy', 'true');
    context.shell.count.textContent = '-';
    context.shell.status.textContent = 'Loading authorization.';
    showAuthorizationState(context, 'Loading authorization.');
    const authorizationResultRead = settle(jsonRequest(
      endpoint, undefined, undefined, context.fetcher,
    ));
    const catalogResultRead = settle(jsonRequest(
      catalogEndpoint, undefined, undefined, context.fetcher,
    ));
    try {
      const authorizationResult = await authorizationResultRead;
      if (generation !== context.refreshGeneration) return;
      const loaded = showAuthorizationLoaded(context, authorizationResult);
      const catalogResult = await catalogResultRead;
      if (generation !== context.refreshGeneration) return;
      showCatalogLoaded(context, catalogResult, loaded);
    } catch {
      if (generation !== context.refreshGeneration) return;
      showAuthorizationError(context);
    } finally {
      if (generation === context.refreshGeneration) context.shell.content.removeAttribute('aria-busy');
    }
}

export function mount({ document, fetcher, shell }) {
  const context = {
    catalog: null,
    catalogPending: false,
    document,
    fetcher,
    items: [],
    mutationPending: false,
    refreshGeneration: 0,
    searchQuery: '',
    selectedEmail: null,
    shell,
  };
  return { refresh: () => refreshAuthorization(context) };
}
