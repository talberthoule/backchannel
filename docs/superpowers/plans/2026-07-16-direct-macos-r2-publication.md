# Direct macOS R2 Publication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish the smoke-tested macOS arm64 bundle directly from its GitHub job to R2 without creating a GitHub artifact.

**Architecture:** Keep the existing tag-pinned `build-macos` job and replace its upload plus the separate publish job with one final R2 publisher step. Attach the existing `production` environment and concurrency key to the macOS job, while mapping credentials only into the final step.

**Tech Stack:** GitHub Actions YAML, PowerShell publisher, Python `unittest`, GitHub CLI, authenticated release portal.

## Global Constraints

- Build application source only from the immutable annotated release tag and verified peeled commit.
- Keep R2 credentials out of build, dependency, packaging, and smoke-test subprocesses.
- Reuse `scripts/publish_release_platform.ps1`; add no dependency or publisher abstraction.
- Create no GitHub artifact and attach no executable to the GitHub Release.
- Preserve fail-closed immutable asset and manifest publication.

---

### Task 1: Direct macOS publication workflow

**Files:**
- Modify: `.github/workflows/desktop-release.yml`
- Modify: `desktop/tests/test_release_contract.py`

**Interfaces:**
- Consumes: workflow inputs `release_ref`, `expected_commit`, `correlation_id`; release timestamp output `steps.release.outputs.published_at`; existing production secrets and bucket variable.
- Produces: one `build-macos` job that publishes `controller/Backchannel-macos-arm64.zip` through `scripts/publish_release_platform.ps1`.

- [ ] **Step 1: Replace artifact-handoff assertions with direct-publication assertions**

Update the macOS workflow contract tests to require a single macOS job, no artifact actions, no artifact API cleanup, and credentials only after the final publish-step marker:

```python
def test_workflow_is_dispatch_only_direct_macos_publish(self):
    self.assertIn("workflow_dispatch:", WORKFLOW)
    self.assertIn("runs-on: macos-latest", WORKFLOW)
    self.assertIn("environment: production", WORKFLOW)
    self.assertIn("group: backchannel-r2-publish", WORKFLOW)
    self.assertNotIn("publish-macos:", WORKFLOW)
    self.assertNotIn("actions/upload-artifact", WORKFLOW)
    self.assertNotIn("actions/download-artifact", WORKFLOW)
    self.assertNotIn("actions/artifacts/", WORKFLOW)

def test_macos_credentials_are_scoped_to_final_publish_step(self):
    marker = "      - name: Publish verified macOS platform"
    build, publish = WORKFLOW.split(marker, 1)
    for name in (
        "CLOUDFLARE_ACCOUNT_ID",
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
        "R2_RELEASES_BUCKET",
    ):
        with self.subTest(name=name):
            self.assertNotIn(name, build)
            self.assertIn(name, publish)
    self.assertIn("steps.release.outputs.published_at", publish)
    self.assertIn("publish_release_platform.ps1", publish)
    self.assertIn("-AssetPath Backchannel-macos-arm64.zip", publish)
```

- [ ] **Step 2: Run the contract test and verify RED**

Run:

```powershell
& 'C:\Users\thoule\AppData\Local\Programs\Python\Python312\python.exe' -m unittest desktop.tests.test_release_contract
```

Expected: FAIL because the workflow still contains `publish-macos`, `upload-artifact`, and `download-artifact`.

- [ ] **Step 3: Replace the handoff with the existing publisher**

Add the production environment and existing serialization key to `build-macos`:

```yaml
  build-macos:
    runs-on: macos-latest
    environment: production
    concurrency:
      group: backchannel-r2-publish
      cancel-in-progress: false
```

Replace `Upload macOS handoff` and the entire `publish-macos` job with this final step:

```yaml
      - name: Publish verified macOS platform
        working-directory: controller
        env:
          CLOUDFLARE_ACCOUNT_ID: ${{ secrets.CLOUDFLARE_ACCOUNT_ID }}
          R2_ACCESS_KEY_ID: ${{ secrets.R2_ACCESS_KEY_ID }}
          R2_SECRET_ACCESS_KEY: ${{ secrets.R2_SECRET_ACCESS_KEY }}
          R2_RELEASES_BUCKET: ${{ vars.R2_RELEASES_BUCKET }}
          RELEASE_REF: ${{ inputs.release_ref }}
          EXPECTED_COMMIT: ${{ inputs.expected_commit }}
          PUBLISHED_AT: ${{ steps.release.outputs.published_at }}
        shell: pwsh
        run: ./scripts/publish_release_platform.ps1 -Version $env:RELEASE_REF -Commit $env:EXPECTED_COMMIT -PublishedAt $env:PUBLISHED_AT -PlatformId macos-arm64 -AssetPath Backchannel-macos-arm64.zip -Confirm:$false
```

Do not add artifact upload, download, cleanup, or a new script.

- [ ] **Step 4: Run focused and workflow syntax checks**

Run:

```powershell
& 'C:\Users\thoule\AppData\Local\Programs\Python\Python312\python.exe' -m unittest desktop.tests.test_release_contract
& powershell -NoProfile -ExecutionPolicy Bypass -File scripts\tests\test_release_desktop.ps1
@'
import pathlib, yaml
yaml.load(pathlib.Path('.github/workflows/desktop-release.yml').read_text(), Loader=yaml.BaseLoader)
print('workflow YAML: OK')
'@ | C:\Users\thoule\AppData\Local\Temp\backchannel-progressive-release-venv\Scripts\python.exe -
git diff --check
```

Expected: 12 release-contract tests pass; coordinator contracts print `OK`; YAML prints `workflow YAML: OK`; diff check is clean.

- [ ] **Step 5: Commit and push**

```powershell
git add -- .github/workflows/desktop-release.yml desktop/tests/test_release_contract.py
git commit -m "fix: publish macOS release without artifact handoff"
git push origin master
```

Expected: clean synchronized `master` containing the direct-publish workflow.

### Task 2: Live macOS publication and acceptance

**Files:**
- No repository file changes.

**Interfaces:**
- Consumes: pushed workflow, immutable `v0.2.4` tag, production R2 configuration.
- Produces: R2 macOS asset/platform metadata, portal availability, a completed correlated GitHub run with zero artifacts.

- [ ] **Step 1: Dispatch an exact correlated run**

```powershell
$correlation = [guid]::NewGuid().ToString('N')
gh workflow run desktop-release.yml --ref master `
  -f 'release_ref=v0.2.4' `
  -f 'expected_commit=8a55c52f942396dd5626407a66e8a56050fadfbe' `
  -f "correlation_id=$correlation"
$expectedTitle = "Desktop release v0.2.4 ($correlation)"
$runId = $null
foreach ($attempt in 1..30) {
  $runs = gh run list --workflow desktop-release.yml --event workflow_dispatch --limit 20 --json databaseId,displayTitle,headSha,createdAt | ConvertFrom-Json
  $match = @($runs | Where-Object displayTitle -CEQ $expectedTitle)
  if ($match.Count -eq 1) { $runId = [long]$match[0].databaseId; break }
  Start-Sleep -Seconds 2
}
if ($null -eq $runId) { throw 'Correlated macOS workflow run was not found' }
Write-Output "run_id=$runId"
```

Expected: GitHub returns one run URL whose title is `Desktop release v0.2.4 (` followed by the exact `$correlation` value and `)`.

- [ ] **Step 2: Wait for build, smoke, and publication**

```powershell
gh run watch $runId --exit-status
gh run view $runId --json status,conclusion,displayTitle,headSha,jobs,url
```

Expected: conclusion `success`; `Build bundle`, `Smoke test bundle`, and `Publish verified macOS platform` all succeed; head SHA equals pushed `master`.

- [ ] **Step 3: Verify zero GitHub artifacts and source-only release**

```powershell
gh api "repos/talberthoule/backchannel/actions/runs/$runId/artifacts"
gh release view v0.2.4 --json tagName,assets,url
```

Expected: run artifact `total_count` is `0`; release assets is `[]`.

- [ ] **Step 4: Verify portal and immutable publication metadata**

Use the authenticated browser at `https://downloads.backchannel.page/?version=v0.2.4`.

Expected headings: `v0.2.4 (Latest)`, `Windows x64`, `macOS arm64`, and `Linux x64`. Verify the macOS download link is `/api/download/releases/v0.2.4/macos-arm64` and R2 platform metadata names `Backchannel-macos-arm64.zip`.

- [ ] **Step 5: Final repository check**

```powershell
git status --short --branch
git rev-parse HEAD
git rev-parse origin/master
```

Expected: clean `master`; local and remote commits match.
