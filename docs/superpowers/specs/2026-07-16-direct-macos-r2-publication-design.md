# Direct macOS R2 Publication Design

## Goal

Publish the authenticated macOS arm64 bundle immediately after its GitHub-hosted build and smoke test, without using GitHub artifact storage.

## Design

Keep one `build-macos` job. It checks out the controller and immutable release tag, builds and smoke-tests the tagged source, and creates `Backchannel-macos-arm64.zip` as it does today. The final step calls the existing `scripts/publish_release_platform.ps1` publisher directly.

The job uses the existing `production` environment, but the four R2 values are mapped into the environment only for the final publish step. Build, dependency, download, packaging, and smoke-test subprocesses do not receive R2 credentials.

Remove the GitHub artifact upload, download, and separate publication job. The coordinator continues to correlate the dispatched run and wait for its result. Existing stale-artifact cleanup remains temporarily to remove legacy handoff artifacts; the new workflow creates none.

## Data Flow

1. The coordinator dispatches `v0.2.4`, its verified peeled commit, and a unique correlation ID.
2. GitHub builds and smoke-tests macOS from the immutable tag.
3. The final step publishes the zip, immutable platform manifest, release identity, and `latest.json` through the existing fail-closed publisher.
4. The portal exposes macOS as soon as its platform manifest is committed.

## Failure and Retry

A build, smoke, or publish failure fails the single workflow job. The publisher's conditional writes and content verification make an exact retry safe. A conflicting asset or manifest remains a hard failure.

## Verification

- Contract tests require no `upload-artifact` or `download-artifact` actions.
- Contract tests require credentials only on the final publish step.
- A real workflow run must pass build, smoke, and publish.
- GitHub artifact count must remain zero.
- The authenticated portal must show macOS alongside Windows and Linux.

## Non-goals

No tag movement, GitHub executable release assets, new storage service, publisher rewrite, or portal change.
