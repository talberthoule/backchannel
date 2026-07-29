# ALP-173 Remote Release Signing Design

Status: stage-one design approved with genesis-release amendment

Date: 2026-07-28

Issue: ALP-173

## Goal

Move normal desktop release signing from a private Ed25519 key stored on a
coordinator laptop to a dedicated Cloudflare Worker. The private key will be
created directly into Cloudflare Secrets Store, bound only to the signing
Worker, and used only after a Cloudflare Access service token is authenticated
and its Access JWT is verified by the Worker.

This changes where signatures are produced. It does not change the signed
descriptor, desktop verification contract, R2 publication protocol, update
grants, or credential-free macOS build.

Stage one contains no Worker code, Cloudflare resources, credentials, key
material, key rotation, deployment, or cutover.

## Decisions

- Use a separate `backchannel-release-signer` Worker, not a route in
  `backchannel-site`.
- Expose one endpoint: `POST /v1/sign` on
  `signing.backchannel.page`.
- Send the exact canonical public-descriptor bytes and sign those bytes
  directly with Ed25519.
- Use key ID `ed25519-2026-07b`.
- Treat `v0.4.0` as the genesis release of the update channel. It ships only
  `ed25519-2026-07b` and is remote-signed with that key from its first byte.
- Store the private key as unpadded base64url PKCS#8 in Secrets Store. Workers
  WebCrypto supports Ed25519 but private-key import is not supported from the
  raw 32-byte form used by the current Python signer.
- Make remote signing the normal publish path after cutover. Keep local signing
  only as an explicit, fail-closed break-glass mode. A remote failure never
  falls back automatically.
- Require the publisher to verify every detached signature locally against the
  active checked-in public key before making any R2 request.
- Use the existing `CLOUDFLARE_ACCESS_CLIENT_ID` and
  `CLOUDFLARE_ACCESS_CLIENT_SECRET` names for the service token, plus
  `BACKCHANNEL_RELEASE_SIGNING_URL` for the endpoint.

## Existing contract

`scripts/publish_release_platform.ps1` currently reads an unpadded base64url
raw private key from `BACKCHANNEL_RELEASE_SIGNING_PRIVATE_KEY` or
`%LOCALAPPDATA%\Backchannel\release-signing\ed25519-2026-07.private`. It passes
the value through an environment variable to
`desktop/scripts/build_platform_manifest.py`.

The Python helper builds the private platform manifest, derives the public
descriptor, and calls `sign_platform_manifest` in
`backend/app/services/update_signing.py`. That function signs
`canonical_update_bytes(descriptor)`: UTF-8 JSON with recursively sorted keys,
no insignificant whitespace, and non-ASCII text preserved.

Desktop clients already verify Ed25519 over those exact canonical bytes. The
remote path must preserve that contract byte for byte.

## Alternatives considered

### Selected: sign canonical descriptor bytes

The publisher asks the Python helper for the exact canonical descriptor bytes,
sends those bytes as the request body, receives a detached signature, and asks
the helper to attach and verify it. This keeps one signing contract across
local, remote, backend, and desktop code.

### Declined: sign a SHA-256 digest

The current clients verify direct Ed25519 signatures over the descriptor, not
Ed25519 signatures over a caller-supplied digest. Signing a digest would require
a new descriptor schema and coordinated client-verification change, or would
incorrectly label a different message as the existing signature. It adds no
useful isolation because the descriptor is small enough to send directly.

### Declined: send release fields and rebuild the descriptor in the Worker

That would duplicate trusted asset rules, release-note limits, and canonical
JSON behavior in a second language. The Python helper already owns this
contract. The Worker should validate the request boundary and sign the exact
bytes, not become another release-manifest builder.

## Components

### Dedicated signing Worker

Stage two adds a small top-level Worker directory with its own `package.json`,
lockfile, `wrangler.jsonc`, source, and Node test. It uses `jose` for Access JWT
verification and Workers WebCrypto for Ed25519.

The final Wrangler configuration will:

- disable `workers.dev` and preview URLs;
- route only `signing.backchannel.page`;
- set the public `SIGNING_KEY_ID` variable to `ed25519-2026-07b`;
- set `ACCESS_TEAM_DOMAIN`, the dedicated Access application audience, and
  `ACCESS_COMMON_NAME` to the release publisher service-token client ID;
- declare one `secrets_store_secrets` binding named
  `RELEASE_SIGNING_PRIVATE_KEY`;
- contain the Secrets Store ID and secret name, never the secret value.

Stage two checks in the deployable base configuration without invented
resource IDs or audience values. Stage three adds the real Access audience,
Secrets Store binding, and other provisioned identifiers before deployment.

Cloudflare Secrets Store has service-level scopes such as `workers`; it does
not provide a per-Worker cryptographic ACL in the secret value. "Scoped to this
Worker" therefore means the secret has only the `workers` service scope and the
signing Worker is the only configured binding. An account principal with
Secrets Store binding or Worker deployment rights can bind or exfiltrate it.
That limitation is part of the accepted Cloudflare-account threat boundary.

### Access authorization

The signing Worker copies the exact security pattern already used by
`docs-site/worker.js`:

1. Require a syntactically valid `*.cloudflareaccess.com`
   `ACCESS_TEAM_DOMAIN`, a non-empty dedicated `ACCESS_AUD`, and a non-empty
   `ACCESS_COMMON_NAME`.
2. Read `cf-access-jwt-assertion`; fail closed when it is absent.
3. Cache a remote JWK set from
   `https://<team-domain>/cdn-cgi/access/certs`.
4. Call `jwtVerify` with the exact issuer and audience.
5. Require the verified payload's `common_name` to exactly equal
   `ACCESS_COMMON_NAME`.
6. Return a generic unauthorized response for every verification or claim
   failure.

The Access application has a Service Auth policy that allows only the release
publisher service token. Unlike the admin host, the Worker does not require an
email claim: the dedicated audience, exact service-token policy, and exact
`common_name` claim are the identity boundary.

The publisher sends the service-token client ID and client secret in
`CF-Access-Client-Id` and `CF-Access-Client-Secret`. Cloudflare Access turns a
valid service-token request into the application JWT that the Worker verifies.
The client secret must exist only in the operator environment and the protected
GitHub production environment.

### Signing endpoint

`POST /v1/sign` accepts `application/json` whose body is the exact canonical
public-descriptor bytes. A valid request is no larger than 16 KiB.

The Worker:

1. Authorizes the Access JWT before reading the request body or secret.
2. Requires the exact path, method, content type, and bounded body.
3. Decodes strict UTF-8 and requires one JSON object with the existing exact
   descriptor fields and field constraints.
4. Requires `schema` 1 and `key_id` equal to `SIGNING_KEY_ID`.
5. Re-encodes the parsed value with recursive key sorting and requires an exact
   byte match, rejecting non-canonical input.
6. Calls `await env.RELEASE_SIGNING_PRIVATE_KEY.get()` only after all preceding
   checks pass.
7. Base64url-decodes PKCS#8, imports it as a non-extractable Ed25519 signing
   `CryptoKey`, signs the original request bytes, and best-effort zeroes mutable
   decoded buffers.
8. Returns only:

   ```json
   {
     "key_id": "ed25519-2026-07b",
     "signature": "<unpadded base64url Ed25519 signature>"
   }
   ```

Responses always use `Cache-Control: no-store` and
`X-Content-Type-Options: nosniff`. Errors are generic and never include the
request body, JWT, service-token values, secret value, imported key, stack
trace, or upstream error text. The Worker contains no `console` call that can
receive any of those values.

### In-memory key ceremony

Stage two adds a one-shot Node 24 script using built-in WebCrypto, `fetch`, and
`child_process`; it adds no key-generation dependency.

The stage-three ceremony will:

1. Capture `wrangler auth token --json` through a child-process pipe and parse
   it in memory. Neither stdout nor stderr is inherited by the terminal.
2. Before key generation, list Secrets Store metadata with the exact fixed
   query `?search=ed25519-2026-07b&per_page=100`; hard-stop if a result name
   exactly equals `ed25519-2026-07b`, and fail closed on invalid list metadata.
3. Generate one Ed25519 keypair in memory.
4. Export the public key as 32 raw bytes and the private key as PKCS#8.
5. Encode both with unpadded base64url.
6. POST the private value over HTTPS to the Cloudflare Secrets Store API with
   the fixed secret name for `ed25519-2026-07b` and scope `workers`.
7. Treat the API response as metadata only and never print its body.
8. After confirmed creation, print exactly one JSON object containing only
   `key_id` and `public_key`.
9. Best-effort zero mutable byte buffers and clear references in `finally`.

The script never writes `.env`, `.dev.vars`, a temporary file, a command-line
argument containing the private key, or the private value to stdout/stderr.
Production key material is not used in local Worker tests.

This is a no-disk ceremony, not a zero-exposure ceremony. The private key
temporarily exists in the script's process memory, WebCrypto internals, a
JavaScript string used to form the API request, TLS buffers, Cloudflare's API,
Secrets Store, and later Worker invocation memory. JavaScript garbage
collection does not guarantee immediate erasure of immutable strings or
internal buffers. The operator must run the ceremony on the trusted
coordinator, with debugging and process dumps disabled, and close the process
immediately afterward.

If the API result is uncertain, the operator lists secret metadata by the fixed
name before retrying. If creation succeeded but the public-only output was
lost, the unusable secret is deleted and the ceremony is rerun with a fresh
keypair. The script never attempts to retrieve the write-only private value.

## Publisher and manifest flow

### Signing request

`build_platform_manifest.py` gains a request mode that performs all current
release, notes, asset, key-document, and descriptor validation, then writes the
canonical unsigned public descriptor to a caller-provided temporary path. It
does not read a private key and does not write a platform manifest in this
mode.

The active key in `desktop/release_signing_keys.json` determines the
descriptor's `key_id`. The request file is public release metadata, not secret
material.

### Remote signing

`publish_release_platform.ps1` gains an explicit signing mode. Remote is the
normal mode after cutover and requires:

- `BACKCHANNEL_RELEASE_SIGNING_URL`, which must be HTTPS outside loopback tests;
- `CLOUDFLARE_ACCESS_CLIENT_ID`;
- `CLOUDFLARE_ACCESS_CLIENT_SECRET`.

The publisher uses .NET HTTP APIs so credentials are headers, not command-line
arguments. It sends the request file bytes unchanged, enforces a finite
timeout, accepts only a successful JSON response with exactly `key_id` and
`signature`, and requires the returned key ID to equal the checked-in active
key.

The helper's detached-signature mode rebuilds the descriptor from the original
release inputs, attaches the returned key ID and signature, and verifies the
signature against the checked-in public key before writing the final private
platform manifest. Rebuilding plus verification makes an asset or notes change
between the two helper calls fail closed.

Remote signing and local signature verification complete before the first R2
operation. A timeout, Access failure, malformed response, wrong key ID, invalid
signature, changed input, or missing binding produces no R2 request.

### Break-glass local signing

Local signing remains behind an explicit `-SigningMode Local` selection and
keeps the current private-key/public-key match check. It accepts the existing
environment variable or an explicit regular-file path only when local mode was
requested.

There is no automatic fallback from remote to local. After cutover no release
private key is retained on a workstation or in GitHub. The code path is an
emergency mechanism, not stored escrow: using it requires an operator-approved
rotation or separately controlled transient key source, followed by cleanup
and an incident record.

Stage two exercises local mode only in tests. All normal and planned production
publishing uses remote mode; a future explicit operator-approved emergency
rotation is the sole possible local production exception.

`scripts/r2-object.mjs` remains the sole release object transport. The signing
Worker cannot list, read, write, or publish R2 objects.

## macOS publication

The credential-free macOS build remains unchanged. The separate protected
`publish-macos` job uses the same remote mode as Windows and Linux publication
after cutover. Its production environment then replaces
`BACKCHANNEL_RELEASE_SIGNING_PRIVATE_KEY` with:

- `BACKCHANNEL_RELEASE_SIGNING_URL`;
- `CLOUDFLARE_ACCESS_CLIENT_ID`;
- `CLOUDFLARE_ACCESS_CLIENT_SECRET`.

The workflow still restores and verifies the exact cache handoff before
calling `publish_release_platform.ps1`. Cleanup remains credential-free and
separate. No signing credential enters the build job.

## Key rotation and stage boundary

`desktop/release_signing_keys.json` is bundled into each desktop application.
`UpdateService` loads that local file at startup; it does not fetch new trust
roots before verifying an update. Tag-history inspection confirms that no
released tag contains that file or `UpdateService`, so no released client
trusts `ed25519-2026-07` and no auto-update client exists to bridge.

`v0.4.0` is therefore the genesis release of the update channel. Its trust
file contains `ed25519-2026-07b` as the only key and marks it active. The
never-used `ed25519-2026-07` public key is removed, and no production release
uses its private key. Existing `v0.3.x` installations continue to upgrade
through the portal.

Future rotations, after `v0.4.0` establishes an installed trust root, still
require the documented two-release procedure: first ship both public keys in a
release signed by the old key, then switch the active key only after the
supported-version floor trusts it.

The production public key cannot exist before the no-disk ceremony generates
the production keypair. Creating it during stage two would provision production
key material before the required shepherd review. A placeholder public key
would be unsafe and unreviewable.

The stages therefore apply the genesis key as follows:

- Stage two implements and tests detached signatures, remote publication, the
  ceremony, Worker, workflow, and docs using test-only fixture keys. It does
  not change the production trust file or add placeholder resource IDs.
- After stage-two review, stage three runs the ceremony, replaces the trust file
  with `ed25519-2026-07b` as its only and active entry, adds the real provisioned
  Worker configuration, reruns the signing and release gates, and commits only
  the public key before the `v0.4.0` tag.

## Provisioning and cutover

Stage three starts only after shepherd approval of stages one and two.

1. Confirm the reviewed source revision and authenticated Wrangler account
   without printing credentials.
2. Create or identify the account Secrets Store and dedicated secret name.
3. Run the mandatory exact-name preflight, then the ceremony, and capture only
   the public JSON output.
4. Replace `desktop/release_signing_keys.json` with the real public key as the
   only entry and set `active` to `ed25519-2026-07b`; run the focused and full
   release gates and commit that exact public-only change.
5. Create the Access self-hosted application for
   `signing.backchannel.page`, its dedicated audience, a Service Auth policy
   allowing only the release publisher token, and the service token.
6. Bind the Secrets Store secret only to the reviewed signing Worker and deploy
   the Worker with the custom domain. Do not enable `workers.dev` or previews.
7. Store the endpoint, client ID, and client secret in the operator environment
   and protected GitHub production environment without printing them.
8. Send a canonical test descriptor through Access, receive a remote signature,
   and verify it locally against the newly checked-in public key.
9. Run the publisher smoke path and confirm a failed or malformed signing
   response makes zero R2 operations.
10. After stage-three review and merge, create the `v0.4.0` tag and publish
    every platform through remote mode. The current cutover has no local-mode
    exception.
11. Remove the obsolete GitHub private-key secret. Machine one securely deletes
    its old laptop-held private file as a separately recorded ALP-170 operator
    action.

No production release is published merely to prove signing. ALP-173 remains
open after Worker deployment and test signing; cutover is complete only when a
remote-signed `v0.4.0` descriptor is accepted by a `v0.4.0` client and the old
private material has been removed.

## Failure handling

- Missing Access configuration or Secrets Store binding: generic 503; no sign.
- Missing or invalid Access assertion, or missing/mismatched `common_name`:
  generic 401; no body or secret read.
- Wrong path or method: generic 404/405; no body or secret read.
- Oversized, malformed, non-canonical, wrong-schema, or wrong-key request:
  generic 400/413; no secret read.
- Secret decode/import/sign failure: generic 503; no internal detail.
- Publisher network timeout, TLS failure, non-2xx status, malformed JSON,
  unexpected fields, wrong key ID, or invalid signature: stop before R2.
- Existing immutable R2 behavior, retries, and conflict handling remain
  unchanged after a verified platform manifest exists.

Service-token compromise permits calls to the signer until the token is
revoked, so token rotation and Access logs are part of operations. Key
compromise requires a new key ID, retained old public keys as appropriate, a
new patch release, and operator communication under the existing update model.

## Security tradeoff

A Worker secret is not an HSM or a non-exportable KMS key. Worker code must
receive the Secrets Store value before importing it, and anyone
with sufficient Cloudflare Worker deployment or Secrets Store binding rights
can deploy code that reads or exfiltrates it. A non-extractable `CryptoKey`
prevents later WebCrypto export by honest code; it does not protect against
malicious Worker code that reads the original binding.

This design moves the principal threat from laptop theft, accidental sync, and
long-lived workstation storage to Cloudflare account compromise. Cloudflare is
already the trust anchor for the R2 release objects, public site, Access, and D1
operator surfaces, so that trade is accepted. Account roles, API tokens,
Access policies, and deploy permissions must remain narrow and audited.

If hardware-backed non-extractability becomes a requirement, move signing to a
KMS that performs Ed25519 signing without exporting the private key, such as an
appropriate Azure Key Vault configuration. That is declined now to keep the
release system Cloudflare-native and avoid an additional production trust
anchor.

## Stage-two tests

### Worker

The Worker Node test will cover:

- exact issuer/audience JWT verification and fail-closed configuration;
- missing, invalid, and rejected Access assertions;
- path, method, content type, and body-size boundaries;
- exact canonical request acceptance;
- non-canonical JSON, extra fields, wrong schema, and wrong key ID rejection;
- Secrets Store lookup only after authorization and request validation;
- a real WebCrypto Ed25519 signature verified by a test public key;
- exact response shape and generic errors with no fixture-secret leakage.

### Python signing contract

Focused tests will cover:

- canonical request bytes remain unchanged;
- detached signature attachment produces the same platform schema as local
  signing;
- valid detached signatures verify against the active key;
- malformed, wrong-key, tampered-input, and extra-field signatures fail before
  output;
- local signing remains available only through the explicit break-glass path.

### PowerShell transport

`scripts/tests/test_publish_release_platform.ps1` will use a loopback test
signer and fixture key to cover:

- exact descriptor body and Access header names;
- remote success followed by the existing R2 operation order;
- timeout, unauthorized, malformed response, wrong key ID, and invalid
  signature all producing zero R2 operations;
- explicit local break-glass mode;
- no service-token or fixture-private-key value in output.

### Gates

Stage two runs:

- the signing Worker's Node tests and local Wrangler check;
- `scripts/tests/test_publish_release_platform.ps1`;
- focused platform-manifest and update-signing tests;
- the Windows `backchannel312` backend suite;
- release-contract tests affected by the macOS credential change;
- `git diff --check`.

Stage three repeats focused Worker, transport, signing, release-contract, and
remote verification checks against the provisioned endpoint before cutover is
accepted.

## Non-goals

- No change to desktop descriptor schema or verification.
- No change to release object format, R2 keys, or `scripts/r2-object.mjs`.
- No R2 binding or R2 credentials on the signing Worker.
- No change to D1, release grants, recipient identity, or download
  authorization.
- No signing in the credential-free macOS build.
- No automatic local fallback.
- No attempt to make Secrets Store equivalent to an HSM.
- No production provisioning, key generation, deployment, or cutover before
  both shepherd reviews.

## Primary references

- Cloudflare Access JWT validation:
  https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/validating-json/
- Cloudflare Access service tokens:
  https://developers.cloudflare.com/cloudflare-one/access-controls/service-credentials/service-tokens/
- Cloudflare Secrets Store Worker bindings:
  https://developers.cloudflare.com/secrets-store/integrations/workers/
- Cloudflare Secrets Store access control:
  https://developers.cloudflare.com/secrets-store/access-control/
- Cloudflare Secrets Store create API:
  https://developers.cloudflare.com/api/resources/secrets_store/subresources/stores/subresources/secrets/methods/create/
- Workers WebCrypto:
  https://developers.cloudflare.com/workers/runtime-apis/web-crypto/
- Wrangler authentication token:
  https://developers.cloudflare.com/workers/wrangler/commands/general/#auth-token
