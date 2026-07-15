$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) {
        throw $Message
    }
}

function Assert-Sequence {
    param([string[]]$Actual, [string[]]$Expected, [string]$Message)
    $same = $Actual.Count -eq $Expected.Count
    if ($same) {
        for ($index = 0; $index -lt $Actual.Count; $index++) {
            if ($Actual[$index] -ne $Expected[$index]) {
                $same = $false
                break
            }
        }
    }
    if (-not $same) {
        throw "$Message`nActual:`n$($Actual -join "`n")"
    }
}

$scriptsRoot = Split-Path -Parent $PSScriptRoot
$publisher = Join-Path $scriptsRoot "publish_release_platform.ps1"
Assert-True (Test-Path -LiteralPath $publisher -PathType Leaf) "Publisher script missing: $publisher"

$Version = "v1.2.3"
$Commit = "a" * 40
$PublishedAt = "2026-07-15T18:00:00Z"

$temporary = Join-Path ([IO.Path]::GetTempPath()) "backchannel-platform-publish-test-$([guid]::NewGuid())"
New-Item -ItemType Directory -Path $temporary | Out-Null
$store = Join-Path $temporary "store"
$assets = Join-Path $temporary "assets"
New-Item -ItemType Directory -Path $store, $assets | Out-Null
$log = Join-Path $temporary "ops.log"
$oldPath = $env:PATH
$oldFakeScript = $env:R2_FAKE_SCRIPT
$oldFakeStore = $env:R2_FAKE_STORE
$oldFakeLog = $env:R2_FAKE_LOG
$oldFakeRaceKey = $env:R2_FAKE_RACE_KEY
$oldFakeRaceDir = $env:R2_FAKE_RACE_DIR
$oldFakeHeadSize = $env:R2_FAKE_HEAD_SIZE
$credentialNames = @(
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "CLOUDFLARE_ACCOUNT_ID",
    "R2_RELEASES_BUCKET"
)
$oldCredentials = @{}
foreach ($name in $credentialNames) {
    $oldCredentials[$name] = [Environment]::GetEnvironmentVariable($name)
    [Environment]::SetEnvironmentVariable($name, "test-value")
}

function Write-Utf8 {
    param([string]$Path, [string]$Text)
    $parent = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Path $parent | Out-Null
    }
    [IO.File]::WriteAllText($Path, $Text, [Text.UTF8Encoding]::new($false))
}

function Object-Path {
    param([string]$Key)
    Join-Path $store ($Key -replace '/', [IO.Path]::DirectorySeparatorChar)
}

function Put-Object {
    param([string]$Key, [string]$Text)
    Write-Utf8 (Object-Path $Key) $Text
}

function Release-Json {
    param(
        [string]$VersionValue = $Version,
        [string]$CommitValue = $Commit,
        [string]$PublishedAtValue = $PublishedAt
    )
    '{{"commit":"{0}","published_at":"{1}","version":"{2}"}}' -f $CommitValue, $PublishedAtValue, $VersionValue
}

function Latest-Json {
    param([string]$VersionValue)
    '{{"version":"{0}"}}' -f $VersionValue
}

function Asset-Info {
    param([string]$PlatformId)
    switch ($PlatformId) {
        "windows-x64" { @("Windows x64", "Backchannel-windows-x64.zip", "application/zip") }
        "macos-arm64" { @("macOS arm64", "Backchannel-macos-arm64.zip", "application/zip") }
        "linux-x64" { @("Linux x64", "Backchannel-linux-x64.tar.gz", "application/gzip") }
        default { throw "unknown platform: $PlatformId" }
    }
}

function New-Asset {
    param([string]$PlatformId = "windows-x64", [string]$Payload = "bundle")
    $info = Asset-Info $PlatformId
    $path = Join-Path $assets $info[1]
    Write-Utf8 $path $Payload
    $path
}

function Platform-Json {
    param(
        [string]$PlatformId = "windows-x64",
        [string]$AssetPath = (Join-Path $assets "Backchannel-windows-x64.zip"),
        [string]$VersionValue = $Version,
        [string]$CommitValue = $Commit
    )
    $info = Asset-Info $PlatformId
    $sha = (Get-FileHash -Algorithm SHA256 -LiteralPath $AssetPath).Hash.ToLowerInvariant()
    $size = (Get-Item -LiteralPath $AssetPath).Length
    '{{"asset":{{"content_type":"{0}","filename":"{1}","id":"{2}","key":"releases/{3}/{1}","platform":"{4}","sha256":"{5}","size":{6}}},"commit":"{7}","version":"{3}"}}' -f $info[2], $info[1], $PlatformId, $VersionValue, $info[0], $sha, $size, $CommitValue
}

function Reset-FakeR2 {
    if (Test-Path -LiteralPath $store) {
        Remove-Item -LiteralPath $store -Recurse -Force
    }
    New-Item -ItemType Directory -Path $store | Out-Null
    Remove-Item -LiteralPath $log -Force -ErrorAction SilentlyContinue
    $env:R2_FAKE_RACE_KEY = $null
    $env:R2_FAKE_HEAD_SIZE = $null
    $raceDir = Join-Path $temporary "races"
    if (Test-Path -LiteralPath $raceDir) {
        Remove-Item -LiteralPath $raceDir -Recurse -Force
    }
    New-Item -ItemType Directory -Path $raceDir | Out-Null
    $env:R2_FAKE_RACE_DIR = $raceDir
}

function Read-Log {
    if (Test-Path -LiteralPath $log) {
        @(Get-Content -LiteralPath $log)
    } else {
        @()
    }
}

function Invoke-Publisher {
    param([string]$PlatformId = "windows-x64", [string]$AssetPath = (New-Asset $PlatformId))
    $records = @()
    $failed = $false
    try {
        $records = @(& $publisher `
            -Version $Version `
            -Commit $Commit `
            -PublishedAt $PublishedAt `
            -PlatformId $PlatformId `
            -AssetPath $AssetPath `
            -Confirm:$false 2>&1)
    } catch {
        $failed = $true
        $records += $_.Exception.Message
    }
    [pscustomobject]@{ Failed = $failed; Output = ($records -join [Environment]::NewLine) }
}

try {
    $fakeNode = Join-Path $temporary "node.cmd"
    $fakeNodeScript = Join-Path $temporary "fake-r2.ps1"
    $fakePython = Join-Path $temporary "python.cmd"
    $fakePythonScript = Join-Path $temporary "fake-python.ps1"

    Write-Utf8 $fakeNode "@echo off`r`npowershell -NoProfile -ExecutionPolicy Bypass -File `"%R2_FAKE_SCRIPT%`" %*`r`nexit /b %ERRORLEVEL%`r`n"
    Write-Utf8 $fakeNodeScript @'
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$RawArgs)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$arguments = @($RawArgs)
if ($arguments.Count -gt 0 -and $arguments[0].EndsWith(".mjs")) {
    $arguments = @($arguments | Select-Object -Skip 1)
}
$operation = $arguments[0]
$options = @{}
for ($index = 1; $index -lt $arguments.Count; $index += 2) {
    $options[$arguments[$index].TrimStart("-")] = $arguments[$index + 1]
}
$key = $options["key"]
Add-Content -LiteralPath $env:R2_FAKE_LOG -Value "$operation $key"
function ObjectPath([string]$ObjectKey) {
    Join-Path $env:R2_FAKE_STORE ($ObjectKey -replace '/', [IO.Path]::DirectorySeparatorChar)
}
function WriteJson([string]$Text, [bool]$Error = $false) {
    if ($Error) {
        [Console]::Error.WriteLine($Text)
    } else {
        [Console]::Out.WriteLine($Text)
    }
}
$path = ObjectPath $key
if ($operation -eq "get") {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        WriteJson '{"error":"request failed","status":404}' $true
        exit 44
    }
    Copy-Item -LiteralPath $path -Destination $options["output"] -Force
    $length = (Get-Item -LiteralPath $path).Length
    WriteJson ('{{"etag":"\"etag\"","contentLength":{0},"contentType":"application/json","output":"{1}"}}' -f $length, $options["output"].Replace('\', '\\'))
    exit 0
}
if ($operation -eq "head") {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        WriteJson '{"error":"request failed","status":404}' $true
        exit 44
    }
    $length = if ($env:R2_FAKE_HEAD_SIZE) { [int64]$env:R2_FAKE_HEAD_SIZE } else { (Get-Item -LiteralPath $path).Length }
    WriteJson ('{{"etag":"\"etag\"","contentLength":{0},"contentType":"application/octet-stream"}}' -f $length)
    exit 0
}
if ($operation -eq "put") {
    $marker = Join-Path $env:R2_FAKE_RACE_DIR (($key -replace '[\\/:*?"<>|]', '_') + ".race")
    if ($env:R2_FAKE_RACE_KEY -eq $key -and -not (Test-Path -LiteralPath $marker)) {
        New-Item -ItemType File -Path $marker | Out-Null
        WriteJson '{"error":"request failed","status":412}' $true
        exit 42
    }
    if ($options.ContainsKey("if-none-match") -and (Test-Path -LiteralPath $path -PathType Leaf)) {
        WriteJson '{"error":"request failed","status":412}' $true
        exit 42
    }
    $parent = Split-Path -Parent $path
    if (-not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Path $parent | Out-Null
    }
    Copy-Item -LiteralPath $options["file"] -Destination $path -Force
    WriteJson '{"etag":"\"etag\""}'
    exit 0
}
WriteJson '{"error":"invalid arguments"}' $true
exit 2
'@

    Write-Utf8 $fakePython "@echo off`r`npowershell -NoProfile -ExecutionPolicy Bypass -File `"$fakePythonScript`" %*`r`nexit /b %ERRORLEVEL%`r`n"
    Write-Utf8 $fakePythonScript @'
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$RawArgs)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$options = @{}
for ($index = 1; $index -lt $RawArgs.Count; $index += 2) {
    $options[$RawArgs[$index].TrimStart("-")] = $RawArgs[$index + 1]
}
function Info([string]$PlatformId) {
    switch ($PlatformId) {
        "windows-x64" { @("Windows x64", "Backchannel-windows-x64.zip", "application/zip") }
        "macos-arm64" { @("macOS arm64", "Backchannel-macos-arm64.zip", "application/zip") }
        "linux-x64" { @("Linux x64", "Backchannel-linux-x64.tar.gz", "application/gzip") }
        default { throw "unknown platform: $PlatformId" }
    }
}
function WriteUtf8([string]$Path, [string]$Text) {
    $parent = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Path $parent | Out-Null
    }
    [IO.File]::WriteAllText($Path, $Text + "`n", [Text.UTF8Encoding]::new($false))
}
$tag = $options["tag"]
$commit = $options["commit"]
$publishedAt = $options["published-at"]
$asset = $options["asset"]
$platformId = $options["platform-id"]
$info = Info $platformId
$sha = (Get-FileHash -Algorithm SHA256 -LiteralPath $asset).Hash.ToLowerInvariant()
$size = (Get-Item -LiteralPath $asset).Length
WriteUtf8 $options["release-out"] ('{{"commit":"{0}","published_at":"{1}","version":"{2}"}}' -f $commit, $publishedAt, $tag)
WriteUtf8 $options["platform-out"] ('{{"asset":{{"content_type":"{0}","filename":"{1}","id":"{2}","key":"releases/{3}/{1}","platform":"{4}","sha256":"{5}","size":{6}}},"commit":"{7}","version":"{3}"}}' -f $info[2], $info[1], $platformId, $tag, $info[0], $sha, $size, $commit)
'@

    $env:R2_FAKE_SCRIPT = $fakeNodeScript
    $env:R2_FAKE_STORE = $store
    $env:R2_FAKE_LOG = $log
    $env:PATH = "$temporary;$oldPath"

    Reset-FakeR2
    $asset = New-Asset
    $result = Invoke-Publisher -AssetPath $asset
    Assert-True (-not $result.Failed) "New Windows publication failed: $($result.Output)"
    Assert-Sequence (Read-Log) @(
        "get releases/v1.2.3/release.json",
        "put releases/v1.2.3/release.json",
        "get releases/v1.2.3/release.json",
        "get releases/v1.2.3/platforms/windows-x64.json",
        "put releases/v1.2.3/Backchannel-windows-x64.zip",
        "head releases/v1.2.3/Backchannel-windows-x64.zip",
        "put releases/v1.2.3/platforms/windows-x64.json",
        "get releases/v1.2.3/platforms/windows-x64.json",
        "get releases/latest.json",
        "put releases/latest.json"
    ) "Unexpected new publication operation order"

    Reset-FakeR2
    Put-Object "releases/v1.2.3/release.json" ((Release-Json -CommitValue ("b" * 40)) + "`n")
    $result = Invoke-Publisher -AssetPath (New-Asset)
    Assert-True $result.Failed "Conflicting identity was accepted"
    Assert-True ($result.Output.Contains("release identity")) "Conflicting identity error was unclear"

    Reset-FakeR2
    $asset = New-Asset
    Put-Object "releases/v1.2.3/release.json" ((Release-Json) + "`n")
    Put-Object "releases/v1.2.3/platforms/windows-x64.json" ((Platform-Json -AssetPath $asset) + "`n")
    $result = Invoke-Publisher -AssetPath $asset
    Assert-True (-not $result.Failed) "Identical platform failed: $($result.Output)"
    $joinedLog = (Read-Log) -join "`n"
    Assert-True (-not $joinedLog.Contains("put releases/v1.2.3/Backchannel-windows-x64.zip")) "Existing platform re-uploaded the asset"
    Assert-True (-not $joinedLog.Contains("put releases/v1.2.3/platforms/windows-x64.json")) "Existing platform rewrote immutable metadata"

    Reset-FakeR2
    $asset = New-Asset
    Put-Object "releases/v1.2.3/release.json" ((Release-Json) + "`n")
    Put-Object "releases/v1.2.3/platforms/windows-x64.json" ((Platform-Json -AssetPath $asset -CommitValue ("b" * 40)) + "`n")
    $result = Invoke-Publisher -AssetPath $asset
    Assert-True $result.Failed "Mismatched existing platform was accepted"
    Assert-True (-not ((Read-Log) -join "`n").Contains("put releases/v1.2.3/Backchannel-windows-x64.zip")) "Mismatched platform uploaded the asset"

    Reset-FakeR2
    $env:R2_FAKE_HEAD_SIZE = "1"
    $result = Invoke-Publisher -AssetPath (New-Asset)
    Assert-True $result.Failed "Remote size mismatch was accepted"
    Assert-True (-not ((Read-Log) -join "`n").Contains("put releases/v1.2.3/platforms/windows-x64.json")) "Size mismatch created the platform manifest"
    $env:R2_FAKE_HEAD_SIZE = $null

    Reset-FakeR2
    $env:R2_FAKE_RACE_KEY = "releases/latest.json"
    $result = Invoke-Publisher -AssetPath (New-Asset)
    Assert-True (-not $result.Failed) "Latest retry failed: $($result.Output)"
    $latestPuts = @((Read-Log) | Where-Object { $_ -eq "put releases/latest.json" })
    Assert-True ($latestPuts.Count -eq 2) "Latest precondition was not retried once"
    Assert-True ((Read-Log)[-1] -eq "put releases/latest.json") "R2 calls continued after Latest update"

    Reset-FakeR2
    Put-Object "releases/latest.json" ((Latest-Json "v1.2.3") + "`n")
    $result = Invoke-Publisher -AssetPath (New-Asset)
    Assert-True (-not $result.Failed) "Latest equality failed: $($result.Output)"
    Assert-True (-not ((Read-Log) -contains "put releases/latest.json")) "Equal Latest was rewritten"

    Reset-FakeR2
    Put-Object "releases/latest.json" ((Latest-Json "v9.0.0") + "`n")
    $result = Invoke-Publisher -AssetPath (New-Asset)
    Assert-True (-not $result.Failed) "Newer Latest failed: $($result.Output)"
    Assert-True (-not ((Read-Log) -contains "put releases/latest.json")) "Newer Latest regressed"

    Write-Output "Immutable platform publisher classification: OK"
} finally {
    $env:PATH = $oldPath
    $env:R2_FAKE_SCRIPT = $oldFakeScript
    $env:R2_FAKE_STORE = $oldFakeStore
    $env:R2_FAKE_LOG = $oldFakeLog
    $env:R2_FAKE_RACE_KEY = $oldFakeRaceKey
    $env:R2_FAKE_RACE_DIR = $oldFakeRaceDir
    $env:R2_FAKE_HEAD_SIZE = $oldFakeHeadSize
    foreach ($name in $credentialNames) {
        [Environment]::SetEnvironmentVariable($name, $oldCredentials[$name])
    }
    if (Test-Path -LiteralPath $temporary) {
        Remove-Item -LiteralPath $temporary -Recurse -Force
    }
}
