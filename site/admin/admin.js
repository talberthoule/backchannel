import { createDialogController } from './admin-core.js';

const routes = new Map([
  ['/', './users.js'],
  ['/users', './users.js'],
  ['/early-access', './early-access.js'],
  ['/authorization', './authorization.js'],
]);

const modulePath = routes.get(location.pathname);
const title = document.getElementById('route-title');
const description = document.getElementById('route-description');
const refreshButton = document.getElementById('refresh');
const shell = {
  content: document.getElementById('route-content'),
  count: document.getElementById('result-count'),
  refreshed: document.getElementById('last-refreshed'),
  status: document.getElementById('admin-status'),
};
const dialogs = createDialogController({
  document,
  navigator,
  addEventListener: globalThis.addEventListener.bind(globalThis),
  URL,
  Blob,
});

for (const link of document.querySelectorAll('.route-nav a')) {
  const active = link.getAttribute('href') === location.pathname
    || (location.pathname === '/' && link.getAttribute('href') === '/users');
  if (active) link.setAttribute('aria-current', 'page');
}

async function start() {
  if (!modulePath) {
    shell.status.textContent = 'This admin route is not available.';
    shell.content.removeAttribute('aria-busy');
    return;
  }
  try {
    const route = await import(modulePath);
    title.textContent = route.meta.title;
    description.textContent = route.meta.description;
    document.title = `${route.meta.title} | Backchannel admin`;
    const mounted = route.mount({ document, fetcher: fetch, shell, dialogs });
    refreshButton.addEventListener('click', async () => {
      refreshButton.disabled = true;
      await mounted.refresh();
      refreshButton.disabled = false;
    });
    refreshButton.disabled = true;
    await mounted.refresh();
    refreshButton.disabled = false;
  } catch {
    refreshButton.disabled = true;
    shell.status.textContent = 'This admin route could not be loaded.';
    shell.content.replaceChildren(document.createTextNode('This admin route could not be loaded.'));
    shell.content.removeAttribute('aria-busy');
  }
}

start();
