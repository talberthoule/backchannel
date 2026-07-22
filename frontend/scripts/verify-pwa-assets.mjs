import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {dirname, join} from 'node:path';
import {test} from 'node:test';
import {fileURLToPath} from 'node:url';

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const target = process.argv.includes('--dist') ? 'dist' : 'public';
const htmlPath = process.argv.includes('--dist') ? 'dist/index.html' : 'index.html';
const expectedDescription = 'Backchannel is a self-hosted, open-source (MIT) AI meeting assistant that runs on your own hardware -- no bot joins your call, and your audio never leaves your infrastructure except for the model API calls you configure.';
const expectedThemeColor = '#0f172a';
const expectedIcons = [
  {src: '/icons/icon-192.png', sizes: '192x192', type: 'image/png', purpose: 'any maskable'},
  {src: '/icons/icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'any maskable'},
];

function file(...parts) {
  return join(root, ...parts);
}

async function json(path) {
  return JSON.parse(await readFile(path, 'utf8'));
}

async function pngSize(path) {
  const bytes = await readFile(path);
  assert.equal(bytes.subarray(0, 8).toString('hex'), '89504e470d0a1a0a');
  assert.equal(bytes.subarray(12, 16).toString('ascii'), 'IHDR');
  return {width: bytes.readUInt32BE(16), height: bytes.readUInt32BE(20)};
}

test('PWA manifest declares the Backchannel install target', async () => {
  assert.deepEqual(await json(file(target, 'manifest.webmanifest')), {
    name: 'Backchannel',
    short_name: 'Backchannel',
    description: expectedDescription,
    start_url: '/',
    scope: '/',
    display: 'standalone',
    background_color: expectedThemeColor,
    theme_color: expectedThemeColor,
    icons: expectedIcons,
  });
});

test('PWA icons are emitted at installable sizes', async () => {
  for (const icon of expectedIcons) {
    const expected = Number(icon.sizes.split('x')[0]);
    assert.deepEqual(await pngSize(file(target, icon.src)), {
      width: expected,
      height: expected,
    });
  }
});

test('HTML links install metadata from origin-root URLs', async () => {
  const html = await readFile(file(htmlPath), 'utf8');
  assert.match(html, /<link rel="manifest" href="\/manifest\.webmanifest" \/>/);
  assert.match(html, /<meta name="theme-color" content="#0f172a" \/>/);
  assert.match(html, /<link rel="apple-touch-icon" href="\/icons\/icon-192\.png" \/>/);
});
