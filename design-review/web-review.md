# Backchannel Website + Docs — Design Review

Design-engineering review of Backchannel's public online presence (landing page, SEO comparison pages, and docs) using the `ui-craft` skill system — anti-slop scan, audit lens, and Nielsen heuristic scoring. Review/critique only; no source was edited.

> **Historical record -- do not read the scope below as current.** This file captures one
> review pass and its scores are frozen at that pass. The site had **four** comparison
> pages when it was written; it now has **twelve**. See the dated update appended at the
> bottom (2026-07-24) and `design-review/comparison-pages-inventory-2026-07-24.md` for
> the current surface. Body text below is left as written.

## Scope + what was captured

**Surfaces reviewed**
- Landing: https://backchannel.page/ (`site/index.html` + `site/style.css`)
- Comparison/SEO pages: `/fireflies-alternative`, `/granola-alternative`, `/otter-alternative`, `/vs-meetily` (`site/*/`)
- Docs: https://backchannel.page/docs/ — Astro Starlight (`docs-site/`, generated from `docs/*.md`)

**Screenshots captured** (live, via Chrome MCP; saved to disk by the browser tool). Target dir: `C:\Users\Houle\OneDrive\Documents\GitHub\backchannel\design-review\screenshots\web\`
- Landing — desktop hero (1280 window), dark theme
- Landing — desktop features grid + quickstart section
- Landing — hero (mobile-window attempt)
- Comparison — `/fireflies-alternative` desktop hero + "why switch" grid
- Docs — home (`/docs/`) desktop
- Docs — article (`/docs/architecture/`) desktop

**Capture limitation (honest note):** the Chrome MCP screenshot pipeline renders at a fixed ~1568px viewport regardless of `resize_window`, so true 768px/375px reflow (nav collapse, single-column stacking) could **not** be forced through the browser tool. Responsive behavior below is assessed from `site/style.css` media queries, not from a rendered narrow viewport. The site is theme-dark by default; there is no light/dark toggle on the marketing pages (docs has the Starlight Auto/light/dark switch).

---

## Anti-slop detector results

Invoked from repo root: `npx --yes ui-craft-detect site`

- **ui-craft anti-slop detector v0.11.0** — scanned 6 files, all 6 flagged. **Exit 0**, `0 errors, 12 warnings, 0 auto-fixed`. The tool emits severity dots only, no numeric score. All findings were warnings, deduplicated to three classes:

| Detector warning | Where | Verdict |
| --- | --- | --- |
| table without overflow / sticky header | comparison tables on every page (`index.html:248`, each `*-alternative` + `vs-meetily`) | **Half false-positive** — tables are wrapped in `.table-scroll { overflow-x:auto }` (`style.css:366`); the missing **sticky `thead`** is legitimate. |
| `<img>` without width/height or aspect-ratio | `site/index.html:237` (architecture.svg) | **Valid** — CLS risk; `.diagram img` has `min-width:720px` but no intrinsic dims. |
| hover state without focus-visible | `site/style.css:68` (and every hover block) | **Valid but low-severity** — no `:focus-visible` styles, but they never `outline:none`, so the UA focus ring survives. Unbranded, not broken. |

**Manual anti-slop scan — axes that are genuinely clean** (called out because the site is restrained, not sloppy):
- **Accent is NOT default blue** — deliberate teal token system, dark-aware: `--accent:#0d9488` (light) / `#2dd4bf` (dark), 90%+ neutral slate ramp. No gradients anywhere.
- **Real SVG feature icons**, no emoji.
- **No `transition:all`** — in fact no transitions at all (a polish gap, not slop).
- **No gradient text, no purple/cyan wash, no glow blobs, no div-built fake screenshots** (architecture is a real SVG; the hero visual is an honest placeholder comment).
- **Radius varied** — 6 / 10 / 12 / 14px steps (passes the uniform-radius test).
- **CTAs specific** ("Self-host in minutes", "View on GitHub"), proof is concrete pricing/model names rather than "trusted by thousands".

**Net:** the site's taste floor is high. Every real problem below stems from one habit — leaning on the *section-eyebrow + uniform-card-grid* template and shipping a *text-only, proof-less hero* — not from color/icon/gradient slop.

---

## Landing page

### Audit findings (Before → After)

**Critical (blocks usability/a11y):** none. Keyboard focus is visible (UA default), nav is reachable, no motion to break, contrast passes on the dark palette.

**High-impact (immediately noticeable — craft + conversion):**

| Before | After | Why |
| --- | --- | --- |
| Hero holds a `PLACEHOLDER: hero product visual` comment (`index.html:127-132`); zero screenshot, GIF, or GitHub star count anywhere on the page | Drop in a real cropped ActiveCallView shot at the fold + a live GitHub star badge | A dev evaluating "should I run this" gets no glimpse of the product working; the recipe calls a text-only marketing page "incomplete work." Biggest single gap. |
| Hero lede ~55-60 words / 6 lines (`index.html:114-121`) | One sentence ≤20 words; move detail to the proof strip | Value prop isn't graspable in one read; hero subtext ceiling is 20 words. |
| Uppercase accent kicker above **all 8 sections** (`.kicker` `style.css:213`; used at `index.html:138,190,215,230,244,286,320,362`) | Keep 1-2 deliberate kickers; delete the rest | Eyebrow budget is `ceil(8/3)=3`; a kicker on every section is template grammar — the strongest AI tell on the page. |
| Uniform 6-card icon grid, 3×2 identical icon+h3+p (`index.html:141-184`, `.grid` `style.css:246`) | 2-3 asymmetric feature rows with a real visual (architecture SVG, transcript snippet, agent-flow) | Uniform icon-card grid is the recipe's "#1 template tell." |
| Nav has **no CTA button** — 7 plain text links incl. a text-only "GitHub" | Add a compact nav CTA (GitHub-star or "Self-host") | CTA hierarchy is only 2 levels (hero primary == final-section primary); the highest-traffic surface converts nothing. |

**Quick wins (big polish, small diff):**

| Before | After | Why |
| --- | --- | --- |
| `td` numerics don't align ("$10", "$39", "8,000 min") | `td { font-variant-numeric: tabular-nums }` | Figures in comparison tables should align on the decimal. |
| `architecture.svg` no width/height (`index.html:237`) | Add `width`/`height` or `aspect-ratio` on `.diagram img` | Prevents layout shift (CLS). |
| No branded focus ring | `a:focus-visible,.btn:focus-visible{outline:2px solid var(--accent);outline-offset:2px}` | Keyboard users get a brand-consistent focus, not just UA default. |
| `thead` not sticky on ~9-row comparison tables | `thead th{position:sticky;top:0;background:var(--surface)}` | Header stays visible while scanning rows. |
| Two labels one intent: "Self-host in minutes" vs "Try the quickstart" (`fireflies-alternative:88` vs `155`), same `#quickstart` target | Reuse one label per intent page-wide | Consistency; one CTA label per intent. |

### Heuristic scorecard (landing)

| Heuristic | Score | Finding |
| --- | --- | --- |
| Visibility of system status | 4 | Sticky nav + smooth-scroll anchors; no active-section highlight on the long one-pager. |
| Match real world | 4 | FAQ is plain-spoken; How-it-works step 1 hits a general buyer with "streams PCM16 16 kHz chunks over a WebSocket." |
| User control & freedom | 4 | All-anchor nav, back works, no traps; external GitHub links don't signal new-tab. |
| Consistency & standards | 4 | CTA labels reused; kicker+h2+sub rhythm consistent (which is also the template flip-side). |
| Error prevention | 4 | Static page, no forms to mis-submit. |
| Recognition over recall | 4 | Sections carry labels; docs cards self-describe. |
| Flexibility & efficiency | 4 | Copy-paste quickstart + shown GPU override + footer comparison links serve power users. |
| Aesthetic & minimalist | **2** | 60-word hero lede, uniform 6-card grid, 8/8 eyebrows, zero imagery (placeholder comment where the shot belongs). |
| Error recovery | 4 | No interactive error surfaces. |
| Help & documentation | 5 | Dedicated docs section, 6-question FAQ, contextual quickstart notes — best-in-class for the page type. |

**Design law audit:** Fitts PASS (buttons ~44px, centered) · Hick PASS (nav exactly 7, at ceiling) · Doherty PASS (static, instant anchors) · Cleveland-McGill PASS (no quantitative charts; architecture SVG is a system diagram) · Miller PASS (nav ≤7, 5-step how-it-works) · Tesler PASS (complexity absorbed by one `docker compose up`).

**UsabilityScore: 73 / C (judged).** Nielsen mean 3.9 → base `round(((3.9−1)/4)×100)=73`; 0 failed laws → −0. Structurally clean (all 6 laws pass, nothing blocks nav), but the entire conversion-critical layer sits inside the one heuristic it fails — Aesthetic/minimalist (2): no proof, no product imagery, over-long hero, template-tell composition. Fixing those four moves the same skeleton to B+.

---

## Comparison pages

Notable findings across `/fireflies-alternative`, `/granola-alternative`, `/otter-alternative`, `/vs-meetily`:

- **Positioning copy is a genuine strength.** Honest, specific, trade-off-aware ("The bot in the meeting", "Cloud-only, private storage at $39", "Meters everywhere") with real pricing and named complaints — exactly the evidence-first tone B2B/dev buyers trust. This is the best-written part of the whole presence.
- **Same template tells, amplified.** Each comparison page carries ~9 uppercase kickers (`fireflies-alternative` lines 97,123,162,224,268,285,307,332,344) and reuses the identical `.grid`/`.card` block — the eyebrow flood and uniform-card grid repeat per page.
- **Same proof-less hero.** Comparison heroes are text-only and centered-symmetric; a small side-by-side comparison table or a product shot would make the "no bot in the room" claim visible instead of asserted.
- **Comparison table quick-wins** apply here most: add `tabular-nums` to price/usage cells and a sticky `thead` (tables run ~9 rows).
- **CTA label drift** noted above ("Self-host in minutes" vs "Try the quickstart" to the same target) — normalize.

Craft floor is identical to the landing (clean teal, no slop); these pages inherit both its strengths and its two structural gaps (imagery, eyebrow budget).

---

## Docs site

Astro Starlight, generated from `docs/*.md` via `sync-docs.mjs` (clean DRY pipeline — docs stay plain GitHub markdown; H1→title, first-prose→meta description, `.md` links rewritten).

**Structure:** 9 pages (Overview, Quickstart, Architecture, Agent System, Audio Pipeline, WebSocket Protocol, REST API, Configuration, Deployment), all short (34–193 lines). Sidebar is a **single flat, ungrouped list** (`docs-site/astro.config.mjs:25-37`). Brand: `custom.css` (13 lines) overrides only the Starlight accent to the landing teal — brand-consistent, system-ui font on both surfaces. Pagefind **search enabled** (default), on-page TOC + breadcrumbs present (verified live). Default Starlight hamburger untouched → mobile nav intact.

| Severity | Finding | Evidence | Fix |
| --- | --- | --- | --- |
| Critical / High | none | — | — |
| Quick-win | Flat ungrouped sidebar of ~10 entries (8 pages + 2 nav aids), just past 7±2, no "learn vs reference" sense | `astro.config.mjs:25-37` bare string array | Group into **Getting started** (Overview, Quickstart, Architecture) + **Reference** (the other 6) — halves per-group choice count. |
| Quick-win | Default Starlight 404, no search prompt back | no `src/pages/404.astro` | Optional custom 404 pointing at search + Overview. |
| Quick-win | Pure system font stack, no display face | `custom.css` sets only accent vars | Leave unless brand wants a display face; if so, apply to both surfaces together. Not a defect. |

Readability is genuinely good and needs no fix: prose is chunked into numbered steps + tables (not walls), heading depth stays H2/H3, code blocks are short focused `bash`/path snippets with inline code chips, Starlight's ~45rem measure keeps line length readable.

**Docs UsabilityScore: 82 / B (judged, from source + live desktop pass).** Nielsen mean 4.3, 0 failed laws. A conventions-first Starlight site with search, TOC, breadcrumbs, brand-matched accent, and well-chunked reference prose. Only friction is the flat sidebar and stock 404 — nothing blocks finding an answer.

---

## Top 5 things to fix to make the online presence stand out

1. **Put the product on the page (conversion, highest ROI).** *Before:* hero is a `PLACEHOLDER` comment; the whole site ships zero screenshots and zero proof. *After:* a real ActiveCallView shot cropped at the fold showing live transcript + surfaced insight, plus a live GitHub-star count in the nav. The one honest proof point for a self-host/star conversion — the repo working — is currently invisible. This alone lifts the landing from C toward B.

2. **Cut the hero lede to one sentence (conversion + clarity).** *Before:* ~55-60 words across 6 lines. *After:* "Self-hosted AI meeting assistant: live speaker-attributed transcript + real-time insight agents, no bot in the call." ≤20 words; push the rest into the proof strip. The value prop must land in one read.

3. **Kill the eyebrow flood (craft — the #1 AI tell here).** *Before:* an uppercase teal kicker over all 8 sections (`.kicker`, `index.html` 8 uses). *After:* keep 1-2 deliberate kickers, delete the other 6 — the `<h2>` carries each section. Same fix on the comparison pages (~9 each → ≤3).

4. **Break the uniform 6-card icon grid into asymmetric feature rows (craft).** *Before:* 3×2 identical icon+h3+p cards (`index.html:141-184`). *After:* 2-3 alternating rows, each with a real visual (the architecture SVG, a transcript snippet, an agent-flow) and varied spans. Removes the strongest template signal while showing the product.

5. **Add a nav CTA + one round of table polish (conversion + polish).** *Before:* nav is 7 plain text links, no button; comparison tables lack `tabular-nums` and sticky headers; `architecture.svg` has no dims. *After:* a compact "Self-host" / GitHub-star button in the nav (restores the missing third CTA level), `font-variant-numeric: tabular-nums` on `td`, `position: sticky` on `thead th`, and `width`/`height` on the diagram img (kills CLS). For docs: group the sidebar into Getting-started / Reference.

---

*Scores: Landing 73/C (judged), Docs 82/B (judged). Critical a11y blockers: 0. Detector: 12 warnings / 0 errors, exit 0. The presence has a high taste floor (clean teal system, real icons, honest specific copy) and one repeated structural gap — a proof-less, template-composed hero — that caps conversion.*

---

# Update -- 2026-07-24 (appended; review above not rewritten)

The comparison surface reviewed above no longer matches the site. Recorded here rather
than edited into the body, because the scores, captures, and detector tally above are a
record of one pass and are only meaningful against the site as it stood then.

This file is undated in its header; it predates the 2026-07-09 Phase 1 audit, which
cites it as "the prior review".

## What changed

Eight comparison pages shipped on 2026-07-24 (commits 476422b, 10da057), taking the
total from four to twelve. The "Comparison pages" section above reviewed
`/fireflies-alternative`, `/granola-alternative`, `/otter-alternative`, `/vs-meetily`.
Also live now: `/open-source-meeting-assistants/` (hub), `/vs-anarlog/`,
`/fathom-alternative/`, `/read-ai-alternative/`, `/gong-and-backchannel/`,
`/vs-clari-copilot/`, `/teams-premium-alternative/`, `/plaud-alternative/`.

Internal linking moved to hub-and-spoke. The shared `footer-compare` block now carries
seven links (hub first) instead of four, identical across 28 HTML files, and each page's
"Other comparisons" doc-list points at same-cluster siblings plus the hub. Full
inventory, cluster map, and the add-a-page checklist:
`design-review/comparison-pages-inventory-2026-07-24.md`.

## What that means for the findings above

- **The comparison-page section is now a four-of-twelve sample.** Its conclusions were
  not re-tested against the eight new pages. Treat the craft findings there
  (eyebrow flood, uniform card grid, proof-less hero) as unverified for the new pages.
- **"Positioning copy is a genuine strength" still holds, with a caveat.** The
  2026-07-24 work also corrected five factual claims on the previously published pages
  (a false "no open-source tool other than Backchannel" claim, a false "Meetily has no
  diarization" claim, a missing mention of Otter Live Assist, an Otter user count of
  40M corrected to 35M, and an agent-roster undersell of four vs the actual nine). The
  honest, specific tone praised above is the asset; it depends on the claims being
  right, and some were not.
- **The detector tally in the summary line (12 warnings / 0 errors) is stale.** Same
  detector version, much larger scope. Re-run recorded in `design-review/site-fixes.md`
  under its own 2026-07-24 update.
- **Landing and docs findings are unaffected** by the comparison-page expansion. Whether
  the shipped fixes moved the 73/C landing score was not re-scored here; no new
  heuristic pass was run on 2026-07-24.

No re-scoring, no re-capture, and no live browser pass was performed for this update.
It is a scope correction only.
