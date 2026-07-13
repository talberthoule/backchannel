import {createHash, createHmac, randomUUID} from 'node:crypto';
import * as defaultFs from 'node:fs';
import {basename, dirname, join} from 'node:path';
import {Readable} from 'node:stream';
import {pipeline} from 'node:stream/promises';
import {pathToFileURL} from 'node:url';

export const EXIT_NOT_FOUND = 44;
export const EXIT_PRECONDITION_FAILED = 42;
export const EXIT_USAGE = 2;

const ACCOUNT_ID_PATTERN = /^[0-9a-f]{32}$/;
const PAYLOAD_HASH_PATTERN = /^[0-9a-f]{64}$/;
const BUCKET_PATTERN = /^[a-z0-9](?:[a-z0-9.-]{1,61}[a-z0-9])$/;

function encodeSegment(value) {
  return encodeURIComponent(value).replace(/[!'()*]/g, character =>
    `%${character.charCodeAt(0).toString(16).toUpperCase()}`);
}

function validBucket(bucket) {
  return BUCKET_PATTERN.test(bucket)
    && !bucket.includes('..')
    && !bucket.includes('.-')
    && !bucket.includes('-.')
    && !/^\d{1,3}(?:\.\d{1,3}){3}$/.test(bucket);
}

export function buildObjectUrl(accountId, bucket, key) {
  const segments = typeof key === 'string' ? key.split('/') : [];
  if (!ACCOUNT_ID_PATTERN.test(accountId)
      || !validBucket(bucket)
      || segments.length === 0
      || segments.some(segment => segment === '' || segment === '.' || segment === '..')) {
    throw new TypeError('invalid R2 object address');
  }
  const path = [bucket, ...segments].map(encodeSegment).join('/');
  return new URL(`https://${accountId}.r2.cloudflarestorage.com/${path}`);
}

function sha256(value) {
  return createHash('sha256').update(value).digest('hex');
}

function hmac(key, value) {
  return createHmac('sha256', key).update(value).digest();
}

function canonicalQuery(url) {
  const compare = (left, right) => left < right ? -1 : left > right ? 1 : 0;
  return [...url.searchParams]
    .map(([name, value]) => [encodeSegment(name), encodeSegment(value)])
    .sort(([leftName, leftValue], [rightName, rightValue]) =>
      compare(leftName, rightName) || compare(leftValue, rightValue))
    .map(([name, value]) => `${name}=${value}`)
    .join('&');
}

export function signRequest({method, url, headers, payloadHash, credentials, now}) {
  if (!(url instanceof URL)
      || url.protocol !== 'https:'
      || !ACCOUNT_ID_PATTERN.test(url.hostname.split('.')[0])
      || !url.hostname.endsWith('.r2.cloudflarestorage.com')
      || !PAYLOAD_HASH_PATTERN.test(payloadHash)
      || !credentials?.accessKeyId
      || !credentials?.secretAccessKey
      || !(now instanceof Date)
      || Number.isNaN(now.valueOf())) {
    throw new TypeError('invalid signing input');
  }

  const signed = new Headers(headers);
  signed.delete('authorization');
  const timestamp = now.toISOString().replace(/[:-]|\.\d{3}/g, '');
  const date = timestamp.slice(0, 8);
  signed.set('host', url.host);
  signed.set('x-amz-content-sha256', payloadHash);
  signed.set('x-amz-date', timestamp);

  const canonical = [...signed]
    .map(([name, value]) => [name.toLowerCase(), value.trim().replace(/\s+/g, ' ')])
    .sort(([left], [right]) => left < right ? -1 : left > right ? 1 : 0);
  const canonicalHeaders = canonical.map(([name, value]) => `${name}:${value}\n`).join('');
  const signedHeaders = canonical.map(([name]) => name).join(';');
  const canonicalRequest = [
    method.toUpperCase(),
    url.pathname,
    canonicalQuery(url),
    canonicalHeaders,
    signedHeaders,
    payloadHash,
  ].join('\n');
  const scope = `${date}/auto/s3/aws4_request`;
  const stringToSign = `AWS4-HMAC-SHA256\n${timestamp}\n${scope}\n${sha256(canonicalRequest)}`;
  const signingKey = hmac(
    hmac(hmac(hmac(`AWS4${credentials.secretAccessKey}`, date), 'auto'), 's3'),
    'aws4_request',
  );
  const signature = createHmac('sha256', signingKey).update(stringToSign).digest('hex');
  signed.set(
    'authorization',
    `AWS4-HMAC-SHA256 Credential=${credentials.accessKeyId}/${scope}, SignedHeaders=${signedHeaders}, Signature=${signature}`,
  );
  return signed;
}

class RequestError extends Error {
  constructor(status) {
    super('request failed');
    this.status = status;
  }
}

function metadata(response) {
  const rawLength = response.headers.get('content-length');
  const contentLength = /^\d+$/.test(rawLength ?? '') ? Number(rawLength) : null;
  return {
    etag: response.headers.get('etag'),
    contentLength: Number.isSafeInteger(contentLength) ? contentLength : null,
    contentType: response.headers.get('content-type'),
  };
}

async function hashFile(fsImpl, file) {
  const hash = createHash('sha256');
  for await (const chunk of fsImpl.createReadStream(file)) hash.update(chunk);
  return hash.digest('hex');
}

export function createR2Client({
  env,
  fetchImpl = globalThis.fetch,
  now = () => new Date(),
  fsImpl = defaultFs,
}) {
  const accountId = env?.CLOUDFLARE_ACCOUNT_ID;
  const credentials = {
    accessKeyId: env?.R2_ACCESS_KEY_ID,
    secretAccessKey: env?.R2_SECRET_ACCESS_KEY,
  };
  if (!ACCOUNT_ID_PATTERN.test(accountId)
      || !credentials.accessKeyId
      || !credentials.secretAccessKey
      || typeof fetchImpl !== 'function') {
    throw new TypeError('invalid R2 client configuration');
  }

  async function request(method, bucket, key, headers, payloadHash, body) {
    const url = buildObjectUrl(accountId, bucket, key);
    const signed = signRequest({
      method,
      url,
      headers,
      payloadHash,
      credentials,
      now: typeof now === 'function' ? now() : now,
    });
    const init = {method, headers: signed, redirect: 'error'};
    if (body) Object.assign(init, {body, duplex: 'half'});
    const response = await fetchImpl(url, init);
    if (!response.ok) throw new RequestError(response.status);
    return response;
  }

  return {
    async head({bucket, key}) {
      return metadata(await request('HEAD', bucket, key, {}, EMPTY_PAYLOAD_HASH));
    },

    async get({bucket, key, output}) {
      const response = await request('GET', bucket, key, {}, EMPTY_PAYLOAD_HASH);
      if (!response.body) throw new RequestError();
      const temporary = join(dirname(output), `.${basename(output)}.${randomUUID()}.tmp`);
      try {
        await pipeline(
          Readable.fromWeb(response.body),
          fsImpl.createWriteStream(temporary, {flags: 'wx'}),
        );
        await fsImpl.promises.rename(temporary, output);
      } catch (error) {
        await fsImpl.promises.rm(temporary, {force: true});
        throw error;
      }
      return {...metadata(response), output};
    },

    async put({
      bucket,
      key,
      file,
      contentType,
      contentDisposition,
      cacheControl,
      ifNoneMatch,
      ifMatch,
    }) {
      if ((ifNoneMatch && ifNoneMatch !== '*') || (ifNoneMatch && ifMatch)) {
        throw new TypeError('invalid write condition');
      }
      const [{size}, payloadHash] = await Promise.all([
        fsImpl.promises.stat(file),
        hashFile(fsImpl, file),
      ]);
      const headers = new Headers({
        'content-length': String(size),
        'content-type': contentType,
      });
      if (contentDisposition) headers.set('content-disposition', contentDisposition);
      if (cacheControl) headers.set('cache-control', cacheControl);
      if (ifNoneMatch) headers.set('if-none-match', ifNoneMatch);
      if (ifMatch) headers.set('if-match', ifMatch);
      const response = await request(
        'PUT',
        bucket,
        key,
        headers,
        payloadHash,
        fsImpl.createReadStream(file),
      );
      return {etag: response.headers.get('etag')};
    },
  };
}

const EMPTY_PAYLOAD_HASH = sha256('');

function parseArguments(argv) {
  const operation = argv[0];
  const allowed = {
    head: new Set(['bucket', 'key']),
    get: new Set(['bucket', 'key', 'output']),
    put: new Set([
      'bucket', 'key', 'file', 'content-type', 'content-disposition', 'cache-control',
      'if-none-match', 'if-match',
    ]),
  }[operation];
  if (!allowed || argv.length % 2 === 0) return null;

  const options = {};
  for (let index = 1; index < argv.length; index += 2) {
    const flag = argv[index];
    const value = argv[index + 1];
    const name = flag?.startsWith('--') ? flag.slice(2) : '';
    if (!allowed.has(name) || !value || value.startsWith('--') || name in options) return null;
    options[name] = value;
  }

  const required = operation === 'head'
    ? ['bucket', 'key']
    : operation === 'get'
      ? ['bucket', 'key', 'output']
      : ['bucket', 'key', 'file', 'content-type'];
  if (required.some(name => !options[name])
      || (options['if-none-match'] && options['if-none-match'] !== '*')
      || (options['if-none-match'] && options['if-match'])) return null;
  return {operation, options};
}

function writeJson(write, value) {
  write(`${JSON.stringify(value)}\n`);
}

export async function main(argv, dependencies = {}) {
  const env = dependencies.env ?? process.env;
  const stdout = dependencies.stdout ?? (value => process.stdout.write(value));
  const stderr = dependencies.stderr ?? (value => process.stderr.write(value));
  const parsed = parseArguments(argv);
  try {
    if (!parsed
        || !env.CLOUDFLARE_ACCOUNT_ID?.trim()
        || !env.R2_ACCESS_KEY_ID?.trim()
        || !env.R2_SECRET_ACCESS_KEY?.trim()) {
      throw new TypeError('invalid arguments');
    }
    buildObjectUrl(env.CLOUDFLARE_ACCOUNT_ID, parsed.options.bucket, parsed.options.key);
  } catch {
    writeJson(stderr, {error: 'invalid arguments'});
    return EXIT_USAGE;
  }

  try {
    const client = createR2Client({
      env,
      fetchImpl: dependencies.fetchImpl,
      now: dependencies.now,
      fsImpl: dependencies.fsImpl,
    });
    const {operation, options} = parsed;
    const common = {bucket: options.bucket, key: options.key};
    const input = operation === 'head'
      ? common
      : operation === 'get'
        ? {...common, output: options.output}
        : {
            ...common,
            file: options.file,
            contentType: options['content-type'],
            contentDisposition: options['content-disposition'],
            cacheControl: options['cache-control'],
            ifNoneMatch: options['if-none-match'],
            ifMatch: options['if-match'],
          };
    const result = await client[operation](input);
    writeJson(stdout, result);
    return 0;
  } catch (error) {
    const status = Number.isInteger(error?.status) ? error.status : undefined;
    writeJson(stderr, status === undefined
      ? {error: 'request failed'}
      : {error: 'request failed', status});
    if (status === 404) return EXIT_NOT_FOUND;
    if (status === 412) return EXIT_PRECONDITION_FAILED;
    return 1;
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  process.exitCode = await main(process.argv.slice(2));
}
