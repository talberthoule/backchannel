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
