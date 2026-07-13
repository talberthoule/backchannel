# Deployment

The Backchannel app deploys as a self-hosted Docker Compose stack:
nginx-served frontend, FastAPI backend, and PostgreSQL. Anything that runs
Docker can host the app. The public documentation site is a separate
Cloudflare Worker with static assets, private D1 access records, and private R2
desktop releases.

## Services (`docker-compose.yml`)

| Service | Image/build | Ports | Notes |
| --- | --- | --- | --- |
| `db` | `postgres:16-alpine` | `5432:5432` | Credentials from `POSTGRES_*` (defaults `callhelper`/`changeme`/`callhelper`); healthcheck gates backend start |
| `backend` | `./backend` Dockerfile | `8001:8000` | Reads `.env`; `DATABASE_URL` is composed from the `POSTGRES_*` values; runs `python scripts/start_backend.py` |
| `frontend` | `./frontend` Dockerfile (Vite build + nginx) | `3000:80` | Proxies `/api` and `/ws` to the backend |

Named volumes:

- `pgdata` -- PostgreSQL data
- `backend_data` -- mounted at `/app/data` (`DATA_DIR`): recorded call
  audio, locally downloaded ASR model weights, and the credentials master
  key. Back this volume up if recordings matter to you.

The backend service also bind-mounts `./backend/app` into the container and
starts uvicorn with reload by default (`BACKEND_RELOAD=true`), so code edits
apply without rebuilding -- a development convenience to disable for
production-like deployments.

## Backend build arguments

Set via environment variables consumed in `docker-compose.yml`:

| Variable | Default | Effect |
| --- | --- | --- |
| `INSTALL_SORTFORMER` | `true` | Install PyTorch/NeMo dependencies for the Sortformer diarizer at build time |
| `PYTORCH_INDEX_URL` | `https://download.pytorch.org/whl/cu130` | PyTorch wheel index (switch to the CPU index to slim the image) |
| `ONNX_GPU` | `false` (set `true` by the GPU override) | Install GPU ONNX Runtime |

## GPU deployment (NVIDIA, Docker)

The GPU overlay reserves NVIDIA GPUs for the backend container and enables
GPU ONNX Runtime:

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build
```

Validate that Docker can see the GPU independently of the app:

```bash
docker run --rm --gpus all nvidia/cuda:13.0.0-base-ubuntu24.04 nvidia-smi
```

The GPU is used for diarization (Sortformer and faster embedding inference).
The Admin panel's diarization capability check
(`GET /api/diagnostics/diarization`) reports whether CUDA is visible inside
the container.

## AMD GPU on Windows (native backend)

Docker cannot pass an AMD GPU through to Linux containers on Windows (WSL2
exposes AMD GPUs only via a DirectX bridge that the standard ROCm stack does
not use), so `docker-compose up` always runs Sortformer on CPU on an AMD
machine. To use an AMD GPU, run the backend natively on Windows with AMD's
official PyTorch-on-Windows (ROCm) wheels.

Requirements:

- An RDNA4 (e.g. Radeon RX 9070 / 9070 XT) or other ROCm-on-Windows
  supported GPU -- see [AMD's Windows compatibility matrix](https://rocm.docs.amd.com/projects/radeon-ryzen/en/latest/docs/compatibility/compatibilityrad/windows/windows_compatibility.html)
- AMD Adrenalin driver 26.2.2 or newer
- Python 3.12 (AMD's wheels are cp312-only): `winget install Python.Python.3.12`

One-time setup, from the repo root in PowerShell:

```powershell
.\backend\scripts\setup_windows_gpu.ps1
```

The script creates `backend/.venv` on Python 3.12, installs backend
requirements, runs `scripts/install_sortformer.py` (which auto-detects the
AMD GPU and installs AMD's ROCm torch wheels from repo.radeon.com instead of
CPU wheels), downloads the ONNX models, and prints whether torch can see the
GPU.

To run the hybrid stack (Postgres in Docker, backend native, frontend via
the Vite dev server):

```powershell
.\backend\scripts\setup_windows_gpu.ps1 -Run   # starts db + backend on :8000
cd frontend; npm run dev                       # separate terminal
```

The compose frontend container cannot reach a native backend (its nginx
proxies to the `backend` container by name), so use the Vite dev frontend --
its proxy already targets a local backend on port 8000.

Once running, ROCm torch builds report through the `torch.cuda` API, so the
Admin panel's diarization card shows Device: CUDA with GPU accel:
ROCm (AMD). Run the Sortformer benchmark from that card to unlock Enhanced
mode.

## Frontend proxying (`frontend/nginx.conf`)

nginx serves the built SPA and proxies backend traffic so the browser only
needs port 3000:

- `location /api/` -> `http://backend:8000` with 1800s read/send timeouts
  (long imports and re-transcription runs)
- `location /ws/` -> `http://backend:8000` with HTTP/1.1 upgrade headers and
  an 86400s read timeout (all-day calls)
- `client_max_body_size 250M` to allow large audio imports
- SPA fallback: `try_files $uri $uri/ /index.html`

If you front the stack with another proxy, replicate the WebSocket upgrade
headers and generous timeouts for `/ws/`.

## Startup behavior

On startup the backend (`backend/app/main.py`):

1. Runs `Base.metadata.create_all()` so a fresh database works with no
   manual migration step
2. Runs `_add_missing_columns()` to patch older local databases with
   columns `create_all` will not add
3. Seeds agent configurations (`backend/app/services/seed_agents.py`)

Alembic migrations exist under `backend/alembic/` for tracked schema
history (`alembic upgrade head`), but the startup patching is part of
current runtime behavior -- see [Quickstart](quickstart.md).

`backend/scripts/start_backend.py` is the container entrypoint; it launches
uvicorn (honoring `BACKEND_RELOAD`) after the database is reachable.

## Data locations

| Data | Location |
| --- | --- |
| Recorded call audio | `DATA_DIR/audio/<session_id>/segment_<n>.wav` |
| Local ASR model weights | `DATA_DIR/asr-models/` (downloaded on first use) |
| Credentials master key | `DATA_DIR/master.key` (unless `CREDENTIALS_MASTER_KEY` is set) |
| VAD / speaker-embedding models | `backend/models/*.onnx` (baked into the image / fetched by `scripts/download_models.py`) |

## Cloudflare release-access deployment gate

The site Worker owns three separate boundaries: public interest capture,
Cloudflare Access-protected administration, and recipient-authenticated desktop
delivery. Run this production gate in order and stop on any failed check.

### 1. Export and back up production D1

From `docs-site/`, export the complete production database before applying any
migration:

```powershell
cd docs-site
$backupPath = $env:BACKCHANNEL_D1_BACKUP_PATH
if ([string]::IsNullOrWhiteSpace($backupPath) -or -not [IO.Path]::IsPathRooted($backupPath)) {
    throw 'BACKCHANNEL_D1_BACKUP_PATH must be an absolute path in approved encrypted storage outside the repository.'
}
$backupPath = [IO.Path]::GetFullPath($backupPath)
$repoRoot = (Resolve-Path ..).Path
if ($backupPath.StartsWith($repoRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'BACKCHANNEL_D1_BACKUP_PATH must be outside the repository.'
}
npx wrangler d1 export INTEREST_DB --remote --output="$backupPath"
```

Set `BACKCHANNEL_D1_BACKUP_PATH` to an operator-controlled absolute path in
approved encrypted storage before running the command. The export contains
personal and authentication data; never create it in the repository first.
Restrict it to the minimum operators and retain it through deployment
acceptance.

### 2. Apply migration 0002 and prove integrity

Exercise the exact commands locally first:

```powershell
npx wrangler d1 migrations apply INTEREST_DB --local
npx wrangler d1 execute INTEREST_DB --local --command "PRAGMA foreign_key_check; PRAGMA integrity_check;"
```

Then apply and check production:

```powershell
npx wrangler d1 migrations apply INTEREST_DB --remote
npx wrangler d1 execute INTEREST_DB --remote --command "PRAGMA foreign_key_check; PRAGMA integrity_check;"
```

Stop unless `foreign_key_check` returns no rows and `integrity_check` returns
exactly `ok`. D1 is authoritative for recipient accounts, password metadata,
version grants, sessions, and release-access events. Recipient identity is
unrelated to the local application PostgreSQL database.

### 3. Create and lock down private R2

Create the bucket once:

```powershell
npx wrangler r2 bucket create backchannel-desktop-releases
```

In the R2 dashboard, disable the bucket's `r2.dev` development URL and remove
or disable every bucket custom domain. Verify anonymous requests cannot reach
either path. The only delivery path is the authenticated Worker binding.

### 4. Bind R2 and configure Worker hosts

`docs-site/wrangler.jsonc` must bind bucket `backchannel-desktop-releases` as
`RELEASES`, include `downloads.backchannel.page` as a custom-domain route, and
keep both `workers_dev` and `preview_urls` false. The existing public and admin
custom domains remain. Confirm DNS and certificate activation before continuing.

### 5. Configure recipient abuse controls

Create a managed Turnstile widget for recipient login with exactly:

- hostname: `downloads.backchannel.page`
- action: `download_login`
- pre-clearance: disabled

Put its public site key in `site/downloads/index.html` and enter the secret
interactively:

```powershell
npx wrangler secret put TURNSTILE_SECRET
```

Create a Cloudflare rate-limit rule matching method `POST` and path
`/api/download/login` on `downloads.backchannel.page`. Rate limit before the
Worker executes, use an operator-approved low per-IP threshold, and return a
generic denial. Do not weaken the Worker's same-origin, body-size, generic
authentication, or exact Turnstile hostname/action checks.

### 6. Deploy the control plane first

Retain the public-interest Turnstile secret separately as
`TURNSTILE_SECRET_KEY`. Protect all of `admin.backchannel.page` with the
existing Cloudflare Access self-hosted application and one exact-email Allow
policy. Enter its values interactively:

```powershell
npx wrangler secret put TURNSTILE_SECRET_KEY
npx wrangler secret put ADMIN_EMAIL
npx wrangler secret put ACCESS_TEAM_DOMAIN
npx wrangler secret put ACCESS_AUD
npm run deploy
```

`npm run deploy` synchronizes and builds the site immediately before invoking
Wrangler. Never deploy a preexisting `dist-site` or invoke Wrangler directly
for production deployment.

Do not add a broad group/domain Include, Bypass, or Service Auth rule. The
Worker must independently validate the Access JWT signature, Cloudflare issuer,
configured audience, and exact case-insensitive `ADMIN_EMAIL`; missing or
invalid configuration fails closed.

Deploy and test the Worker before uploading releases or enabling customer
links. Signed-out and wrong-identity requests must not reach admin assets or
APIs. The authenticated admin API provides interest review, release catalog,
approve, reject, grant replacement, password reset, and revoke endpoints. It
must remain private and `Cache-Control: no-store`; never log credentials,
sessions, subscriber data, Access assertions, or R2 keys.

### 7. Benchmark the real password work factor

On the deployed Worker plan, approve a disposable operator test recipient and
perform repeated real login attempts through the hostname-bound Turnstile flow.
Confirm Workers observability reports successful 600,000-iteration
PBKDF2-HMAC-SHA256 derivations within the plan's request CPU ceiling, including
unknown-account dummy derivation. If the ceiling is insufficient, upgrade the
Worker plan before enabling recipient accounts. Never lower the 600,000
iterations.

### 8. Configure an independent R2 writer

Create bucket-scoped R2 S3 Object Read & Write credentials for
`backchannel-desktop-releases`. Configure the GitHub production environment
with secrets `CLOUDFLARE_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, and
`R2_SECRET_ACCESS_KEY`, plus variable
`R2_RELEASES_BUCKET=backchannel-desktop-releases`. These credentials are
separate from the site deployment token; do not expand that token.

### 9. Migrate, accept, then cut over links

Follow [Releasing](releasing.md) to migrate `v0.1.0` through `v0.2.1`, verify
every immutable manifest and asset, and advance Latest only after all intended
objects verify. Test approved, expired, revoked, Latest-only, and explicitly
granted operator accounts. Confirm portal downloads match manifest size and
SHA-256 without GitHub cookies. Only then publish customer links to
`https://downloads.backchannel.page/`.

Keep old private GitHub executable files for one full release cycle. Remove
those executable files only after R2 and portal acceptance for the following
release; keep all GitHub source tags and release notes.

## Interest-list operations

Public `POST /api/interest` remains Turnstile-protected and stores normalized
consent records in D1. Its widget remains restricted to hostname
`backchannel.page`, action `interest`, and no pre-clearance. There is no public
list or mutation route.

List consent records for an approved communication operation:

```powershell
npx wrangler d1 execute INTEREST_DB --remote --command "SELECT email, status, source, consent_at, invited_at, last_contacted_at FROM interest_subscribers ORDER BY created_at;"
```

Use parameterized statements in the authenticated D1 console to record an
invite or unsubscribe:

```sql
UPDATE interest_subscribers
SET status = 'invited', invited_at = datetime('now'), last_contacted_at = datetime('now')
WHERE email = ?;

UPDATE interest_subscribers
SET status = 'unsubscribed', last_contacted_at = datetime('now')
WHERE email = ?;
```

If a mailing sender is added later, it must provide unsubscribe handling and
write that state to D1 before another send. Export only the required consent
table directly to an operator-controlled absolute path in approved encrypted
storage, then delete it after the record-count check:

```powershell
$exportPath = $env:BACKCHANNEL_INTEREST_EXPORT_PATH
if ([string]::IsNullOrWhiteSpace($exportPath) -or -not [IO.Path]::IsPathRooted($exportPath)) {
    throw 'BACKCHANNEL_INTEREST_EXPORT_PATH must be an absolute path in approved encrypted storage outside the repository.'
}
$exportPath = [IO.Path]::GetFullPath($exportPath)
$repoRoot = (Resolve-Path ..).Path
if ($exportPath.StartsWith($repoRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'BACKCHANNEL_INTEREST_EXPORT_PATH must be outside the repository.'
}
npx wrangler d1 export backchannel-interest --remote --table=interest_subscribers --output="$exportPath"
```

Rotate either Turnstile secret by replacing only its encrypted Worker binding
and verifying a fresh production request; never print saved secrets into
source, logs, screenshots, or issue trackers.
