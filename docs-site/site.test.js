import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const html = readFileSync(new URL('../site/index.html', import.meta.url), 'utf8');
const marker = 'var form = document.getElementById("interest-form")';
const markerAt = html.indexOf(marker);
const scriptStart = html.lastIndexOf('<script>', markerAt) + '<script>'.length;
const scriptEnd = html.indexOf('</script>', markerAt);
const interestScript = html.slice(scriptStart, scriptEnd);

test('network failures keep the email valid and show an actionable retry', async () => {
  let submit;
  const emailAttributes = new Map();
  const button = { disabled: false };
  const status = { dataset: {}, textContent: '' };
  const email = {
    removeAttribute(name) { emailAttributes.delete(name); },
    setAttribute(name, value) { emailAttributes.set(name, value); },
  };
  const form = {
    addEventListener(_name, handler) { submit = handler; },
    querySelector() { return button; },
    removeAttribute() {},
    reportValidity() { return true; },
    reset() {},
    setAttribute() {},
  };
  const document = {
    getElementById(id) {
      return { 'interest-form': form, 'interest-email': email, 'interest-status': status }[id];
    },
  };
  class FakeFormData {
    get(name) {
      return name === 'email' ? 'person@example.com' : 'turnstile-token';
    }
  }

  vm.runInNewContext(interestScript, {
    document,
    fetch: async () => { throw new TypeError('Failed to fetch'); },
    FormData: FakeFormData,
    window: { turnstile: { reset() {} } },
  });
  submit({ preventDefault() {} });
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(status.textContent, "We couldn't save this right now. Please try again.");
  assert.equal(emailAttributes.has('aria-invalid'), false);
  assert.equal(button.disabled, false);
});
