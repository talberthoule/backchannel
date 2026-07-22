[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = "High")]
param(
    [Parameter(Mandatory = $true)]
    [string]$Version,

    [Parameter(Mandatory = $true)]
    [string]$Commit,

    [Parameter(Mandatory = $true)]
    [string]$PublishedAt,

    [Parameter(Mandatory = $true)]
    [string]$AssetDirectory,

    [switch]$SetLatest
)

. (Join-Path $PSScriptRoot "r2-release-common.ps1")

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Test-ExactSet {
    param([string[]]$Actual, [string[]]$Expected)

    @(Compare-Object $Actual $Expected).Count -eq 0
}

foreach ($name in @(
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "CLOUDFLARE_ACCOUNT_ID",
    "R2_RELEASES_BUCKET"
)) {
    if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($name))) {
        throw "Missing required environment variable: $name"
    }
}

if (-not (Test-Path -LiteralPath $AssetDirectory -PathType Container)) {
    throw "AssetDirectory must be an existing directory: $AssetDirectory"
}
$AssetDirectory = (Resolve-Path -LiteralPath $AssetDirectory).Path

$windows = "Backchannel-windows-x64.zip"
$macos = "Backchannel-macos-arm64.zip"
$linux = "Backchannel-linux-x64.tar.gz"
$names = @(Get-ChildItem -LiteralPath $AssetDirectory -Force | ForEach-Object Name | Sort-Object)
$normal = @(($linux, $macos, $windows) | Sort-Object)
$legacy = @(($macos, $windows) | Sort-Object)
$isNormal = Test-ExactSet $names $normal
$isLegacy = Test-ExactSet $names $legacy
if (-not $isNormal -and -not $isLegacy) {
    throw "AssetDirectory must contain exactly three release assets or the legacy Windows/macOS pair"
}
if ($isLegacy -and $Version -notin @("v0.1.0", "v0.1.1")) {
    throw "Legacy two-asset migration is limited to v0.1.0 and v0.1.1"
}

$script:Bucket = $env:R2_RELEASES_BUCKET
$repoRoot = Split-Path -Parent $PSScriptRoot
$script:R2Client = Join-Path $repoRoot "scripts/r2-object.mjs"
if (-not (Test-Path -LiteralPath $script:R2Client -PathType Leaf)) {
    throw "R2 client not found: $script:R2Client"
}
$node = Get-Command node -CommandType Application -ErrorAction SilentlyContinue
if ($null -eq $node) {
    throw "Node.js 24 or newer is required"
}
$nodeVersion = @(& $node.Source --version 2>&1)
if ($LASTEXITCODE -ne 0 -or $nodeVersion.Count -ne 1 -or
    $nodeVersion[0] -notmatch '^v(?<major>\d+)\.') {
    throw "Unable to determine the Node.js version"
}
if ([int]$Matches.major -lt 24) {
    throw "Node.js 24 or newer is required"
}

$helper = Join-Path $repoRoot "desktop/scripts/build_release_manifest.py"
$temporary = Join-Path ([IO.Path]::GetTempPath()) "backchannel-r2-$([guid]::NewGuid())"
$manifestPath = Join-Path $temporary "manifest.json"
$latestPath = Join-Path $temporary "latest.json"
$currentLatestPath = Join-Path $temporary "current-latest.json"
$remoteManifestPath = Join-Path $temporary "remote-manifest.json"
New-Item -ItemType Directory -Path $temporary | Out-Null
$manifestCreated = $false

try {
    $helperArguments = @(
        $helper,
        "--asset-dir", $AssetDirectory,
        "--tag", $Version,
        "--commit", $Commit,
        "--published-at", $PublishedAt,
        "--manifest-out", $manifestPath,
        "--latest-out", $latestPath
    )
    if ($isLegacy) {
        $helperArguments += "--allow-legacy-partial"
    }
    & python @helperArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Release manifest validation failed"
    }
    $manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json

    $manifestKey = "releases/$Version/manifest.json"
    $existing = Invoke-R2Object `
        -Client $script:R2Client `
        -Arguments @("head", "--bucket", $script:Bucket, "--key", $manifestKey)
    if ($existing.Code -eq 0) {
        throw "Release manifest already exists: $manifestKey"
    }
    if ($existing.Code -ne 44) {
        throw "Checking immutable manifest failed: $($existing.Output)"
    }

    if ($SetLatest) {
        $remoteLatest = Get-R2Latest $currentLatestPath $script:Bucket $script:R2Client
        if ($remoteLatest.Exists) {
            $validationArguments = @($helperArguments) + @("--current-latest", $currentLatestPath)
            & python @validationArguments
            if ($LASTEXITCODE -ne 0) {
                throw "Latest monotonicity validation failed"
            }
        }
    }

    if (-not $PSCmdlet.ShouldProcess(
        "$script:Bucket/releases/$Version",
        "Upload immutable release assets and manifest"
    )) {
        return
    }

    foreach ($asset in $manifest.assets) {
        $source = Join-Path $AssetDirectory $asset.filename
        $upload = Invoke-R2Object -Client $script:R2Client -Arguments @(
            "put",
            "--bucket", $script:Bucket,
            "--key", $asset.key,
            "--file", $source,
            "--content-type", $asset.content_type,
            "--content-disposition", "attachment; filename=`"$($asset.filename)`""
        )
        Assert-R2Success $upload "Uploading $($asset.filename)"
    }

    foreach ($asset in $manifest.assets) {
        $head = Invoke-R2Object `
            -Client $script:R2Client `
            -Arguments @("head", "--bucket", $script:Bucket, "--key", $asset.key)
        Assert-R2Success $head "Verifying $($asset.filename)"
        if ([long]$head.Data.contentLength -ne [long]$asset.size) {
            throw "ContentLength mismatch for $($asset.filename)"
        }
    }

    $create = Invoke-R2Object -Client $script:R2Client -Arguments @(
        "put",
        "--bucket", $script:Bucket,
        "--key", $manifestKey,
        "--file", $manifestPath,
        "--content-type", "application/json",
        "--cache-control", "no-store",
        "--if-none-match", "create-only"
    )
    Assert-R2Success $create "Creating immutable manifest"
    $manifestCreated = $true

    $readback = Invoke-R2Object -Client $script:R2Client -Arguments @(
        "get",
        "--bucket", $script:Bucket,
        "--key", $manifestKey,
        "--output", $remoteManifestPath
    )
    Assert-R2Success $readback "Reading immutable manifest"
    $localBytes = [Convert]::ToBase64String([IO.File]::ReadAllBytes($manifestPath))
    $remoteBytes = [Convert]::ToBase64String([IO.File]::ReadAllBytes($remoteManifestPath))
    if ($localBytes -cne $remoteBytes) {
        throw "Immutable manifest readback did not match"
    }

    if ($SetLatest) {
        foreach ($attempt in 1..2) {
            $remoteLatest = Get-R2Latest $currentLatestPath $script:Bucket $script:R2Client
            $retryArguments = @($helperArguments)
            if ($remoteLatest.Exists) {
                $retryArguments += @("--current-latest", $currentLatestPath)
                $condition = @("--if-match", $remoteLatest.ETag)
            } else {
                $condition = @("--if-none-match", "create-only")
            }
            & python @retryArguments
            if ($LASTEXITCODE -ne 0) {
                throw "Latest monotonicity validation failed"
            }
            $putLatestArguments = @(
                "put",
                "--bucket", $script:Bucket,
                "--key", "releases/latest.json",
                "--file", $latestPath,
                "--content-type", "application/json",
                "--cache-control", "no-store"
            ) + $condition
            $writeLatest = Invoke-R2Object -Client $script:R2Client -Arguments $putLatestArguments
            if ($writeLatest.Code -eq 0) {
                break
            }
            if ($attempt -eq 1 -and $writeLatest.Code -eq 42) {
                Write-Host "Latest precondition conflict; retrying once"
                continue
            }
            throw "Updating Latest failed: $($writeLatest.Output)"
        }
    }
} catch {
    if ($manifestCreated) {
        Write-Warning "Recovery: immutable manifest $manifestKey was created before a later step failed. Do not overwrite it; verify the existing objects and follow the Task 6 release runbook."
    }
    throw
} finally {
    if (Test-Path -LiteralPath $temporary) {
        Remove-Item -LiteralPath $temporary -Recurse -Force
    }
}
