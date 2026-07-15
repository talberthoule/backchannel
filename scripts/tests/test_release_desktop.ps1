$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Assert-True {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) {
        throw $Message
    }
}

$coordinator = Join-Path (Split-Path -Parent $PSScriptRoot) "release_desktop.ps1"
Assert-True (Test-Path -LiteralPath $coordinator -PathType Leaf) `
    "Release coordinator file is missing"
$tokens = $null
$errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile(
    $coordinator,
    [ref]$tokens,
    [ref]$errors
)
Assert-True ($errors.Count -eq 0) "Release coordinator did not parse"

$requiredFunctions = @(
    "Invoke-Checked",
    "Test-ExactProperties",
    "Resolve-ReleaseTag",
    "Get-ReleasePublicationState",
    "Invoke-GhJson",
    "Remove-StaleMacArtifacts",
    "Build-WindowsRelease",
    "Build-LinuxRelease"
)
$definitions = @{}
foreach ($name in $requiredFunctions) {
    $definition = $ast.Find(
        {
            param($node)
            $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
                $node.Name -eq $name
        },
        $true
    )
    Assert-True ($null -ne $definition) "Missing function: $name"
    $definitions[$name] = $definition.Extent.Text
}

$source = [IO.File]::ReadAllText($coordinator)
$gitignore = [IO.File]::ReadAllText(
    (Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) ".gitignore")
)
Assert-True $gitignore.Contains("release-assets/") `
    "Versioned local release assets are not ignored"
foreach ($value in @(
    "SupportsShouldProcess",
    "worktree add --detach",
    "^{commit}",
    "taggerdate",
    "workflow run desktop-release.yml",
    "desktop-release.yml",
    "publish_release_platform.ps1",
    "Backchannel-windows-x64.zip",
    "Backchannel-linux-x64.tar.gz",
    "run watch",
    "release view",
    "finally"
)) {
    Assert-True $source.Contains($value) "Coordinator is missing contract text: $value"
}
$main = $source.Substring($source.IndexOf('$localPending'))
Assert-True ($main.IndexOf("Build-WindowsRelease") -lt $main.IndexOf("Build-LinuxRelease")) `
    "Windows must be attempted before Linux"
Assert-True ($main.IndexOf("Build-LinuxRelease") -lt $main.IndexOf("run watch")) `
    "Local publication must not wait for macOS"
Assert-True $main.Contains('-Dockerfile (Join-Path $repoRoot "desktop\Dockerfile.release-linux")') `
    "Linux must use controller tooling while building the exact tagged source"
foreach ($platformId in @("windows-x64", "linux-x64")) {
    Assert-True $main.Contains('elseif ($state["' + $platformId + '"] -eq "Pending")') `
        "Completed $platformId metadata does not skip its build"
}
Assert-True $source.Contains('elseif ($state["macos-arm64"] -eq "Pending")') `
    "Completed macOS metadata does not skip dispatch"

. ([scriptblock]::Create($definitions["Remove-StaleMacArtifacts"]))

$now = [DateTimeOffset]::Parse("2026-07-15T18:00:00Z")
$script:Artifacts = @(
    [pscustomobject]@{ id = 1; name = "Backchannel-macos-arm64.zip"; created_at = "2026-07-14T17:00:00Z"; workflow_run = [pscustomobject]@{ id = 101 } },
    [pscustomobject]@{ id = 2; name = "Backchannel-macos-arm64.zip"; created_at = "2026-07-15T17:00:00Z"; workflow_run = [pscustomobject]@{ id = 102 } },
    [pscustomobject]@{ id = 3; name = "Backchannel-macos-arm64.zip"; created_at = "2026-07-14T17:00:00Z"; workflow_run = [pscustomobject]@{ id = 103 } },
    [pscustomobject]@{ id = 4; name = "Unrelated.zip"; created_at = "2026-07-14T17:00:00Z"; workflow_run = [pscustomobject]@{ id = 104 } },
    [pscustomobject]@{ id = 5; name = "Backchannel-macos-arm64.zip"; created_at = "2026-07-14T17:00:00Z"; workflow_run = [pscustomobject]@{ id = 105 } }
)
$script:Runs = @{
    101 = [pscustomobject]@{ path = ".github/workflows/desktop-release.yml"; status = "completed" }
    102 = [pscustomobject]@{ path = ".github/workflows/desktop-release.yml"; status = "completed" }
    103 = [pscustomobject]@{ path = ".github/workflows/another.yml"; status = "completed" }
    105 = [pscustomobject]@{ path = ".github/workflows/desktop-release.yml"; status = "in_progress" }
}
$script:Deleted = [Collections.Generic.List[int]]::new()
$script:FailGh = $false

function Invoke-GhJson {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)
    if ($script:FailGh) {
        throw "simulated gh failure"
    }
    $endpoint = $Arguments[-1]
    if ($Arguments -contains "DELETE") {
        $script:Deleted.Add([int]($endpoint -replace '^.*/', ''))
        return $null
    }
    if ($endpoint -match '/runs/(?<id>[0-9]+)$') {
        return $script:Runs[[int]$Matches.id]
    }
    return ,@([pscustomobject]@{ artifacts = $script:Artifacts })
}

Remove-StaleMacArtifacts -Repository "owner/repo" -Now $now
Assert-True ($script:Deleted.Count -eq 1) "Cleanup deleted the wrong number of artifacts"
Assert-True ($script:Deleted[0] -eq 1) "Cleanup did not select only the stale exact artifact"

$script:FailGh = $true
$failurePropagated = $false
try {
    Remove-StaleMacArtifacts -Repository "owner/repo" -Now $now
} catch {
    $failurePropagated = $_.Exception.Message.Contains("simulated gh failure")
}
Assert-True $failurePropagated "Artifact API failure did not block cleanup"

. ([scriptblock]::Create($definitions["Test-ExactProperties"]))
. ([scriptblock]::Create($definitions["Get-ReleasePublicationState"]))

$script:R2Objects = @{}
function Invoke-R2Object {
    param(
        [Parameter(Mandatory = $true)][string]$Client,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )
    $keyIndex = [Array]::IndexOf($Arguments, "--key")
    $outputIndex = [Array]::IndexOf($Arguments, "--output")
    Assert-True ($Arguments[0] -eq "get") "Preflight issued a non-read R2 operation"
    Assert-True ($keyIndex -ge 0 -and $outputIndex -ge 0) "Preflight omitted key or output"
    $key = $Arguments[$keyIndex + 1]
    if (-not $script:R2Objects.ContainsKey($key)) {
        return [pscustomobject]@{ Code = 44; Output = "missing"; Data = $null }
    }
    [IO.File]::WriteAllText($Arguments[$outputIndex + 1], $script:R2Objects[$key])
    return [pscustomobject]@{ Code = 0; Output = '{}'; Data = [pscustomobject]@{} }
}

$version = "v1.2.3"
$commit = "0123456789abcdef0123456789abcdef01234567"
$publishedAt = "2026-07-15T18:00:00Z"
$state = Get-ReleasePublicationState `
    -Version $version -Commit $commit -PublishedAt $publishedAt `
    -Bucket "test-bucket" -Client "ignored.mjs"
foreach ($platformId in @("windows-x64", "linux-x64", "macos-arm64")) {
    Assert-True ($state[$platformId] -eq "Pending") "Missing release was not pending: $platformId"
}

$script:R2Objects["releases/$version/release.json"] = @"
{"commit":"$commit","published_at":"$publishedAt","version":"$version"}
"@
$script:R2Objects["releases/$version/platforms/windows-x64.json"] = @"
{"asset":{"content_type":"application/zip","filename":"Backchannel-windows-x64.zip","id":"windows-x64","key":"releases/$version/Backchannel-windows-x64.zip","platform":"Windows x64","sha256":"$("a" * 64)","size":10},"commit":"$commit","version":"$version"}
"@
$state = Get-ReleasePublicationState `
    -Version $version -Commit $commit -PublishedAt $publishedAt `
    -Bucket "test-bucket" -Client "ignored.mjs"
Assert-True ($state["windows-x64"] -eq "Completed") "Valid Windows metadata was not completed"
Assert-True ($state["linux-x64"] -eq "Pending") "Missing Linux metadata was not pending"

$script:R2Objects["releases/$version/platforms/linux-x64.json"] = @"
{"asset":{"content_type":"application/gzip","filename":"wrong.tar.gz","id":"linux-x64","key":"releases/$version/Backchannel-linux-x64.tar.gz","platform":"Linux x64","sha256":"$("b" * 64)","size":10},"commit":"$commit","version":"$version"}
"@
$state = Get-ReleasePublicationState `
    -Version $version -Commit $commit -PublishedAt $publishedAt `
    -Bucket "test-bucket" -Client "ignored.mjs"
Assert-True ($state["windows-x64"] -eq "Completed") "Invalid sibling hid valid Windows"
Assert-True ($state["linux-x64"] -eq "Failed") "Invalid Linux metadata did not fail"

$script:R2Objects["releases/$version/release.json"] = @"
{"commit":"$("f" * 40)","published_at":"$publishedAt","version":"$version"}
"@
$identityConflict = $false
try {
    $null = Get-ReleasePublicationState `
        -Version $version -Commit $commit -PublishedAt $publishedAt `
        -Bucket "test-bucket" -Client "ignored.mjs"
} catch {
    $identityConflict = $_.Exception.Message.Contains("release identity")
}
Assert-True $identityConflict "Conflicting release identity did not stop preflight"

$script:R2Objects.Remove("releases/$version/release.json")
$script:R2Objects.Remove("releases/$version/platforms/linux-x64.json")
$state = Get-ReleasePublicationState `
    -Version $version -Commit $commit -PublishedAt $publishedAt `
    -Bucket "test-bucket" -Client "ignored.mjs"
Assert-True ($state["windows-x64"] -eq "Failed") `
    "Platform metadata without release identity did not fail"

Write-Output "Desktop release coordinator contracts: OK"
