import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const customerFiles = [
  '../README.md',
  '../docs/quickstart.md',
  '../docs/releasing.md',
  '../docs/deployment.md',
  '../docs/README.md',
  '../AGENTS.md',
  '../CLAUDE.md',
  '../site/index.html',
  '../site/fireflies-alternative/index.html',
  '../site/granola-alternative/index.html',
  '../site/otter-alternative/index.html',
  '../site/vs-meetily/index.html',
  '../site/releases/v0.1.0/index.html',
  '../site/releases/v0.1.1/index.html',
  '../site/releases/v0.2.0/index.html',
  '../site/releases/v0.2.1/index.html',
  '../site/llms.txt',
  '../site/sitemap.xml',
  '../.github/release-notes/v0.1.1.md',
  '../.github/release-notes/v0.2.0.md',
  '../.github/release-notes/v0.2.1.md',
];
const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8');
const customerContent = customerFiles.map((path) => [path, read(path)]);

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

test('customer guidance retains the pre-cutover GitHub executable boundary', () => {
  assert.match(read('../README.md'), /private GitHub repository/i);
  assert.match(read('../docs/quickstart.md'), /private GitHub repository/i);
  assert.match(read('../site/index.html'), /releases\/download\/v0\.2\.1/i);
});

test('customer download entry points stay on the public release page before cutover', () => {
  for (const path of [
    '../README.md',
    '../docs/quickstart.md',
    '../site/index.html',
    '../site/fireflies-alternative/index.html',
    '../site/granola-alternative/index.html',
    '../site/otter-alternative/index.html',
    '../site/vs-meetily/index.html',
    '../site/llms.txt',
  ]) {
    assert.match(read(path), /(?:backchannel\.page\/|\/|")releases\/v0\.2\.1\//i, path);
    assert.doesNotMatch(read(path), /downloads\.backchannel\.page/i, path);
  }
});

test('historical release pages retain their own GitHub executable links', () => {
  for (const version of ['v0.1.0', 'v0.1.1', 'v0.2.0', 'v0.2.1']) {
    const path = `../site/releases/${version}/index.html`;
    const content = read(path);
    assert.match(content, new RegExp(`github\\.com/talberthoule/backchannel/releases/download/${version}/`, 'i'), path);
    assert.doesNotMatch(content, /downloads\.backchannel\.page/i, path);
  }
});

test('public GitHub source, issue, license, star, and release-note links remain', () => {
  const content = customerContent.map(([, value]) => value).join('\n');
  assert.match(content, /https:\/\/github\.com\/talberthoule\/backchannel(?:\.git)?["')\s]/i);
  assert.match(content, /https:\/\/github\.com\/talberthoule\/backchannel\/issues/i);
  assert.match(content, /https:\/\/github\.com\/talberthoule\/backchannel\/blob\/master\/LICENSE/i);
  assert.match(read('../site/index.html'), /href="https:\/\/github\.com\/talberthoule\/backchannel"[^>]*>Star on GitHub/i);
  for (const version of ['v0.1.0', 'v0.1.1', 'v0.2.0', 'v0.2.1']) {
    assert.match(content, new RegExp(`https://github\\.com/talberthoule/backchannel/releases/tag/${version}`));
  }
});

test('the sitemap remains a same-host index while public pages stay pre-cutover', () => {
  const sitemap = read('../site/sitemap.xml');
  const locations = [...sitemap.matchAll(/<loc>([^<]+)<\/loc>/g)].map((match) => match[1]);
  assert.ok(locations.length > 0);
  assert.ok(locations.every((location) => location.startsWith('https://backchannel.page/')));
  assert.doesNotMatch(sitemap, /downloads\.backchannel\.page/i);
  assert.match(read('../site/index.html'), /releases\/v0\.2\.1\//i);
  assert.doesNotMatch(read('../site/index.html'), /downloads\.backchannel\.page/i);
});

test('historical migration normalizes peeled commit timestamps to strict UTC', () => {
  const releasing = read('../docs/releasing.md');
  assert.match(releasing, /\[DateTimeOffset\]::Parse/);
  assert.match(releasing, /\.UtcDateTime\.ToString\("yyyy-MM-dd'T'HH:mm:ss'Z'"/);
  for (const version of ['v0.1.0', 'v0.1.1', 'v0.2.0', 'v0.2.1']) {
    assert.match(releasing, new RegExp(`git rev-parse ['"]${version}\\^\\{commit\\}['"]`));
  }
  assert.doesNotMatch(releasing, /\$v\d+Time\s*=\s*\(& git show[^\n]+\)\.Trim\(\)/);
});

test('production deployment always rebuilds immediately before Wrangler deploy', () => {
  const deployment = read('../docs/deployment.md');
  assert.match(deployment, /^npm run deploy$/m);
  assert.doesNotMatch(deployment, /^npx wrangler deploy$/m);
  assert.match(deployment, /never deploy (?:a )?preexisting `dist-site`|fresh build immediately before deploy/i);
});

test('PBKDF2 benchmarking follows a verified catalog and precedes link cutover', () => {
  const deployment = read('../docs/deployment.md');
  const verifiedCatalog = deployment.indexOf('at least one verified test manifest');
  const benchmark = deployment.indexOf('Benchmark the real password work factor');
  const cutover = deployment.indexOf('cut over customer links');
  assert.ok(verifiedCatalog >= 0);
  assert.ok(verifiedCatalog < benchmark);
  assert.ok(benchmark < cutover);
  assert.match(deployment, /available.*true/i);
});

test('staged link cutover names the exact mechanically revertible hold', () => {
  const hold = '57fc8d991b8101a2db5889df16ce5a26078baff2';
  for (const path of ['../docs/deployment.md', '../docs/releasing.md']) {
    const runbook = read(path);
    assert.match(runbook, new RegExp(hold));
    assert.match(runbook, new RegExp(`git revert ${hold}`));
    assert.ok([...runbook.matchAll(/git revert ([0-9a-f]{40})/g)]
      .every((match) => match[1] === hold));
  }
  const deployment = read('../docs/deployment.md');
  assert.match(deployment, /master[^.\n]*auto-deploy/i);
  assert.ok(deployment.indexOf('control-plane HEAD') < deployment.indexOf('live Task 7 acceptance'));
  assert.ok(deployment.indexOf('live Task 7 acceptance') < deployment.indexOf(`git revert ${hold}`));
});

test('D1 exports require operator-supplied absolute paths outside the repository', () => {
  const deployment = read('../docs/deployment.md');
  assert.match(deployment, /BACKCHANNEL_D1_BACKUP_PATH/);
  assert.match(deployment, /\[IO\.Path\]::IsPathRooted\(/);
  assert.match(deployment, /--output="\$backupPath"/);
  assert.doesNotMatch(deployment, /--output=(?:backchannel-interest-backup|interest-subscribers)\.sql/);
});

test('release recovery names the Update Latest boundary precisely', () => {
  const releasing = read('../docs/releasing.md');
  assert.match(releasing, /failure before the Update Latest step leaves Latest unchanged/i);
  assert.match(releasing, /GitHub note creation fails after Latest advances/i);
  assert.doesNotMatch(releasing, /failure before the last step/i);
});
