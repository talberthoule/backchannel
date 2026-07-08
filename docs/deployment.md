# Deployment

Backchannel deploys as a self-hosted Docker Compose stack: nginx-served
frontend, FastAPI backend, and PostgreSQL. There is no cloud-specific
tooling; anything that runs Docker can host it.

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
