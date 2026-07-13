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
foreach ($name in @("Invoke-Aws", "Test-NotFound", "Get-RemoteLatest")) {
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

$temporary = Join-Path ([IO.Path]::GetTempPath()) "backchannel-aws-test-$([guid]::NewGuid())"
New-Item -ItemType Directory -Path $temporary | Out-Null
$oldPath = $env:PATH
$script:Endpoint = "https://example.invalid"
$script:Bucket = "test-bucket"

try {
    $env:PATH = "$temporary;$oldPath"
    $aws = Join-Path $temporary "aws.cmd"
    [IO.File]::WriteAllLines(
        $aws,
        @(
            "@echo off",
            ">&2 echo An error occurred (NoSuchKey) when calling the GetObject operation: The specified key does not exist.",
            "exit /b 255"
        )
    )

    $expected = Invoke-Aws @("s3api", "get-object")
    Assert-True ($expected.Code -eq 255) "Expected exit code 255, got $($expected.Code)"
    Assert-True (Test-NotFound $expected.Output "GetObject") "NoSuchKey was not classified"
    Assert-True (-not $expected.Output.Contains("NativeCommandError")) "PowerShell diagnostics polluted stderr"
    Assert-True ($ErrorActionPreference -eq "Stop") "Invoke-Aws did not restore ErrorActionPreference"
    $latest = Get-RemoteLatest (Join-Path $temporary "latest.json")
    Assert-True (-not $latest.Exists) "NoSuchKey did not produce an absent Latest"

    [IO.File]::WriteAllLines(
        $aws,
        @(
            "@echo off",
            ">&2 echo An error occurred (AccessDenied) when calling the GetObject operation: denied",
            "exit /b 254"
        )
    )
    $unexpected = Invoke-Aws @("s3api", "get-object")
    Assert-True ($unexpected.Code -eq 254) "Expected exit code 254, got $($unexpected.Code)"
    Assert-True (-not (Test-NotFound $unexpected.Output "GetObject")) "AccessDenied was treated as absence"
    $failedClosed = $false
    try {
        Get-RemoteLatest (Join-Path $temporary "latest.json")
    } catch {
        $failedClosed = $_.Exception.Message.Contains("Reading Latest failed")
    }
    Assert-True $failedClosed "AccessDenied did not fail closed"
    Write-Output "Windows PowerShell native AWS classification: OK"
} finally {
    $env:PATH = $oldPath
    if (Test-Path -LiteralPath $temporary) {
        Remove-Item -LiteralPath $temporary -Recurse -Force
    }
}
