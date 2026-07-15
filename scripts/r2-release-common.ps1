Set-StrictMode -Version Latest

function Invoke-R2Object {
    param(
        [Parameter(Mandatory = $true, Position = 0)][string]$Client,
        [Parameter(Position = 1, ValueFromRemainingArguments = $true)][string[]]$Arguments
    )

    $savedErrorActionPreference = $ErrorActionPreference
    $hasNativePreference = Test-Path Variable:PSNativeCommandUseErrorActionPreference
    if ($hasNativePreference) {
        $savedNativePreference = $PSNativeCommandUseErrorActionPreference
    }
    try {
        $ErrorActionPreference = "Continue"
        if ($hasNativePreference) {
            $PSNativeCommandUseErrorActionPreference = $false
        }
        $records = @(& node $Client @Arguments 2>&1)
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $savedErrorActionPreference
        if ($hasNativePreference) {
            $PSNativeCommandUseErrorActionPreference = $savedNativePreference
        }
    }
    $output = ($records | ForEach-Object { $_.ToString() }) -join [Environment]::NewLine
    $output = $output.Trim()
    $data = $null
    if ($exitCode -eq 0) {
        $data = $output | ConvertFrom-Json
    }
    [pscustomobject]@{ Code = $exitCode; Output = $output; Data = $data }
}

function Assert-R2Success {
    param(
        [object]$Result,
        [string]$Action
    )

    if ($Result.Code -ne 0) {
        throw "$Action failed: $($Result.Output)"
    }
}

function Get-R2Latest {
    param(
        [Parameter(Mandatory = $true)][string]$Destination,
        [Parameter(Mandatory = $true)][string]$Bucket,
        [Parameter(Mandatory = $true)][string]$Client
    )
    if (Test-Path -LiteralPath $Destination) {
        Remove-Item -LiteralPath $Destination -Force
    }
    $result = Invoke-R2Object `
        -Client $Client `
        -Arguments @("get", "--bucket", $Bucket, "--key", "releases/latest.json", "--output", $Destination)
    if ($result.Code -eq 0) {
        return [pscustomobject]@{ Exists = $true; ETag = $result.Data.etag }
    }
    if ($result.Code -eq 44) {
        return [pscustomobject]@{ Exists = $false; ETag = $null }
    }
    throw "Reading Latest failed: $($result.Output)"
}
