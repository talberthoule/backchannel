# Quickstart

## Desktop app (easiest)

Prefer the shortest path? Download the latest desktop build from the
[Backchannel download portal](https://downloads.backchannel.page/).
Downloads are open to everyone; no account, GitHub identity, or repository
membership is required. See the public [v0.4.0 release notes](https://backchannel.page/releases/v0.4.0/)
for the current asset inventory.

- **Windows** -- `Backchannel-windows-x64.zip`; unzip and run `Backchannel.exe`.
- **macOS** (Apple Silicon) -- `Backchannel-macos-arm64.zip`; unzip and open `Backchannel.app`.
- **Linux** (x64) -- `Backchannel-linux-x64.tar.gz`; a portable bundle (not a
  package-manager installer): `tar -xzf` it and run `Backchannel/Backchannel`.

The app runs from your system tray / menu bar and stores data per-user --
`%LOCALAPPDATA%\Backchannel` on Windows,
`~/Library/Application Support/Backchannel` on macOS,
`~/.local/share/backchannel` on Linux -- no Docker needed. Set a Gemini API key in Admin -> Connections on first run ([Getting API Keys](api-keys.md) shows how to create one in about two minutes). For the full self-hosted stack, use Docker Compose below.

### Keeping the desktop app up to date

From v0.4.0 the desktop app updates itself in place. "Check for updates" in
the tray menu (or Admin -> About) checks for a newer version; when one is
available, download it from the update card, completing the authorization
step in the secure downloads window if prompted. Every update is verified
against the Ed25519 signing keys shipped with the app before it is applied,
and installation is blocked until any active call, recording, or
post-processing has finished. The app then restarts into the new version,
keeping a backup and rolling back to the previous version automatically if
the new one fails to start.

## Prerequisites

- Docker with Docker Compose (the primary way to run the stack), or
  Node 24.x / Python 3.11+ / PostgreSQL 16 for local development
- A Google Gemini API key (transcription and default analysis models).
  An OpenAI key is optional and only needed for OpenAI-routed agents.
  New to either provider? [Getting API Keys](api-keys.md) is a two-minute
  walkthrough.
- `ffmpeg` on `PATH` when running outside Docker, if you want compressed
  audio imports (MP3, M4A) or the browser-recorded voice profile and mic
  benchmark clips (WebM). Desktop releases after v0.3.1 bundle ffmpeg on
  Windows and Linux; the macOS desktop bundle still needs a system install

API keys can be supplied two ways:

1. In the app: Admin -> Connections stores keys encrypted at rest
   (see [Configuration](configuration.md)) -- recommended.
2. Environment fallback: copy `.env.example` to `.env` and set
   `GEMINI_API_KEY` (and optionally `OPENAI_API_KEY`).

## Docker Compose (primary)

```bash
cp .env.example .env   # then edit values
docker compose up --build
```

- Frontend: http://localhost:3000
- Backend API: http://localhost:8001 (interactive OpenAPI docs at
  http://localhost:8001/docs)
- PostgreSQL 16 on host port 5432

The frontend nginx container proxies `/api` and `/ws` traffic from port 3000
to the backend, so the browser only ever talks to port 3000.

Stop the stack:

```bash
docker compose down        # keep data
docker compose down -v     # also delete the database and audio volumes
```

### GPU startup (Sortformer diarization)

Use the GPU override when running on a host with NVIDIA GPU support. It
builds the backend with GPU ONNX Runtime and reserves the GPU for the
backend container:

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build
```

See [Deployment](deployment.md) for build arguments and GPU validation.

On Windows with an AMD GPU (e.g. Radeon RX 9070 XT), Docker cannot use the
GPU; run the backend natively instead with
`.\backend\scripts\setup_windows_gpu.ps1` -- see
[AMD GPU on Windows](deployment.md#amd-gpu-on-windows-native-backend).

## Local development

Frontend:

```bash
cd frontend
npm install
npm run dev
```

The Vite dev server proxies `/api` and `/ws` to the backend (see
`frontend/vite.config.ts`).

Backend:

```bash
cd backend
pip install -r requirements.txt
python scripts/download_models.py   # fetches the VAD and speaker-embedding ONNX models
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

For local backend runs, set `DATABASE_URL` if your PostgreSQL host differs
from the default in `backend/app/config.py`.

## Database migrations

```bash
cd backend
alembic upgrade head
alembic downgrade -1
```

Note that the app also runs `Base.metadata.create_all()` and a
column-patching step on startup (`backend/app/main.py`), so a fresh database
works without running Alembic manually. Migrations matter for tracked schema
history and downgrades.

## Tests and checks

Backend tests are stdlib `unittest` files:

```bash
cd backend
python -m unittest discover -s tests
```

Frontend behavior check is the typecheck build:

```bash
cd frontend
npm run build
```
