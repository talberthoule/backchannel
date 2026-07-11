# Deployment

The Backchannel app deploys as a self-hosted Docker Compose stack:
nginx-served frontend, FastAPI backend, and PostgreSQL. Anything that runs
Docker can host the app. The public documentation site is a separate
Cloudflare Worker with static assets and a private D1 interest list.

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

## Public-site interest list

The landing page sends early-access requests to `POST /api/interest` on the
Cloudflare Worker. The Worker verifies Cloudflare Turnstile before storing the
lowercased email and consent metadata in the private `backchannel-interest` D1
database. It exposes no public list, export, update, or unsubscribe endpoint.

### One-time Cloudflare setup

From `docs-site/`, authenticate Wrangler with a narrowly scoped Cloudflare API
token, then apply the checked-in schema:

```powershell
cd docs-site
npx wrangler d1 migrations apply INTEREST_DB --local
npx wrangler d1 migrations apply INTEREST_DB --remote
npx wrangler secret put TURNSTILE_SECRET_KEY
```

The production Worker must have these bindings:

- D1 database `backchannel-interest` as `INTEREST_DB`
- encrypted secret `TURNSTILE_SECRET_KEY`

Create a managed Turnstile widget named `Backchannel early access`, allow only
`backchannel.page`, use action `interest`, and leave pre-clearance disabled.
The widget's site key is public and belongs in `site/index.html`; its secret
belongs only in the Worker secret binding. The same setup can be completed in
the authenticated Cloudflare dashboard when Wrangler is not authorized. Never
paste the secret into source, documentation, command history, logs, or issue
trackers.

### Private interest admin

The read-only interest console is available only at
`https://admin.backchannel.page/`. Protect the complete hostname with one
Cloudflare Access self-hosted application before routing production traffic to
it; do not configure only a path. Add one Allow policy whose Include rule is
the exact operator email, with no broad group, domain, Bypass, or Service Auth
rule.

Copy the application's Audience (AUD) tag and your Access team hostname, then
enter all three values interactively as encrypted Worker secrets:

```powershell
cd docs-site
npx wrangler secret put ADMIN_EMAIL
npx wrangler secret put ACCESS_TEAM_DOMAIN
npx wrangler secret put ACCESS_AUD
```

Use only the hostname (for example, `<team>.cloudflareaccess.com`) for
`ACCESS_TEAM_DOMAIN`; omit the scheme and path. `ADMIN_EMAIL` must match the
single email in the Access Allow policy. The Worker validates the
`Cf-Access-Jwt-Assertion` signature, issuer, and audience against Access's JWKS,
then requires an exact case-insensitive email match before serving any private
asset or D1 row. Missing configuration fails closed. The endpoint supports only
`GET`, returns only the existing consent fields, and sends `Cache-Control:
no-store`; record changes remain an authenticated D1-console operation.

After deployment, verify that the configured operator can load the page and
refresh its table, while a signed-out browser and a different Access identity
cannot load the page or `/api/admin/interests`. Never place any of these values
in `wrangler.jsonc`, source, logs, screenshots, or issue trackers.

### Review and track invites

List the structured records in creation order:

```powershell
npx wrangler d1 execute INTEREST_DB --remote --command "SELECT email, status, source, consent_at, invited_at, last_contacted_at FROM interest_subscribers ORDER BY created_at;"
```

After sending an invite, run this as a parameterized statement in the
authenticated D1 console or an approved administrative client:

```sql
UPDATE interest_subscribers
SET status = 'invited',
    invited_at = datetime('now'),
    last_contacted_at = datetime('now')
WHERE email = ?;
```

After any later release or news update, set `last_contacted_at` for the exact
recipients. When someone unsubscribes, preserve the record so they are not
silently re-added:

```sql
UPDATE interest_subscribers
SET status = 'unsubscribed', last_contacted_at = datetime('now')
WHERE email = ?;
```

There is no mailing-service integration yet. If a sender is added later, it
must include an unsubscribe option in every message and write unsubscribes back
to D1 before another send.

### Export and retention

Export only when importing the list into an approved sender:

```powershell
npx wrangler d1 export backchannel-interest --remote --table=interest_subscribers --output=interest-subscribers.sql
```

The export contains personal data. Keep it outside Git and shared folders,
limit access to the invite/update operator, and delete the local file after the
approved sender has accepted it. `docs-site/.gitignore` blocks the standard
export filename as a second line of defense.

### Rotate Turnstile

Rotate the widget secret in Cloudflare, immediately replace
`TURNSTILE_SECRET_KEY` in the Worker, and verify a fresh production request.
The public site key and application code do not change. Never retrieve or print
the saved Worker secret; verify it by binding name only.
