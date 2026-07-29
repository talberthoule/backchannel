import assert from "node:assert/strict";
import { test } from "node:test";
import { createRemoteJWKSet } from "jose";

import {
  default as worker,
  authorizeAccess,
  handleRequest,
  verifyAccessToken,
} from "../src/index.mjs";

const encoder = new TextEncoder();
const decoder = new TextDecoder();
const SECRET_FIXTURE = "fixture-secret-that-must-never-leak";

function descriptor() {
  return {
    asset: {
      filename: "Backchannel-windows-x64.zip",
      id: "windows-x64",
      platform: "Windows x64",
      sha256: "a".repeat(64),
      size: 7,
    },
    commit: "b".repeat(40),
    key_id: "fixture-key",
    published_at: "2026-07-26T18:00:00Z",
    release_notes: "Fixture release.",
    schema: 1,
    version: "v1.2.3",
  };
}

function canonical(value) {
  function sorted(item) {
    if (Array.isArray(item)) return item.map(sorted);
    if (item && typeof item === "object") {
      return Object.fromEntries(
        Object.keys(item).sort().map((key) => [key, sorted(item[key])]),
      );
    }
    return item;
  }
  return encoder.encode(JSON.stringify(sorted(value)));
}

function request(body = canonical(descriptor()), options = {}) {
  return new Request(options.url || "https://signing.example/v1/sign", {
    method: options.method || "POST",
    headers: options.headers || { "content-type": "application/json" },
    body,
  });
}

function testEnv(secret, overrides = {}) {
  let reads = 0;
  return {
    env: {
      SIGNING_KEY_ID: "fixture-key",
      RELEASE_SIGNING_PRIVATE_KEY: {
        get: async () => {
          reads += 1;
          return secret;
        },
      },
      ...overrides,
    },
    reads: () => reads,
  };
}

const allow = { verifyAccess: async () => {} };

test("Worker fetch ignores the execution context dependency slot", async () => {
  const response = await worker.fetch(
    new Request("https://signing.example/v1/sign", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: canonical(descriptor()),
    }),
    {},
    { waitUntil() {} },
  );
  assert.equal(response.status, 503);
});

test("verifyAccessToken uses the exact Cloudflare Access issuer and audience", async () => {
  const calls = [];
  const keys = {};
  const payload = { sub: "service-token" };
  const result = await verifyAccessToken(
    "fixture-jwt",
    {
      ACCESS_TEAM_DOMAIN: " Example.CloudflareAccess.com ",
      ACCESS_AUD: "dedicated-audience",
    },
    {
      createRemoteJWKSet(url) {
        calls.push(["keys", url.href]);
        return keys;
      },
      async jwtVerify(token, actualKeys, options) {
        calls.push(["verify", token, actualKeys, options]);
        return { payload };
      },
    },
  );

  assert.equal(result, payload);
  assert.deepEqual(calls, [
    ["keys", "https://example.cloudflareaccess.com/cdn-cgi/access/certs"],
    [
      "verify",
      "fixture-jwt",
      keys,
      {
        issuer: "https://example.cloudflareaccess.com",
        audience: "dedicated-audience",
      },
    ],
  ]);
});

test("verifyAccessToken rejects invalid Access issuers before JWK lookup", async () => {
  for (const host of [
    "",
    "example.com",
    ".cloudflareaccess.com",
    "example.cloudflareaccess.com.evil.test",
    "https://example.cloudflareaccess.com",
  ]) {
    let called = false;
    await assert.rejects(
      verifyAccessToken("jwt", { ACCESS_TEAM_DOMAIN: host }, {
        createRemoteJWKSet() {
          called = true;
        },
        jwtVerify: async () => ({ payload: {} }),
      }),
      /invalid Access issuer/,
    );
    assert.equal(called, false, host);
  }
});

test("verifyAccessToken caches the remote JWK set by exact issuer", async () => {
  const keySets = [];
  const dependencies = {
    createRemoteJWKSet,
    async jwtVerify(_token, keys) {
      keySets.push(keys);
      return { payload: {} };
    },
  };
  const env = {
    ACCESS_TEAM_DOMAIN: "cache-fixture.cloudflareaccess.com",
    ACCESS_AUD: "dedicated-audience",
  };
  await verifyAccessToken("first", env, dependencies);
  await verifyAccessToken("second", env, dependencies);
  assert.equal(keySets.length, 2);
  assert.equal(keySets[0], keySets[1]);
});

test("Access authorization accepts the exact verified common_name without an email", async () => {
  const result = await authorizeAccess(
    new Request("https://signing.example/v1/sign", {
      headers: { "cf-access-jwt-assertion": "fixture-jwt" },
    }),
    {
      ACCESS_TEAM_DOMAIN: "example.cloudflareaccess.com",
      ACCESS_AUD: "dedicated-audience",
      ACCESS_COMMON_NAME: "release-publisher-token",
    },
    async () => ({
      sub: "service-token",
      common_name: "release-publisher-token",
    }),
  );
  assert.equal(result, 0);
});

test("Access configuration and assertion failures are generic and do not read the body or secret", async () => {
  const cases = [
    {
      name: "missing configuration",
      env: {},
      headers: { "cf-access-jwt-assertion": "jwt" },
      status: 503,
    },
    {
      name: "missing common_name configuration",
      env: {
        ACCESS_TEAM_DOMAIN: "example.cloudflareaccess.com",
        ACCESS_AUD: "aud",
      },
      headers: { "cf-access-jwt-assertion": "jwt" },
      status: 503,
      verify: async () => ({common_name: "release-publisher-token"}),
    },
    {
      name: "missing assertion",
      env: {
        ACCESS_TEAM_DOMAIN: "example.cloudflareaccess.com",
        ACCESS_AUD: "aud",
        ACCESS_COMMON_NAME: "release-publisher-token",
      },
      headers: {},
      status: 401,
    },
    {
      name: "rejected assertion",
      env: {
        ACCESS_TEAM_DOMAIN: "example.cloudflareaccess.com",
        ACCESS_AUD: "aud",
        ACCESS_COMMON_NAME: "release-publisher-token",
      },
      headers: { "cf-access-jwt-assertion": SECRET_FIXTURE },
      status: 401,
      verify: async () => {
        throw new Error(SECRET_FIXTURE);
      },
    },
    {
      name: "missing common_name claim",
      env: {
        ACCESS_TEAM_DOMAIN: "example.cloudflareaccess.com",
        ACCESS_AUD: "aud",
        ACCESS_COMMON_NAME: "release-publisher-token",
      },
      headers: {"cf-access-jwt-assertion": "jwt"},
      status: 401,
      verify: async () => ({sub: "service-token"}),
    },
    {
      name: "different common_name claim",
      env: {
        ACCESS_TEAM_DOMAIN: "example.cloudflareaccess.com",
        ACCESS_AUD: "aud",
        ACCESS_COMMON_NAME: "release-publisher-token",
      },
      headers: {"cf-access-jwt-assertion": "jwt"},
      status: 401,
      verify: async () => ({common_name: "other-token"}),
    },
  ];

  for (const item of cases) {
    let reads = 0;
    const body = new ReadableStream({
      pull(controller) {
        controller.enqueue(canonical(descriptor()));
        controller.close();
      },
    });
    const req = new Request("https://signing.example/v1/sign", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        ...item.headers,
      },
      body,
      duplex: "half",
    });
    const response = await handleRequest(
      req,
      {
        SIGNING_KEY_ID: "fixture-key",
        RELEASE_SIGNING_PRIVATE_KEY: {
          get: async () => {
            reads += 1;
            return SECRET_FIXTURE;
          },
        },
        ...item.env,
      },
      {
        verifyAccess: (req, env) =>
          authorizeAccess(req, env, item.verify),
      },
    );
    assert.equal(response.status, item.status, item.name);
    assert.equal(req.bodyUsed, false, item.name);
    assert.equal(reads, 0, item.name);
    assert.doesNotMatch(await response.text(), new RegExp(SECRET_FIXTURE));
  }
});

test("route, method, and content type fail before body or secret reads", async () => {
  const cases = [
    {
      name: "path",
      url: "https://signing.example/v1/other",
      method: "POST",
      headers: { "content-type": "application/json" },
      status: 404,
    },
    {
      name: "method",
      url: "https://signing.example/v1/sign",
      method: "PUT",
      headers: { "content-type": "application/json" },
      status: 405,
    },
    {
      name: "content type",
      url: "https://signing.example/v1/sign",
      method: "POST",
      headers: { "content-type": "application/json; charset=utf-8" },
      status: 400,
    },
    {
      name: "missing content type",
      url: "https://signing.example/v1/sign",
      method: "POST",
      headers: {},
      status: 400,
    },
  ];

  for (const item of cases) {
    const body = new ReadableStream({
      pull(controller) {
        controller.enqueue(canonical(descriptor()));
        controller.close();
      },
    });
    const state = testEnv(SECRET_FIXTURE);
    const req = new Request(item.url, {
      method: item.method,
      headers: item.headers,
      body,
      duplex: "half",
    });
    const response = await handleRequest(
      req,
      state.env,
      allow,
    );
    assert.equal(response.status, item.status, item.name);
    assert.equal(req.bodyUsed, false, item.name);
    assert.equal(state.reads(), 0, item.name);
  }
});

test("body size is enforced while streaming at 16 KiB", async () => {
  async function send(size) {
    const chunks = [new Uint8Array(8192).fill(0x20)];
    chunks.push(new Uint8Array(size - 8192).fill(0x20));
    let index = 0;
    const body = new ReadableStream({
      pull(controller) {
        if (index === chunks.length) return controller.close();
        controller.enqueue(chunks[index++]);
      },
    });
    const state = testEnv(SECRET_FIXTURE);
    const response = await handleRequest(
      new Request("https://signing.example/v1/sign", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body,
        duplex: "half",
      }),
      state.env,
      allow,
    );
    return { response, reads: state.reads() };
  }

  const atLimit = await send(16 * 1024);
  assert.equal(atLimit.response.status, 400);
  assert.equal(atLimit.reads, 0);

  const overLimit = await send(16 * 1024 + 1);
  assert.equal(overLimit.response.status, 413);
  assert.equal(overLimit.reads, 0);
});

test("strict UTF-8 and canonical byte equality are required before secret access", async () => {
  const cases = [
    {
      name: "invalid UTF-8",
      body: new Uint8Array([0xff]),
    },
    {
      name: "non-canonical key order",
      body: encoder.encode(JSON.stringify({
        version: "v1.2.3",
        ...descriptor(),
      })),
    },
    {
      name: "non-canonical whitespace",
      body: encoder.encode(`${decoder.decode(canonical(descriptor()))}\n`),
    },
  ];

  for (const item of cases) {
    const state = testEnv(SECRET_FIXTURE);
    const response = await handleRequest(request(item.body), state.env, allow);
    assert.equal(response.status, 400, item.name);
    assert.equal(state.reads(), 0, item.name);
  }
});

test("unpaired release-note surrogates are rejected before secret access", async () => {
  for (const notes of ["\ud800", "\udc00"]) {
    const value = descriptor();
    value.release_notes = notes;
    const state = testEnv(SECRET_FIXTURE);
    const response = await handleRequest(
      request(canonical(value)),
      state.env,
      allow,
    );
    assert.equal(response.status, 400);
    assert.equal(state.reads(), 0);
  }
});

test("valid Unicode release notes including surrogate pairs are accepted", async () => {
  const value = descriptor();
  value.release_notes = "Café \ud83d\ude80";
  const state = testEnv("invalid");
  const response = await handleRequest(
    request(canonical(value)),
    state.env,
    allow,
  );
  assert.equal(response.status, 503);
  assert.equal(state.reads(), 1);
});

test("descriptor validation exactly matches the public update contract", async () => {
  const cases = [
    ["top-level extra field", (d) => { d.extra = true; }],
    ["top-level missing field", (d) => { delete d.commit; }],
    ["asset extra field", (d) => { d.asset.content_type = "application/zip"; }],
    ["asset missing field", (d) => { delete d.asset.size; }],
    ["asset id", (d) => { d.asset.id = "other"; }],
    ["asset platform", (d) => { d.asset.platform = "Windows"; }],
    ["asset filename", (d) => { d.asset.filename = "other.zip"; }],
    ["version prefix", (d) => { d.version = "1.2.3"; }],
    ["version leading zero", (d) => { d.version = "v01.2.3"; }],
    ["commit uppercase", (d) => { d.commit = "B".repeat(40); }],
    ["commit length", (d) => { d.commit = "b".repeat(39); }],
    ["impossible timestamp", (d) => { d.published_at = "2026-02-29T18:00:00Z"; }],
    ["timestamp offset", (d) => { d.published_at = "2026-07-26T18:00:00+00:00"; }],
    ["empty notes", (d) => { d.release_notes = ""; }],
    ["oversized UTF-8 notes", (d) => { d.release_notes = "é".repeat(4097); }],
    ["zero size", (d) => { d.asset.size = 0; }],
    ["fractional size", (d) => { d.asset.size = 1.5; }],
    ["boolean size", (d) => { d.asset.size = true; }],
    ["uppercase sha256", (d) => { d.asset.sha256 = "A".repeat(64); }],
    ["short sha256", (d) => { d.asset.sha256 = "a".repeat(63); }],
    ["invalid key id", (d) => { d.key_id = "Fixture_key"; }],
    ["oversized key id", (d) => { d.key_id = `a${"-a".repeat(20)}`; }],
    ["wrong key id", (d) => { d.key_id = "other-key"; }],
    ["wrong schema", (d) => { d.schema = 2; }],
    ["string schema", (d) => { d.schema = "1"; }],
  ];

  for (const [name, mutate] of cases) {
    const value = descriptor();
    mutate(value);
    const state = testEnv(SECRET_FIXTURE);
    const response = await handleRequest(
      request(canonical(value)),
      state.env,
      allow,
    );
    assert.equal(response.status, 400, name);
    assert.equal(state.reads(), 0, name);
  }
});

test("all three trusted public asset tuples are accepted", async () => {
  const assets = [
    ["windows-x64", "Windows x64", "Backchannel-windows-x64.zip"],
    ["macos-arm64", "macOS arm64", "Backchannel-macos-arm64.zip"],
    ["linux-x64", "Linux x64", "Backchannel-linux-x64.tar.gz"],
  ];

  for (const [id, platform, filename] of assets) {
    const value = descriptor();
    value.asset = {
      filename,
      id,
      platform,
      sha256: "a".repeat(64),
      size: 7,
    };
    const state = testEnv("invalid");
    const response = await handleRequest(
      request(canonical(value)),
      state.env,
      allow,
    );
    assert.equal(response.status, 503, id);
    assert.equal(state.reads(), 1, id);
  }
});

test("a valid descriptor is signed with the Secrets Store PKCS#8 key", async () => {
  const pair = await crypto.subtle.generateKey(
    "Ed25519",
    true,
    ["sign", "verify"],
  );
  const pkcs8 = new Uint8Array(
    await crypto.subtle.exportKey("pkcs8", pair.privateKey),
  );
  const canonicalBytes = canonical(descriptor());
  const state = testEnv(Buffer.from(pkcs8).toString("base64url"));
  const response = await handleRequest(
    request(canonicalBytes),
    state.env,
    allow,
  );

  assert.equal(response.status, 200);
  assert.equal(response.headers.get("cache-control"), "no-store");
  assert.equal(response.headers.get("x-content-type-options"), "nosniff");
  assert.equal(response.headers.get("content-type"), "application/json; charset=utf-8");
  const result = await response.json();
  assert.deepEqual(Object.keys(result).sort(), ["key_id", "signature"]);
  assert.equal(result.key_id, "fixture-key");
  assert.equal(state.reads(), 1);
  assert.equal(
    await crypto.subtle.verify(
      "Ed25519",
      pair.publicKey,
      Buffer.from(result.signature, "base64url"),
      canonicalBytes,
    ),
    true,
  );
});

test("secret failures are generic and every response has security headers", async () => {
  const cases = [
    ["missing binding", { SIGNING_KEY_ID: "fixture-key" }],
    [
      "secret read failure",
      {
        SIGNING_KEY_ID: "fixture-key",
        RELEASE_SIGNING_PRIVATE_KEY: {
          get: async () => {
            throw new Error(SECRET_FIXTURE);
          },
        },
      },
    ],
    [
      "secret decode failure",
      {
        SIGNING_KEY_ID: "fixture-key",
        RELEASE_SIGNING_PRIVATE_KEY: {
          get: async () => SECRET_FIXTURE,
        },
      },
    ],
  ];

  for (const [name, env] of cases) {
    const response = await handleRequest(request(), env, allow);
    assert.equal(response.status, 503, name);
    assert.equal(response.headers.get("cache-control"), "no-store", name);
    assert.equal(response.headers.get("x-content-type-options"), "nosniff", name);
    const text = await response.text();
    assert.doesNotMatch(text, new RegExp(SECRET_FIXTURE), name);
    assert.doesNotMatch(text, /stack|pkcs|decode|import/i, name);
  }
});

test("decoded PKCS#8 bytes are zeroed when key import fails", async () => {
  const pair = await crypto.subtle.generateKey("Ed25519", true, ["sign"]);
  const pkcs8 = new Uint8Array(
    await crypto.subtle.exportKey("pkcs8", pair.privateKey),
  );
  const originalImportKey = crypto.subtle.importKey;
  let importedBytes;
  crypto.subtle.importKey = async (_format, bytes) => {
    importedBytes = bytes;
    throw new Error(SECRET_FIXTURE);
  };
  try {
    const state = testEnv(Buffer.from(pkcs8).toString("base64url"));
    const response = await handleRequest(request(), state.env, allow);
    assert.equal(response.status, 503);
    assert.ok(importedBytes.length > 0);
    assert.equal(importedBytes.every((value) => value === 0), true);
  } finally {
    crypto.subtle.importKey = originalImportKey;
  }
});
