import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const read = (path) => existsSync(new URL(path, import.meta.url))
  ? readFileSync(new URL(path, import.meta.url), 'utf8')
  : '';
const html = read('../site/downloads/index.html');
const publicHtml = read('../site/index.html');
const script = read('../site/downloads/downloads.js');
const css = read('../site/downloads/downloads.css');
const packageJson = JSON.parse(read('./package.json'));
const wrangler = JSON.parse(read('./wrangler.jsonc'));

function panel(id) {
  return html.match(new RegExp(`<section[^>]+id="${id}"[\\s\\S]*?<\\/section>`))?.[0] || '';
}

function fetchOptions(path) {
  return script.match(new RegExp(`fetch\\(['"]\\/api\\/download\\/${path}['"],\\s*\\{([\\s\\S]*?)\\n\\s*\\}\\)`))?.[1] || '';
}

test('recipient page uses only local assets and the exact public Turnstile widget', () => {
  const publicSiteKey = publicHtml.match(/class="cf-turnstile"[^>]*data-sitekey="([^"]+)"/)?.[1];
  const recipientWidget = html.match(/class="cf-turnstile"[^>]*>/)?.[0] || '';
  const recipientSiteKey = recipientWidget.match(/data-sitekey="([^"]+)"/)?.[1];
  const assetRefs = [...html.matchAll(/<(?:link|script)\b[^>]*(?:href|src)="([^"]+)"[^>]*>/g)]
    .map((match) => match[1]);
  const remoteAssets = [...`${html}\n${script}\n${css}`.matchAll(/https?:\/\/[^\s"'<>]+/g)]
    .map((match) => match[0]);

  assert.ok(publicSiteKey);
  assert.equal(recipientSiteKey, publicSiteKey);
  assert.match(recipientWidget, /data-action="download_login"/);
  assert.match(recipientWidget, /data-size="compact"/);
  assert.match(recipientWidget, /data-error-callback="onTurnstileError"/);
  assert.match(html, /href="\/downloads\.css"/);
  assert.match(html, /src="\/downloads\.js"\s+defer/);
  assert.deepEqual(assetRefs, [
    '/downloads.css',
    '/downloads.js',
    'https://challenges.cloudflare.com/turnstile/v0/api.js',
  ]);
  assert.deepEqual(remoteAssets, ['https://challenges.cloudflare.com/turnstile/v0/api.js']);
  assert.match(html, /src="https:\/\/challenges\.cloudflare\.com\/turnstile\/v0\/api\.js"\s+defer/);
  assert.doesNotMatch(html, /<script(?![^>]*\bsrc=)[^>]*>|<style\b|\sstyle=|\son\w+=/i);
});

test('recipient page exposes labelled controls and accessible feedback in every panel', () => {
  for (const id of ['email', 'password', 'new-password']) {
    assert.match(html, new RegExp(`<label[^>]+for="${id}"`));
    assert.match(html, new RegExp(`<input[^>]+id="${id}"`));
  }
  assert.match(html, /id="new-password"[^>]*minlength="14"[^>]*maxlength="128"/);
  for (const [panelId, alertId] of [
    ['login-panel', 'login-alert'],
    ['change-panel', 'change-alert'],
    ['releases-panel', 'releases-alert'],
  ]) {
    const source = panel(panelId);
    assert.match(source, /hidden/);
    assert.match(source, /aria-hidden="true"/);
    assert.match(source, new RegExp(`id="${alertId}"[^>]*role="alert"[^>]*aria-live="assertive"`));
  }
  assert.match(script, /setAlert\(['"]#login-alert['"]/);
  assert.match(script, /setAlert\(['"]#change-alert['"]/);
  assert.match(script, /['"]#change-alert['"]\s*:\s*['"]#releases-alert['"]/);
  assert.match(script, /setAlert\(alertId,/);
  assert.match(html, /releases will load/i);
  assert.equal((html.match(/role="alert"/g) || []).length, 3);
  assert.match(html, /type="submit"[^>]*>\s*Sign in/i);
  assert.match(html, /type="submit"[^>]*>\s*Change password/i);
  assert.ok((html.match(/>\s*Log out\s*</gi) || []).length >= 2);
});

test('recipient requests have exact methods, bodies, and same-origin credentials', () => {
  const session = script.match(/fetch\(['"]\/api\/download\/session['"],\s*\{([^}]*)\}\)/)?.[1] || '';
  const login = fetchOptions('login');
  const passwordChange = fetchOptions('password');
  const logout = fetchOptions('logout');

  assert.match(session, /credentials:\s*['"]same-origin['"]/);
  assert.doesNotMatch(session, /method:|body:/);
  for (const options of [login, passwordChange, logout]) {
    assert.match(options, /method:\s*['"]POST['"]/);
    assert.match(options, /credentials:\s*['"]same-origin['"]/);
    assert.match(options, /headers:\s*\{\s*['"]content-type['"]:\s*['"]application\/json['"]\s*\}/);
  }
  assert.match(login, /body:\s*JSON\.stringify\(\{\s*email:\s*email\.value,\s*password:\s*password\.value,\s*turnstile_token:\s*token\s*\}\)/s);
  assert.match(passwordChange, /body:\s*JSON\.stringify\(\{\s*password\s*\}\)/);
  assert.match(logout, /body:\s*JSON\.stringify\(\{\s*\}\)/);
});

test('recipient script resets Turnstile in login finally and uses safe browser APIs', () => {
  const loginHandler = script.match(/loginForm\.addEventListener\(['"]submit['"][\s\S]*?^\}\);/m)?.[0] || '';
  assert.match(script, /turnstile\??\.getResponse/);
  assert.match(loginHandler, /finally\s*\{[\s\S]*turnstileToken\s*=\s*['"][\s\S]*turnstile\??\.reset\(\)/);
  assert.ok(loginHandler.indexOf('turnstile?.reset()') > loginHandler.indexOf("fetch('/api/download/login'"));
  assert.equal((script.match(/turnstile\??\.reset\(\)/g) || []).length, 1);
  assert.match(script, /\.disabled\s*=\s*true/);
  assert.match(script, /\.disabled\s*=\s*false/);
  assert.match(script, /\.focus\(\)/);
  assert.match(script, /password\.value\s*=\s*['"]/);
  assert.doesNotMatch(script, /innerHTML|outerHTML|insertAdjacentHTML/);
  assert.doesNotMatch(script, /localStorage|sessionStorage|document\.cookie|console\./);
});

test('recipient UI renders entitled releases and validates optional deep links with safe DOM APIs', () => {
  assert.match(script, /releasesList\.id\s*=\s*['"]releases-list['"]/);
  assert.match(script, /releasesList\.setAttribute\(['"]aria-live['"],\s*['"]polite['"]\)/);
  assert.match(script, /releasesIntro\.setAttribute\(['"]role['"],\s*['"]status['"]\)/);
  assert.match(script, /releasesIntro\.setAttribute\(['"]aria-live['"],\s*['"]polite['"]\)/);
  assert.match(script, /fetch\(['"]\/api\/download\/releases['"]/);
  assert.match(script, /createElement\(/);
  assert.match(script, /\.textContent\s*=/);
  assert.match(script, /encodeURIComponent\(release\.version\)/);
  assert.match(script, /encodeURIComponent\(asset\.id\)/);
  assert.match(script, /URLSearchParams\(location\.search\)/);
  assert.match(script, /\^v\(\?:0\|\[1-9\]\[0-9\]\*\)\\\./);
  assert.match(script, /Loading releases/i);
  assert.match(script, /No releases are available/i);
  assert.match(script, /scrollIntoView/);
  assert.match(script, /section\.className\s*=\s*['"]release['"]/);
  assert.match(script, /checksum\.className\s*=\s*['"]checksum['"]/);
  assert.match(css, /\.checksum\s*\{[^}]*overflow-wrap:\s*anywhere/);
  assert.match(css, /\.release:focus-visible/);
  assert.doesNotMatch(script, /innerHTML|outerHTML|insertAdjacentHTML/);
});

test('recipient release rendering executes with safe fields, encoded links, and exact deep-link focus', async () => {
  class Element {
    constructor(tagName, id = '') {
      this.tagName = tagName;
      this.id = id;
      this.children = [];
      this.attributes = new Map();
      this.hidden = true;
      this.textContent = '';
      this.value = '';
    }

    addEventListener() {}
    append(...children) { this.children.push(...children); }
    replaceChildren(...children) { this.children = [...children]; }
    setAttribute(name, value) { this.attributes.set(name, String(value)); }
    focus() { this.focused = true; }
    scrollIntoView() { this.scrolled = true; }
    insertBefore(child, reference) {
      const index = this.children.indexOf(reference);
      this.children.splice(index < 0 ? this.children.length : index, 0, child);
    }
    querySelector(selector) {
      return selector === '.intro' ? this.children.find(({ className }) => className === 'intro') : null;
    }
  }

  const page = new Element('main');
  const loginPanel = new Element('section', 'login-panel');
  const changePanel = new Element('section', 'change-panel');
  const releasesPanel = new Element('section', 'releases-panel');
  const releasesIntro = new Element('p');
  releasesIntro.className = 'intro';
  const releasesAlert = new Element('p', 'releases-alert');
  releasesPanel.children.push(releasesIntro, releasesAlert);
  const elements = new Map([
    ['.page', page],
    ['#login-panel', loginPanel],
    ['#change-panel', changePanel],
    ['#releases-panel', releasesPanel],
    ['#login-form', new Element('form')],
    ['#change-form', new Element('form')],
    ['#email', new Element('input')],
    ['#password', new Element('input')],
    ['#new-password', new Element('input')],
    ['#login-submit', new Element('button')],
    ['#change-submit', new Element('button')],
    ['#releases-heading', new Element('h1')],
    ['#login-alert', new Element('p')],
    ['#change-alert', new Element('p')],
    ['#releases-alert', releasesAlert],
  ]);
  const documentStub = {
    querySelector: (selector) => elements.get(selector) || null,
    querySelectorAll: (selector) => selector === '.panel'
      ? [loginPanel, changePanel, releasesPanel]
      : [],
    createElement: (tagName) => new Element(tagName),
  };
  const payload = {
    latest_version: 'v1.2.3',
    items: [{
      version: 'v1.2.3',
      published_at: '2026-07-12T18:00:00Z',
      assets: [{
        id: 'windows/x64',
        platform: 'Windows x64',
        filename: 'Backchannel-windows-x64.zip',
        size: 2048,
        sha256: 'a'.repeat(64),
      }],
    }],
  };
  const fetchCalls = [];
  const saved = {
    document: globalThis.document,
    location: globalThis.location,
    fetch: globalThis.fetch,
    verified: globalThis.onTurnstileVerified,
    error: globalThis.onTurnstileError,
  };

  try {
    globalThis.document = documentStub;
    globalThis.location = { search: '?version=v1.2.3' };
    globalThis.fetch = async (url) => {
      fetchCalls.push(url);
      const body = url.endsWith('/session')
        ? { authenticated: true, must_change_password: false }
        : payload;
      return new Response(JSON.stringify(body), {
        headers: { 'content-type': 'application/json' },
      });
    };
    await import(`${new URL('../site/downloads/downloads.js', import.meta.url).href}?dom-stub=1`);
    for (let i = 0; i < 4; i += 1) {
      await new Promise((resolve) => setImmediate(resolve));
    }

    assert.deepEqual(fetchCalls, ['/api/download/session', '/api/download/releases']);
    const list = releasesPanel.children.find(({ id }) => id === 'releases-list');
    const release = list.children[0];
    const article = release.children.find(({ tagName }) => tagName === 'article');
    const link = article.children.find(({ tagName }) => tagName === 'a');
    assert.equal(release.children[0].textContent, 'v1.2.3 (Latest)');
    assert.equal(article.children[0].textContent, 'Windows x64');
    assert.equal(article.children[1].textContent, 'Backchannel-windows-x64.zip - 2.0 KiB');
    assert.equal(article.children[2].textContent, `SHA-256: ${'a'.repeat(64)}`);
    assert.equal(link.href, '/api/download/releases/v1.2.3/windows%2Fx64');
    assert.equal(release.focused, true);
    assert.equal(release.scrolled, true);
  } finally {
    globalThis.document = saved.document;
    globalThis.location = saved.location;
    globalThis.fetch = saved.fetch;
    globalThis.onTurnstileVerified = saved.verified;
    globalThis.onTurnstileError = saved.error;
  }
});

test('logout buttons stay disabled during the logout request and ignore duplicate clicks', async () => {
  const start = script.indexOf("for (const button of document.querySelectorAll('.logout')) {");
  const end = script.indexOf('loadSession();', start);
  assert.ok(start >= 0 && end > start);
  const logoutLoop = script.slice(start, end);
  const state = { alert: '', fetchCalls: [], focused: '', shown: '' };
  const logoutButton = {
    disabled: false,
    handlers: new Map(),
    addEventListener(name, handler) { this.handlers.set(name, handler); },
    closest() { return null; },
    focus() { state.focused = 'logout'; },
  };
  let resolveLogout;
  const pendingLogout = new Promise((resolve) => { resolveLogout = resolve; });
  const context = {
    document: {
      querySelector: (selector) => ({ id: selector.slice(1) }),
      querySelectorAll: (selector) => (selector === '.logout' ? [logoutButton] : []),
    },
    email: { focus() { state.focused = 'email'; } },
    password: { value: 'old' },
    newPassword: { value: 'new' },
    setAlert(id, message) { state.alert = `${id}:${message}`; },
    show(panel, focusTarget) {
      state.shown = panel.id;
      focusTarget.focus();
    },
    fetch(url) {
      state.fetchCalls.push(url);
      return pendingLogout;
    },
    JSON,
    Error,
  };

  vm.runInNewContext(logoutLoop, context);
  const firstClick = logoutButton.handlers.get('click')();
  const secondClick = logoutButton.handlers.get('click')();
  assert.equal(logoutButton.disabled, true);
  assert.equal(state.fetchCalls.filter((url) => url.endsWith('/logout')).length, 1);
  resolveLogout({ ok: true });
  await Promise.all([firstClick, secondClick]);
  assert.equal(logoutButton.disabled, false);
});

test('Turnstile errors clear only challenge state and alert an already-active login', () => {
  const body = script.match(/globalThis\.onTurnstileError\s*=\s*\(\)\s*=>\s*\{([\s\S]*?)\n\};/)?.[1] || '';
  const run = ({ loginHidden, activePanel, focused, submitDisabled }) => {
    const state = { alert: '', activePanel, focused, submitDisabled, token: 'unread' };
    const context = { state };
    vm.runInNewContext(`
      let turnstileToken = 'held-token';
      const genericError = 'generic error';
      const loginSubmit = { disabled: state.submitDisabled };
      const email = { focus() { state.focused = 'email'; } };
      const loginPanel = { id: 'login-panel', hidden: ${loginHidden} };
      const document = { querySelector() { return loginPanel; } };
      function setAlert(id, message) {
        if (id === '#login-alert') state.alert = message;
      }
      function show(panel, focusTarget) {
        state.activePanel = panel.id;
        focusTarget.focus();
      }
      globalThis.onTurnstileError = () => {${body}
      };
      state.result = globalThis.onTurnstileError();
      state.token = turnstileToken;
      state.submitDisabled = loginSubmit.disabled;
    `, context);
    return state;
  };

  const change = run({
    loginHidden: true,
    activePanel: 'change-panel',
    focused: 'new-password',
    submitDisabled: false,
  });
  assert.deepEqual(change, {
    alert: '',
    activePanel: 'change-panel',
    focused: 'new-password',
    submitDisabled: false,
    token: '',
    result: true,
  });

  const login = run({
    loginHidden: false,
    activePanel: 'login-panel',
    focused: 'email',
    submitDisabled: false,
  });
  assert.equal(login.alert, 'generic error');
  assert.equal(login.activePanel, 'login-panel');
  assert.equal(login.focused, 'email');
  assert.equal(login.submitDisabled, false);
  assert.equal(login.token, '');
  assert.equal(login.result, true);

  const inFlight = run({
    loginHidden: false,
    activePanel: 'login-panel',
    focused: 'password',
    submitDisabled: true,
  });
  assert.equal(inFlight.alert, 'generic error');
  assert.equal(inFlight.focused, 'password');
  assert.equal(inFlight.submitDisabled, true);
  assert.equal(inFlight.token, '');
  assert.equal(inFlight.result, true);
  assert.doesNotMatch(body, /show\(|\.focus\(|loginSubmit\.disabled/);
});

test('recipient styles are accessible and resilient at 320px', () => {
  const pageGutter = Number(css.match(/@media\s*\(max-width:\s*320px\)[\s\S]*?\.page\s*\{[^}]*width:\s*min\(100%\s*-\s*(\d+)px,/)?.[1]);
  const panelPadding = Number(css.match(/@media\s*\(max-width:\s*320px\)[\s\S]*?\.panel\s*\{[^}]*padding:\s*(\d+)px/)?.[1]);
  const panelBorder = Number(css.match(/\.panel\s*\{[\s\S]*?border:\s*(\d+)px/)?.[1]);
  const contentWidth = 320 - pageGutter - (2 * panelPadding) - (2 * panelBorder);

  assert.match(css, /:focus-visible/);
  assert.match(css, /@media\s*\(prefers-reduced-motion:\s*reduce\)/);
  assert.ok(Number.isFinite(contentWidth));
  assert.ok(contentWidth >= 150, `320px content width ${contentWidth}px must fit compact Turnstile`);
  assert.doesNotMatch(css, /overflow(?:-x)?:\s*(?:hidden|clip)/);
  assert.match(css, /min-height:\s*44px/);
  assert.match(css, /max-width:\s*100%/);
  assert.match(css, /\.cf-turnstile\s*\{[^}]*max-width:\s*100%/);
});

test('recipient controls use valid inherited font declarations', () => {
  const button = css.match(/button\s*\{([\s\S]*?)\}/)?.[1] || '';
  const shorthands = [...button.matchAll(/\bfont:\s*([^;]+);/g)];
  for (const shorthand of shorthands) {
    assert.equal(shorthand[1].trim(), 'inherit');
  }
  const explicit = /font-family:\s*inherit/.test(button)
    && /font-size:\s*16px/.test(button)
    && /font-weight:\s*650/.test(button)
    && /line-height:\s*1\.25/.test(button);
  assert.ok(shorthands.some((match) => match[1].trim() === 'inherit') || explicit);
});

test('download contract is runnable and static assets contain no secrets', () => {
  assert.equal(packageJson.scripts?.['test:download'], 'node --test download.test.js');
  assert.doesNotMatch(`${html}\n${script}\n${css}`, /ADMIN_EMAIL|ACCESS_AUD|TURNSTILE_SECRET|owner@example\.com|cloudflareaccess\.com/i);
});

test('Wrangler disables public Worker URLs and binds private releases on four custom domains', () => {
  assert.equal(wrangler.workers_dev, false);
  assert.equal(wrangler.preview_urls, false);
  assert.deepEqual(wrangler.observability, {
    enabled: true,
    head_sampling_rate: 1,
  });
  assert.equal(wrangler.compatibility_flags, undefined);
  assert.equal(packageJson.dependencies?.['@noble/hashes'], '2.2.0');
  assert.deepEqual(wrangler.routes, [
    { pattern: 'backchannel.page', custom_domain: true },
    { pattern: 'www.backchannel.page', custom_domain: true },
    { pattern: 'admin.backchannel.page', custom_domain: true },
    { pattern: 'downloads.backchannel.page', custom_domain: true },
  ]);
  assert.deepEqual(wrangler.r2_buckets, [{
    binding: 'RELEASES', bucket_name: 'backchannel-desktop-releases',
  }]);
  assert.equal(wrangler.d1_databases[0].binding, 'INTEREST_DB');
  assert.equal(wrangler.assets.binding, 'ASSETS');
});
