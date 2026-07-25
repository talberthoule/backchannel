# Retired `user-*` showcase assets (archived 2026-07-24)

These are the previous product screenshots, kept for visual comparison only.
**Do not return them to the site.**

## Why they were retired

They were captured from a replay of a real 32-minute customer call. The images
themselves were reviewed and are deliberate crops that cut identifying cards out
of frame, so they are safe to look at -- but the session behind them contained a
real employer, a real client, and several real personal names.

Three problems followed from that:

1. **They could never be regenerated.** No script could reproduce them, so when
   the UI drifted they went stale and nobody noticed. The `admin-agents` pair
   shipped for weeks showing "Agents 8/8" against a shipped nine.
2. **They were dark-mode only.** The site has a light default, so ten of the
   thirteen surfaces showed a dark screenshot on a light page.
3. **Any new capture from that session was unsafe** without a full frame-by-frame
   review, which made routine refreshes expensive.

## What replaced them

A wholly fictional demo workspace seeded by `showcase/seed_demo.py`, captured by
`showcase/capture.mjs`. Twelve surfaces, every one with a light and dark variant,
regenerable in three commands at no API cost beyond one analysis run. See
`showcase/screenshots/README.md`.

## Using these for comparison

Fine locally. If you need to compare framing, density, or a specific UI state
against the current set, these are the reference. They are also recoverable from
git history at any commit before 2026-07-24.
