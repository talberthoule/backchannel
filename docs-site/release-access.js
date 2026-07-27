import { pbkdf2 } from '@noble/hashes/pbkdf2.js';
import { sha256 } from '@noble/hashes/sha2.js';

export const PASSWORD_ITERATIONS = 600_000;
export const TEMPORARY_PASSWORD_TTL_SECONDS = 259_200;
export const CHANGE_SESSION_TTL_SECONDS = 1_800;
export const SESSION_TTL_SECONDS = 604_800;
export const SESSION_COOKIE = '__Host-backchannel_release';

const UPPER = 'ABCDEFGHJKLMNPQRSTUVWXYZ';
const LOWER = 'abcdefghijkmnopqrstuvwxyz';
const NUMBER = '23456789';
const SYMBOL = '!#$%&*+?@';
const PASSWORD_ALPHABET = UPPER + LOWER + NUMBER + SYMBOL;
const VERSION_PATTERN = /^(?=.{2,32}$)v(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$/;
const MANIFEST_KEY_PATTERN = /^releases\/((?=.{2,32}\/manifest\.json$)v(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*))\/manifest\.json$/;
const RELEASE_KEY_PATTERN = /^releases\/((?=.{2,32}\/release\.json$)v(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*))\/release\.json$/;
const PLATFORM_KEY_PATTERN = /^releases\/((?=.{2,32}\/platforms\/)v(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*))\/platforms\/(windows-x64|macos-arm64|linux-x64)\.json$/;
const ASSET_TUPLES = new Map([
  ['windows-x64', ['Windows x64', 'Backchannel-windows-x64.zip', 'application/zip']],
  ['macos-arm64', ['macOS arm64', 'Backchannel-macos-arm64.zip', 'application/zip']],
  ['linux-x64', ['Linux x64', 'Backchannel-linux-x64.tar.gz', 'application/gzip']],
]);
const DUMMY_SALT = new Uint8Array(16);

function secureRandomBytes(length) {
  return globalThis.crypto.getRandomValues(new Uint8Array(length));
}

function randomIndexReader(randomBytes) {
  let bytes = new Uint8Array();
  let offset = 0;
  return (size) => {
    const limit = 256 - (256 % size);
    while (true) {
      if (offset === bytes.length) {
        bytes = randomBytes(64);
        if (!(bytes instanceof Uint8Array) || bytes.length === 0) {
          throw new TypeError('Random byte source must return bytes');
        }
        offset = 0;
      }
      const byte = bytes[offset];
      offset += 1;
      if (byte < limit) return byte % size;
    }
  };
}

function encodeBase64Url(bytes) {
  return btoa(String.fromCharCode(...bytes))
    .replaceAll('+', '-')
    .replaceAll('/', '_')
    .replace(/=+$/, '');
}

function decodeBase64Url(value, expectedLength) {
  if (typeof value !== 'string' || !/^[A-Za-z0-9_-]+$/.test(value)) return null;
  try {
    const padded = value.replaceAll('-', '+').replaceAll('_', '/')
      + '='.repeat((4 - (value.length % 4)) % 4);
    const bytes = Uint8Array.from(atob(padded), (character) => character.charCodeAt(0));
    if (bytes.length !== expectedLength || encodeBase64Url(bytes) !== value) return null;
    return bytes;
  } catch {
    return null;
  }
}

function derivePbkdf2(password, salt, iterations, length) {
  return pbkdf2(sha256, password, salt, { c: iterations, dkLen: length });
}

async function derivePassword(password, salt, iterations, derive = derivePbkdf2) {
  return new Uint8Array(derive(
    new TextEncoder().encode(password),
    salt,
    iterations,
    32,
  ));
}

function equalBytes(left, right) {
  const native = globalThis.crypto.subtle.timingSafeEqual;
  if (typeof native === 'function') return native.call(globalThis.crypto.subtle, left, right);
  let difference = left.length ^ right.length;
  for (let i = 0; i < Math.max(left.length, right.length); i += 1) {
    difference |= (left[i % left.length] ?? 0) ^ (right[i % right.length] ?? 0);
  }
  return difference === 0;
}

export function generateTemporaryPassword(randomBytes = secureRandomBytes) {
  const randomIndex = randomIndexReader(randomBytes);
  const characters = [
    UPPER[randomIndex(UPPER.length)],
    LOWER[randomIndex(LOWER.length)],
    NUMBER[randomIndex(NUMBER.length)],
    SYMBOL[randomIndex(SYMBOL.length)],
  ];
  while (characters.length < 20) {
    characters.push(PASSWORD_ALPHABET[randomIndex(PASSWORD_ALPHABET.length)]);
  }
  for (let i = characters.length - 1; i > 0; i -= 1) {
    const other = randomIndex(i + 1);
    [characters[i], characters[other]] = [characters[other], characters[i]];
  }
  return characters.join('');
}

export async function hashPassword(password, { salt, iterations = PASSWORD_ITERATIONS } = {}) {
  const saltBytes = salt === undefined ? secureRandomBytes(16) : salt;
  if (!(saltBytes instanceof Uint8Array) || saltBytes.length === 0) {
    throw new TypeError('Salt must contain bytes');
  }
  if (!Number.isSafeInteger(iterations) || iterations < 1) {
    throw new TypeError('Iterations must be a positive safe integer');
  }
  const hash = await derivePassword(password, saltBytes, iterations);
  return {
    hash: encodeBase64Url(hash),
    salt: encodeBase64Url(saltBytes),
    iterations,
  };
}

export async function verifyPassword(password, record, derive) {
  const salt = decodeBase64Url(record?.salt, 16);
  const expected = decodeBase64Url(record?.hash, 32);
  if (!salt || !expected || record?.iterations !== PASSWORD_ITERATIONS) {
    await derivePassword(password, DUMMY_SALT, PASSWORD_ITERATIONS, derive);
    return false;
  }
  const actual = await derivePassword(password, salt, PASSWORD_ITERATIONS, derive);
  return equalBytes(actual, expected);
}

export async function createSessionToken(randomBytes = secureRandomBytes) {
  const bytes = randomBytes(32);
  if (!(bytes instanceof Uint8Array) || bytes.length !== 32) {
    throw new TypeError('Session token source must return 32 bytes');
  }
  const hash = new Uint8Array(await globalThis.crypto.subtle.digest('SHA-256', bytes));
  return { token: encodeBase64Url(bytes), tokenHash: encodeBase64Url(hash) };
}

function exactKeys(value, keys) {
  return Object.keys(value).length === keys.length && keys.every((key) => key in value);
}

function validUtcTimestamp(value) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{3})?Z$/.test(value)) {
    return false;
  }
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return false;
  const normalized = value.includes('.') ? value : value.replace('Z', '.000Z');
  return new Date(timestamp).toISOString() === normalized;
}

export function parseManifest(value, expectedVersion) {
  if (!value || typeof value !== 'object' || Array.isArray(value)
    || !exactKeys(value, ['version', 'published_at', 'commit', 'assets'])
    || !VERSION_PATTERN.test(value.version)
    || (expectedVersion !== undefined && value.version !== expectedVersion)
    || !validUtcTimestamp(value.published_at)
    || !/^[0-9a-f]{40}$/.test(value.commit)
    || !Array.isArray(value.assets)
    || value.assets.length === 0) {
    return null;
  }

  const ids = new Set();
  const filenames = new Set();
  for (const asset of value.assets) {
    if (!parseAsset(asset, value.version)
      || ids.has(asset.id)
      || filenames.has(asset.filename)) {
      return null;
    }
    ids.add(asset.id);
    filenames.add(asset.filename);
  }
  return value;
}

function parseAsset(asset, version) {
  if (!asset || typeof asset !== 'object' || Array.isArray(asset)
    || !exactKeys(asset, ['id', 'platform', 'filename', 'key', 'size', 'sha256', 'content_type'])
    || !/^[a-z0-9-]{1,32}$/.test(asset.id)) return null;
  const tuple = ASSET_TUPLES.get(asset.id);
  return tuple
    && asset.platform === tuple[0]
    && asset.filename === tuple[1]
    && asset.content_type === tuple[2]
    && asset.key === `releases/${version}/${asset.filename}`
    && Number.isSafeInteger(asset.size)
    && asset.size > 0
    && /^[0-9a-f]{64}$/.test(asset.sha256) ? asset : null;
}

export function parseReleaseIdentity(value, expectedVersion) {
  if (!value || typeof value !== 'object' || Array.isArray(value)
    || !exactKeys(value, ['version', 'published_at', 'commit'])
    || !VERSION_PATTERN.test(value.version)
    || (expectedVersion !== undefined && value.version !== expectedVersion)
    || !validUtcTimestamp(value.published_at)
    || !/^[0-9a-f]{40}$/.test(value.commit)) return null;
  return value;
}

function parseUpdate(value) {
  return value && typeof value === 'object' && !Array.isArray(value)
    && exactKeys(value, ['key_id', 'schema', 'signature'])
    && /^[a-z0-9-]{1,40}$/.test(value.key_id)
    && value.schema === 1
    && /^[A-Za-z0-9_-]{86}$/.test(value.signature)
    ? value
    : null;
}

function validReleaseNotes(value) {
  return typeof value === 'string' && value.length > 0
    && new TextEncoder().encode(value).byteLength <= 8192;
}

export function parsePlatformManifest(value, identity, platformId) {
  if (!parseReleaseIdentity(identity)
    || !value || typeof value !== 'object' || Array.isArray(value)) return null;
  const unsigned = exactKeys(value, ['version', 'commit', 'asset']);
  const signed = exactKeys(
    value,
    ['version', 'commit', 'published_at', 'release_notes', 'asset', 'update'],
  );
  if ((!unsigned && !signed)
    || value.version !== identity.version || value.commit !== identity.commit
    || (signed && (value.published_at !== identity.published_at
      || !validReleaseNotes(value.release_notes) || !parseUpdate(value.update)))) return null;
  const asset = parseAsset(value.asset, identity.version);
  return asset?.id === platformId ? value : null;
}

async function readJson(bucket, key) {
  const object = await bucket.get(key);
  if (!object || typeof object.json !== 'function') return null;
  return object.json();
}

export async function loadReleaseCatalog(bucket) {
  const manifests = new Map();
  const diagnostics = [];
  const legacyKeys = new Map();
  const releaseKeys = new Map();
  const platformKeys = new Map();
  let cursor;
  do {
    let page;
    try {
      page = await bucket.list({ prefix: 'releases/', cursor });
    } catch {
      diagnostics.push('catalog-unavailable');
      break;
    }
    for (const { key } of page.objects ?? []) {
      let match = MANIFEST_KEY_PATTERN.exec(key);
      if (match) {
        legacyKeys.set(match[1], key);
        continue;
      }
      match = RELEASE_KEY_PATTERN.exec(key);
      if (match) {
        releaseKeys.set(match[1], key);
        continue;
      }
      match = PLATFORM_KEY_PATTERN.exec(key);
      if (match) {
        if (!platformKeys.has(match[1])) platformKeys.set(match[1], new Map());
        platformKeys.get(match[1]).set(match[2], key);
      }
    }
    cursor = page.truncated ? page.cursor : undefined;
    if (page.truncated && !cursor) {
      diagnostics.push('catalog-invalid');
      break;
    }
  } while (cursor);

  const progressiveVersions = new Set([...releaseKeys.keys(), ...platformKeys.keys()]);
  for (const [version, key] of legacyKeys) {
    if (progressiveVersions.has(version)) {
      diagnostics.push('manifest-conflict');
      continue;
    }
    try {
      const manifest = parseManifest(await readJson(bucket, key), version);
      if (manifest) manifests.set(manifest.version, manifest);
      else diagnostics.push('manifest-invalid');
    } catch {
      diagnostics.push('manifest-unavailable');
    }
  }

  for (const version of progressiveVersions) {
    if (legacyKeys.has(version)) continue;
    const releaseKey = releaseKeys.get(version);
    if (!releaseKey) {
      diagnostics.push('release-unavailable');
      continue;
    }
    let identity;
    try {
      identity = parseReleaseIdentity(await readJson(bucket, releaseKey), version);
      if (!identity) diagnostics.push('release-invalid');
    } catch {
      diagnostics.push('release-unavailable');
    }
    if (!identity) continue;

    const assets = [];
    let releaseNotes;
    let notesConflict = false;
    for (const platformId of ASSET_TUPLES.keys()) {
      const key = platformKeys.get(version)?.get(platformId);
      if (!key) continue;
      try {
        const platform = parsePlatformManifest(
          await readJson(bucket, key), identity, platformId,
        );
        if (platform) {
          if (platform.update) {
            if (releaseNotes === undefined) releaseNotes = platform.release_notes;
            else if (releaseNotes !== platform.release_notes) notesConflict = true;
          }
          assets.push(platform.update
            ? { ...platform.asset, update: platform.update }
            : platform.asset);
        }
        else diagnostics.push('platform-invalid');
      } catch {
        diagnostics.push('platform-unavailable');
      }
    }
    if (notesConflict) {
      diagnostics.push('release-notes-conflict');
      continue;
    }
    if (assets.length > 0) manifests.set(version, {
      ...identity,
      ...(releaseNotes === undefined ? {} : { release_notes: releaseNotes }),
      assets,
    });
  }

  let latestVersion = null;
  try {
    const latest = await readJson(bucket, 'releases/latest.json');
    if (latest && typeof latest === 'object' && !Array.isArray(latest)
      && exactKeys(latest, ['version'])
      && VERSION_PATTERN.test(latest.version)
      && manifests.has(latest.version)) {
      latestVersion = latest.version;
    } else {
      diagnostics.push('latest-invalid');
    }
  } catch {
    diagnostics.push('latest-unavailable');
  }
  return { latestVersion, manifests, diagnostics };
}

function compareVersionsNewestFirst(left, right) {
  const leftParts = left.slice(1).split('.').map(BigInt);
  const rightParts = right.slice(1).split('.').map(BigInt);
  for (let i = 0; i < 3; i += 1) {
    if (leftParts[i] > rightParts[i]) return -1;
    if (leftParts[i] < rightParts[i]) return 1;
  }
  return 0;
}

export function resolveEntitlements(account, explicitVersions, catalog) {
  const versions = new Set();
  if (account?.include_latest === 1 && VERSION_PATTERN.test(catalog?.latestVersion)) {
    versions.add(catalog.latestVersion);
  }
  for (const version of Array.isArray(explicitVersions) ? explicitVersions : []) {
    if (typeof version === 'string' && VERSION_PATTERN.test(version)
      && catalog?.manifests?.has(version)) versions.add(version);
  }
  return [...versions]
    .sort(compareVersionsNewestFirst)
    .map((version) => catalog.manifests.get(version));
}

export function releaseSummary(manifest) {
  return {
    version: manifest.version,
    published_at: manifest.published_at,
    assets: manifest.assets.map(({ id, platform, filename, size, sha256 }) => ({
      id, platform, filename, size, sha256,
    })),
  };
}

export function publicUpdateDescriptor(manifest, assetId) {
  if (!manifest || typeof manifest !== 'object' || Array.isArray(manifest)
    || !parseReleaseIdentity({
      version: manifest.version,
      published_at: manifest.published_at,
      commit: manifest.commit,
    })
    || !validReleaseNotes(manifest.release_notes)
    || !Array.isArray(manifest.assets)) return null;
  const asset = manifest.assets.find((value) => value?.id === assetId);
  const update = parseUpdate(asset?.update);
  if (!asset || !update) return null;
  const privateAsset = {
    id: asset.id,
    platform: asset.platform,
    filename: asset.filename,
    key: asset.key,
    size: asset.size,
    sha256: asset.sha256,
    content_type: asset.content_type,
  };
  if (!parseAsset(privateAsset, manifest.version)) return null;
  return {
    version: manifest.version,
    commit: manifest.commit,
    published_at: manifest.published_at,
    release_notes: manifest.release_notes,
    asset: {
      id: asset.id,
      platform: asset.platform,
      filename: asset.filename,
      size: asset.size,
      sha256: asset.sha256,
    },
    key_id: update.key_id,
    schema: update.schema,
    signature: update.signature,
  };
}

export function parseSingleRange(header, size) {
  if (header == null) return null;
  if (!Number.isSafeInteger(size) || size <= 0 || typeof header !== 'string') {
    return { unsatisfiable: true };
  }
  const match = /^bytes=(\d*)-(\d*)$/.exec(header);
  if (!match || (!match[1] && !match[2])) return { unsatisfiable: true };

  const total = BigInt(size);
  let start;
  let end;
  if (!match[1]) {
    const suffix = BigInt(match[2]);
    if (suffix === 0n) return { unsatisfiable: true };
    start = suffix >= total ? 0n : total - suffix;
    end = total - 1n;
  } else {
    start = BigInt(match[1]);
    if (start >= total) return { unsatisfiable: true };
    end = match[2] ? BigInt(match[2]) : total - 1n;
    if (end < start) return { unsatisfiable: true };
    if (end >= total) end = total - 1n;
  }

  const offset = Number(start);
  const length = Number(end - start + 1n);
  return { offset, length, contentRange: `bytes ${start}-${end}/${size}` };
}
