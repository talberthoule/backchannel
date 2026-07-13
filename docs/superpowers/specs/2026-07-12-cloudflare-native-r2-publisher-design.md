# Cloudflare-native R2 publisher design

## Objective

Publish Backchannel desktop releases directly to Cloudflare R2 without an AWS
CLI, SDK, account, or storage service. Preserve the approved release boundary:
immutable versioned assets and manifests, a conditionally updated monotonic
`releases/latest.json`, exact post-write verification, and bucket-scoped
Cloudflare-issued credentials.

Cloudflare R2 exposes its object API at
`https://<account-id>.r2.cloudflarestorage.com` using the S3-compatible wire
protocol. Protocol names such as `AWS4-HMAC-SHA256` and `x-amz-*` are therefore
unavoidable request fields, but every network request targets Cloudflare and
no AWS product or credential is involved.

## Decision

Add one dependency-free Node 24 CLI at `scripts/r2-object.mjs`. It signs and
streams requests to the official Cloudflare R2 endpoint using only Node
standard-library modules and the existing Cloudflare-issued values:

- `CLOUDFLARE_ACCOUNT_ID`
- `R2_ACCESS_KEY_ID`
- `R2_SECRET_ACCESS_KEY`

The CLI provides only the operations the release path already needs:

- `head --bucket <bucket> --key <key>`
- `get --bucket <bucket> --key <key> --output <path>`
- `put --bucket <bucket> --key <key> --file <path> --content-type <type>`
  with optional `--if-none-match '*'` or `--if-match <etag>`

Successful commands write one compact JSON object to stdout. Expected missing
objects and failed preconditions use distinct nonzero exit codes so callers can
preserve the current immutable-create and compare-and-swap behavior without
parsing vendor prose. Other failures are generic and never print credentials or
signed authorization material.

## Data flow

For uploads, the CLI hashes the file with SHA-256 in a streaming pass, signs the
request for R2 region `auto` and service `s3`, then streams the file body with an
exact content length. It never buffers a desktop bundle in memory. `head`
returns normalized ETag and size metadata. `get` streams to the requested file
and only replaces the destination after a successful response.

The owner migration script replaces its `Invoke-Aws` adapter with the new CLI
while retaining its current version validation, manifest generation, remote
verification, seed ordering, and monotonic Latest logic. The tag workflow uses
the same checked-in CLI for assets, manifest creation, verification, and the
conditional Latest update. There is one R2 implementation shared by local and
CI publication rather than separate PowerShell and shell signers.

## Security and failure handling

- The production endpoint is derived from the configured Cloudflare account ID;
  callers cannot redirect credentials to an arbitrary host.
- Bucket and key values are encoded as URL path segments and never interpolated
  into shell commands.
- Access and secret keys are read only from the process environment and never
  emitted.
- Versioned manifests use `If-None-Match: *`; an existing object is a hard stop.
- Latest creation uses `If-None-Match: *`; replacement uses the exact prior
  ETag in `If-Match`.
- HTTP 404 and 412 have stable, separate exit codes. All other non-2xx responses
  fail closed.
- Downloads write to a sibling temporary file and rename only after the body
  completes, preventing partial verification inputs.

## Testing

Tests are written before production changes.

1. A Node test imports the signer/client with injected clock, credentials, and
   fetch implementation. It proves deterministic signing, Cloudflare-only host
   construction, encoded keys, streamed PUTs, metadata normalization, atomic
   GET output, conditional headers, and redacted failures.
2. Release-contract tests require both the workflow and owner script to call the
   checked-in Cloudflare R2 CLI and reject `aws`, `aws s3`, and `aws s3api`.
3. The PowerShell native-exit harness is adapted to the new Node CLI adapter so
   stale `$LASTEXITCODE` handling remains covered.
4. The existing release manifest, workflow, migration, Worker, admin, recipient,
   site, and production build gates all remain mandatory.

## Rejected alternatives

- Wrangler-only object commands do not expose the conditional request controls
  required for immutable manifests and atomic Latest changes.
- A dedicated publishing Worker could use R2 binding conditions, but it would add
  a new authenticated upload service and attack surface solely to replace a
  small client-side protocol adapter.
- AWS CLI or an S3 SDK would work against R2, but both add an unnecessary AWS-
  branded dependency contrary to the approved Cloudflare-only operating model.
