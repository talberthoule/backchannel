import { createRemoteJWKSet, jwtVerify } from "jose";

const ACCESS_HOST =
  /^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.cloudflareaccess\.com$/;
const KEY_ID = /^[a-z0-9][a-z0-9-]{0,39}$/;
const VERSION =
  /^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$/;
const COMMIT = /^[0-9a-f]{40}$/;
const HASH = /^[0-9a-f]{64}$/;
const TIMESTAMP = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/;
const PUBLIC_FIELDS = new Set([
  "version",
  "commit",
  "published_at",
  "release_notes",
  "asset",
  "key_id",
  "schema",
]);
const ASSET_FIELDS = new Set([
  "id",
  "platform",
  "filename",
  "size",
  "sha256",
]);
const TRUSTED_ASSETS = new Map([
  [
    "windows-x64",
    ["Windows x64", "Backchannel-windows-x64.zip"],
  ],
  [
    "macos-arm64",
    ["macOS arm64", "Backchannel-macos-arm64.zip"],
  ],
  [
    "linux-x64",
    ["Linux x64", "Backchannel-linux-x64.tar.gz"],
  ],
]);
const MAX_BODY_BYTES = 16 * 1024;
const MAX_NOTES_BYTES = 8192;
const encoder = new TextEncoder();
const decoder = new TextDecoder("utf-8", { fatal: true });
const accessKeySets = new Map();
const RESPONSE_HEADERS = {
  "cache-control": "no-store",
  "content-type": "application/json; charset=utf-8",
  "x-content-type-options": "nosniff",
};

function json(status, value) {
  return new Response(JSON.stringify(value), {
    status,
    headers: RESPONSE_HEADERS,
  });
}

function error(status) {
  return json(status, { error: "Request failed." });
}

export async function verifyAccessToken(
  token,
  env,
  dependencies = { createRemoteJWKSet, jwtVerify },
) {
  const host = String(env.ACCESS_TEAM_DOMAIN || "").trim().toLowerCase();
  if (!ACCESS_HOST.test(host)) throw new Error("invalid Access issuer");
  const issuer = `https://${host}`;
  let keys;
  if (dependencies.createRemoteJWKSet === createRemoteJWKSet) {
    keys = accessKeySets.get(issuer);
    if (!keys) {
      keys = createRemoteJWKSet(
        new URL(`${issuer}/cdn-cgi/access/certs`),
      );
      accessKeySets.set(issuer, keys);
    }
  } else {
    keys = dependencies.createRemoteJWKSet(
      new URL(`${issuer}/cdn-cgi/access/certs`),
    );
  }
  const { payload } = await dependencies.jwtVerify(token, keys, {
    issuer,
    audience: env.ACCESS_AUD,
  });
  return payload;
}

export async function authorizeAccess(
  request,
  env,
  verify = verifyAccessToken,
) {
  if (
    typeof env.ACCESS_TEAM_DOMAIN !== "string" ||
    !env.ACCESS_TEAM_DOMAIN.trim() ||
    typeof env.ACCESS_AUD !== "string" ||
    !env.ACCESS_AUD.trim() ||
    typeof env.ACCESS_COMMON_NAME !== "string" ||
    !env.ACCESS_COMMON_NAME.trim()
  ) {
    return 503;
  }
  const token = request.headers.get("cf-access-jwt-assertion");
  if (!token) return 401;
  try {
    const payload = await verify(token, env);
    return payload?.common_name === env.ACCESS_COMMON_NAME ? 0 : 401;
  } catch {
    return 401;
  }
}

async function readBoundedBody(request) {
  if (!request.body) return new Uint8Array();
  const reader = request.body.getReader();
  const chunks = [];
  let total = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > MAX_BODY_BYTES) {
      await reader.cancel().catch(() => {});
      throw new RangeError();
    }
    chunks.push(value);
  }
  const body = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    body.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return body;
}

function hasExactFields(value, fields) {
  if (
    value === null ||
    typeof value !== "object" ||
    Array.isArray(value)
  ) {
    return false;
  }
  const keys = Object.keys(value);
  return keys.length === fields.size && keys.every((key) => fields.has(key));
}

function validTimestamp(value) {
  if (
    typeof value !== "string" ||
    !TIMESTAMP.test(value) ||
    value.startsWith("0000")
  ) {
    return false;
  }
  const date = new Date(value);
  return (
    Number.isFinite(date.valueOf()) &&
    date.toISOString() === `${value.slice(0, -1)}.000Z`
  );
}

function validDescriptor(value, signingKeyId) {
  if (!hasExactFields(value, PUBLIC_FIELDS)) return false;
  const asset = value.asset;
  if (!hasExactFields(asset, ASSET_FIELDS)) return false;
  const trusted = TRUSTED_ASSETS.get(asset.id);
  return Boolean(
    typeof value.version === "string" &&
      VERSION.test(value.version) &&
      typeof value.commit === "string" &&
      COMMIT.test(value.commit) &&
      validTimestamp(value.published_at) &&
      typeof value.release_notes === "string" &&
      value.release_notes.length > 0 &&
      value.release_notes.isWellFormed() &&
      encoder.encode(value.release_notes).byteLength <= MAX_NOTES_BYTES &&
      typeof value.key_id === "string" &&
      KEY_ID.test(value.key_id) &&
      value.key_id === signingKeyId &&
      Number.isInteger(value.schema) &&
      value.schema === 1 &&
      trusted &&
      asset.platform === trusted[0] &&
      asset.filename === trusted[1] &&
      Number.isInteger(asset.size) &&
      asset.size > 0 &&
      typeof asset.sha256 === "string" &&
      HASH.test(asset.sha256),
  );
}

function canonicalBytes(value) {
  function sorted(item) {
    if (Array.isArray(item)) return item.map(sorted);
    if (item && typeof item === "object") {
      return Object.fromEntries(
        Object.keys(item)
          .sort()
          .map((key) => [key, sorted(item[key])]),
      );
    }
    return item;
  }
  return encoder.encode(JSON.stringify(sorted(value)));
}

function equalBytes(left, right) {
  return (
    left.byteLength === right.byteLength &&
    left.every((value, index) => value === right[index])
  );
}

function encodeBase64Url(bytes) {
  let binary = "";
  for (const value of bytes) binary += String.fromCharCode(value);
  return btoa(binary)
    .replaceAll("+", "-")
    .replaceAll("/", "_")
    .replace(/=+$/, "");
}

function decodeBase64Url(value) {
  if (
    typeof value !== "string" ||
    !/^[A-Za-z0-9_-]+$/.test(value) ||
    value.length % 4 === 1
  ) {
    throw new TypeError();
  }
  const padded = value
    .replaceAll("-", "+")
    .replaceAll("_", "/")
    .padEnd(value.length + ((4 - (value.length % 4)) % 4), "=");
  const binary = atob(padded);
  const decoded = Uint8Array.from(binary, (character) =>
    character.charCodeAt(0),
  );
  if (encodeBase64Url(decoded) !== value) throw new TypeError();
  return decoded;
}

export async function handleRequest(
  request,
  env,
  dependencies = { verifyAccess: authorizeAccess },
) {
  let authorization;
  try {
    authorization = await dependencies.verifyAccess(request, env);
  } catch {
    return error(401);
  }
  if (authorization) return error(authorization === 503 ? 503 : 401);

  if (new URL(request.url).pathname !== "/v1/sign") return error(404);
  if (request.method !== "POST") return error(405);
  if (request.headers.get("content-type") !== "application/json") {
    return error(400);
  }
  if (
    typeof env.SIGNING_KEY_ID !== "string" ||
    !KEY_ID.test(env.SIGNING_KEY_ID)
  ) {
    return error(503);
  }

  let body;
  try {
    body = await readBoundedBody(request);
  } catch (cause) {
    return error(cause instanceof RangeError ? 413 : 400);
  }

  try {
    const value = JSON.parse(decoder.decode(body));
    if (
      !validDescriptor(value, env.SIGNING_KEY_ID) ||
      !equalBytes(body, canonicalBytes(value))
    ) {
      return error(400);
    }
  } catch {
    return error(400);
  }

  let decodedKey;
  try {
    decodedKey = decodeBase64Url(
      await env.RELEASE_SIGNING_PRIVATE_KEY.get(),
    );
    const key = await crypto.subtle.importKey(
      "pkcs8",
      decodedKey,
      { name: "Ed25519" },
      false,
      ["sign"],
    );
    const signature = new Uint8Array(
      await crypto.subtle.sign("Ed25519", key, body),
    );
    return json(200, {
      key_id: env.SIGNING_KEY_ID,
      signature: encodeBase64Url(signature),
    });
  } catch {
    return error(503);
  } finally {
    decodedKey?.fill(0);
  }
}

export default {
  fetch(request, env) {
    return handleRequest(request, env);
  },
};
