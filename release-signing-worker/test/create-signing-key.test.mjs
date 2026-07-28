import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import test from "node:test";

import {
  captureWranglerAuth,
  runCeremony,
} from "../scripts/create-signing-key.mjs";

const ACCOUNT_ID = "a".repeat(32);
const STORE_ID = "b".repeat(32);
const KEY_ID = "ed25519-2026-07b";
const REQUEST_URL =
  `https://api.cloudflare.com/client/v4/accounts/${ACCOUNT_ID}` +
  `/secrets_store/stores/${STORE_ID}/secrets`;
const FILESYSTEM_MODULE = /(["'`])(?:node:)?fs(?:\/promises)?\1/g;
let streamCaptureTail = Promise.resolve();

function successResponse() {
  return new Response(JSON.stringify({
    success: true,
    errors: [],
    messages: [],
    result: [{
      id: "c".repeat(32),
      created: "2026-07-28T00:00:00Z",
      modified: "2026-07-28T00:00:00Z",
      name: KEY_ID,
      status: "active",
      store_id: STORE_ID,
      scopes: ["workers"],
    }],
  }));
}

async function keyFixture() {
  const pair = await crypto.subtle.generateKey(
    "Ed25519", true, ["sign", "verify"],
  );
  const privateBytes = new Uint8Array(
    await crypto.subtle.exportKey("pkcs8", pair.privateKey),
  );
  const privateValue = Buffer.from(
    privateBytes.buffer,
    privateBytes.byteOffset,
    privateBytes.byteLength,
  ).toString("base64url");
  return {
    pair,
    privateValue,
    wipe: () => privateBytes.fill(0),
  };
}

async function runSuccess(auth) {
  const fixture = await keyFixture();
  const output = [];
  let captured;
  try {
    await withoutProcessLeaks(
      [...Object.values(auth), fixture.privateValue],
      () => runCeremony({
        accountId: ACCOUNT_ID,
        storeId: STORE_ID,
        authToken: async () => auth,
        generateKeyPair: async () => fixture.pair,
        fetchImpl: async (url, init) => {
          captured = {url, init};
          return successResponse();
        },
        writeOutput: value => output.push(value),
      }),
    );
    return {captured, output};
  } finally {
    fixture.wipe();
  }
}

async function withoutProcessLeaks(sensitiveValues, operation) {
  const previousCapture = streamCaptureTail;
  let releaseCapture;
  streamCaptureTail = new Promise(resolve => {
    releaseCapture = resolve;
  });
  await previousCapture;

  const stderr = [];
  const stdout = [];
  const stderrWrite = process.stderr.write;
  const stdoutWrite = process.stdout.write;
  const sensitive = sensitiveValues.filter(Boolean);
  let error;
  let result;
  process.stderr.write = function (chunk, ...args) {
    stderr.push({args, chunk});
    return true;
  };
  process.stdout.write = function (chunk, ...args) {
    stdout.push({args, chunk});
    return true;
  };
  try {
    result = await operation();
  } catch (caught) {
    error = caught;
  } finally {
    process.stderr.write = stderrWrite;
    process.stdout.write = stdoutWrite;
  }
  try {
    const stderrText = stderr.map(({chunk}) => String(chunk)).join("");
    const stdoutText = stdout.map(({chunk}) => String(chunk)).join("");
    for (const item of sensitive) {
      assert.ok(
        !stdoutText.includes(item),
        "actual stdout leaked sensitive test data",
      );
      assert.ok(
        !stderrText.includes(item),
        "actual stderr leaked sensitive test data",
      );
    }
    for (const {args, chunk} of stdout) {
      stdoutWrite.call(process.stdout, chunk, ...args);
    }
    for (const {args, chunk} of stderr) {
      stderrWrite.call(process.stderr, chunk, ...args);
    }
    if (error) throw error;
    return result;
  } finally {
    releaseCapture();
  }
}

async function captureFailure(operation) {
  let caught;
  try {
    await operation();
  } catch (error) {
    caught = error;
  }
  assert.ok(caught, "operation must fail");
  return caught;
}

test("posts the PKCS8 key over HTTPS and prints only the public key", async () => {
  const output = [];
  let captured;
  let timeoutMs;
  const timeoutSignal = {};
  const fixture = await keyFixture();
  const fixturePublic = Buffer.from(
    await crypto.subtle.exportKey("raw", fixture.pair.publicKey),
  ).toString("base64url");

  try {
    await withoutProcessLeaks(
      [fixture.privateValue, "fixture-token"],
      () => runCeremony({
        accountId: ACCOUNT_ID,
        storeId: STORE_ID,
        authToken: async () => ({type: "api_token", token: "fixture-token"}),
        createTimeoutSignal: milliseconds => {
          timeoutMs = milliseconds;
          return timeoutSignal;
        },
        generateKeyPair: async () => fixture.pair,
        fetchImpl: async (url, init) => {
          captured = {
            url,
            headers: init.headers,
            method: init.method,
            redirect: init.redirect,
            signal: init.signal,
            body: JSON.parse(Buffer.from(init.body).toString()),
            mutableBody: init.body,
          };
          return successResponse();
        },
        writeOutput: value => output.push(value),
      }),
    );

    assert.equal(captured.url, REQUEST_URL);
    assert.equal(captured.method, "POST");
    assert.equal(captured.redirect, "error");
    assert.deepEqual(captured.headers, {
      Authorization: "Bearer fixture-token",
      "Content-Type": "application/json",
    });
    assert.equal(timeoutMs, 30_000);
    assert.equal(captured.signal, timeoutSignal);
    assert.equal(captured.body.length, 1);
    assert.deepEqual(Object.keys(captured.body[0]).sort(), [
      "name", "scopes", "value",
    ]);
    assert.equal(captured.body[0].name, KEY_ID);
    assert.deepEqual(captured.body[0].scopes, ["workers"]);
    assert.ok(
      captured.body[0].value === fixture.privateValue,
      "request must contain the fixture PKCS8 value",
    );
    assert.equal(output.length, 1);
    assert.deepEqual(JSON.parse(output[0]), {
      key_id: KEY_ID,
      public_key: fixturePublic,
    });
    assert.deepEqual(Object.keys(JSON.parse(output[0])).sort(), [
      "key_id", "public_key",
    ]);
    assert.ok(!output[0].includes(fixture.privateValue));
    assert.ok(!process.argv.join("\0").includes(fixture.privateValue));
    assert.ok(!Object.values(process.env).join("\0").includes(
      fixture.privateValue,
    ));
    assert.ok(captured.mutableBody.every(byte => byte === 0));
  } finally {
    fixture.wipe();
    if (captured?.body?.[0]) captured.body[0].value = "";
  }
});

test("ceremony source has no filesystem-write path", async () => {
  const source = await readFile(
    new URL("../scripts/create-signing-key.mjs", import.meta.url),
    "utf8",
  );
  const filesystemModules = source.match(FILESYSTEM_MODULE) ?? [];
  assert.equal(
    filesystemModules.length,
    0,
    "ceremony must have no Node filesystem module or file-write path",
  );
});

test("filesystem guard covers static, dynamic, require, and builtin access", () => {
  for (const source of [
    'import fs from "fs"',
    'import "fs/promises"',
    'await import("node:fs")',
    'require("node:fs/promises")',
    'process.getBuiltinModule("fs")',
    'process.getBuiltinModule("node:fs/promises")',
  ]) {
    assert.equal((source.match(FILESYSTEM_MODULE) ?? []).length, 1);
  }
});

test("uses a Bearer header for Wrangler OAuth", async () => {
  const {captured} = await runSuccess({
    type: "oauth",
    token: "fixture-oauth",
  });
  assert.deepEqual(captured.init.headers, {
    Authorization: "Bearer fixture-oauth",
    "Content-Type": "application/json",
  });
});

test("uses legacy Wrangler API key headers", async () => {
  const {captured} = await runSuccess({
    type: "api_key",
    key: "fixture-key",
    email: "fixture@example.test",
  });
  assert.deepEqual(captured.init.headers, {
    "Content-Type": "application/json",
    "X-Auth-Email": "fixture@example.test",
    "X-Auth-Key": "fixture-key",
  });
});

test("rejects invalid IDs and non-HTTPS API URLs before external work", async () => {
  for (const options of [
    {accountId: "A".repeat(32), storeId: STORE_ID},
    {accountId: ACCOUNT_ID, storeId: "short"},
    {
      accountId: ACCOUNT_ID,
      storeId: STORE_ID,
      apiUrl: "http://api.cloudflare.test/client/v4",
    },
  ]) {
    let externalWork = false;
    const error = await captureFailure(() => runCeremony({
      ...options,
      authToken: async () => {
        externalWork = true;
      },
      generateKeyPair: async () => {
        externalWork = true;
      },
      fetchImpl: async () => {
        externalWork = true;
      },
      writeOutput: () => {
        externalWork = true;
      },
    }));
    assert.equal(error.message, "Invalid ceremony configuration");
    assert.equal(externalWork, false);
  }
});

test("captures Wrangler auth without inheriting output or exposing failures", async () => {
  let invocation;
  const auth = await withoutProcessLeaks(
    ["fixture-token", "captured-stderr"],
    () => captureWranglerAuth((file, args, options, callback) => {
      invocation = {file, args, options};
      callback(
        null,
        JSON.stringify({type: "api_token", token: "fixture-token"}),
        "captured-stderr",
      );
    }),
  );

  assert.deepEqual(auth, {type: "api_token", token: "fixture-token"});
  assert.equal(invocation.file, process.execPath);
  assert.deepEqual(invocation.args.slice(-3), ["auth", "token", "--json"]);
  assert.equal(invocation.options.encoding, "utf8");
  assert.ok(invocation.options.timeout > 0);
  assert.notEqual(invocation.options.stdio, "inherit");

  const marker = "fixture-auth-private";
  const error = await captureFailure(() => withoutProcessLeaks(
    [marker],
    () => captureWranglerAuth((_file, _args, _options, callback) => {
      callback(new Error(marker), marker, marker);
    }),
  ));
  assert.equal(error.message, "Cloudflare authentication failed");
  assert.ok(!error.message.includes(marker));
});

test("fails generically when Wrangler auth is invalid", async () => {
  const output = [];
  const marker = "fixture-auth-private";
  for (const authToken of [
    async () => ({type: "api_token", token: ""}),
    async () => {
      throw new Error(marker);
    },
  ]) {
    const error = await captureFailure(() => withoutProcessLeaks(
      [marker],
      () => runCeremony({
        accountId: ACCOUNT_ID,
        storeId: STORE_ID,
        authToken,
        generateKeyPair: async () => {
          assert.fail("must not generate a key after auth failure");
        },
        fetchImpl: async () => {
          assert.fail("must not fetch after auth failure");
        },
        writeOutput: value => output.push(value),
      }),
    ));
    assert.equal(error.message, "Cloudflare authentication failed");
    assert.ok(!error.message.includes(marker));
  }
  assert.deepEqual(output, []);
});

test("fails generically on non-success responses without printing the body", async () => {
  const fixture = await keyFixture();
  const output = [];
  const marker = "fixture-response-private";
  let error;
  try {
    error = await captureFailure(() => withoutProcessLeaks(
      ["fixture-token", marker, fixture.privateValue],
      () => runCeremony({
        accountId: ACCOUNT_ID,
        storeId: STORE_ID,
        authToken: async () => ({type: "api_token", token: "fixture-token"}),
        generateKeyPair: async () => fixture.pair,
        fetchImpl: async () => new Response(marker, {status: 403}),
        writeOutput: value => output.push(value),
      }),
    ));
  } finally {
    fixture.wipe();
  }
  assert.equal(error.message, "Cloudflare secret creation failed");
  assert.ok(!error.message.includes(marker));
  assert.deepEqual(output, []);
});

test("fails generically on invalid success metadata", async () => {
  const fixture = await keyFixture();
  const output = [];
  const marker = "fixture-response-private";
  try {
    for (const body of [
      marker,
      JSON.stringify({success: false, errors: [{message: marker}]}),
      JSON.stringify({success: true, result: []}),
      JSON.stringify({success: true, result: [{name: "wrong-secret"}]}),
    ]) {
      const error = await captureFailure(() => withoutProcessLeaks(
        ["fixture-token", marker, fixture.privateValue],
        () => runCeremony({
          accountId: ACCOUNT_ID,
          storeId: STORE_ID,
          authToken: async () => ({type: "api_token", token: "fixture-token"}),
          generateKeyPair: async () => fixture.pair,
          fetchImpl: async () => new Response(body),
          writeOutput: value => output.push(value),
        }),
      ));
      assert.equal(error.message, "Cloudflare secret creation failed");
      assert.ok(!error.message.includes(marker));
    }
  } finally {
    fixture.wipe();
  }
  assert.deepEqual(output, []);
});
