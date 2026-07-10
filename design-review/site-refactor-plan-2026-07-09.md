# Backchannel marketing-site refactor plan (Phase 1 audit)

Date: 2026-07-09. Scope: `site/` (landing `index.html` + shared `style.css` + four
comparison pages). This is the audit + punch-list; Phase 2 executes it.

Method: `/audit` ui-craft skill (usable; a11y / performance / responsive / visual-craft
lens applied). Visual assessment is code-based, folding in the prior live Chrome MCP
captures of the same surfaces in `design-review/web-review.md`. I did not re-capture
live: the browser tool renders at a fixed ~1568px viewport (documented in the prior
review, so true 375/768px reflow cannot be forced), the surfaces are fully determinable
from source, and the brief says not to rabbit-hole on browser setup. Sections that would
change under a rendered narrow viewport are called out from the CSS media queries.

**[VISUAL: code + prior-capture, not freshly rendered]**

## Environment facts Phase 2 must know

- **ffmpeg is NOT on PATH** (brief assumed it was; it is not, and not in common install
  dirs). ImageMagick and `cwebp` also absent. **Python 3.14 + Pillow 12.0.0 IS present**
  and is the resize/encode tool the optimization spec below targets.
- **Asset count is 20 PNGs**, not 21. `showcase/screenshots/` holds 20 `.png` + 1
  `README.md` (= the 21 files the brief counted). The README maps them across 15 surface
  rows; the 5 scripted rows each ship a light + `-dark` pair (10 files), plus 10
  dark-only `user-*` files.
- The site currently references **no** raw `showcase/` or `user-*` path and no `.webp`
  (verified). The 4 shots in use are re-compressed copies in `site/assets/shots/`
  (`postcall-insights/transcript/briefing.png`, `admin-agents.png`). The perf guardrail
  below is therefore preventive: keep it that way.
- Most of the prior review's Top-5 are already DONE in the working tree: one-sentence
  hero lede, eyebrows cut to 3, uniform 6-card grid broken into 3 feature rows, nav
  "Star on GitHub" CTA, `tabular-nums`, sticky `thead`, `architecture.svg` dims, and a
  branded `:focus-visible` ring (`style.css:74-82`). Docs sidebar grouping also shipped
  (commit b809f76). Still-open prior items are folded into the table below.

---

## 1. Prioritized findings (P0 / P1 / P2)

Lens tags: [perf] [a11y] [resp] [craft]. "prior" = carried from `web-review.md` and
still open.

### P0 -- blocks the refactor goal or is a hard perf cliff

| # | Lens | Finding | Fix direction |
| --- | --- | --- | --- |
| P0-1 | perf | `user-*` source shots are 2558-3838px wide, up to 845 KB each, 5.4 MB for the set. Wiring any raw into the page (esp. the hero) is an LCP/decode cliff -- a 3823px, 845 KB hero image displayed in a 940px box. | Downscale + WebP-encode every placed asset first (spec in section 3). Never reference a raw `user-*.png`. Guardrail-check before ship. |
| P0-2 | craft | Hero shows a **static, light, post-call insights** panel (`postcall-insights.png`) while the H1 promises "surfaced mid-call." The product's live moment is invisible; the one honest proof point (the app working live under load) is not on the page. | Swap hero to `user-live-early` (live call, 03:52 in, real load) per README, inside a browser-frame mockup. |

### P1 -- immediately noticeable; craft / conversion / responsive

| # | Lens | Finding | Fix direction |
| --- | --- | --- | --- |
| P1-1 | craft/resp | **Light/dark screenshot mismatch.** Page is theme-aware (full dark palette via `prefers-color-scheme`), but all 4 wired shots are light-mode PNGs shown on both themes -- dark-mode visitors get bright screenshots on a dark page. | Scripted `postcall-*`/`admin-*` shots -> `<picture>` swapping `-dark` on `(prefers-color-scheme: dark)`. Dark-only `user-*` shots -> keep dark, place inside a browser-frame mockup so the chrome reads as "product shot" on both themes. |
| P1-2 | perf | Every **new** `<img>` added in Phase 2 will reintroduce CLS unless given intrinsic `width`/`height` (or `aspect-ratio`). Current shots do set dims; new ones must too, and the hero swap changes AR (1.78 -> 2.09) so its `width`/`height` must be updated. | Set `width`/`height` on every placed `<img>` to the optimized pixel size (section 3 gives them). |
| P1-3 | craft | **No browser-frame mockup component exists.** README explicitly requires `user-*` shown in a CSS browser frame; current `.hero-shot`/`.feature-visual` are plain rounded borders. | Add a `.browser-frame` component (window bar + 3 dots, rounded, `overflow:hidden`, shadow) and a `.shot-strip` for the two wide banner strips. |
| P1-4 | resp | **Mobile nav drops everything.** `nav.site-nav { display:none }` under 720px hides all section anchors AND the "Star on GitHub" CTA, with no hamburger or replacement. Mobile users get zero nav and lose the third CTA level. (prior review deferred this as out-of-scope; it is in scope for a refactor.) | Minimal: keep `.nav-cta` visible under 720px, hide only the text anchors. Or add a lightweight disclosure menu. |

### P2 -- polish / a11y hygiene / still-open prior items

| # | Lens | Finding | Fix direction |
| --- | --- | --- | --- |
| P2-1 | a11y | `html { scroll-behavior: smooth }` (`style.css:40`) is motion not gated by reduced-motion. | Wrap in `@media (prefers-reduced-motion: no-preference)`. |
| P2-2 | craft | CTA label drift: "Self-host in minutes" vs "Try the quickstart" both target `#quickstart` on all 4 comparison pages (e.g. `fireflies-alternative` lines 88 vs 155). (prior) | Normalize to one label per intent page-wide. |
| P2-3 | a11y | No skip-to-content link; external GitHub links have no `rel="noopener"` / new-tab affordance. | Add a visually-hidden skip link; add `rel` on external links (cosmetic, low sev). |
| P2-4 | a11y | Code-comment contrast: `pre .cmt { color:#64748b }` on `--code-bg:#0f172a` is ~3.3:1 (below 4.5 for text). | Lighten comment color in code blocks (e.g. `#94a3b8`). |
| P2-5 | craft | Comparison-page heroes are still text-only (no product shot). (prior) | Optional: drop one framed shot into each; flag only, do not balloon scope. |
| P2-6 | craft | How-it-works step 1 leads a general buyer with "streams PCM16 16 kHz chunks over a WebSocket." (prior, minor) | Optional softening; acceptable for a dev-tool audience. |

No P0 a11y blocker exists: focus ring is present, contrast broadly passes, nav is
keyboard-reachable, there is no autoplaying motion.

---

## 2. Screenshot -> placement punch-list (all 20 assets)

Strategy: **scripted `postcall-*`/`admin-*` pairs** carry the theme-swappable "explainer"
surfaces (they have light + dark). **Dark-only `user-*`** carry the "real load / proof"
surfaces, always inside a browser frame. Frame column: BF = browser-frame mockup,
STRIP = wide banner strip (no window chrome), PLAIN = existing bordered container ok.

| Asset | Theme | Frame | Placement (per README) -> concrete site location |
| --- | --- | --- | --- |
| `user-live-early.png` | dark | BF | **HERO** (replaces postcall-insights). Live call under load. |
| `user-live-synthesis.png` | dark | BF | Feature Row 2 "Agents that work the call" (Synthesizer, richest signal row). |
| `user-live-answered.png` | dark | BF | NEW section "Questions answer themselves" (card flips to Answered + Refined). |
| `user-insights-158.png` | dark | BF | NEW "Post-call results" section (stat tiles: 158 total). |
| `user-insights-enhanced.png` | dark | BF | Same results section, "speaker-enhancement" beat (first-person rewrite). |
| `user-speaker-mapping.png` | dark | BF | NEW "Know who said what" diarization/speakers section (53 speakers). |
| `user-chat-tech.png` | dark | BF | NEW "Ask across every meeting" cross-session chat section. (README nit: raw `*` markdown visible -- acceptable, honest.) |
| `user-export-menu.png` | dark | BF | Exports blurb -- fold into the "Exports and chat" feature-extras card or a small strip. |
| `user-postprocessing.png` | dark | STRIP | NEW "When the call ends" banner (3808x360 -> keep ultrawide AR). |
| `user-session-header.png` | dark | STRIP | Proof strip "one call -> 158 insights" (3838x440 -> keep ultrawide AR). |
| `postcall-transcript.png` + `-dark` | light+dark | PLAIN/BF | Feature Row 1 "Live diarized transcription" via `<picture>` theme swap. |
| `admin-agents.png` + `-dark` | light+dark | PLAIN/BF | Feature Row 3 "Provider-routed models, on your keys" via `<picture>`. |
| `postcall-insights.png` + `-dark` | light+dark | PLAIN | Light/dark pool: docs/quickstart visual, or light teaser once freed from hero. |
| `postcall-briefing.png` + `-dark` | light+dark | PLAIN/BF | Briefing beat -- fold into agents/results, or a small "dual-lens briefing" note. |
| `postcall-chat.png` + `-dark` | light+dark | PLAIN | Light/dark alternate for the chat section (clean pair; `user-chat-tech` is the dark "real load" primary). |

Hero light/dark note: `user-live-early` is dark-only and MUST NOT be re-shot (privacy
crop from the unscrubbed "Fairview discussion #2"). Keep it dark on both themes inside
the browser frame; do not fall back to the light post-call shot (that reintroduces P0-2).
The frame's neutral bezel makes a dark shot read fine on the light theme.

Privacy guardrail reminder: all `user-*` assets are deliberate crops. Use as-is. Do not
uncrop, re-screenshot, or export from that session.

---

## 3. Image-optimization spec

Tool: **Python 3.14 + Pillow 12.0.0** (present; ffmpeg is not). Format: **WebP, quality
80, method 6** -- ideal for UI screenshots (sharp text, ~97% browser support, no PNG
fallback needed). Downscale with LANCZOS. **Preserve every source aspect ratio** (the two
strips are 10.58:1 and 8.72:1 -- do not letterbox or crop them). Output: `site/assets/shots/`,
same basenames with `.webp` (and `-dark.webp`).

Target widths by role (heights derived from AR; all well under the raw weights):

| Asset(s) | Source | Target (WxH) | Role |
| --- | --- | --- | --- |
| `user-live-early` | 3823x1827 | **1600x765** | hero |
| `user-live-answered` | 3808x1798 | 1600x755 | full-width section |
| `user-live-synthesis` | 3810x1797 | 1600x755 | feature row |
| `user-insights-158` | 3838x1670 | 1600x696 | full-width section |
| `user-insights-enhanced` | 2558x855 | 1440x481 | section |
| `user-speaker-mapping` | 2558x1438 | 1440x810 | section |
| `user-chat-tech` | 3838x2157 | 1400x787 | section |
| `user-export-menu` | 3838x870 | 1400x317 | blurb |
| `user-postprocessing` | 3808x360 | **1600x151** | STRIP (AR 10.58 kept) |
| `user-session-header` | 3838x440 | **1600x184** | STRIP (AR 8.72 kept) |
| `postcall-*` / `admin-*` (x10) | 1280x720 | 1280x720 (re-encode only) | explainer pairs |

Weight budget: `user-*` full shots <= 180 KB, strips <= 60 KB, scripted <= 80 KB each.
Whole placed set should land ~1.0-1.2 MB WebP vs 5.4 MB raw PNG.

Ready-to-run Pillow spec (Phase 2 can adapt; keeps AR, only downscales):

```python
from PIL import Image
from pathlib import Path
SRC = Path("showcase/screenshots"); DST = Path("site/assets/shots"); DST.mkdir(exist_ok=True)
TARGET_W = {  # else default 1600 for user-*, keep native for scripted
  "user-live-early":1600,"user-live-answered":1600,"user-live-synthesis":1600,
  "user-insights-158":1600,"user-insights-enhanced":1440,"user-speaker-mapping":1440,
  "user-chat-tech":1400,"user-export-menu":1400,"user-postprocessing":1600,
  "user-session-header":1600,
}
for p in SRC.glob("*.png"):
    stem = p.stem
    w = TARGET_W.get(stem, None)
    im = Image.open(p).convert("RGB")
    if w and im.width > w:                       # never upscale; preserve AR
        h = round(im.height * w / im.width)
        im = im.resize((w, h), Image.LANCZOS)
    im.save(DST / f"{stem}.webp", "WEBP", quality=80, method=6)
    print(stem, im.size)
```

After generation, delete the 4 now-superseded PNGs in `site/assets/shots/` (references
move to `.webp`).

---

## 4. Ordered Phase-2 edit list (files + changes)

Execute top-to-bottom; no re-audit needed.

1. **Generate assets.** Run the Pillow script -> 20 `.webp` in `site/assets/shots/`.
   Guardrail: confirm no raw `user-*.png` is ever copied into `site/`.
2. **`site/style.css` -- new components.** Add `.browser-frame` (window top-bar with 3
   traffic-light dots via a flex header or `::before`, rounded corners, `overflow:hidden`,
   `var(--shadow)`, `var(--border)`) wrapping the shot `<img>`; add `.shot-strip`
   (full-bleed thin banner, rounded, border, no chrome) for the two strips. Ensure inner
   `img { display:block; width:100%; height:auto }`.
3. **`site/style.css` -- a11y/polish.** Gate smooth scroll:
   `@media (prefers-reduced-motion: no-preference){ html{scroll-behavior:smooth} }`
   (P2-1). Lighten `pre .cmt` to `#94a3b8` (P2-4). Add a `.skip-link` visually-hidden
   style (P2-3).
4. **`site/style.css` -- mobile nav (P1-4).** Under `@media (max-width:720px)`, stop
   hiding the whole nav; keep `.nav-cta` visible, hide only the text anchors
   (`nav.site-nav a:not(.nav-cta){display:none}`), or add a small disclosure.
5. **`site/index.html` -- hero (P0-2, P1-2).** Replace the `.hero-shot` `<img>` with a
   `.browser-frame`-wrapped `assets/shots/user-live-early.webp`, `width="1600"
   height="765"`, rewrite `alt` to describe the live call (dual Listening indicators,
   strategic-signal cards, live transcript). Keep dark on both themes.
6. **`site/index.html` -- feature rows.** Row 1 -> `<picture>` `postcall-transcript.webp`
   / `-dark.webp`; Row 2 -> framed `user-live-synthesis.webp` (1600x755); Row 3 ->
   `<picture>` `admin-agents.webp` / `-dark.webp`. Every `<img>` gets `width`/`height`
   + accurate `alt`.
7. **`site/index.html` -- new sections** (insert after features, before/around
   how-it-works so the narrative reads hero -> agents -> answered -> ends -> results ->
   speakers -> chat): "Questions answer themselves" (`user-live-answered`), "When the
   call ends" banner (`user-postprocessing` strip), "One call, 158 insights"
   (`user-insights-158` + `user-insights-enhanced`), "Know who said what"
   (`user-speaker-mapping`), "Ask across every meeting" (`user-chat-tech`), plus the
   `user-session-header` proof strip. Exports card hosts `user-export-menu`. Each image:
   `.browser-frame`/`.shot-strip`, exact `width`/`height` from section 3, written `alt`.
8. **`site/index.html` -- retire old refs.** Any remaining `postcall-*.png` / `admin-agents.png`
   references switch to `.webp` (+ `-dark` `<picture>` sources). Delete the 4 superseded
   PNGs in `site/assets/shots/`.
9. **Comparison pages (flag, lower priority).** Normalize the CTA label to one per intent
   (P2-2). Optionally add one framed shot per hero (P2-5) -- only if cheap; do not expand
   scope.
10. **Validate.** `npx --yes ui-craft-detect site`; grep `site/` for any `user-*.png` or
    `showcase/` (must be empty); confirm every `<img>` has `width`/`height`; spot-check
    hero LCP and dark-mode rendering in DevTools.
