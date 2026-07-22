[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = "High")]
param(
    [Parameter(Mandatory = $true)]
    [string]$Version
)

. (Join-Path $PSScriptRoot "r2-release-common.ps1")

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$Action,
        [Parameter(Mandatory = $true)][scriptblock]$Command
    )

    $savedErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $output = @(& $Command 2>&1)
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $savedErrorActionPreference
    }
    $result = @($output | ForEach-Object { $_.ToString() })
    if ($exitCode -ne 0) {
        $details = ($result -join [Environment]::NewLine).Trim()
        if (-not [string]::IsNullOrWhiteSpace($details)) {
            throw "$Action failed$([Environment]::NewLine)$details"
        }
        throw "$Action failed"
    }
    if ($result.Count -gt 0) {
        Write-Output -NoEnumerate $result
    }
}

function Get-AndClearR2Credentials {
    param([Parameter(Mandatory = $true)][string[]]$Names)

    $credentials = @{}
    foreach ($name in $Names) {
        $value = [Environment]::GetEnvironmentVariable($name)
        if ([string]::IsNullOrWhiteSpace($value)) {
            throw "Missing required environment variable: $name"
        }
        $credentials[$name] = $value
    }
    foreach ($name in $Names) {
        [Environment]::SetEnvironmentVariable($name, $null)
    }
    return $credentials
}

function Invoke-WithR2Credentials {
    param(
        [Parameter(Mandatory = $true)][hashtable]$Credentials,
        [Parameter(Mandatory = $true)][scriptblock]$Command
    )

    $previous = @{}
    foreach ($name in $Credentials.Keys) {
        $previous[$name] = [Environment]::GetEnvironmentVariable($name)
        [Environment]::SetEnvironmentVariable($name, $Credentials[$name])
    }
    try {
        return & $Command
    } finally {
        foreach ($name in $Credentials.Keys) {
            [Environment]::SetEnvironmentVariable($name, $previous[$name])
        }
    }
}

function Test-ExactProperties {
    param(
        [object]$Value,
        [string[]]$Names
    )

    if ($null -eq $Value -or $Value -isnot [pscustomobject]) {
        return $false
    }
    $actual = @($Value.PSObject.Properties.Name | Sort-Object)
    $expected = @($Names | Sort-Object)
    return @(Compare-Object $actual $expected).Count -eq 0
}

function Resolve-ReleaseTag {
    param(
        [Parameter(Mandatory = $true)][string]$Version,
        [Parameter(Mandatory = $true)][string]$Git
    )

    if ($Version -notmatch '^(?=.{2,32}$)v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$') {
        throw "Version must be a canonical vX.Y.Z tag"
    }
    $type = (Invoke-Checked "Reading release tag type" { & $Git cat-file -t $Version })[-1].Trim()
    if ($type -ne "tag") {
        throw "Release ref must be an annotated tag: $Version"
    }
    $tagObject = (Invoke-Checked "Resolving release tag object" { & $Git rev-parse $Version })[-1].Trim()
    $commit = (Invoke-Checked "Resolving release commit" { & $Git rev-parse "$Version^{commit}" })[-1].Trim()
    if ($tagObject -notmatch '^[0-9a-f]{40}$' -or $commit -notmatch '^[0-9a-f]{40}$') {
        throw "Release tag did not resolve to canonical Git object IDs"
    }

    $remote = @{}
    $remoteLines = Invoke-Checked "Reading remote release tag" {
        & $Git ls-remote origin "refs/tags/$Version" "refs/tags/$Version^{}"
    }
    foreach ($line in $remoteLines) {
        $parts = $line -split "`t", 2
        if ($parts.Count -eq 2) {
            $remote[$parts[1]] = $parts[0]
        }
    }
    if ($remote["refs/tags/$Version"] -cne $tagObject -or
        $remote["refs/tags/$Version^{}"] -cne $commit) {
        throw "Local and remote release tags do not match"
    }

    $taggerDate = (Invoke-Checked "Reading annotated tag timestamp" {
        & $Git for-each-ref "--format=%(taggerdate:iso-strict)" "refs/tags/$Version"
    })[-1].Trim()
    try {
        $timestamp = [DateTimeOffset]::Parse(
            $taggerDate,
            [Globalization.CultureInfo]::InvariantCulture
        ).ToUniversalTime().ToString(
            "yyyy-MM-dd'T'HH:mm:ss'Z'",
            [Globalization.CultureInfo]::InvariantCulture
        )
    } catch {
        throw "Annotated tag timestamp is invalid"
    }
    return [pscustomobject]@{
        Version = $Version
        Commit = $commit
        PublishedAt = $timestamp
        TagObject = $tagObject
    }
}

function Get-ReleasePublicationState {
    param(
        [Parameter(Mandatory = $true)][string]$Version,
        [Parameter(Mandatory = $true)][string]$Commit,
        [Parameter(Mandatory = $true)][string]$PublishedAt,
        [Parameter(Mandatory = $true)][string]$Bucket,
        [Parameter(Mandatory = $true)][string]$Client
    )

    $platforms = [ordered]@{
        "windows-x64" = @("Windows x64", "Backchannel-windows-x64.zip", "application/zip")
        "linux-x64" = @("Linux x64", "Backchannel-linux-x64.tar.gz", "application/gzip")
        "macos-arm64" = @("macOS arm64", "Backchannel-macos-arm64.zip", "application/zip")
    }
    $state = [ordered]@{}
    foreach ($platformId in $platforms.Keys) {
        $state[$platformId] = "Pending"
    }

    $tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
    $temporary = Join-Path $tempRoot ("backchannel-release-preflight-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $temporary | Out-Null
    try {
        $identityPath = Join-Path $temporary "release.json"
        $identityResult = Invoke-R2Object -Client $Client -Arguments @(
            "get", "--bucket", $Bucket,
            "--key", "releases/$Version/release.json",
            "--output", $identityPath
        )
        $identityExists = $identityResult.Code -eq 0
        if ($identityResult.Code -notin @(0, 44)) {
            throw "Reading release identity failed: $($identityResult.Output)"
        }
        if ($identityExists) {
            try {
                $identity = Get-Content -Raw -LiteralPath $identityPath | ConvertFrom-Json
            } catch {
                throw "Existing release identity is invalid"
            }
            if (-not (Test-ExactProperties $identity @("commit", "published_at", "version")) -or
                $identity.version -cne $Version -or
                $identity.commit -cne $Commit -or
                $identity.published_at -cne $PublishedAt) {
                throw "Existing release identity conflicts with the annotated tag"
            }
        }

        foreach ($platformId in $platforms.Keys) {
            $platformPath = Join-Path $temporary "$platformId.json"
            $result = Invoke-R2Object -Client $Client -Arguments @(
                "get", "--bucket", $Bucket,
                "--key", "releases/$Version/platforms/$platformId.json",
                "--output", $platformPath
            )
            if ($result.Code -eq 44) {
                continue
            }
            if ($result.Code -ne 0) {
                throw "Reading $platformId metadata failed: $($result.Output)"
            }
            if (-not $identityExists) {
                $state[$platformId] = "Failed"
                Write-Warning "$platformId has platform metadata without release identity"
                continue
            }
            try {
                $manifest = Get-Content -Raw -LiteralPath $platformPath | ConvertFrom-Json
                $asset = $manifest.asset
                $trusted = $platforms[$platformId]
                $valid = (Test-ExactProperties $manifest @("asset", "commit", "version")) -and
                    (Test-ExactProperties $asset @(
                        "content_type", "filename", "id", "key", "platform", "sha256", "size"
                    )) -and
                    $manifest.version -ceq $Version -and
                    $manifest.commit -ceq $Commit -and
                    $asset.id -ceq $platformId -and
                    $asset.platform -ceq $trusted[0] -and
                    $asset.filename -ceq $trusted[1] -and
                    $asset.key -ceq "releases/$Version/$($trusted[1])" -and
                    $asset.content_type -ceq $trusted[2] -and
                    $asset.sha256 -is [string] -and
                    $asset.sha256 -cmatch '^[0-9a-f]{64}$' -and
                    $asset.size -is [ValueType] -and
                    [long]$asset.size -gt 0 -and
                    [double]$asset.size -eq [long]$asset.size
            } catch {
                $valid = $false
            }
            if ($valid) {
                $state[$platformId] = "Completed"
            } else {
                $state[$platformId] = "Failed"
                Write-Warning "$platformId metadata is invalid or conflicts with the release"
            }
        }
        return $state
    } finally {
        $resolved = [IO.Path]::GetFullPath($temporary)
        if (-not $resolved.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing preflight cleanup outside the temporary root"
        }
        if (Test-Path -LiteralPath $resolved) {
            Remove-Item -LiteralPath $resolved -Recurse -Force
        }
    }
}

function Invoke-GhJson {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)

    $savedErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $records = @(& $script:Gh @Arguments 2>&1)
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $savedErrorActionPreference
    }
    if ($exitCode -ne 0) {
        throw "GitHub CLI request failed"
    }
    $text = (($records | ForEach-Object { $_.ToString() }) -join [Environment]::NewLine).Trim()
    if ([string]::IsNullOrWhiteSpace($text)) {
        return $null
    }
    try {
        $parsed = $text | ConvertFrom-Json
    } catch {
        throw "GitHub CLI returned invalid JSON"
    }
    if ($parsed -is [array]) {
        foreach ($item in $parsed) {
            Write-Output $item
        }
        return
    }
    return $parsed
}

function Remove-StaleMacArtifacts {
    param(
        [Parameter(Mandatory = $true)][string]$Repository,
        [DateTimeOffset]$Now = [DateTimeOffset]::UtcNow
    )

    $pages = @(Invoke-GhJson -Arguments @(
        "api", "--paginate", "--slurp", "repos/$Repository/actions/artifacts"
    ))
    foreach ($page in $pages) {
        foreach ($artifact in @($page.artifacts)) {
            if ($artifact.name -cne "Backchannel-macos-arm64.zip") {
                continue
            }
            if ($null -eq $artifact.workflow_run -or $null -eq $artifact.workflow_run.id) {
                throw "macOS artifact is missing its workflow run"
            }
            $run = Invoke-GhJson -Arguments @(
                "api", "repos/$Repository/actions/runs/$($artifact.workflow_run.id)"
            )
            try {
                $created = [DateTimeOffset]::Parse($artifact.created_at)
            } catch {
                throw "macOS artifact has an invalid creation timestamp"
            }
            if ($run.path -ceq ".github/workflows/desktop-release.yml" -and
                $run.status -ceq "completed" -and
                $created -lt $Now.AddHours(-24)) {
                $null = Invoke-GhJson -Arguments @(
                    "api", "--method", "DELETE",
                    "repos/$Repository/actions/artifacts/$($artifact.id)"
                )
            }
        }
    }
}

function Build-WindowsRelease {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$AssetPath,
        [Parameter(Mandatory = $true)][string]$Python
    )

    Invoke-Checked "Installing frontend dependencies" {
        & $script:Npm ci --prefix (Join-Path $Source "frontend")
    } | Out-Null
    Invoke-Checked "Building frontend" {
        & $script:Npm run build --prefix (Join-Path $Source "frontend")
    } | Out-Null
    $venv = Join-Path $Source ".release-venv"
    Invoke-Checked "Creating release virtual environment" { & $Python -m venv $venv } | Out-Null
    $venvPython = Join-Path $venv "Scripts\python.exe"
    Invoke-Checked "Installing release dependencies" {
        & $venvPython -m pip install `
            -r (Join-Path $Source "backend\requirements.txt") `
            -r (Join-Path $Source "desktop\requirements.txt")
    } | Out-Null
    Invoke-Checked "Downloading ONNX models" {
        & $venvPython (Join-Path $Source "backend\scripts\download_models.py")
    } | Out-Null
    Invoke-Checked "Downloading embedded Postgres" {
        & $venvPython (Join-Path $Source "desktop\scripts\download_pg.py")
    } | Out-Null
    Push-Location $Source
    try {
        Invoke-Checked "Building Windows desktop bundle" {
            & $venvPython -m PyInstaller desktop/backchannel.spec `
                --distpath dist --workpath build --noconfirm
        } | Out-Null
        Invoke-Checked "Smoke testing Windows desktop bundle" {
            & $venvPython (Join-Path $PSScriptRoot "..\desktop\scripts\smoke_test.py")
        } | Out-Null
    } finally {
        Pop-Location
    }
    $bundle = Join-Path $Source "dist\Backchannel"
    if (-not (Test-Path -LiteralPath $bundle -PathType Container)) {
        throw "Windows bundle directory is missing"
    }
    Compress-Archive -LiteralPath $bundle -DestinationPath $AssetPath -Force
    $asset = Get-Item -LiteralPath $AssetPath
    if ($asset.Length -le 0) {
        throw "Windows release zip is empty"
    }
    return $asset.FullName
}

function Build-LinuxRelease {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Dockerfile,
        [Parameter(Mandatory = $true)][string]$ControllerScripts,
        [Parameter(Mandatory = $true)][string]$OutputDirectory,
        [Parameter(Mandatory = $true)][string]$AssetPath
    )

    New-Item -ItemType Directory -Path $OutputDirectory | Out-Null
    Invoke-Checked "Building Linux release container" {
        & $script:Docker build `
            --file $Dockerfile `
            --build-context "controller=$ControllerScripts" `
            --target export `
            --output "type=local,dest=$OutputDirectory" `
            $Source
    } | Out-Null
    $files = @(Get-ChildItem -LiteralPath $OutputDirectory -File -Force)
    if ($files.Count -ne 1 -or $files[0].Name -cne "Backchannel-linux-x64.tar.gz" -or
        $files[0].Length -le 0) {
        throw "Linux export must contain exactly one positive-length trusted tarball"
    }
    Copy-Item -LiteralPath $files[0].FullName -Destination $AssetPath -Force
    return (Get-Item -LiteralPath $AssetPath).FullName
}

function Resolve-RequiredApplication {
    param([string]$Name)
    $command = Get-Command $Name -CommandType Application -ErrorAction SilentlyContinue
    if ($null -eq $command) {
        throw "Required application is missing: $Name"
    }
    return $command.Source
}

function Resolve-Python312 {
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe")
    )
    $python = Get-Command python -CommandType Application -ErrorAction SilentlyContinue
    if ($null -ne $python) {
        $candidates += $python.Source
    }
    foreach ($candidate in $candidates | Select-Object -Unique) {
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            continue
        }
        & $candidate -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) {
            return $candidate
        }
    }
    throw "Python 3.12 is required"
}

$releaseCredentialNames = @(
    "CLOUDFLARE_ACCOUNT_ID", "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY", "R2_RELEASES_BUCKET"
)
$releaseCredentials = $null
$hasNativeErrorPreference = Test-Path Variable:PSNativeCommandUseErrorActionPreference
if ($hasNativeErrorPreference) {
    $savedNativeErrorPreference = $PSNativeCommandUseErrorActionPreference
}
try {
if ($hasNativeErrorPreference) {
    $PSNativeCommandUseErrorActionPreference = $false
}
$releaseCredentials = Get-AndClearR2Credentials -Names $releaseCredentialNames
if (-not [Runtime.InteropServices.RuntimeInformation]::IsOSPlatform(
        [Runtime.InteropServices.OSPlatform]::Windows
    ) -or
    [Runtime.InteropServices.RuntimeInformation]::OSArchitecture -ne
        [Runtime.InteropServices.Architecture]::X64) {
    throw "Windows x64 host is required"
}
$repoRoot = Split-Path -Parent $PSScriptRoot
$script:Git = Resolve-RequiredApplication "git.exe"
$script:Gh = Resolve-RequiredApplication "gh.exe"
$script:Node = Resolve-RequiredApplication "node.exe"
$script:Npm = Resolve-RequiredApplication "npm.cmd"
$script:Docker = Resolve-RequiredApplication "docker.exe"
$python = Resolve-Python312

Push-Location $repoRoot
$oldPath = $env:PATH
$tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$temporary = Join-Path $tempRoot ("backchannel-desktop-release-" + [guid]::NewGuid().ToString("N"))
$sourceRoot = Join-Path $temporary "source"
$worktreeAdded = $false
$failures = [Collections.Generic.List[string]]::new()
$runUrls = [Collections.Generic.List[string]]::new()
try {
    $env:PATH = "$(Split-Path -Parent $python);$oldPath"
    if ((Invoke-Checked "Reading current branch" { & $script:Git branch --show-current })[-1].Trim() -cne "master") {
        throw "Release coordinator must run from master"
    }
    if (@(Invoke-Checked "Checking working tree" { & $script:Git status --porcelain }).Count -ne 0) {
        throw "Release coordinator requires a clean working tree"
    }
    Invoke-Checked "Fetching release refs" { & $script:Git fetch origin master --tags } | Out-Null
    $head = (Invoke-Checked "Resolving controller commit" { & $script:Git rev-parse HEAD })[-1].Trim()
    $remoteMaster = (Invoke-Checked "Resolving remote master" { & $script:Git rev-parse origin/master })[-1].Trim()
    if ($head -cne $remoteMaster) {
        throw "Local master is not synchronized with origin/master"
    }
    Invoke-Checked "Checking GitHub authentication" { & $script:Gh auth status } | Out-Null
    $repository = (Invoke-GhJson -Arguments @("repo", "view", "--json", "nameWithOwner")).nameWithOwner
    if ($repository -notmatch '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$') {
        throw "GitHub repository identity is invalid"
    }
    $nodeVersion = (Invoke-Checked "Reading Node.js version" { & $script:Node --version })[-1].Trim()
    if ($nodeVersion -notmatch '^v(?<major>[0-9]+)\.' -or [int]$Matches.major -lt 24) {
        throw "Node.js 24 or newer is required"
    }
    $dockerPlatform = (Invoke-Checked "Checking Docker engine" {
        & $script:Docker info --format '{{.OSType}}/{{.Architecture}}'
    })[-1].Trim()
    if ($dockerPlatform -cne "linux/x86_64") {
        throw "Docker must provide a linux/x86_64 engine"
    }
    $tag = Resolve-ReleaseTag -Version $Version -Git $script:Git
    $r2Client = Join-Path $repoRoot "scripts\r2-object.mjs"
    $publisher = Join-Path $repoRoot "scripts\publish_release_platform.ps1"
    foreach ($path in @($r2Client, $publisher, (Join-Path $repoRoot ".github\workflows\desktop-release.yml"))) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "Required release file is missing: $path"
        }
    }
    $state = Invoke-WithR2Credentials -Credentials $releaseCredentials -Command {
        Get-ReleasePublicationState `
            -Version $Version -Commit $tag.Commit -PublishedAt $tag.PublishedAt `
            -Bucket $env:R2_RELEASES_BUCKET -Client $r2Client
    }

    if (-not $PSCmdlet.ShouldProcess($Version, "Build and publish desktop release platforms")) {
        return
    }

    $macRunId = $null
    if ($state["macos-arm64"] -eq "Failed") {
        $failures.Add("macos-arm64")
    } elseif ($state["macos-arm64"] -eq "Pending") {
        try {
            Remove-StaleMacArtifacts -Repository $repository
            $dispatchTime = [DateTimeOffset]::UtcNow
            $dispatchCorrelation = [guid]::NewGuid().ToString("N")
            $expectedDisplayTitle = "Desktop release $Version ($dispatchCorrelation)"
            Invoke-Checked "Dispatching macOS release" {
                & $script:Gh workflow run desktop-release.yml --ref master `
                    -f "release_ref=$Version" -f "expected_commit=$($tag.Commit)" `
                    -f "correlation_id=$dispatchCorrelation"
            } | Out-Null
            foreach ($attempt in 1..60) {
                $runs = @(Invoke-GhJson -Arguments @(
                    "run", "list", "--workflow", "desktop-release.yml",
                    "--event", "workflow_dispatch", "--limit", "50",
                    "--json", "databaseId,headSha,createdAt,status,displayTitle"
                ))
                $match = @($runs | Where-Object {
                    $_.headSha -ceq $head -and
                    $_.displayTitle -ceq $expectedDisplayTitle -and
                    [DateTimeOffset]::Parse($_.createdAt) -ge $dispatchTime.AddSeconds(-5)
                } | Sort-Object { [DateTimeOffset]::Parse($_.createdAt) } | Select-Object -First 1)
                if ($match.Count -eq 1) {
                    $macRunId = [long]$match[0].databaseId
                    $runUrls.Add("https://github.com/$repository/actions/runs/$macRunId")
                    break
                }
                Start-Sleep -Seconds 2
            }
            if ($null -eq $macRunId) {
                throw "Unable to capture the dispatched macOS workflow run"
            }
        } catch {
            Write-Warning $_.Exception.Message
            $failures.Add("macos-arm64")
        }
    }

    $localPending = $state["windows-x64"] -eq "Pending" -or $state["linux-x64"] -eq "Pending"
    if ($localPending) {
        New-Item -ItemType Directory -Path $temporary | Out-Null
        Invoke-Checked "Creating release worktree" {
            & $script:Git worktree add --detach $sourceRoot $tag.Commit
        } | Out-Null
        $worktreeAdded = $true
        $sourceCommit = (Invoke-Checked "Verifying release worktree commit" {
            & $script:Git -C $sourceRoot rev-parse HEAD
        })[-1].Trim()
        if ($sourceCommit -cne $tag.Commit) {
            throw "Release worktree does not match the verified peeled commit"
        }
        $assetDirectory = Join-Path $repoRoot "release-assets\$Version"
        New-Item -ItemType Directory -Force -Path $assetDirectory | Out-Null
    }

    if ($state["windows-x64"] -eq "Failed") {
        $failures.Add("windows-x64")
    } elseif ($state["windows-x64"] -eq "Pending") {
        try {
            $windowsAsset = Join-Path $assetDirectory "Backchannel-windows-x64.zip"
            $windowsAsset = Build-WindowsRelease `
                -Source $sourceRoot -AssetPath $windowsAsset -Python $python
            Invoke-WithR2Credentials -Credentials $releaseCredentials -Command {
                & $publisher `
                    -Version $Version -Commit $tag.Commit -PublishedAt $tag.PublishedAt `
                    -PlatformId "windows-x64" -AssetPath $windowsAsset -Confirm:$false
            }
        } catch {
            Write-Warning $_.Exception.Message
            $failures.Add("windows-x64")
        }
    }

    if ($state["linux-x64"] -eq "Failed") {
        $failures.Add("linux-x64")
    } elseif ($state["linux-x64"] -eq "Pending") {
        try {
            $linuxAsset = Join-Path $assetDirectory "Backchannel-linux-x64.tar.gz"
            $linuxAsset = Build-LinuxRelease `
                -Source $sourceRoot `
                -Dockerfile (Join-Path $repoRoot "desktop\Dockerfile.release-linux") `
                -ControllerScripts (Join-Path $repoRoot "desktop\scripts") `
                -OutputDirectory (Join-Path $temporary "linux-output") `
                -AssetPath $linuxAsset
            Invoke-WithR2Credentials -Credentials $releaseCredentials -Command {
                & $publisher `
                    -Version $Version -Commit $tag.Commit -PublishedAt $tag.PublishedAt `
                    -PlatformId "linux-x64" -AssetPath $linuxAsset -Confirm:$false
            }
        } catch {
            Write-Warning $_.Exception.Message
            $failures.Add("linux-x64")
        }
    }

    if ($null -ne $macRunId) {
        try {
            Invoke-Checked "Waiting for macOS release" {
                & $script:Gh run watch $macRunId --exit-status
            } | Out-Null
        } catch {
            if (-not $failures.Contains("macos-arm64")) {
                $failures.Add("macos-arm64")
            }
        }
    }

    $notes = Join-Path $repoRoot ".github\release-notes\$Version.md"
    if (-not (Test-Path -LiteralPath $notes -PathType Leaf)) {
        throw "Release notes file is missing: $notes"
    }
    $savedErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & $script:Gh release view $Version --json tagName *> $null
        $releaseExists = $LASTEXITCODE -eq 0
    } finally {
        $ErrorActionPreference = $savedErrorActionPreference
    }
    if ($releaseExists) {
        Invoke-Checked "Updating GitHub release notes" {
            & $script:Gh release edit $Version --notes-file $notes
        } | Out-Null
    } else {
        Invoke-Checked "Creating GitHub release notes" {
            & $script:Gh release create $Version --title "Backchannel $Version" --notes-file $notes
        } | Out-Null
    }

    if ($failures.Count -gt 0) {
        $details = ($failures | Select-Object -Unique) -join ", "
        $urls = if ($runUrls.Count -gt 0) { "; runs: " + ($runUrls -join ", ") } else { "" }
        throw "Desktop release is incomplete: $details$urls"
    }
} finally {
    $env:PATH = $oldPath
    if ($worktreeAdded) {
        $resolvedSource = [IO.Path]::GetFullPath($sourceRoot)
        $resolvedTemporary = [IO.Path]::GetFullPath($temporary)
        if (-not $resolvedSource.StartsWith(
            $resolvedTemporary + [IO.Path]::DirectorySeparatorChar,
            [StringComparison]::OrdinalIgnoreCase
        )) {
            throw "Refusing to remove release worktree outside its temporary parent"
        }
        & $script:Git worktree remove --force $resolvedSource
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "Release worktree cleanup failed: $resolvedSource"
        }
    }
    $resolvedTemporary = [IO.Path]::GetFullPath($temporary)
    if (-not $resolvedTemporary.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing release cleanup outside the temporary root"
    }
    if (Test-Path -LiteralPath $resolvedTemporary) {
        Remove-Item -LiteralPath $resolvedTemporary -Recurse -Force
    }
    Pop-Location
}
} finally {
    if ($null -ne $releaseCredentials) {
        foreach ($name in $releaseCredentials.Keys) {
            [Environment]::SetEnvironmentVariable($name, $releaseCredentials[$name])
        }
    }
    if ($hasNativeErrorPreference) {
        $PSNativeCommandUseErrorActionPreference = $savedNativeErrorPreference
    }
}
