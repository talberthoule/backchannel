# Versioned Download Filenames Design

## Goal

Append the release version to every downloaded desktop artifact while preserving
the immutable R2 object names and release manifests.

Examples for release `v0.2.1`:

- `Backchannel-windows-x64-v0.2.1.zip`
- `Backchannel-macos-arm64-v0.2.1.zip`
- `Backchannel-linux-x64-v0.2.1.tar.gz`

## Design

The authenticated Worker download route already has the trusted manifest asset
and validated release version. It will derive a response-only filename by
inserting the version before `.zip` or `.tar.gz`, then use that value in the
`Content-Disposition` attachment header.

R2 keys, object metadata, manifests, catalog responses, and portal display text
remain unchanged. Existing and future releases therefore gain versioned local
download names without object migration or re-upload.

## Error Handling and Security

Manifest validation already restricts versions and filenames to fixed trusted
formats before the response is built. The filename derivation adds no new user
input and does not change authorization, entitlement, range, conditional request,
streaming, or audit-event behavior.

## Verification

Extend the Worker download test with table-driven Windows/macOS `.zip` and Linux
`.tar.gz` cases. Each case must assert the exact `Content-Disposition` filename;
the existing streaming, range, cache, type, ETag, and event assertions remain in
force. Run the complete docs-site test and build gate before deployment.
