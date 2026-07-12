const panels = [...document.querySelectorAll('.panel')];
const page = document.querySelector('.page');
const loginForm = document.querySelector('#login-form');
const changeForm = document.querySelector('#change-form');
const email = document.querySelector('#email');
const password = document.querySelector('#password');
const newPassword = document.querySelector('#new-password');
const loginSubmit = document.querySelector('#login-submit');
const changeSubmit = document.querySelector('#change-submit');
const genericError = "We couldn't complete this request. Please try again.";
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

async function loadSession() {
  try {
    const response = await fetch('/api/download/session', { credentials: 'same-origin' });
    if (!response.ok) throw new Error();
    const session = await response.json();
    if (!session.authenticated) return show(document.querySelector('#login-panel'), email);
    if (session.must_change_password) return show(document.querySelector('#change-panel'), newPassword);
    show(document.querySelector('#releases-panel'), document.querySelector('#releases-heading'));
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
    else show(document.querySelector('#releases-panel'), document.querySelector('#releases-heading'));
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
    show(document.querySelector('#releases-panel'), document.querySelector('#releases-heading'));
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
