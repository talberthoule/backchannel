const panels = [...document.querySelectorAll('.panel')];
const page = document.querySelector('.page');
const loginForm = document.querySelector('#login-form');
const changeForm = document.querySelector('#change-form');
const email = document.querySelector('#email');
const password = document.querySelector('#password');
const newPassword = document.querySelector('#new-password');
const loginSubmit = document.querySelector('#login-submit');
const changeSubmit = document.querySelector('#change-submit');
const releasesPanel = document.querySelector('#releases-panel');
const releasesHeading = document.querySelector('#releases-heading');
const releasesIntro = releasesPanel.querySelector('.intro');
const releasesAlert = document.querySelector('#releases-alert');
const releasesList = document.createElement('div');
releasesIntro.setAttribute('role', 'status');
releasesIntro.setAttribute('aria-live', 'polite');
releasesList.id = 'releases-list';
releasesList.setAttribute('aria-live', 'polite');
releasesPanel.insertBefore(releasesList, releasesAlert);
const genericError = "We couldn't complete this request. Please try again.";
const releaseVersion = /^v(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$/;
let turnstileToken = '';

globalThis.onTurnstileVerified = (token) => { turnstileToken = token; };
globalThis.onTurnstileError = () => {
  turnstileToken = '';
  if (!document.querySelector('#login-panel').hidden) {
    setAlert('#login-alert', genericError);
  }
  return true;
};

function show(panel, focusTarget) {
  for (const item of panels) {
    const active = item === panel;
    item.hidden = !active;
    item.setAttribute('aria-hidden', String(!active));
  }
  page.setAttribute('aria-busy', 'false');
  focusTarget.focus();
}

function setAlert(id, message) {
  document.querySelector(id).textContent = message;
}

function humanSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  const units = ['KiB', 'MiB', 'GiB'];
  let value = bytes;
  let unit = -1;
  do {
    value /= 1024;
    unit += 1;
  } while (value >= 1024 && unit < units.length - 1);
  return `${value.toFixed(value >= 10 ? 0 : 1)} ${units[unit]}`;
}

function renderReleases(payload) {
  releasesList.replaceChildren();
  if (!Array.isArray(payload.items) || payload.items.length === 0) {
    releasesIntro.textContent = 'No releases are available for this account.';
    return;
  }
  releasesIntro.textContent = 'Choose an authorized release for your platform.';
  const requested = new URLSearchParams(location.search).get('version');
  let requestedSection;
  for (const release of payload.items) {
    const section = document.createElement('section');
    section.className = 'release';
    const heading = document.createElement('h2');
    heading.textContent = release.version === payload.latest_version
      ? `${release.version} (Latest)`
      : release.version;
    const published = document.createElement('time');
    published.dateTime = release.published_at;
    published.textContent = new Date(release.published_at).toLocaleString();
    section.append(heading, published);

    for (const asset of release.assets) {
      const item = document.createElement('article');
      const platform = document.createElement('h3');
      platform.textContent = asset.platform;
      const details = document.createElement('p');
      details.textContent = `${asset.filename} - ${humanSize(asset.size)}`;
      const checksum = document.createElement('p');
      checksum.className = 'checksum';
      checksum.textContent = `SHA-256: ${asset.sha256}`;
      const link = document.createElement('a');
      link.href = `/api/download/releases/${encodeURIComponent(release.version)}/${encodeURIComponent(asset.id)}`;
      link.textContent = `Download ${asset.filename}`;
      item.append(platform, details, checksum, link);
      section.append(item);
    }
    releasesList.append(section);
    if (releaseVersion.test(requested || '') && requested === release.version) {
      requestedSection = section;
    }
  }
  if (requestedSection) {
    requestedSection.tabIndex = -1;
    requestedSection.focus({ preventScroll: true });
    requestedSection.scrollIntoView({ block: 'start' });
  }
}

async function loadReleases() {
  releasesIntro.textContent = 'Loading releases...';
  releasesList.replaceChildren();
  setAlert('#releases-alert', '');
  try {
    const response = await fetch('/api/download/releases', { credentials: 'same-origin' });
    if (!response.ok) throw new Error();
    renderReleases(await response.json());
  } catch {
    releasesIntro.textContent = 'Releases are unavailable.';
    setAlert('#releases-alert', genericError);
  }
}

function showReleases() {
  show(releasesPanel, releasesHeading);
  loadReleases();
}

async function loadSession() {
  try {
    const response = await fetch('/api/download/session', { credentials: 'same-origin' });
    if (!response.ok) throw new Error();
    const session = await response.json();
    if (!session.authenticated) return show(document.querySelector('#login-panel'), email);
    if (session.must_change_password) return show(document.querySelector('#change-panel'), newPassword);
    showReleases();
  } catch {
    password.value = '';
    setAlert('#login-alert', genericError);
    show(document.querySelector('#login-panel'), email);
  }
}

loginForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  loginSubmit.disabled = true;
  setAlert('#login-alert', '');
  const token = turnstileToken || globalThis.turnstile?.getResponse() || '';
  try {
    const response = await fetch('/api/download/login', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ email: email.value, password: password.value, turnstile_token: token }),
    });
    if (!response.ok) throw new Error();
    const result = await response.json();
    password.value = '';
    if (result.must_change_password) show(document.querySelector('#change-panel'), newPassword);
    else showReleases();
  } catch {
    password.value = '';
    setAlert('#login-alert', genericError);
    password.focus();
  } finally {
    turnstileToken = '';
    globalThis.turnstile?.reset();
    loginSubmit.disabled = false;
  }
});

changeForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  changeSubmit.disabled = true;
  setAlert('#change-alert', '');
  const password = newPassword.value;
  try {
    const response = await fetch('/api/download/password', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ password }),
    });
    if (!response.ok) throw new Error();
    newPassword.value = '';
    showReleases();
  } catch {
    newPassword.value = '';
    setAlert('#change-alert', genericError);
    newPassword.focus();
  } finally {
    changeSubmit.disabled = false;
  }
});

for (const button of document.querySelectorAll('.logout')) {
  button.addEventListener('click', async () => {
    const alertId = button.closest('#change-panel') ? '#change-alert' : '#releases-alert';
    setAlert(alertId, '');
    try {
      const response = await fetch('/api/download/logout', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({}),
      });
      if (!response.ok) throw new Error();
      password.value = '';
      newPassword.value = '';
      show(document.querySelector('#login-panel'), email);
    } catch {
      password.value = '';
      newPassword.value = '';
      setAlert(alertId, genericError);
      button.focus();
    }
  });
}

loadSession();
