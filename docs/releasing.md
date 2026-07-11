# Releasing Backchannel

Backchannel supports three delivery paths with different publication triggers.
A release is complete only when all applicable paths have been updated and
verified.

## Delivery paths

| Target | Publication trigger | Result |
| --- | --- | --- |
| Docker Compose | Source commit or tag; users rebuild locally | `backend` and `frontend` images are built from the checked-out source. No container registry image is published. |
| Documentation site | Push to `master` that changes `site/`, `docs/`, `docs-site/`, `architecture.svg`, or the site workflow | Cloudflare deploy of `backchannel.page` and `/docs/` |
| Windows and macOS desktop | Push of a `v*` tag | GitHub Actions builds, smoke-tests, zips, and attaches Windows x64 and macOS arm64 bundles to the GitHub release |

A normal push to `master` does not rebuild desktop downloads. Existing GitHub
release assets are immutable release output and do not change when source code
changes.

## Installer access policy

Desktop installers remain in the repository's private GitHub releases. Creating
a tag and verifying its assets does not authorize public access. Unless the
repository owner gives explicit approval for that release:

- Keep the repository and release assets private.
- Do not change repository visibility, mirror installers to another host,
  create public sharing URLs, or otherwise enable anonymous downloads.
- Verify release assets with authenticated GitHub access and confirm anonymous
  release and download requests remain denied.

An anonymous `404` from a private GitHub release is the expected access-control
result, not a failed build. Record explicit approval before changing that state.

## Versioned release files

For each public version `vX.Y.Z`, update or add all of the following before
tagging:

- `.github/release-notes/vX.Y.Z.md` - GitHub release notes used by the desktop workflow
- `site/releases/vX.Y.Z/index.html` - public release/download page
- Current-version links in `README.md`, `docs/quickstart.md`, `site/index.html`,
  comparison pages under `site/`, `site/llms.txt`, and `site/sitemap.xml`
- Any version-specific installation or compatibility notes

Keep older release pages and tags intact. Never move or replace a published
tag; use a new patch version for a corrected build.

## Release checklist

### 1. Prepare

1. Start from a clean `master` synchronized with `origin/master`.
2. Confirm the version is unused locally and remotely.
3. Review the complete diff since the previous tag.
4. Write user-facing release notes and update every current-version link.
5. Search for stale references:

   ```bash
   rg -n "vOLD" README.md docs site .github
   ```

Historical references inside the old version's release page are expected.

### 2. Validate

Run checks appropriate to the changes, with these as the release minimum:

```bash
cd frontend
npm ci
npm run build
npm audit --omit=dev

cd ../docs-site
npm install
npm run build

cd ..
docker compose config
docker compose build frontend backend
```

Also run the backend and desktop unit suites and `git diff --check`. The
tag-triggered desktop workflow performs a clean build and bundle smoke test on
both operating systems; do not treat local tests as a replacement for those
jobs.

### 3. Commit and tag

Commit all release metadata on `master`, then create an annotated tag on that
exact commit:

```bash
git tag -a vX.Y.Z -m "Backchannel vX.Y.Z"
```

Push the tag first. This lets desktop assets finish before the website sends
users to the new download URLs:

```bash
git push origin vX.Y.Z
```

Wait for every `Desktop release` matrix job to succeed. With authenticated
GitHub access, confirm the release has both exact assets:

- `Backchannel-windows-x64.zip`
- `Backchannel-macos-arm64.zip`

The workflow's manual-dispatch mode uploads workflow artifacts for testing,
but it does not attach them to a GitHub release because there is no tag.

### 4. Publish the site and Docker source

After both desktop assets are downloadable, push the release commit to
`master`:

```bash
git push origin master
```

This publishes the source used by Docker builders and triggers the site
workflow when release pages or docs changed. Docker users receive the new code
after pulling the commit or tag and rebuilding:

```bash
docker compose up -d --build
```

### 5. Verify public state

Do not call the release complete until all of these are true:

- The GitHub tag points to the intended release commit.
- Both desktop assets exist and are downloadable with authenticated access.
- Anonymous installer access remains denied unless explicit approval to make
  that release public has been recorded.
- The Windows and macOS workflow smoke tests passed.
- The site deployment passed and the new release page returns HTTP 200.
- Landing-page, README, quickstart, comparison-page, sitemap, and `llms.txt`
  links resolve to the new version.
- A Compose build from the released source succeeds.
- `master` and `origin/master` are synchronized and the worktree is clean.

## Recovery

- Re-run a failed workflow job when the source and tag are correct and the
  failure is transient.
- Fix site-only mistakes with another `master` commit and site deployment.
- For code or bundle defects, make a new patch release. Do not force-push or
  move an already published version tag.
