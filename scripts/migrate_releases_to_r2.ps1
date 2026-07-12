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

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Invoke-Aws {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)

    $output = (& aws @Arguments --endpoint-url $script:Endpoint --region auto --no-cli-pager 2>&1 | Out-String).Trim()
    [pscustomobject]@{ Code = $LASTEXITCODE; Output = $output }
}

function Test-NotFound {
    param(
        [string]$Output,
        [string]$Operation
    )

    $escaped = [regex]::Escape($Operation)
    $Output -match "^An error occurred \((404|NoSuchKey|NotFound)\) when calling the $escaped operation: (Not Found|NoSuchKey|The specified key does not exist\.)$"
}

function Assert-AwsSuccess {
    param(
        [object]$Result,
        [string]$Action
    )

    if ($Result.Code -ne 0) {
        throw "$Action failed: $($Result.Output)"
    }
}

function Get-RemoteLatest {
    param([string]$Destination)

    if (Test-Path -LiteralPath $Destination) {
        Remove-Item -LiteralPath $Destination -Force
    }
    $result = Invoke-Aws @(
        "s3api", "get-object",
        "--bucket", $script:Bucket,
        "--key", "releases/latest.json",
        $Destination,
        "--query", "ETag",
        "--output", "text"
    )
    if ($result.Code -eq 0) {
        return [pscustomobject]@{ Exists = $true; ETag = $result.Output }
    }
    if (Test-NotFound $result.Output "GetObject") {
        return [pscustomobject]@{ Exists = $false; ETag = $null }
    }
    throw "Reading Latest failed: $($result.Output)"
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
$isNormal = (Compare-Object $names $normal).Count -eq 0
$isLegacy = (Compare-Object $names $legacy).Count -eq 0
if (-not $isNormal -and -not $isLegacy) {
    throw "AssetDirectory must contain exactly three release assets or the legacy Windows/macOS pair"
}
if ($isLegacy -and $Version -notin @("v0.1.0", "v0.1.1")) {
    throw "Legacy two-asset migration is limited to v0.1.0 and v0.1.1"
}

$script:Endpoint = "https://$($env:CLOUDFLARE_ACCOUNT_ID).r2.cloudflarestorage.com"
$script:Bucket = $env:R2_RELEASES_BUCKET
$env:AWS_ACCESS_KEY_ID = $env:R2_ACCESS_KEY_ID
$env:AWS_SECRET_ACCESS_KEY = $env:R2_SECRET_ACCESS_KEY
$env:AWS_DEFAULT_REGION = "auto"
$env:AWS_EC2_METADATA_DISABLED = "true"

$repoRoot = Split-Path -Parent $PSScriptRoot
$helper = Join-Path $repoRoot "desktop/scripts/build_release_manifest.py"
$temporary = Join-Path ([IO.Path]::GetTempPath()) "backchannel-r2-$([guid]::NewGuid())"
$manifestPath = Join-Path $temporary "manifest.json"
$latestPath = Join-Path $temporary "latest.json"
$currentLatestPath = Join-Path $temporary "current-latest.json"
$remoteManifestPath = Join-Path $temporary "remote-manifest.json"
New-Item -ItemType Directory -Path $temporary | Out-Null

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

    if (-not $PSCmdlet.ShouldProcess(
        "$script:Bucket/releases/$Version",
        "Upload immutable release assets and manifest"
    )) {
        return
    }

    $manifestKey = "releases/$Version/manifest.json"
    $existing = Invoke-Aws @(
        "s3api", "head-object",
        "--bucket", $script:Bucket,
        "--key", $manifestKey
    )
    if ($existing.Code -eq 0) {
        throw "Release manifest already exists: $manifestKey"
    }
    if (-not (Test-NotFound $existing.Output "HeadObject")) {
        throw "Checking immutable manifest failed: $($existing.Output)"
    }

    if ($SetLatest) {
        $remoteLatest = Get-RemoteLatest $currentLatestPath
        if ($remoteLatest.Exists) {
            $validationArguments = @($helperArguments) + @("--current-latest", $currentLatestPath)
            & python @validationArguments
            if ($LASTEXITCODE -ne 0) {
                throw "Latest monotonicity validation failed"
            }
        }
    }

    foreach ($asset in $manifest.assets) {
        $source = Join-Path $AssetDirectory $asset.filename
        $upload = Invoke-Aws @(
            "s3", "cp", $source, "s3://$script:Bucket/$($asset.key)",
            "--content-type", $asset.content_type,
            "--content-disposition", "attachment; filename=`"$($asset.filename)`"",
            "--only-show-errors"
        )
        Assert-AwsSuccess $upload "Uploading $($asset.filename)"
    }

    foreach ($asset in $manifest.assets) {
        $head = Invoke-Aws @(
            "s3api", "head-object",
            "--bucket", $script:Bucket,
            "--key", $asset.key,
            "--query", "ContentLength",
            "--output", "text"
        )
        Assert-AwsSuccess $head "Verifying $($asset.filename)"
        if ([long]$head.Output -ne [long]$asset.size) {
            throw "ContentLength mismatch for $($asset.filename)"
        }
    }

    $create = Invoke-Aws @(
        "s3api", "put-object",
        "--bucket", $script:Bucket,
        "--key", $manifestKey,
        "--body", $manifestPath,
        "--content-type", "application/json",
        "--cache-control", "no-store",
        "--if-none-match", "*"
    )
    Assert-AwsSuccess $create "Creating immutable manifest"

    $readback = Invoke-Aws @(
        "s3api", "get-object",
        "--bucket", $script:Bucket,
        "--key", $manifestKey,
        $remoteManifestPath
    )
    Assert-AwsSuccess $readback "Reading immutable manifest"
    $localBytes = [Convert]::ToBase64String([IO.File]::ReadAllBytes($manifestPath))
    $remoteBytes = [Convert]::ToBase64String([IO.File]::ReadAllBytes($remoteManifestPath))
    if ($localBytes -cne $remoteBytes) {
        throw "Immutable manifest readback did not match"
    }

    if ($SetLatest) {
        foreach ($attempt in 1..2) {
            $remoteLatest = Get-RemoteLatest $currentLatestPath
            $retryArguments = @($helperArguments)
            if ($remoteLatest.Exists) {
                $retryArguments += @("--current-latest", $currentLatestPath)
                $condition = @("--if-match", $remoteLatest.ETag)
            } else {
                $condition = @("--if-none-match", "*")
            }
            & python @retryArguments
            if ($LASTEXITCODE -ne 0) {
                throw "Latest monotonicity validation failed"
            }
            $putLatestArguments = @(
                "s3api", "put-object",
                "--bucket", $script:Bucket,
                "--key", "releases/latest.json",
                "--body", $latestPath,
                "--content-type", "application/json",
                "--cache-control", "no-store"
            ) + $condition
            $writeLatest = Invoke-Aws $putLatestArguments
            if ($writeLatest.Code -eq 0) {
                break
            }
            if ($attempt -eq 1 -and $writeLatest.Output -match "(412|PreconditionFailed)") {
                Write-Host "Latest precondition conflict; retrying once"
                continue
            }
            throw "Updating Latest failed: $($writeLatest.Output)"
        }
    }
} finally {
    if (Test-Path -LiteralPath $temporary) {
        Remove-Item -LiteralPath $temporary -Recurse -Force
    }
}
