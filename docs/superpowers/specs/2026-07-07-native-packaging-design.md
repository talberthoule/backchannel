# Native Windows/Mac Executable Packaging - Design

Date: 2026-07-07
Status: Approved

## Goal

Ship Backchannel as a double-clickable executable for Windows and macOS so
non-technical users can run it without installing Docker, Python, Node, or
PostgreSQL. The Docker Compose path remains unchanged as the isolated option.

## Decisions

| Decision | Choice | Why |
| --- | --- | --- |
| Database | Embedded PostgreSQL (zonky.io standalone binaries) | Same engine in both modes; no SQLite compatibility fork; ~30-50 MB cost |
| Form factor | Tray launcher + default browser | Mic capture (getUserMedia) and tab/system audio (getDisplayMedia) require a real browser; embedded webviews are a functional risk |
| Distribution | GitHub Actions matrix, unsigned, attached to GitHub Releases | Free; standard OSS UX (SmartScreen "Run anyway" / right-click-Open on Mac); signing can be added later without rework |
| Packaging tool | PyInstaller one-dir | Mature hooks for onnxruntime/numpy/soundfile; one-dir avoids slow onefile extraction; works in CI matrix |

## Architecture

One process tree per launch:

```
launcher (PyInstaller exe, tray icon)
  -> pg_ctl start (bundled Postgres, data dir in platform app-data)
  -> uvicorn in-process (FastAPI app, serves API + WS + built frontend)
  -> webbrowser.open("http://localhost:<port>")
```

## Components

### 1. App changes (small)

- `backend/app/models.py`: replace `sqlalchemy.dialects.postgresql.UUID`
  with SQLAlchemy 2.0 portable `Uuid` type. Drop-in on Postgres.
- `backend/app/main.py`: mount `StaticFiles` serving the built frontend
  (`frontend/dist`) when a `SERVE_STATIC` setting is set. Docker keeps nginx;
  the setting is unset there.
- No other app changes: the DB engine is still Postgres, so queries,
  `create_all()`, `_add_missing_columns()`, and the dialect-guarded advisory
  lock in `briefing_synthesis.py` all work as-is.

### 2. Native launcher (`desktop/launcher.py` - the new code)

Responsibilities, in order:

1. Resolve platform app-data dir (`%LOCALAPPDATA%\Backchannel` on Windows,
   `~/Library/Application Support/Backchannel` on macOS). `DATA_DIR` lives here.
2. First run: `initdb` into `<app-data>/pgdata` with a generated local
   password stored beside it.
3. Find a free TCP port for Postgres and one for the app.
4. `pg_ctl start` the bundled Postgres. Use pid-file handling so a stale
   postgres from a crashed previous run is recovered/stopped, not duplicated.
5. Set `DATABASE_URL` and `DATA_DIR`, start uvicorn in-process.
6. Open the default browser at `http://localhost:<app-port>`.
7. Tray icon (pystray): Open (re-opens browser), Quit (stop uvicorn, then
   `pg_ctl stop`).

### 3. Build pipeline (GitHub Actions)

One workflow triggered on version tags, matrix over `windows-latest` and
`macos-latest`:

1. `npm ci && npm run build` in `frontend/`.
2. Download zonky Postgres binaries for the target platform.
3. `python scripts/download_models.py` (Silero VAD + WeSpeaker ONNX into the bundle).
4. PyInstaller one-dir build from a checked-in `desktop/backchannel.spec`.
5. Smoke test the bundle headlessly: launch, poll health endpoint, shut down.
6. Zip (`Backchannel-win64.zip`, `Backchannel-macos.zip` containing the
   `.app`) and attach to the GitHub Release.

### 4. Deliberate scope cuts (all recoverable later)

- Sortformer/PyTorch diarizer: Docker-only. The existing
  `resolve_effective_diarizer_mode` fallback silently uses the lightweight
  ONNX path when Sortformer is absent.
- ffmpeg: not bundled. WAV/FLAC/OGG import works via soundfile; MP3/M4A
  import documents "install ffmpeg". Bundle later if it becomes a complaint.
- Code signing/notarization: skipped. README documents SmartScreen /
  right-click-Open. Add when there is budget/demand.
- Auto-update: none. Users download new releases.

## Error handling

- Port in use: pick a free port dynamically (never hardcode 8000/5432).
- Stale Postgres after crash: pg_ctl pid-file recovery before start.
- Second instance launched: detect the running instance (lock file in
  app-data) and just open the browser to it instead of starting a duplicate.
- Postgres fails to start: surface the log path in a native error dialog
  (tray notification / message box), do not start uvicorn.

## Testing

- Launcher self-check: start -> health endpoint responds -> clean shutdown,
  against the bundled Postgres (runs in CI smoke test, step 5 above).
- Existing backend unittest suite unchanged (still Postgres).
- Frontend check unchanged (`npm run build`).

## Documentation

README gains an install section framing the choice:

- Download the executable (easiest): unzip, double-click, note about
  SmartScreen (Windows) and right-click-Open (macOS).
- Docker Compose (isolated, includes Sortformer diarizer): existing
  instructions, unchanged.

## Estimated effort

Moderate: roughly 3-5 focused days. Most of the work is the launcher
lifecycle code and CI pipeline, not app changes.
