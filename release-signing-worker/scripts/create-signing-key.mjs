import {execFile} from "node:child_process";
import {createRequire} from "node:module";
import {dirname, resolve} from "node:path";
import {pathToFileURL} from "node:url";

const API_URL = "https://api.cloudflare.com/client/v4";
const KEY_ID = "ed25519-2026-07b";
const ID = /^[0-9a-f]{32}$/;
const require = createRequire(import.meta.url);
const WRANGLER_ENTRY = resolve(
  dirname(require.resolve("wrangler/package.json")),
  "bin",
  "wrangler.js",
);

function ceremonyError(message) {
  return new Error(message);
}

function requestUrl(apiUrl, accountId, storeId) {
  let base;
  try {
    base = new URL(apiUrl);
  } catch {
    throw ceremonyError("Invalid ceremony configuration");
  }
  if (
    !ID.test(accountId) ||
    !ID.test(storeId) ||
    base.protocol !== "https:" ||
    base.username ||
    base.password ||
    base.search ||
    base.hash
  ) {
    throw ceremonyError("Invalid ceremony configuration");
  }
  return `${base.href.replace(/\/+$/, "")}/accounts/${accountId}` +
    `/secrets_store/stores/${storeId}/secrets`;
}

function authHeaders(auth) {
  if (
    (auth?.type === "api_token" || auth?.type === "oauth") &&
    typeof auth.token === "string" &&
    auth.token.length
  ) {
    return {Authorization: `Bearer ${auth.token}`};
  }
  if (
    auth?.type === "api_key" &&
    typeof auth.key === "string" &&
    auth.key.length &&
    typeof auth.email === "string" &&
    auth.email.length
  ) {
    return {"X-Auth-Email": auth.email, "X-Auth-Key": auth.key};
  }
  throw ceremonyError("Cloudflare authentication failed");
}

export function captureWranglerAuth(execFileImpl = execFile) {
  return new Promise((resolvePromise, reject) => {
    const fail = () => reject(ceremonyError("Cloudflare authentication failed"));
    try {
      execFileImpl(
        process.execPath,
        [WRANGLER_ENTRY, "auth", "token", "--json"],
        {
          encoding: "utf8",
          maxBuffer: 1024 * 1024,
          timeout: 30_000,
          windowsHide: true,
        },
        (error, stdout) => {
          if (error) return fail();
          try {
            resolvePromise(JSON.parse(stdout));
          } catch {
            fail();
          }
        },
      );
    } catch {
      fail();
    }
  });
}

export async function runCeremony({
  accountId,
  storeId,
  apiUrl = API_URL,
  authToken = captureWranglerAuth,
  createTimeoutSignal = milliseconds => AbortSignal.timeout(milliseconds),
  generateKeyPair = () =>
    crypto.subtle.generateKey("Ed25519", true, ["sign", "verify"]),
  fetchImpl = fetch,
  writeOutput = value => process.stdout.write(`${value}\n`),
}) {
  const url = requestUrl(apiUrl, accountId, storeId);
  let headers;
  try {
    headers = authHeaders(await authToken());
  } catch {
    throw ceremonyError("Cloudflare authentication failed");
  }

  let bodyBytes;
  let bodyText;
  let pair;
  let privateBytes;
  let privateValue;
  let publicBytes;
  try {
    try {
      pair = await generateKeyPair();
      publicBytes = new Uint8Array(
        await crypto.subtle.exportKey("raw", pair.publicKey),
      );
      privateBytes = new Uint8Array(
        await crypto.subtle.exportKey("pkcs8", pair.privateKey),
      );
    } catch {
      throw ceremonyError("Signing key generation failed");
    }

    privateValue = Buffer.from(
      privateBytes.buffer,
      privateBytes.byteOffset,
      privateBytes.byteLength,
    ).toString("base64url");
    bodyText = JSON.stringify([{
      name: KEY_ID,
      scopes: ["workers"],
      value: privateValue,
    }]);
    bodyBytes = new TextEncoder().encode(bodyText);

    let response;
    try {
      response = await fetchImpl(url, {
        method: "POST",
        headers: {...headers, "Content-Type": "application/json"},
        body: bodyBytes,
        signal: createTimeoutSignal(30_000),
      });
    } catch {
      throw ceremonyError("Cloudflare secret creation failed");
    }
    if (!response?.ok) {
      throw ceremonyError("Cloudflare secret creation failed");
    }

    let metadata;
    try {
      metadata = await response.json();
    } catch {
      throw ceremonyError("Cloudflare secret creation failed");
    }
    if (
      metadata?.success !== true ||
      !Array.isArray(metadata.result) ||
      metadata.result.length !== 1 ||
      metadata.result[0]?.name !== KEY_ID
    ) {
      throw ceremonyError("Cloudflare secret creation failed");
    }

    const publicKey = Buffer.from(
      publicBytes.buffer,
      publicBytes.byteOffset,
      publicBytes.byteLength,
    ).toString("base64url");
    await writeOutput(JSON.stringify({key_id: KEY_ID, public_key: publicKey}));
  } finally {
    bodyBytes?.fill(0);
    privateBytes?.fill(0);
    publicBytes?.fill(0);
    // Immutable strings and WebCrypto internals cannot be reliably zeroed.
    bodyText = pair = privateValue = undefined;
  }
}

if (
  process.argv[1] &&
  import.meta.url === pathToFileURL(process.argv[1]).href
) {
  runCeremony({
    accountId: process.env.CLOUDFLARE_ACCOUNT_ID,
    storeId: process.env.BACKCHANNEL_RELEASE_SIGNING_STORE_ID,
  }).catch(() => {
    process.stderr.write("Signing key ceremony failed\n");
    process.exitCode = 1;
  });
}
