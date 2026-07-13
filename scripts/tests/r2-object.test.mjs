import assert from 'node:assert/strict';
import {execFile} from 'node:child_process';
import * as fs from 'node:fs';
import {mkdtemp, readFile, readdir, rm, writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {promisify} from 'node:util';
import test from 'node:test';

import {
  EXIT_NOT_FOUND,
  EXIT_PRECONDITION_FAILED,
  EXIT_USAGE,
  buildObjectUrl,
  createR2Client,
  main,
  signRequest,
} from '../r2-object.mjs';

const ACCOUNT_ID = '0123456789abcdef0123456789abcdef';
const BUCKET = 'backchannel-desktop-releases';
const NOW = new Date('2026-07-12T15:04:05.000Z');
const CREDENTIALS = {
  CLOUDFLARE_ACCOUNT_ID: ACCOUNT_ID,
  R2_ACCESS_KEY_ID: 'R2TESTACCESS',
  R2_SECRET_ACCESS_KEY: 'r2-test-secret',
};
const EMPTY_HASH = 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855';
const execFileAsync = promisify(execFile);

test('exports stable exit codes', () => {
  assert.equal(EXIT_NOT_FOUND, 44);
  assert.equal(EXIT_PRECONDITION_FAILED, 42);
  assert.equal(EXIT_USAGE, 2);
});

test('buildObjectUrl cannot redirect credentials away from Cloudflare', () => {
  const url = buildObjectUrl(
    ACCOUNT_ID,
    BUCKET,
    'releases/v0.2.1/Backchannel macos.zip',
  );
  assert.equal(url.origin, `https://${ACCOUNT_ID}.r2.cloudflarestorage.com`);
  assert.equal(url.pathname, `/${BUCKET}/releases/v0.2.1/Backchannel%20macos.zip`);
  assert.equal(url.search, '');
});

test('buildObjectUrl applies RFC 3986 path escaping', () => {
  assert.equal(
    buildObjectUrl(ACCOUNT_ID, BUCKET, "releases/!file'()*.zip").pathname,
    `/${BUCKET}/releases/%21file%27%28%29%2A.zip`,
  );
});

for (const [label, accountId, bucket, key] of [
  ['short account ID', '0123', BUCKET, 'releases/latest.json'],
  ['uppercase account ID', ACCOUNT_ID.toUpperCase(), BUCKET, 'releases/latest.json'],
  ['bucket with uppercase letters', ACCOUNT_ID, 'Release-Bucket', 'releases/latest.json'],
  ['bucket beginning with a hyphen', ACCOUNT_ID, '-release-bucket', 'releases/latest.json'],
  ['IP-form bucket', ACCOUNT_ID, '192.168.0.1', 'releases/latest.json'],
  ['empty key', ACCOUNT_ID, BUCKET, ''],
  ['empty key segment', ACCOUNT_ID, BUCKET, 'releases//latest.json'],
  ['relative dot segment', ACCOUNT_ID, BUCKET, 'releases/./latest.json'],
  ['relative parent segment', ACCOUNT_ID, BUCKET, 'releases/../latest.json'],
]) {
  test(`buildObjectUrl rejects ${label}`, () => {
    assert.throws(() => buildObjectUrl(accountId, bucket, key), TypeError);
  });
}

test('signRequest produces deterministic Cloudflare wire authorization', () => {
  const original = new Headers({'Content-Type': '  application/zip  '});
  const signed = signRequest({
    method: 'PUT',
    url: buildObjectUrl(ACCOUNT_ID, BUCKET, 'releases/v0.2.1/Backchannel macos.zip'),
    headers: original,
    payloadHash: EMPTY_HASH,
    credentials: {accessKeyId: 'R2TESTACCESS', secretAccessKey: 'r2-test-secret'},
    now: NOW,
  });

  assert.notEqual(signed, original);
  assert.equal(original.has('authorization'), false);
  assert.equal(signed.get('x-amz-date'), '20260712T150405Z');
  assert.equal(signed.get('x-amz-content-sha256'), EMPTY_HASH);
  assert.equal(
    signed.get('authorization'),
    'AWS4-HMAC-SHA256 Credential=R2TESTACCESS/20260712/auto/s3/aws4_request, '
      + 'SignedHeaders=content-type;host;x-amz-content-sha256;x-amz-date, '
      + 'Signature=c192cacb79344369124b1060ec846a9debed1490e306d80c87dae8b123d332b3',
  );
});

test('signRequest rejects non-lowercase SHA-256 payload hashes', () => {
  assert.throws(() => signRequest({
    method: 'HEAD',
    url: buildObjectUrl(ACCOUNT_ID, BUCKET, 'releases/latest.json'),
    headers: {},
    payloadHash: EMPTY_HASH.toUpperCase(),
    credentials: {accessKeyId: 'R2TESTACCESS', secretAccessKey: 'r2-test-secret'},
    now: NOW,
  }), TypeError);
});

async function expectUsage(argv, env = CREDENTIALS) {
  const stdout = [];
  const stderr = [];
  const code = await main(argv, {
    env,
    fetchImpl: async () => { throw new Error('fetch must not run'); },
    now: () => NOW,
    stdout: value => stdout.push(value),
    stderr: value => stderr.push(value),
  });
  assert.equal(code, EXIT_USAGE);
  assert.deepEqual(stdout, []);
  assert.deepEqual(JSON.parse(stderr.join('')), {error: 'invalid arguments'});
}

for (const [label, argv] of [
  ['missing HEAD flags', ['head']],
  ['missing GET output', ['get', '--bucket', BUCKET, '--key', 'releases/latest.json']],
  ['missing PUT content type', ['put', '--bucket', BUCKET, '--key', 'releases/latest.json', '--file', 'latest.json']],
  ['unknown operation', ['delete', '--bucket', BUCKET, '--key', 'releases/latest.json']],
  ['unknown flag', ['head', '--bucket', BUCKET, '--key', 'releases/latest.json', '--quiet']],
  ['conflicting conditions', ['put', '--bucket', BUCKET, '--key', 'releases/latest.json', '--file', 'latest.json', '--content-type', 'application/json', '--if-none-match', '*', '--if-match', '"etag"']],
  ['invalid if-none-match value', ['put', '--bucket', BUCKET, '--key', 'releases/latest.json', '--file', 'latest.json', '--content-type', 'application/json', '--if-none-match', 'anything']],
]) {
  test(`main rejects ${label}`, async () => expectUsage(argv));
}

test('usage errors are distinct from R2 response failures', async () => {
  await expectUsage(['head']);
});

test('main rejects absent Cloudflare credentials', async () => {
  await expectUsage(
    ['head', '--bucket', BUCKET, '--key', 'releases/latest.json'],
    {CLOUDFLARE_ACCOUNT_ID: ACCOUNT_ID},
  );
});

function clientFor(fetchImpl) {
  return createR2Client({env: CREDENTIALS, fetchImpl, now: () => NOW, fsImpl: fs});
}

async function temporaryDirectory(t) {
  const directory = await mkdtemp(join(tmpdir(), 'backchannel-r2-object-'));
  t.after(() => rm(directory, {recursive: true, force: true}));
  return directory;
}

test('HEAD uses only the signed Cloudflare URL and normalizes metadata', async () => {
  let request;
  const client = clientFor(async (url, init) => {
    request = {url, init};
    return new Response(null, {
      status: 200,
      headers: {
        ETag: '"release-etag"',
        'Content-Length': '12345',
        'Content-Type': 'application/json',
      },
    });
  });

  assert.deepEqual(await client.head({bucket: BUCKET, key: 'releases/latest.json'}), {
    etag: '"release-etag"',
    contentLength: 12345,
    contentType: 'application/json',
  });
  assert.equal(request.url.href, `https://${ACCOUNT_ID}.r2.cloudflarestorage.com/${BUCKET}/releases/latest.json`);
  assert.equal(request.init.method, 'HEAD');
  assert.match(request.init.headers.get('authorization'), /Credential=R2TESTACCESS\/20260712\/auto\/s3\/aws4_request/);
  assert.equal(request.init.headers.get('x-amz-content-sha256'), EMPTY_HASH);
});

test('HEAD maps missing or malformed metadata to null without changing quoted ETags', async () => {
  for (const [headers, expected] of [
    [{ETag: '"quoted"', 'Content-Length': '12x'}, {etag: '"quoted"', contentLength: null, contentType: null}],
    [{}, {etag: null, contentLength: null, contentType: null}],
  ]) {
    const client = clientFor(async () => new Response(null, {status: 200, headers}));
    assert.deepEqual(await client.head({bucket: BUCKET, key: 'releases/latest.json'}), expected);
  }
});

test('PUT streams multiple chunks with exact metadata, length, hash, and create condition', async t => {
  const directory = await temporaryDirectory(t);
  const source = join(directory, 'release.zip');
  const bytes = Buffer.alloc(200_000, 0x5a);
  await writeFile(source, bytes);
  let chunks = 0;
  let uploaded;

  const client = clientFor(async (url, init) => {
    const parts = [];
    for await (const chunk of init.body) {
      chunks += 1;
      parts.push(chunk);
    }
    uploaded = Buffer.concat(parts);
    assert.equal(url.origin, `https://${ACCOUNT_ID}.r2.cloudflarestorage.com`);
    assert.equal(init.method, 'PUT');
    assert.equal(init.duplex, 'half');
    assert.equal(init.headers.get('content-type'), 'application/zip');
    assert.equal(init.headers.get('content-disposition'), 'attachment; filename="release.zip"');
    assert.equal(init.headers.get('cache-control'), 'private, no-store');
    assert.equal(init.headers.get('content-length'), String(bytes.length));
    assert.equal(init.headers.get('if-none-match'), '*');
    assert.equal(init.headers.get('if-match'), null);
    assert.equal(
      init.headers.get('x-amz-content-sha256'),
      '38b2f7cf459e18e9f488b5164cd553ba6c0dc286df97c0121e319ca601730362',
    );
    return new Response(null, {status: 200, headers: {ETag: '"new-etag"'}});
  });

  assert.deepEqual(await client.put({
    bucket: BUCKET,
    key: 'releases/v0.2.1/release.zip',
    file: source,
    contentType: 'application/zip',
    contentDisposition: 'attachment; filename="release.zip"',
    cacheControl: 'private, no-store',
    ifNoneMatch: '*',
  }), {etag: '"new-etag"'});
  assert.ok(chunks > 1);
  assert.deepEqual(uploaded, bytes);
});

test('PUT sends an exact quoted If-Match condition', async t => {
  const directory = await temporaryDirectory(t);
  const source = join(directory, 'latest.json');
  await writeFile(source, '{}');
  const client = clientFor(async (_url, init) => {
    assert.equal(init.headers.get('if-match'), '"old-etag"');
    assert.equal(init.headers.get('if-none-match'), null);
    for await (const _chunk of init.body) {}
    return new Response(null, {status: 200});
  });
  assert.deepEqual(await client.put({
    bucket: BUCKET,
    key: 'releases/latest.json',
    file: source,
    contentType: 'application/json',
    ifMatch: '"old-etag"',
  }), {etag: null});
});

test('GET preserves the old destination until the complete body is atomically replaced', async t => {
  const directory = await temporaryDirectory(t);
  const output = join(directory, 'latest.json');
  await writeFile(output, 'old destination');
  let observedOldDestination = false;
  let pull = 0;
  const body = new ReadableStream({
    async pull(controller) {
      pull += 1;
      if (pull === 1) {
        controller.enqueue(new TextEncoder().encode('new '));
        return;
      }
      observedOldDestination = (await readFile(output, 'utf8')) === 'old destination';
      controller.enqueue(new TextEncoder().encode('destination'));
      controller.close();
    },
  });
  const client = clientFor(async () => new Response(body, {
    status: 200,
    headers: {ETag: '"download-etag"', 'Content-Length': '15', 'Content-Type': 'application/json'},
  }));

  assert.deepEqual(await client.get({bucket: BUCKET, key: 'releases/latest.json', output}), {
    etag: '"download-etag"',
    contentLength: 15,
    contentType: 'application/json',
    output,
  });
  assert.equal(observedOldDestination, true);
  assert.equal(await readFile(output, 'utf8'), 'new destination');
  assert.deepEqual(await readdir(directory), ['latest.json']);
});

test('GET stream failure preserves the old destination and removes its sibling temporary file', async t => {
  const directory = await temporaryDirectory(t);
  const output = join(directory, 'latest.json');
  await writeFile(output, 'old destination');
  const body = new ReadableStream({
    start(controller) {
      controller.enqueue(new TextEncoder().encode('partial'));
      controller.error(new Error('stream contains sensitive body details'));
    },
  });
  const client = clientFor(async () => new Response(body, {status: 200}));

  await assert.rejects(client.get({bucket: BUCKET, key: 'releases/latest.json', output}));
  assert.equal(await readFile(output, 'utf8'), 'old destination');
  assert.deepEqual(await readdir(directory), ['latest.json']);
});

test('successful main writes the exact compact HEAD JSON contract', async () => {
  const stdout = [];
  const stderr = [];
  const code = await main(
    ['head', '--bucket', BUCKET, '--key', 'releases/latest.json'],
    {
      env: CREDENTIALS,
      fetchImpl: async () => new Response(null, {
        status: 200,
        headers: {ETag: '"etag"', 'Content-Length': '2', 'Content-Type': 'application/json'},
      }),
      now: () => NOW,
      stdout: value => stdout.push(value),
      stderr: value => stderr.push(value),
    },
  );
  assert.equal(code, 0);
  assert.equal(stdout.join(''), '{"etag":"\\"etag\\"","contentLength":2,"contentType":"application/json"}\n');
  assert.deepEqual(stderr, []);
});

test('HTTP status contracts are stable and redacted', async () => {
  for (const [status, expected] of [[404, 44], [412, 42], [403, 1], [500, 1]]) {
    const stderr = [];
    const code = await main(
      ['head', '--bucket', BUCKET, '--key', 'releases/latest.json'],
      {
        env: CREDENTIALS,
        fetchImpl: async () => new Response('sensitive vendor prose', {status}),
        now: () => NOW,
        stderr: value => stderr.push(value),
      },
    );
    assert.equal(code, expected);
    assert.deepEqual(JSON.parse(stderr.join('')), {error: 'request failed', status});
    assert.doesNotMatch(stderr.join(''), /sensitive|R2TESTACCESS|r2-test-secret|authorization/i);
  }
});

test('fetch rejection is generic and redacts error text, credentials, authorization, and URLs', async () => {
  const stderr = [];
  const code = await main(
    ['head', '--bucket', BUCKET, '--key', 'releases/latest.json'],
    {
      env: CREDENTIALS,
      fetchImpl: async () => {
        throw new Error(`Authorization R2TESTACCESS r2-test-secret https://${ACCOUNT_ID}.example.invalid/?signed=secret`);
      },
      now: () => NOW,
      stderr: value => stderr.push(value),
    },
  );
  assert.equal(code, 1);
  assert.deepEqual(JSON.parse(stderr.join('')), {error: 'request failed'});
  assert.doesNotMatch(stderr.join(''), /R2TESTACCESS|r2-test-secret|authorization|signed|https?:/i);
});

test('the executable module returns the usage contract without import side effects', async () => {
  const script = fileURLToPath(new URL('../r2-object.mjs', import.meta.url));
  await assert.rejects(
    execFileAsync(process.execPath, [script, 'head'], {env: CREDENTIALS}),
    error => {
      assert.equal(error.code, EXIT_USAGE);
      assert.equal(error.stdout, '');
      assert.equal(error.stderr, '{"error":"invalid arguments"}\n');
      return true;
    },
  );
});
