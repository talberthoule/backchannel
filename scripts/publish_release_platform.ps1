[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = "High")]
param(
    [Parameter(Mandatory = $true)]
    [string]$Version,

    [Parameter(Mandatory = $true)]
    [string]$Commit,

    [Parameter(Mandatory = $true)]
    [string]$PublishedAt,

    [Parameter(Mandatory = $true)]
    [ValidateSet("windows-x64", "macos-arm64", "linux-x64")]
    [string]$PlatformId,

    [Parameter(Mandatory = $true)]
    [string]$AssetPath
)

. (Join-Path $PSScriptRoot "r2-release-common.ps1")

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Assert-ExactBytes {
    param([string]$Expected, [string]$Actual, [string]$Label)
    if (-not (Test-Path -LiteralPath $Actual -PathType Leaf) -or
        [Convert]::ToBase64String([IO.File]::ReadAllBytes($Expected)) -cne
        [Convert]::ToBase64String([IO.File]::ReadAllBytes($Actual))) {
        throw "$Label readback did not match"
    }
}

function Read-R2Json {
    param([string]$Key, [string]$Destination)
    Invoke-R2Object `
        -Client $script:R2Client `
        -Arguments @("get", "--bucket", $script:Bucket, "--key", $Key, "--output", $Destination)
}

function Write-Utf8 {
    param([string]$Path, [string]$Text)
    [IO.File]::WriteAllText($Path, $Text, [Text.UTF8Encoding]::new($false))
}

function Get-VersionParts {
    param([string]$Value)
    if ($Value -notmatch '^v(?<major>0|[1-9][0-9]*)\.(?<minor>0|[1-9][0-9]*)\.(?<patch>0|[1-9][0-9]*)$') {
        throw "Invalid release version: $Value"
    }
    @([int]$Matches.major, [int]$Matches.minor, [int]$Matches.patch)
}

function Compare-ReleaseVersion {
    param([string]$Left, [string]$Right)
    $leftParts = Get-VersionParts $Left
    $rightParts = Get-VersionParts $Right
    for ($index = 0; $index -lt 3; $index++) {
        if ($leftParts[$index] -lt $rightParts[$index]) { return -1 }
        if ($leftParts[$index] -gt $rightParts[$index]) { return 1 }
    }
    0
}

function Assert-ExistingJson {
    param(
        [string]$Key,
        [string]$Expected,
        [string]$Actual,
        [string]$Label
    )
    $read = Read-R2Json $Key $Actual
    Assert-R2Success $read "Reading $Label"
    Assert-ExactBytes $Expected $Actual $Label
}

# Creating immutable platform manifest happens before the final Latest write.
function Set-Latest {
    param([string]$LatestPath, [string]$CurrentLatestPath)

    foreach ($attempt in 1..2) {
        $remoteLatest = Get-R2Latest $CurrentLatestPath $script:Bucket $script:R2Client
        if ($remoteLatest.Exists) {
            $current = Get-Content -Raw -LiteralPath $CurrentLatestPath | ConvertFrom-Json
            if ($null -eq $current.version) {
                throw "Latest metadata is invalid"
            }
            $comparison = Compare-ReleaseVersion $Version $current.version
            if ($comparison -eq 0) {
                return
            }
            if ($comparison -lt 0) {
                return
            }
            $condition = @("--if-match", $remoteLatest.ETag)
        } else {
            $condition = @("--if-none-match", "*")
        }

        Write-Verbose "Updating Latest"
        $writeLatest = Invoke-R2Object -Client $script:R2Client -Arguments (@(
            "put",
            "--bucket", $script:Bucket,
            "--key", "releases/latest.json",
            "--file", $LatestPath,
            "--content-type", "application/json",
            "--cache-control", "no-store"
        ) + $condition)
        if ($writeLatest.Code -eq 0) {
            return
        }
        if ($attempt -eq 1 -and $writeLatest.Code -eq 42) {
            continue
        }
        throw "Updating Latest failed: $($writeLatest.Output)"
    }
}

foreach ($name in @(
    "CLOUDFLARE_ACCOUNT_ID",
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "R2_RELEASES_BUCKET"
)) {
    if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($name))) {
        throw "Missing required environment variable: $name"
    }
}

if (-not (Test-Path -LiteralPath $AssetPath -PathType Leaf)) {
    throw "AssetPath must be an existing file: $AssetPath"
}
$asset = Get-Item -LiteralPath $AssetPath
if (($asset.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
    throw "AssetPath must be a regular file: $AssetPath"
}
$AssetPath = $asset.FullName

$script:Bucket = $env:R2_RELEASES_BUCKET
$repoRoot = Split-Path -Parent $PSScriptRoot
$script:R2Client = Join-Path $repoRoot "scripts/r2-object.mjs"
if (-not (Test-Path -LiteralPath $script:R2Client -PathType Leaf)) {
    throw "R2 client not found: $script:R2Client"
}

$metadataHelper = Join-Path $repoRoot "desktop/scripts/build_platform_manifest.py"
$temporary = Join-Path ([IO.Path]::GetTempPath()) "backchannel-platform-r2-$([guid]::NewGuid())"
$releasePath = Join-Path $temporary "release.json"
$platformPath = Join-Path $temporary "$PlatformId.json"
$latestPath = Join-Path $temporary "latest.json"
$currentReleasePath = Join-Path $temporary "current-release.json"
$currentPlatformPath = Join-Path $temporary "current-platform.json"
$currentLatestPath = Join-Path $temporary "current-latest.json"
New-Item -ItemType Directory -Path $temporary | Out-Null

try {
    & python $metadataHelper `
        --asset $AssetPath `
        --platform-id $PlatformId `
        --tag $Version `
        --commit $Commit `
        --published-at $PublishedAt `
        --release-out $releasePath `
        --platform-out $platformPath
    if ($LASTEXITCODE -ne 0) {
        throw "Platform metadata validation failed"
    }
    Write-Utf8 $latestPath (@{ version = $Version } | ConvertTo-Json -Compress)
    $platform = Get-Content -Raw -LiteralPath $platformPath | ConvertFrom-Json

    if (-not $PSCmdlet.ShouldProcess(
        "$script:Bucket/releases/$Version/$PlatformId",
        "Publish immutable platform release"
    )) {
        return
    }

    $releaseKey = "releases/$Version/release.json"
    $platformKey = "releases/$Version/platforms/$PlatformId.json"
    $identity = Read-R2Json $releaseKey $currentReleasePath
    if ($identity.Code -eq 0) {
        Assert-ExactBytes $releasePath $currentReleasePath "release identity"
    } elseif ($identity.Code -eq 44) {
        $createIdentity = Invoke-R2Object -Client $script:R2Client -Arguments @(
            "put",
            "--bucket", $script:Bucket,
            "--key", $releaseKey,
            "--file", $releasePath,
            "--content-type", "application/json",
            "--cache-control", "no-store",
            "--if-none-match", "*"
        )
        if ($createIdentity.Code -eq 42) {
            Assert-ExistingJson $releaseKey $releasePath $currentReleasePath "release identity"
        } else {
            Assert-R2Success $createIdentity "Creating immutable release identity"
            Assert-ExistingJson $releaseKey $releasePath $currentReleasePath "release identity"
        }
    } else {
        throw "Reading release identity failed: $($identity.Output)"
    }

    $existingPlatform = Read-R2Json $platformKey $currentPlatformPath
    if ($existingPlatform.Code -eq 0) {
        Assert-ExactBytes $platformPath $currentPlatformPath "platform manifest"
        Set-Latest $latestPath $currentLatestPath
        Write-Output (@{
            version = $Version
            platform_id = $PlatformId
            asset_key = $platform.asset.key
            size = [long]$platform.asset.size
        } | ConvertTo-Json -Compress)
        return
    }
    if ($existingPlatform.Code -ne 44) {
        throw "Reading platform manifest failed: $($existingPlatform.Output)"
    }

    $upload = Invoke-R2Object -Client $script:R2Client -Arguments @(
        "put",
        "--bucket", $script:Bucket,
        "--key", $platform.asset.key,
        "--file", $AssetPath,
        "--content-type", $platform.asset.content_type,
        "--content-disposition", "attachment; filename=`"$($platform.asset.filename)`""
    )
    Assert-R2Success $upload "Uploading $($platform.asset.filename)"

    $head = Invoke-R2Object -Client $script:R2Client -Arguments @(
        "head",
        "--bucket", $script:Bucket,
        "--key", $platform.asset.key
    )
    Assert-R2Success $head "Verifying $($platform.asset.filename)"
    if ([long]$head.Data.contentLength -ne [long]$platform.asset.size) {
        throw "ContentLength mismatch for $($platform.asset.filename)"
    }

    Write-Verbose "Creating immutable platform manifest"
    $createPlatform = Invoke-R2Object -Client $script:R2Client -Arguments @(
        "put",
        "--bucket", $script:Bucket,
        "--key", $platformKey,
        "--file", $platformPath,
        "--content-type", "application/json",
        "--cache-control", "no-store",
        "--if-none-match", "*"
    )
    if ($createPlatform.Code -eq 42) {
        Assert-ExistingJson $platformKey $platformPath $currentPlatformPath "platform manifest"
    } else {
        Assert-R2Success $createPlatform "Creating immutable platform manifest"
        Assert-ExistingJson $platformKey $platformPath $currentPlatformPath "platform manifest"
    }

    Set-Latest $latestPath $currentLatestPath
    Write-Output (@{
        version = $Version
        platform_id = $PlatformId
        asset_key = $platform.asset.key
        size = [long]$platform.asset.size
    } | ConvertTo-Json -Compress)
} finally {
    if (Test-Path -LiteralPath $temporary) {
        Remove-Item -LiteralPath $temporary -Recurse -Force
    }
}
