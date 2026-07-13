$ErrorActionPreference = "Stop"

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) {
        throw $Message
    }
}

$migration = Join-Path (Split-Path -Parent $PSScriptRoot) "migrate_releases_to_r2.ps1"
$tokens = $null
$errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile(
    $migration,
    [ref]$tokens,
    [ref]$errors
)
Assert-True ($errors.Count -eq 0) "Migration script did not parse"
foreach ($name in @("Invoke-R2", "Assert-R2Success", "Get-RemoteLatest")) {
    $definition = $ast.Find(
        {
            param($node)
            $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
                $node.Name -eq $name
        },
        $true
    )
    if ($null -eq $definition) {
        throw "Missing function: $name"
    }
    . ([scriptblock]::Create($definition.Extent.Text))
}

$temporary = Join-Path ([IO.Path]::GetTempPath()) "backchannel-r2-test-$([guid]::NewGuid())"
New-Item -ItemType Directory -Path $temporary | Out-Null
$oldPath = $env:PATH
$oldFakeResult = $env:R2_FAKE_RESULT
$hadNativePreference = Test-Path Variable:PSNativeCommandUseErrorActionPreference
if ($hadNativePreference) {
    $oldNativePreference = $PSNativeCommandUseErrorActionPreference
}
$PSNativeCommandUseErrorActionPreference = $true
$script:R2Client = "C:\ignored\r2-object.mjs"
$script:Bucket = "test-bucket"

try {
    $env:PATH = "$temporary;$oldPath"
    $node = Join-Path $temporary "node.cmd"
    [IO.File]::WriteAllLines(
        $node,
        @(
            "@echo off",
            "shift",
            "if `%R2_FAKE_RESULT`%==missing (",
            "  >&2 echo {`"error`":`"request failed`",`"status`":404}",
            "  exit /b 44",
            ")",
            "if `%R2_FAKE_RESULT`%==denied (",
            "  >&2 echo {`"error`":`"request failed`",`"status`":403}",
            "  exit /b 1",
            ")",
            "if `%R2_FAKE_RESULT`%==invalid (",
            "  echo not-json",
            "  exit /b 0",
            ")",
            "echo {`"etag`":`"\`"release-etag\`"`",`"contentLength`":123,`"contentType`":`"application/json`"}",
            "exit /b 0"
        )
    )

    $env:R2_FAKE_RESULT = "success"
    $success = Invoke-R2 @("head", "--bucket", $script:Bucket, "--key", "releases/latest.json")
    Assert-True ($success.Code -eq 0) "Expected exit code 0, got $($success.Code)"
    Assert-True ($success.Data.etag -eq '"release-etag"') "Success JSON did not preserve the quoted ETag"
    Assert-True ($success.Data.contentLength -eq 123) "Success JSON was not parsed"
    Assert-True ($ErrorActionPreference -eq "Stop") "Invoke-R2 did not restore ErrorActionPreference"
    Assert-True $PSNativeCommandUseErrorActionPreference "Invoke-R2 did not restore PSNativeCommandUseErrorActionPreference"
    Assert-True (-not $success.Output.Contains("NativeCommandError")) "PowerShell diagnostics polluted stderr"

    $env:R2_FAKE_RESULT = "invalid"
    $ErrorActionPreference = "Continue"
    $invalidRejected = $false
    try {
        $null = Invoke-R2 @("head", "--bucket", $script:Bucket, "--key", "releases/latest.json")
    } catch {
        $invalidRejected = $true
    }
    $restoredContinuePreference = $ErrorActionPreference -eq "Continue"
    $ErrorActionPreference = "Stop"
    Assert-True $invalidRejected "Invalid success JSON did not fail closed"
    Assert-True $restoredContinuePreference "Invoke-R2 did not restore a Continue ErrorActionPreference"

    $env:R2_FAKE_RESULT = "missing"
    $missing = Invoke-R2 @("get", "--bucket", $script:Bucket, "--key", "releases/latest.json", "--output", "ignored.json")
    Assert-True ($missing.Code -eq 44) "Expected exit code 44, got $($missing.Code)"
    Assert-True ($null -eq $missing.Data) "Failure output was parsed as success JSON"
    Assert-True (-not $missing.Output.Contains("NativeCommandError")) "PowerShell diagnostics polluted stderr"
    $latest = Get-RemoteLatest (Join-Path $temporary "latest.json")
    Assert-True (-not $latest.Exists) "Exit 44 did not produce an absent Latest"
    $missingRejected = $false
    try {
        Assert-R2Success $missing "Checking missing object"
    } catch {
        $missingRejected = $_.Exception.Message.Contains("Checking missing object failed")
    }
    Assert-True $missingRejected "Assert-R2Success accepted exit 44"

    $env:R2_FAKE_RESULT = "denied"
    $denied = Invoke-R2 @("get", "--bucket", $script:Bucket, "--key", "releases/latest.json", "--output", "ignored.json")
    Assert-True ($denied.Code -eq 1) "Expected exit code 1, got $($denied.Code)"
    $deniedRejected = $false
    try {
        Assert-R2Success $denied "Reading denied object"
    } catch {
        $deniedRejected = $_.Exception.Message.Contains("Reading denied object failed")
    }
    Assert-True $deniedRejected "Assert-R2Success accepted exit 1"
    $failedClosed = $false
    try {
        Get-RemoteLatest (Join-Path $temporary "latest.json")
    } catch {
        $failedClosed = $_.Exception.Message.Contains("Reading Latest failed")
    }
    Assert-True $failedClosed "Access denied did not fail closed"
    Write-Output "Windows PowerShell native R2 classification: OK"
} finally {
    $env:PATH = $oldPath
    $env:R2_FAKE_RESULT = $oldFakeResult
    if ($hadNativePreference) {
        $PSNativeCommandUseErrorActionPreference = $oldNativePreference
    } else {
        Remove-Variable PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue
    }
    if (Test-Path -LiteralPath $temporary) {
        Remove-Item -LiteralPath $temporary -Recurse -Force
    }
}
