# Docs site design fixes

Scope: `docs-site/` config + CSS overrides only. No generated content
(`docs-site/src/content/docs/`) and no `docs/*.md` sources were touched. Docs
scored 82/B in the review; these are the listed quick-win polish items.

## Changes

### 1. Grouped the sidebar (Miller's Law / nav depth)
`docs-site/astro.config.mjs`

Was a flat list of ~10 entries (past 7 plus or minus 2). Now two logical groups:

- **Getting started**: Overview, Quickstart, Architecture
- **Reference**: Agent System, Audio Pipeline, WebSocket Protocol, REST API,
  Configuration, Deployment

The "Back to homepage" link stays top-level above the groups. Halves the
per-group choice count and adds a learn-vs-reference sense the flat list lacked.

### 2. Table + code-block polish
`docs-site/src/styles/custom.css`

Added one rule scoped to `.sl-markdown-content table`:
`display: block; overflow-x: auto` so wide reference tables scroll inside their
own box on mobile instead of overflowing the page, plus
`font-variant-numeric: tabular-nums` so figures (prices, thresholds, ms values)
align. Applied via the custom CSS override, not per page.

Code blocks: no change needed. Starlight's built-in Expressive Code already
renders code blocks styled and horizontally scrollable on narrow viewports.

### 3. Branded `:focus-visible` ring
`docs-site/src/styles/custom.css`

Added a `2px solid var(--sl-color-accent-high)` outline (with offset) on
focusable elements (links, buttons, summary, form controls, `[tabindex]`).
Keyboard users now get a teal brand-consistent focus ring instead of Starlight's
default. Uses the existing accent tokens, so it adapts to light/dark.

## Not done (deliberate)

- **Custom 404 page** (report's other quick-win): left as Starlight default.
  Optional per the report ("Optional custom 404"), and the Cloudflare Worker
  build already emits a `404.html`; a bespoke one is a net-new page, not polish.
- **Display font**: report explicitly said "Not a defect. Leave unless brand
  wants a display face" and that it should be applied to both surfaces together.
  Out of scope for a docs-only pass.

## Verification

`cd docs-site && npm run build` -> PASS. 10 pages built, "Complete!". The
`Entry docs -> 404 was not found` line is a pre-existing Starlight/Cloudflare
route note, not introduced here and not an error (build exits 0).
