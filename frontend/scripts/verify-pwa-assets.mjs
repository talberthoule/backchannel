import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {dirname, join} from 'node:path';
import {test} from 'node:test';
import {fileURLToPath} from 'node:url';
import {inflateSync} from 'node:zlib';

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const target = process.argv.includes('--dist') ? 'dist' : 'public';
const htmlPath = process.argv.includes('--dist') ? 'dist/index.html' : 'index.html';
const expectedDescription = 'Backchannel is a self-hosted, open-source (MIT) AI meeting assistant that runs on your own hardware -- no bot joins your call, and your audio never leaves your infrastructure except for the model API calls you configure.';
const expectedThemeColor = '#0f172a';
const expectedIcons = [
  {src: '/icons/icon-192.png', sizes: '192x192', type: 'image/png', purpose: 'any'},
  {src: '/icons/icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'any'},
  {src: '/icons/icon-maskable-192.png', sizes: '192x192', type: 'image/png', purpose: 'maskable'},
  {src: '/icons/icon-maskable-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable'},
];
const maskableBackground = {red: 0x0f, green: 0x17, blue: 0x2a};
const safeRadiusRatio = 0.4;

function file(...parts) {
  return join(root, ...parts);
}

async function json(path) {
  return JSON.parse(await readFile(path, 'utf8'));
}

const crcTable = Array.from({length: 256}, (_, value) => {
  let crc = value;
  for (let bit = 0; bit < 8; bit++) {
    crc = (crc & 1) ? (0xedb88320 ^ (crc >>> 1)) : (crc >>> 1);
  }
  return crc >>> 0;
});

function crc32(bytes) {
  let crc = 0xffffffff;
  for (const byte of bytes) crc = crcTable[(crc ^ byte) & 0xff] ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}

function paeth(left, above, upperLeft) {
  const p = left + above - upperLeft;
  const pa = Math.abs(p - left);
  const pb = Math.abs(p - above);
  const pc = Math.abs(p - upperLeft);
  if (pa <= pb && pa <= pc) return left;
  return pb <= pc ? above : upperLeft;
}

function inspectPngBytes(bytes) {
  assert.equal(bytes.subarray(0, 8).toString('hex'), '89504e470d0a1a0a');
  let offset = 8;
  let ihdr;
  let seenIend = false;
  const idat = [];
  while (offset < bytes.length) {
    assert.ok(offset + 12 <= bytes.length, 'PNG chunk header is truncated');
    const length = bytes.readUInt32BE(offset);
    const type = bytes.subarray(offset + 4, offset + 8).toString('ascii');
    const dataStart = offset + 8;
    const dataEnd = dataStart + length;
    const crcEnd = dataEnd + 4;
    assert.ok(crcEnd <= bytes.length, `PNG ${type} chunk is truncated`);
    const data = bytes.subarray(dataStart, dataEnd);
    const expectedCrc = bytes.readUInt32BE(dataEnd);
    const actualCrc = crc32(bytes.subarray(offset + 4, dataEnd));
    assert.equal(actualCrc, expectedCrc, `PNG ${type} CRC mismatch`);
    if (type === 'IHDR') {
      assert.equal(length, 13, 'PNG IHDR length is invalid');
      ihdr = {
        width: data.readUInt32BE(0),
        height: data.readUInt32BE(4),
        bitDepth: data[8],
        colorType: data[9],
      };
    } else if (type === 'IDAT') {
      idat.push(data);
    } else if (type === 'IEND') {
      assert.equal(length, 0, 'PNG IEND length is invalid');
      assert.equal(crcEnd, bytes.length, 'PNG has trailing data after IEND');
      seenIend = true;
      break;
    }
    offset = crcEnd;
  }
  assert.ok(seenIend, 'PNG IEND chunk is missing');
  assert.ok(ihdr, 'PNG IHDR chunk is missing');
  assert.equal(ihdr.bitDepth, 8, 'PNG must use 8-bit channels');
  assert.ok(ihdr.colorType === 6 || ihdr.colorType === 2, 'PNG must be RGB or RGBA');

  const channels = ihdr.colorType === 6 ? 4 : 3;
  const stride = ihdr.width * channels;
  const raw = inflateSync(Buffer.concat(idat));
  assert.equal(raw.length, (stride + 1) * ihdr.height, 'PNG image data length is invalid');
  const pixels = [];
  let previous = Buffer.alloc(stride);
  for (let rowIndex = 0; rowIndex < ihdr.height; rowIndex++) {
    const rowStart = rowIndex * (stride + 1);
    const filter = raw[rowStart];
    const row = Buffer.from(raw.subarray(rowStart + 1, rowStart + 1 + stride));
    for (let index = 0; index < row.length; index++) {
      const left = index >= channels ? row[index - channels] : 0;
      const above = previous[index];
      const upperLeft = index >= channels ? previous[index - channels] : 0;
      if (filter === 1) row[index] = (row[index] + left) & 0xff;
      else if (filter === 2) row[index] = (row[index] + above) & 0xff;
      else if (filter === 3) row[index] = (row[index] + Math.floor((left + above) / 2)) & 0xff;
      else if (filter === 4) row[index] = (row[index] + paeth(left, above, upperLeft)) & 0xff;
      else assert.equal(filter, 0, 'PNG filter type is invalid');
    }
    for (let column = 0; column < ihdr.width; column++) {
      const pixel = column * channels;
      pixels.push({
        red: row[pixel],
        green: row[pixel + 1],
        blue: row[pixel + 2],
        alpha: channels === 4 ? row[pixel + 3] : 255,
        x: column,
        y: rowIndex,
      });
    }
    previous = row;
  }
  return {...ihdr, pixels};
}

async function inspectPng(path) {
  return inspectPngBytes(await readFile(path));
}

function transparentRatio(image) {
  return image.pixels.filter(({alpha}) => alpha < 255).length / image.pixels.length;
}

function artworkRadiusRatio(image) {
  const center = (image.width - 1) / 2;
  const maxRadius = Math.max(...image.pixels
    .filter(({red, green, blue}) => (
      red !== maskableBackground.red
      || green !== maskableBackground.green
      || blue !== maskableBackground.blue
    ))
    .map(({x, y}) => Math.hypot(x - center, y - center)));
  return maxRadius / image.width;
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
    const image = await inspectPng(file(target, icon.src));
    assert.deepEqual({width: image.width, height: image.height}, {width: expected, height: expected});
  }
});

test('PWA maskable icons are opaque and stay inside the safe zone', async () => {
  const manifest = await json(file(target, 'manifest.webmanifest'));
  const maskableIcons = manifest.icons.filter(({purpose = ''}) => purpose.split(/\s+/).includes('maskable'));
  assert.equal(maskableIcons.length, 2);
  for (const icon of maskableIcons) {
    const image = await inspectPng(file(target, icon.src));
    assert.equal(transparentRatio(image), 0, `${icon.src} must be opaque`);
    assert.ok(
      artworkRadiusRatio(image) <= safeRadiusRatio,
      `${icon.src} artwork exceeds the ${safeRadiusRatio * 100}% maskable safe radius`,
    );
  }
});

test('PNG validation rejects truncation, CRC errors, and missing IEND', async () => {
  const bytes = await readFile(file(target, 'icons/icon-192.png'));
  assert.throws(() => inspectPngBytes(bytes.subarray(0, bytes.length - 1)), /truncated|IEND/);
  const badCrc = Buffer.from(bytes);
  badCrc[badCrc.length - 5] ^= 0xff;
  assert.throws(() => inspectPngBytes(badCrc), /CRC mismatch/);
  assert.throws(() => inspectPngBytes(bytes.subarray(0, bytes.length - 12)), /IEND/);
});

test('HTML links install metadata from origin-root URLs', async () => {
  const html = await readFile(file(htmlPath), 'utf8');
  assert.match(html, /<link rel="manifest" href="\/manifest\.webmanifest" \/>/);
  assert.match(html, /<meta name="theme-color" content="#0f172a" \/>/);
  assert.match(html, /<link rel="apple-touch-icon" href="\/icons\/icon-192\.png" \/>/);
});
