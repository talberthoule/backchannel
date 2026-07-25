<#
Sets up a native Windows backend with AMD ROCm GPU support for Sortformer.

Docker cannot pass an AMD GPU through to Linux containers on Windows, so the
backend must run natively; Postgres stays in Docker. AMD's official
PyTorch-on-Windows (ROCm) wheels require Python 3.12 and Adrenalin driver
26.2.2+, and support RDNA4 GPUs such as the Radeon RX 9070 / 9070 XT.
See docs/deployment.md ("AMD GPU on Windows").

Usage (from the repo root):
  .\backend\scripts\setup_windows_gpu.ps1        # one-time setup (idempotent)
  .\backend\scripts\setup_windows_gpu.ps1 -Run   # setup, then start db + backend
#>
param([switch]$Run)

$ErrorActionPreference = "Stop"
$backendDir = Split-Path -Parent $PSScriptRoot
$repoRoot = Split-Path -Parent $backendDir
$venvPython = Join-Path $backendDir ".venv\Scripts\python.exe"

Write-Host "Note: the ROCm wheels require AMD Adrenalin driver 26.2.2 or newer." -ForegroundColor Yellow

# AMD's Windows torch wheels are cp312-only.
try { py -3.12 --version | Out-Null }
catch { throw "Python 3.12 is required (AMD's ROCm wheels are 3.12-only). Install it with: winget install Python.Python.3.12" }

if (-not (Test-Path $venvPython)) {
    Write-Host "Creating Python 3.12 venv at backend\.venv..."
    py -3.12 -m venv (Join-Path $backendDir ".venv")
}

& $venvPython -m pip install -r (Join-Path $backendDir "requirements.txt")
# Auto-detects the AMD GPU and installs AMD's ROCm torch wheels + NeMo.
& $venvPython (Join-Path $backendDir "scripts\install_sortformer.py")
& $venvPython (Join-Path $backendDir "scripts\download_models.py")

& $venvPython -c "import torch; ok = torch.cuda.is_available(); print('torch', torch.__version__, '| GPU:', torch.cuda.get_device_name(0) if ok else 'NOT DETECTED (CPU only)')"

if (-not $Run) {
    Write-Host ""
    Write-Host "Setup complete. To run the stack:"
    Write-Host "  backend + db: .\backend\scripts\setup_windows_gpu.ps1 -Run"
    Write-Host "  frontend:     cd frontend; npm run dev   (then open the printed URL)"
    exit 0
}

docker compose -f (Join-Path $repoRoot "docker-compose.yml") up -d db

$pgUser = if ($env:POSTGRES_USER) { $env:POSTGRES_USER } else { "callhelper" }
$pgPass = if ($env:POSTGRES_PASSWORD) { $env:POSTGRES_PASSWORD } else { "changeme" }
$pgDb = if ($env:POSTGRES_DB) { $env:POSTGRES_DB } else { "callhelper" }
$env:DATABASE_URL = "postgresql+asyncpg://${pgUser}:${pgPass}@localhost:5432/${pgDb}"

Write-Host "Backend starting on http://localhost:8000 - start the frontend with: cd frontend; npm run dev"
Set-Location $backendDir
& $venvPython -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --ws-ping-timeout 90 --ws-max-queue 2048 --ws-max-size 65536
