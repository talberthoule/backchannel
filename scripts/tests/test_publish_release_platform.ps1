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
$validSignature = "A" * 86
$invalidSignature = "B" * 86
$expectedSigningRequest = '{"asset":{"filename":"Backchannel-windows-x64.zip","id":"windows-x64","platform":"Windows x64","sha256":"1e6ed65d77d6364eeaed5a745ba5c4985ae2b700dd85d7cf7f027bdf294a33fc","size":6},"commit":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","key_id":"ed25519-2026-07","published_at":"2026-07-15T18:00:00Z","release_notes":"test notes","schema":1,"version":"v1.2.3"}'

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
$oldFakeSigningRequestFailure = $env:R2_FAKE_SIGNING_REQUEST_FAILURE
$oldFakePowerShell = $env:R2_FAKE_POWERSHELL
$oldSigningSecret = $env:BACKCHANNEL_RELEASE_SIGNING_PRIVATE_KEY
$oldSigningUrl = $env:BACKCHANNEL_RELEASE_SIGNING_URL
$oldAccessClientId = $env:CLOUDFLARE_ACCESS_CLIENT_ID
$oldAccessClientSecret = $env:CLOUDFLARE_ACCESS_CLIENT_SECRET
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
    $signature = "A" * 86
    '{{"asset":{{"content_type":"{0}","filename":"{1}","id":"{2}","key":"releases/{3}/{1}","platform":"{4}","sha256":"{5}","size":{6}}},"commit":"{7}","published_at":"{8}","release_notes":"test notes","update":{{"key_id":"ed25519-2026-07","schema":1,"signature":"{9}"}},"version":"{3}"}}' -f $info[2], $info[1], $PlatformId, $VersionValue, $info[0], $sha, $size, $CommitValue, $PublishedAt, $signature
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

function Start-TestSigner {
    param(
        [int]$StatusCode = 200,
        [string]$ResponseBody,
        [int]$DelayMilliseconds = 0,
        [string]$Location
    )
    $capture = Join-Path $temporary "signer-capture-$([guid]::NewGuid()).json"
    $ready = Join-Path $temporary "signer-ready-$([guid]::NewGuid()).txt"
    $job = Start-Job -ArgumentList $capture, $ready, $StatusCode, $ResponseBody, $DelayMilliseconds, $Location -ScriptBlock {
        param($CapturePath, $ReadyPath, $Status, $Body, $Delay, $LocationHeader)
        $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
        try {
            $listener.Start()
            [IO.File]::WriteAllText(
                $ReadyPath,
                [string]$listener.LocalEndpoint.Port,
                [Text.UTF8Encoding]::new($false)
            )
            $accept = $listener.AcceptTcpClientAsync()
            if (-not $accept.Wait(10000)) {
                return
            }
            $client = $accept.Result
            try {
                $stream = $client.GetStream()
                $received = [Collections.Generic.List[byte]]::new()
                $buffer = [byte[]]::new(4096)
                $headerEnd = -1
                $contentLength = 0
                while ($true) {
                    $count = $stream.Read($buffer, 0, $buffer.Length)
                    if ($count -eq 0) {
                        break
                    }
                    for ($index = 0; $index -lt $count; $index++) {
                        $received.Add($buffer[$index])
                    }
                    $bytes = $received.ToArray()
                    $text = [Text.Encoding]::ASCII.GetString($bytes)
                    if ($headerEnd -lt 0) {
                        $headerEnd = $text.IndexOf("`r`n`r`n", [StringComparison]::Ordinal)
                        if ($headerEnd -ge 0 -and
                            $text.Substring(0, $headerEnd) -match '(?im)^Content-Length:\s*(\d+)\s*$') {
                            $contentLength = [int]$Matches[1]
                        }
                    }
                    if ($headerEnd -ge 0 -and
                        $received.Count -ge $headerEnd + 4 + $contentLength) {
                        break
                    }
                }

                $allBytes = $received.ToArray()
                $headerText = [Text.Encoding]::ASCII.GetString($allBytes, 0, $headerEnd)
                $headerLines = @($headerText -split "`r`n")
                $headers = @()
                foreach ($line in @($headerLines | Select-Object -Skip 1)) {
                    $separator = $line.IndexOf(":")
                    if ($separator -gt 0) {
                        $headers += [ordered]@{
                            name = $line.Substring(0, $separator)
                            value = $line.Substring($separator + 1).Trim()
                        }
                    }
                }
                $bodyBytes = [byte[]]::new($contentLength)
                if ($contentLength -gt 0) {
                    [Array]::Copy(
                        $allBytes, $headerEnd + 4, $bodyBytes, 0, $contentLength
                    )
                }
                $captureValue = [ordered]@{
                    request_line = $headerLines[0]
                    headers = $headers
                    body = [Text.Encoding]::UTF8.GetString($bodyBytes)
                } | ConvertTo-Json -Compress -Depth 4
                [IO.File]::WriteAllText(
                    $CapturePath,
                    $captureValue,
                    [Text.UTF8Encoding]::new($false)
                )

                if ($Delay -gt 0) {
                    Start-Sleep -Milliseconds $Delay
                }
                $reason = if ($Status -eq 200) { "OK" } elseif ($Status -eq 401) { "Unauthorized" } else { "Error" }
                $responseBytes = [Text.Encoding]::UTF8.GetBytes($Body)
                $locationLine = if ($LocationHeader) { "Location: $LocationHeader`r`n" } else { "" }
                $responseHead = "HTTP/1.1 $Status $reason`r`n${locationLine}Content-Type: application/json`r`nX-Fixture-Response: fixture-response-body-value`r`nContent-Length: $($responseBytes.Length)`r`nConnection: close`r`n`r`n"
                $headBytes = [Text.Encoding]::ASCII.GetBytes($responseHead)
                $stream.Write($headBytes, 0, $headBytes.Length)
                $stream.Write($responseBytes, 0, $responseBytes.Length)
                $stream.Flush()
            } finally {
                $client.Dispose()
            }
        } finally {
            $listener.Stop()
        }
    }
    foreach ($attempt in 1..200) {
        if (Test-Path -LiteralPath $ready -PathType Leaf) {
            return [pscustomobject]@{
                Capture = $capture
                Job = $job
                Url = "http://127.0.0.1:$((Get-Content -Raw -LiteralPath $ready).Trim())/v1/sign"
            }
        }
        if ($job.State -ne "Running") {
            break
        }
        Start-Sleep -Milliseconds 25
    }
    Stop-Job -Job $job -ErrorAction SilentlyContinue
    Remove-Job -Job $job -Force -ErrorAction SilentlyContinue
    throw "Test signer did not start"
}

function Complete-TestSigner {
    param($Signer)
    $null = Wait-Job -Job $Signer.Job -Timeout 5
    if ($Signer.Job.State -eq "Running") {
        Stop-Job -Job $Signer.Job
    }
    $null = Receive-Job -Job $Signer.Job -ErrorAction SilentlyContinue
    Remove-Job -Job $Signer.Job -Force
}

function Invoke-Publisher {
    param(
        [string]$PlatformId = "windows-x64",
        [string]$AssetPath = (New-Asset $PlatformId),
        [string]$SigningMode = "Local",
        [int]$SigningTimeoutSeconds = 30,
        [switch]$UseDefaultSigningMode,
        [switch]$AllowTestLoopbackSigningUrl
    )
    $records = @()
    $failed = $false
    $arguments = @{
        Version = $Version
        Commit = $Commit
        PublishedAt = $PublishedAt
        PlatformId = $PlatformId
        AssetPath = $AssetPath
        ReleaseNotesPath = $releaseNotes
        SigningPrivateKeyPath = $privateKey
        SigningTimeoutSeconds = $SigningTimeoutSeconds
        Confirm = $false
    }
    if (-not $UseDefaultSigningMode) {
        $arguments.SigningMode = $SigningMode
    }
    if ($AllowTestLoopbackSigningUrl) {
        $arguments.AllowTestLoopbackSigningUrl = $true
    }
    try {
        $records = @(& $publisher @arguments 2>&1)
    } catch {
        $failed = $true
        $records += $_.Exception.Message
    }
    [pscustomobject]@{ Failed = $failed; Output = ($records -join [Environment]::NewLine) }
}

function Invoke-RemotePublisher {
    param(
        [int]$StatusCode,
        [string]$ResponseBody,
        [int]$DelayMilliseconds = 0,
        [int]$TimeoutSeconds = 30,
        [switch]$UseDefaultSigningMode
    )
    Reset-FakeR2
    $signer = Start-TestSigner `
        -StatusCode $StatusCode `
        -ResponseBody $ResponseBody `
        -DelayMilliseconds $DelayMilliseconds
    $env:BACKCHANNEL_RELEASE_SIGNING_URL = $signer.Url
    try {
        $result = Invoke-Publisher `
            -AssetPath (New-Asset) `
            -SigningMode Remote `
            -SigningTimeoutSeconds $TimeoutSeconds `
            -UseDefaultSigningMode:$UseDefaultSigningMode `
            -AllowTestLoopbackSigningUrl
    } finally {
        Complete-TestSigner $signer
    }
    $capture = if (Test-Path -LiteralPath $signer.Capture -PathType Leaf) {
        Get-Content -Raw -LiteralPath $signer.Capture | ConvertFrom-Json
    } else {
        $null
    }
    [pscustomobject]@{ Result = $result; Capture = $capture }
}

function Assert-NoFixtureLeak {
    param([string]$Output, [string[]]$Additional = @())
    foreach ($secret in @(
        "fixture-client-id",
        "fixture-client-secret",
        "fixture-private-value",
        "fixture-response-body-value"
    ) + $Additional) {
        Assert-True (-not $Output.Contains($secret)) "Publisher leaked a fixture secret"
    }
}

function Get-CapturedHeader {
    param($Capture, [string]$Name)
    $matches = @($Capture.headers | Where-Object { $_.name -ceq $Name })
    Assert-True ($matches.Count -eq 1) "Missing or duplicate captured header: $Name"
    $matches[0].value
}

try {
    $fakeNode = Join-Path $temporary "node.cmd"
    $fakeNodeScript = Join-Path $temporary "fake-r2.ps1"
    $fakePython = Join-Path $temporary "python.cmd"
    $fakePythonScript = Join-Path $temporary "fake-python.ps1"
    $releaseNotes = Join-Path $temporary "release-notes.md"
    $privateKey = Join-Path $temporary "release-signing.private"
    Write-Utf8 $releaseNotes "test notes"
    Write-Utf8 $privateKey "fixture-private-value"
    $env:BACKCHANNEL_RELEASE_SIGNING_PRIVATE_KEY = $null

    Write-Utf8 $fakeNode "@echo off`r`n`"%R2_FAKE_POWERSHELL%`" -NoProfile -ExecutionPolicy Bypass -File `"%R2_FAKE_SCRIPT%`" %*`r`nexit /b %ERRORLEVEL%`r`n"
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

    Write-Utf8 $fakePython "@echo off`r`n`"%R2_FAKE_POWERSHELL%`" -NoProfile -ExecutionPolicy Bypass -File `"$fakePythonScript`" %*`r`nexit /b %ERRORLEVEL%`r`n"
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
function WriteExactUtf8([string]$Path, [string]$Text) {
    $parent = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Path $parent | Out-Null
    }
    [IO.File]::WriteAllText($Path, $Text, [Text.UTF8Encoding]::new($false))
}
$tag = $options["tag"]
$commit = $options["commit"]
$publishedAt = $options["published-at"]
$asset = $options["asset"]
$platformId = $options["platform-id"]
$info = Info $platformId
$sha = (Get-FileHash -Algorithm SHA256 -LiteralPath $asset).Hash.ToLowerInvariant()
$size = (Get-Item -LiteralPath $asset).Length
$request = '{{"asset":{{"filename":"{0}","id":"{1}","platform":"{2}","sha256":"{3}","size":{4}}},"commit":"{5}","key_id":"ed25519-2026-07","published_at":"{6}","release_notes":"test notes","schema":1,"version":"{7}"}}' -f $info[1], $platformId, $info[0], $sha, $size, $commit, $publishedAt, $tag
if ($options.ContainsKey("signing-request-out")) {
    WriteExactUtf8 $options["signing-request-out"] $request
    if ($env:R2_FAKE_SIGNING_REQUEST_FAILURE) {
        exit 2
    }
    exit 0
}
if ($options.ContainsKey("detached-key-id")) {
    if ($options["detached-key-id"] -cne "ed25519-2026-07" -or
        $options["detached-signature"] -cne ("A" * 86)) {
        [Console]::Error.WriteLine("detached verification failed")
        exit 2
    }
    $signature = $options["detached-signature"]
} else {
    if ($env:BACKCHANNEL_RELEASE_SIGNING_PRIVATE_KEY -cne "fixture-private-value") {
        [Console]::Error.WriteLine("local signing input rejected")
        exit 2
    }
    $signature = "A" * 86
}
WriteUtf8 $options["release-out"] ('{{"commit":"{0}","published_at":"{1}","version":"{2}"}}' -f $commit, $publishedAt, $tag)
WriteUtf8 $options["platform-out"] ('{{"asset":{{"content_type":"{0}","filename":"{1}","id":"{2}","key":"releases/{3}/{1}","platform":"{4}","sha256":"{5}","size":{6}}},"commit":"{7}","published_at":"{8}","release_notes":"test notes","update":{{"key_id":"ed25519-2026-07","schema":1,"signature":"{9}"}},"version":"{3}"}}' -f $info[2], $info[1], $platformId, $tag, $info[0], $sha, $size, $commit, $publishedAt, $signature)
'@

    $env:R2_FAKE_SCRIPT = $fakeNodeScript
    $env:R2_FAKE_STORE = $store
    $env:R2_FAKE_LOG = $log
    $env:R2_FAKE_POWERSHELL = (Get-Process -Id $PID).Path
    $env:R2_FAKE_SIGNING_REQUEST_FAILURE = $null
    $env:PATH = "$temporary;$oldPath"

    $env:BACKCHANNEL_RELEASE_SIGNING_PRIVATE_KEY = "fixture-private-value"
    $env:CLOUDFLARE_ACCESS_CLIENT_ID = "fixture-client-id"
    $env:CLOUDFLARE_ACCESS_CLIENT_SECRET = "fixture-client-secret"
    $validResponse = '{{"key_id":"ed25519-2026-07","signature":"{0}"}}' -f $validSignature
    $remote = Invoke-RemotePublisher `
        -StatusCode 200 `
        -ResponseBody $validResponse `
        -UseDefaultSigningMode
    Assert-True (-not $remote.Result.Failed) "Remote publication failed: $($remote.Result.Output)"
    Assert-True ($null -ne $remote.Capture) "Remote signer did not capture a request"
    Assert-True ($remote.Capture.request_line -ceq "POST /v1/sign HTTP/1.1") "Wrong signer request target"
    Assert-True ($remote.Capture.body -ceq $expectedSigningRequest) "Wrong canonical signing request bytes"
    Assert-True (
        (Get-CapturedHeader $remote.Capture "CF-Access-Client-Id") -ceq "fixture-client-id"
    ) "Wrong Access client ID"
    Assert-True (
        (Get-CapturedHeader $remote.Capture "CF-Access-Client-Secret") -ceq "fixture-client-secret"
    ) "Wrong Access client secret"
    Assert-True (
        (Get-CapturedHeader $remote.Capture "Content-Type") -ceq "application/json"
    ) "Wrong signer content type"
    Assert-NoFixtureLeak $remote.Result.Output
    Assert-True (@(Read-Log).Count -gt 0) "Remote publication did not reach R2"

    $responseSecret = "fixture-response-body-value"
    $failureCases = @(
        @{
            Label = "timeout"
            Status = 200
            Body = $validResponse
            Delay = 1500
            Timeout = 1
        },
        @{
            Label = "401"
            Status = 401
            Body = $responseSecret
            Delay = 0
            Timeout = 30
        },
        @{
            Label = "malformed response"
            Status = 200
            Body = "not-json-$responseSecret"
            Delay = 0
            Timeout = 30
        },
        @{
            Label = "extra response field"
            Status = 200
            Body = ('{{"extra":"no","key_id":"ed25519-2026-07","signature":"{0}"}}' -f $validSignature)
            Delay = 0
            Timeout = 30
        },
        @{
            Label = "top-level array"
            Status = 200
            Body = ('[{{"key_id":"ed25519-2026-07","signature":"{0}"}}]' -f $validSignature)
            Delay = 0
            Timeout = 30
        },
        @{
            Label = "wrong key ID"
            Status = 200
            Body = ('{{"key_id":"other-key","signature":"{0}"}}' -f $validSignature)
            Delay = 0
            Timeout = 30
        },
        @{
            Label = "invalid signature"
            Status = 200
            Body = ('{{"key_id":"ed25519-2026-07","signature":"{0}"}}' -f $invalidSignature)
            Delay = 0
            Timeout = 30
        }
    )
    foreach ($case in $failureCases) {
        $remote = Invoke-RemotePublisher `
            -StatusCode $case.Status `
            -ResponseBody $case.Body `
            -DelayMilliseconds $case.Delay `
            -TimeoutSeconds $case.Timeout
        Assert-True $remote.Result.Failed "$($case.Label) was accepted"
        Assert-True (@(Read-Log).Count -eq 0) "$($case.Label) reached R2"
        Assert-NoFixtureLeak $remote.Result.Output @($responseSecret)
    }

    Reset-FakeR2
    $redirectTarget = Start-TestSigner -StatusCode 200 -ResponseBody $validResponse
    $redirectSource = Start-TestSigner `
        -StatusCode 302 `
        -ResponseBody $responseSecret `
        -Location $redirectTarget.Url
    $env:BACKCHANNEL_RELEASE_SIGNING_URL = $redirectSource.Url
    try {
        $result = Invoke-Publisher `
            -SigningMode Remote `
            -AssetPath (New-Asset) `
            -AllowTestLoopbackSigningUrl
    } finally {
        Complete-TestSigner $redirectSource
        Complete-TestSigner $redirectTarget
    }
    Assert-True $result.Failed "Signer redirect was followed"
    Assert-True (
        -not (Test-Path -LiteralPath $redirectTarget.Capture -PathType Leaf)
    ) "Signer redirect reached another authority"
    Assert-True (@(Read-Log).Count -eq 0) "Signer redirect reached R2"
    Assert-NoFixtureLeak $result.Output @($responseSecret)

    $env:R2_FAKE_SIGNING_REQUEST_FAILURE = "1"
    try {
        Reset-FakeR2
        $env:BACKCHANNEL_RELEASE_SIGNING_URL = "https://signing.backchannel.page/v1/sign"
        $result = Invoke-Publisher -SigningMode Remote -AssetPath (New-Asset)
        Assert-True $result.Failed "Production signer validation did not reach the safe fixture stop"
        Assert-True (
            $result.Output.Contains("Platform metadata validation failed")
        ) "Exact production signer authority was rejected"
        Assert-True (@(Read-Log).Count -eq 0) "Signer validation reached R2"

        $invalidSigningUrls = @(
            @{ Label = "non-HTTPS URL"; Url = "http://example.com/v1/sign" },
            @{ Label = "implicit loopback"; Url = "http://127.0.0.1:12345/v1/sign" },
            @{ Label = "wrong host"; Url = "https://example.com/v1/sign" },
            @{ Label = "wrong port"; Url = "https://signing.backchannel.page:444/v1/sign" },
            @{ Label = "wrong path"; Url = "https://signing.backchannel.page/v1/other" },
            @{ Label = "query"; Url = "https://signing.backchannel.page/v1/sign?next=other" },
            @{ Label = "userinfo"; Url = "https://fixture-user@signing.backchannel.page/v1/sign" },
            @{ Label = "fragment"; Url = "https://signing.backchannel.page/v1/sign#other" }
        )
        foreach ($case in $invalidSigningUrls) {
            Reset-FakeR2
            $env:BACKCHANNEL_RELEASE_SIGNING_URL = $case.Url
            $result = Invoke-Publisher -SigningMode Remote -AssetPath (New-Asset)
            Assert-True $result.Failed "$($case.Label) signer URL was accepted"
            Assert-True (
                $result.Output.Contains("Remote release signing configuration is invalid")
            ) "$($case.Label) signer URL did not fail closed"
            Assert-True (@(Read-Log).Count -eq 0) "$($case.Label) signer URL reached R2"
        }

        Reset-FakeR2
        $env:BACKCHANNEL_RELEASE_SIGNING_URL = "http://example.com/v1/sign"
        $result = Invoke-Publisher `
            -SigningMode Remote `
            -AssetPath (New-Asset) `
            -AllowTestLoopbackSigningUrl
        Assert-True $result.Failed "Test-only signer switch accepted a non-loopback authority"
        Assert-True (
            $result.Output.Contains("Remote release signing configuration is invalid")
        ) "Test-only signer switch accepted a non-loopback authority"
        Assert-True (@(Read-Log).Count -eq 0) "Test-only signer switch reached R2"
    } finally {
        $env:R2_FAKE_SIGNING_REQUEST_FAILURE = $null
    }

    $env:BACKCHANNEL_RELEASE_SIGNING_PRIVATE_KEY = $null
    Remove-Item -LiteralPath $privateKey -Force
    Reset-FakeR2
    $result = Invoke-Publisher
    Assert-True $result.Failed "Missing signing key was accepted"
    Assert-True (@(Read-Log).Count -eq 0) "Missing signing key reached R2"
    Write-Utf8 $privateKey "fixture-private-value"

    Reset-FakeR2
    $asset = New-Asset
    $result = Invoke-Publisher -AssetPath $asset
    Assert-True (-not $result.Failed) "New Windows publication failed: $($result.Output)"
    Assert-NoFixtureLeak $result.Output
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
    $asset = New-Asset
    Put-Object "releases/v1.2.3/Backchannel-windows-x64.zip" "bundle"
    $result = Invoke-Publisher -AssetPath $asset
    Assert-True (-not $result.Failed) "Matching orphan asset was not reusable: $($result.Output)"
    Assert-True ((Read-Log) -contains "get releases/v1.2.3/Backchannel-windows-x64.zip") `
        "Existing orphan asset was not read back"

    Reset-FakeR2
    Put-Object "releases/v1.2.3/Backchannel-windows-x64.zip" "different"
    $result = Invoke-Publisher -AssetPath (New-Asset)
    Assert-True $result.Failed "Conflicting orphan asset was overwritten"
    $joinedLog = (Read-Log) -join "`n"
    Assert-True (-not $joinedLog.Contains("head releases/v1.2.3/Backchannel-windows-x64.zip")) `
        "Conflicting orphan asset reached remote-size verification"
    Assert-True (-not $joinedLog.Contains("put releases/v1.2.3/platforms/windows-x64.json")) `
        "Conflicting orphan asset created immutable metadata"

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

    Reset-FakeR2
    Put-Object "releases/latest.json" '{"extra":true,"version":"v9.0.0"}'
    $result = Invoke-Publisher -AssetPath (New-Asset)
    Assert-True $result.Failed "Non-canonical Latest metadata was accepted"
    Assert-True ($result.Output.Contains("Latest metadata is invalid")) `
        "Invalid Latest error was unclear"

    Write-Output "Immutable platform publisher classification ($($PSVersionTable.PSEdition) $($PSVersionTable.PSVersion)): OK"
} finally {
    $env:PATH = $oldPath
    $env:R2_FAKE_SCRIPT = $oldFakeScript
    $env:R2_FAKE_STORE = $oldFakeStore
    $env:R2_FAKE_LOG = $oldFakeLog
    $env:R2_FAKE_RACE_KEY = $oldFakeRaceKey
    $env:R2_FAKE_RACE_DIR = $oldFakeRaceDir
    $env:R2_FAKE_HEAD_SIZE = $oldFakeHeadSize
    $env:R2_FAKE_SIGNING_REQUEST_FAILURE = $oldFakeSigningRequestFailure
    $env:R2_FAKE_POWERSHELL = $oldFakePowerShell
    $env:BACKCHANNEL_RELEASE_SIGNING_PRIVATE_KEY = $oldSigningSecret
    $env:BACKCHANNEL_RELEASE_SIGNING_URL = $oldSigningUrl
    $env:CLOUDFLARE_ACCESS_CLIENT_ID = $oldAccessClientId
    $env:CLOUDFLARE_ACCESS_CLIENT_SECRET = $oldAccessClientSecret
    foreach ($name in $credentialNames) {
        [Environment]::SetEnvironmentVariable($name, $oldCredentials[$name])
    }
    if (Test-Path -LiteralPath $temporary) {
        Remove-Item -LiteralPath $temporary -Recurse -Force
    }
}
