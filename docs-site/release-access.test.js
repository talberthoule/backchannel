import assert from 'node:assert/strict';
import test from 'node:test';

import {
  CHANGE_SESSION_TTL_SECONDS,
  PASSWORD_ITERATIONS,
  SESSION_COOKIE,
  SESSION_TTL_SECONDS,
  TEMPORARY_PASSWORD_TTL_SECONDS,
  createSessionToken,
  generateTemporaryPassword,
  hashPassword,
  loadReleaseCatalog,
  parseManifest,
  parsePlatformManifest,
  parseReleaseIdentity,
  parseSingleRange,
  releaseSummary,
  resolveEntitlements,
  verifyPassword,
} from './release-access.js';

const baseAsset = {
  id: 'windows-x64',
  platform: 'Windows x64',
  filename: 'Backchannel-windows-x64.zip',
  key: 'releases/v1.2.3/Backchannel-windows-x64.zip',
  size: 123,
  sha256: 'a'.repeat(64),
  content_type: 'application/zip',
};

const baseManifest = {
  version: 'v1.2.3',
  published_at: '2026-07-12T18:00:00Z',
  commit: 'b'.repeat(40),
  assets: [baseAsset],
};

const releaseIdentity = {
  version: 'v1.2.3',
  published_at: '2026-07-15T18:00:00Z',
  commit: 'b'.repeat(40),
};

const platformManifest = {
  version: 'v1.2.3',
  commit: releaseIdentity.commit,
  asset: baseAsset,
};

const trustedAssets = [
  baseAsset,
  {
    id: 'macos-arm64',
    platform: 'macOS arm64',
    filename: 'Backchannel-macos-arm64.zip',
    key: 'releases/v1.2.3/Backchannel-macos-arm64.zip',
    size: 456,
    sha256: 'c'.repeat(64),
    content_type: 'application/zip',
  },
  {
    id: 'linux-x64',
    platform: 'Linux x64',
    filename: 'Backchannel-linux-x64.tar.gz',
    key: 'releases/v1.2.3/Backchannel-linux-x64.tar.gz',
    size: 789,
    sha256: 'd'.repeat(64),
    content_type: 'application/gzip',
  },
];

function deterministicBytes(seed = 1) {
  let state = seed >>> 0;
  return (length) => {
    const bytes = new Uint8Array(length);
    for (let i = 0; i < length; i += 1) {
      state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
      bytes[i] = state >>> 24;
    }
    return bytes;
  };
}

function jsonObject(value) {
  return { json: async () => structuredClone(value) };
}

function manifestFor(version, overrides = {}) {
  return {
    ...baseManifest,
    version,
    assets: [{
      ...baseAsset,
      key: `releases/${version}/${baseAsset.filename}`,
    }],
    ...overrides,
  };
}

function progressiveBucket({ platformIds, invalidId, includeLegacy = false }) {
  const objects = new Map([
    [`releases/${releaseIdentity.version}/release.json`, jsonObject(releaseIdentity)],
    ...platformIds.map((platformId) => {
      const asset = trustedAssets.find(({ id }) => id === platformId);
      const value = {
        version: releaseIdentity.version,
        commit: platformId === invalidId ? 'c'.repeat(40) : releaseIdentity.commit,
        asset,
      };
      return [`releases/${releaseIdentity.version}/platforms/${platformId}.json`, jsonObject(value)];
    }),
    ...(includeLegacy ? [[
      `releases/${releaseIdentity.version}/manifest.json`, jsonObject(baseManifest),
    ]] : []),
    ['releases/latest.json', jsonObject({ version: releaseIdentity.version })],
  ]);
  return {
    async list() {
      return {
        objects: [...objects.keys()].map((key) => ({ key })),
        truncated: false,
      };
    },
    async get(key) { return objects.get(key) ?? null; },
  };
}

test('exports the fixed security constants', () => {
  assert.equal(PASSWORD_ITERATIONS, 600_000);
  assert.equal(TEMPORARY_PASSWORD_TTL_SECONDS, 259_200);
  assert.equal(CHANGE_SESSION_TTL_SECONDS, 1_800);
  assert.equal(SESSION_TTL_SECONDS, 604_800);
  assert.equal(SESSION_COOKIE, '__Host-backchannel_release');
});

test('temporary passwords meet the complete contract', () => {
  const seen = new Set();
  for (let i = 0; i < 10_000; i += 1) {
    const value = generateTemporaryPassword();
    assert.match(value, /^(?=.*[A-Z])(?=.*[a-z])(?=.*[2-9])(?=.*[!#$%&*+?@])[A-HJ-NP-Za-km-z2-9!#$%&*+?@]{20}$/);
    seen.add(value);
  }
  assert.equal(seen.size, 10_000);
});

test('temporary passwords support deterministic bytes and reject biased samples', () => {
  assert.equal(
    generateTemporaryPassword(deterministicBytes(42)),
    generateTemporaryPassword(deterministicBytes(42)),
  );

  let calls = 0;
  const source = (length) => {
    calls += 1;
    return calls === 1 ? new Uint8Array(length).fill(255) : deterministicBytes(7)(length);
  };
  assert.equal(generateTemporaryPassword(source).length, 20);
  assert.ok(calls > 1, 'values above the rejection limit must be discarded');
});

test('PBKDF2-HMAC-SHA256 matches a known vector', async () => {
  const record = await hashPassword('password', {
    salt: new TextEncoder().encode('salt'),
    iterations: 1,
  });
  assert.equal(record.hash, 'Eg-2z_z4syxD5yJSVsT4N6hlSMkszDVICAWYfLcL4Xs');
  assert.equal(record.salt, 'c2FsdA');
  assert.equal(record.iterations, 1);
});

test('600,000-iteration PBKDF2 does not use the capped Web Crypto implementation', async () => {
  const originalDeriveBits = globalThis.crypto.subtle.deriveBits;
  globalThis.crypto.subtle.deriveBits = async function cappedDeriveBits(algorithm, ...rest) {
    if (algorithm.iterations > 100_000) {
      throw new Error('Pbkdf2 failed: iteration counts above 100000 are not supported');
    }
    return originalDeriveBits.call(this, algorithm, ...rest);
  };
  try {
    const record = await hashPassword('cloudflare-native', {
      salt: new TextEncoder().encode('0123456789abcdef'),
    });
    assert.equal(record.hash, 'yYXBDzFSQhArwPC7oDV81iUdxV7zc6t7JfLedwugn0Y');
    assert.equal(record.iterations, 600_000);
  } finally {
    globalThis.crypto.subtle.deriveBits = originalDeriveBits;
  }
});

test('password hashes use unique 16-byte salts and verify only the right password', async () => {
  const first = await hashPassword('correct horse battery staple');
  const second = await hashPassword('correct horse battery staple');
  assert.notEqual(first.salt, second.salt);
  assert.equal(Buffer.from(first.salt, 'base64url').length, 16);
  assert.equal(Buffer.from(first.hash, 'base64url').length, 32);
  assert.equal(first.iterations, PASSWORD_ITERATIONS);
  assert.equal(await verifyPassword('correct horse battery staple', first), true);
  assert.equal(await verifyPassword('wrong', first), false);
});

test('password verification rejects malformed records after a fixed dummy derivation', async () => {
  const valid = await hashPassword('secret');
  const malformed = [
    null,
    {},
    { ...valid, salt: '***' },
    { ...valid, salt: 'AA' },
    { ...valid, hash: 'AA' },
    { ...valid, iterations: PASSWORD_ITERATIONS - 1 },
  ];

  let derivations = 0;
  const derive = (password, salt, iterations, length) => {
    derivations += 1;
    assert.equal(password instanceof Uint8Array, true);
    assert.equal(salt.byteLength, 16);
    assert.equal(iterations, PASSWORD_ITERATIONS);
    assert.equal(length, 32);
    return new Uint8Array(32);
  };
  for (const record of malformed) {
    assert.equal(await verifyPassword('secret', record, derive), false);
  }
  assert.equal(derivations, malformed.length);
});

test('sessions return separate 32-byte opaque tokens and SHA-256 hashes', async () => {
  const session = await createSessionToken(deterministicBytes(99));
  assert.notEqual(session.token, session.tokenHash);
  assert.equal(Buffer.from(session.token, 'base64url').length, 32);
  assert.equal(Buffer.from(session.tokenHash, 'base64url').length, 32);
  assert.deepEqual(session, await createSessionToken(deterministicBytes(99)));
});

test('manifest validation accepts every trusted release asset tuple', () => {
  assert.deepEqual(parseManifest({ ...baseManifest, assets: trustedAssets }), {
    ...baseManifest,
    assets: trustedAssets,
  });
  assert.deepEqual(parseManifest(baseManifest, 'v1.2.3'), baseManifest);
});

test('progressive metadata is exact and commit-pinned', () => {
  assert.deepEqual(parseReleaseIdentity(releaseIdentity, 'v1.2.3'), releaseIdentity);
  assert.deepEqual(
    parsePlatformManifest(platformManifest, 'v1.2.3', releaseIdentity.commit, 'windows-x64'),
    platformManifest,
  );
  assert.equal(parseReleaseIdentity({ ...releaseIdentity, extra: true }), null);
  assert.equal(parseReleaseIdentity({ ...releaseIdentity, version: 'v01.2.3' }), null);
  assert.equal(parsePlatformManifest(
    { ...platformManifest, commit: 'c'.repeat(40) },
    'v1.2.3', releaseIdentity.commit, 'windows-x64',
  ), null);
  assert.equal(parsePlatformManifest(
    { ...platformManifest, asset: { ...baseAsset, id: 'linux-x64' } },
    'v1.2.3', releaseIdentity.commit, 'windows-x64',
  ), null);
});

test('manifest validation rejects malformed or untrusted content', () => {
  const cases = [
    null,
    'not an object',
    { ...baseManifest, version: '1.2.3' },
    { ...baseManifest, version: 'v1.2' },
    { ...baseManifest, published_at: '2026-07-12T18:00:00-05:00' },
    { ...baseManifest, published_at: '2026-02-30T18:00:00Z' },
    { ...baseManifest, commit: 'A'.repeat(40) },
    { ...baseManifest, assets: [] },
    { ...baseManifest, assets: [{ ...baseAsset, id: 'unknown' }] },
    { ...baseManifest, assets: [{ ...baseAsset, platform: 'Windows' }] },
    { ...baseManifest, assets: [{ ...baseAsset, filename: '../Backchannel-windows-x64.zip' }] },
    { ...baseManifest, assets: [{ ...baseAsset, key: '../secret' }] },
    { ...baseManifest, assets: [{ ...baseAsset, key: `releases/v9.9.9/${baseAsset.filename}` }] },
    { ...baseManifest, assets: [{ ...baseAsset, size: 0 }] },
    { ...baseManifest, assets: [{ ...baseAsset, size: Number.MAX_SAFE_INTEGER + 1 }] },
    { ...baseManifest, assets: [{ ...baseAsset, sha256: 'A'.repeat(64) }] },
    { ...baseManifest, assets: [{ ...baseAsset, content_type: 'text/html' }] },
    { ...baseManifest, assets: [baseAsset, { ...baseAsset }] },
    { ...baseManifest, assets: [baseAsset, { ...trustedAssets[1], id: baseAsset.id }] },
    { ...baseManifest, assets: [baseAsset, { ...trustedAssets[1], filename: baseAsset.filename }] },
  ];

  for (const value of cases) assert.equal(parseManifest(value), null);
  assert.equal(parseManifest(baseManifest, 'v1.2.4'), null);
});

test('manifest validation rejects leading-zero version aliases', () => {
  const version = 'v01.2.3';
  const manifest = {
    ...baseManifest,
    version,
    assets: [{ ...baseAsset, key: `releases/${version}/${baseAsset.filename}` }],
  };
  assert.equal(parseManifest(manifest), null);
  assert.equal(parseManifest(manifest, version), null);
  assert.equal(parseManifest(baseManifest, version), null);
});

test('canonical versions enforce the 32-character boundary', () => {
  const accepted = `v${'1'.repeat(10)}.${'2'.repeat(9)}.${'3'.repeat(10)}`;
  const rejected = `${accepted}4`;
  const manifest = (version) => ({
    ...baseManifest,
    version,
    assets: [{ ...baseAsset, key: `releases/${version}/${baseAsset.filename}` }],
  });

  assert.equal(accepted.length, 32);
  assert.equal(rejected.length, 33);
  assert.deepEqual(parseManifest(manifest(accepted)), manifest(accepted));
  assert.equal(parseManifest(manifest(rejected)), null);
  assert.deepEqual(
    resolveEntitlements({ include_latest: 0 }, [accepted], {
      latestVersion: null,
      manifests: new Map([[accepted, manifest(accepted)]]),
    }),
    [manifest(accepted)],
  );
  assert.deepEqual(
    resolveEntitlements({ include_latest: 0 }, [rejected], {
      latestVersion: null,
      manifests: new Map([[rejected, manifest(rejected)]]),
    }),
    [],
  );
});

test('release catalog paginates, ignores untrusted keys, and returns generic diagnostics', async () => {
  const calls = { list: [], get: [] };
  const valid = manifestFor('v1.2.3');
  const objects = new Map([
    ['releases/v1.2.3/manifest.json', jsonObject(valid)],
    ['releases/v2.0.0/manifest.json', jsonObject({ ...manifestFor('v2.0.0'), assets: [] })],
    ['releases/latest.json', jsonObject({ version: 'v1.2.3' })],
  ]);
  const bucket = {
    async list(options) {
      calls.list.push(options);
      if (!options.cursor) return {
        objects: [
          { key: 'releases/v1.2.3/manifest.json' },
          { key: 'releases/v1.2.3/private.txt' },
          { key: 'releases/../manifest.json' },
        ],
        truncated: true,
        cursor: 'page-2',
      };
      return {
        objects: [{ key: 'releases/v2.0.0/manifest.json' }],
        truncated: false,
      };
    },
    async get(key) {
      calls.get.push(key);
      return objects.get(key) ?? null;
    },
  };

  const catalog = await loadReleaseCatalog(bucket);
  assert.deepEqual(calls.list, [
    { prefix: 'releases/', cursor: undefined },
    { prefix: 'releases/', cursor: 'page-2' },
  ]);
  assert.deepEqual(calls.get, [
    'releases/v1.2.3/manifest.json',
    'releases/v2.0.0/manifest.json',
    'releases/latest.json',
  ]);
  assert.equal(catalog.latestVersion, 'v1.2.3');
  assert.deepEqual([...catalog.manifests.keys()], ['v1.2.3']);
  assert.deepEqual(catalog.diagnostics, ['manifest-invalid']);
  assert.ok(catalog.diagnostics.every((value) => !value.includes('releases/')));
});

test('progressive catalog exposes one, two, or three completed platforms', async () => {
  for (const platformIds of [
    ['windows-x64'],
    ['windows-x64', 'linux-x64'],
    ['macos-arm64', 'linux-x64', 'windows-x64'],
  ]) {
    const catalog = await loadReleaseCatalog(progressiveBucket({ platformIds }));
    assert.equal(catalog.latestVersion, 'v1.2.3');
    assert.deepEqual(
      catalog.manifests.get('v1.2.3').assets.map(({ id }) => id).sort(),
      [...platformIds].sort(),
    );
  }
});

test('anchor alone is hidden and invalid sibling does not hide valid assets', async () => {
  const empty = await loadReleaseCatalog(progressiveBucket({ platformIds: [] }));
  assert.equal(empty.manifests.has('v1.2.3'), false);
  const partial = await loadReleaseCatalog(progressiveBucket({
    platformIds: ['windows-x64', 'linux-x64'], invalidId: 'linux-x64',
  }));
  assert.deepEqual(partial.manifests.get('v1.2.3').assets.map(({ id }) => id), ['windows-x64']);
  assert.ok(partial.diagnostics.includes('platform-invalid'));
});

test('legacy and progressive metadata conflict fails closed for the version', async () => {
  const catalog = await loadReleaseCatalog(progressiveBucket({
    platformIds: ['windows-x64'], includeLegacy: true,
  }));
  assert.equal(catalog.manifests.has('v1.2.3'), false);
  assert.ok(catalog.diagnostics.includes('manifest-conflict'));
});

test('release catalog follows Latest changes while retaining valid history', async () => {
  let latest = 'v1.0.0';
  const versions = ['v1.0.0', 'v1.1.0'];
  const bucket = {
    async list() {
      return {
        objects: versions.map((version) => ({ key: `releases/${version}/manifest.json` })),
        truncated: false,
      };
    },
    async get(key) {
      if (key === 'releases/latest.json') return jsonObject({ version: latest });
      const version = key.split('/')[1];
      return jsonObject(manifestFor(version));
    },
  };

  const first = await loadReleaseCatalog(bucket);
  latest = 'v1.1.0';
  const second = await loadReleaseCatalog(bucket);
  assert.equal(first.latestVersion, 'v1.0.0');
  assert.equal(second.latestVersion, 'v1.1.0');
  assert.deepEqual([...second.manifests.keys()], versions);
});

test('release catalog rejects missing, malformed, or unknown Latest generically', async () => {
  for (const latestObject of [null, jsonObject({}), jsonObject({ version: 'v9.9.9' })]) {
    const bucket = {
      async list() { return { objects: [], truncated: false }; },
      async get() { return latestObject; },
    };
    const catalog = await loadReleaseCatalog(bucket);
    assert.equal(catalog.latestVersion, null);
    assert.deepEqual(catalog.diagnostics, ['latest-invalid']);
  }
});

test('release catalog ignores leading-zero manifest keys and Latest aliases', async () => {
  const version = 'v01.2.3';
  const bucket = {
    async list() {
      return { objects: [{ key: `releases/${version}/manifest.json` }], truncated: false };
    },
    async get(key) {
      if (key === 'releases/latest.json') return jsonObject({ version });
      return jsonObject(manifestFor(version));
    },
  };
  const catalog = await loadReleaseCatalog(bucket);
  assert.equal(catalog.latestVersion, null);
  assert.deepEqual([...catalog.manifests.keys()], []);
});

test('entitlements combine dynamic Latest and valid grants newest-first without duplicates', () => {
  const catalog = {
    latestVersion: 'v2.0.0',
    manifests: new Map([
      ['v1.9.10', manifestFor('v1.9.10')],
      ['v1.10.0', manifestFor('v1.10.0')],
      ['v2.0.0', manifestFor('v2.0.0')],
    ]),
  };
  assert.deepEqual(
    resolveEntitlements(
      { include_latest: 1 },
      ['v1.9.10', 'v2.0.0', 'missing', null, 'v1.10.0', 'v1.9.10'],
      catalog,
    ).map(({ version }) => version),
    ['v2.0.0', 'v1.10.0', 'v1.9.10'],
  );
  assert.deepEqual(
    resolveEntitlements({ include_latest: 0 }, ['v1.9.10'], catalog).map(({ version }) => version),
    ['v1.9.10'],
  );
});

test('entitlements reject leading-zero version aliases even from a supplied catalog', () => {
  const version = 'v01.2.3';
  const catalog = {
    latestVersion: version,
    manifests: new Map([[version, manifestFor(version)]]),
  };
  assert.deepEqual(resolveEntitlements({ include_latest: 1 }, [version], catalog), []);
});

test('release summaries expose recipient fields without trusted storage metadata', () => {
  const summary = releaseSummary({ ...baseManifest, assets: trustedAssets });
  assert.deepEqual(summary, {
    version: 'v1.2.3',
    published_at: '2026-07-12T18:00:00Z',
    assets: trustedAssets.map(({ id, platform, filename, size, sha256 }) => ({
      id, platform, filename, size, sha256,
    })),
  });
  assert.equal(JSON.stringify(summary).includes('releases/'), false);
  assert.equal(JSON.stringify(summary).includes('content_type'), false);
  assert.equal(JSON.stringify(summary).includes(baseManifest.commit), false);
});

test('single byte ranges parse all supported shapes', () => {
  const cases = [
    [null, 100, null],
    ['bytes=0-9', 100, { offset: 0, length: 10, contentRange: 'bytes 0-9/100' }],
    ['bytes=90-200', 100, { offset: 90, length: 10, contentRange: 'bytes 90-99/100' }],
    ['bytes=25-', 100, { offset: 25, length: 75, contentRange: 'bytes 25-99/100' }],
    ['bytes=-10', 100, { offset: 90, length: 10, contentRange: 'bytes 90-99/100' }],
    ['bytes=-200', 100, { offset: 0, length: 100, contentRange: 'bytes 0-99/100' }],
  ];
  for (const [header, size, expected] of cases) {
    assert.deepEqual(parseSingleRange(header, size), expected, header);
  }
});

test('single byte ranges reject invalid, multiple, and out-of-bounds values', () => {
  const invalid = [
    '',
    'items=0-1',
    'bytes=0-1,5-6',
    'bytes=-',
    'bytes=10-9',
    'bytes=100-',
    'bytes=-0',
    'bytes=1.5-2',
    'bytes=+1-2',
  ];
  for (const header of invalid) {
    assert.deepEqual(parseSingleRange(header, 100), { unsatisfiable: true }, header);
  }
  assert.deepEqual(parseSingleRange('bytes=0-1', 0), { unsatisfiable: true });
});
