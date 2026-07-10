# Backchannel Application — Design Review

Design-engineering review of the running Backchannel web app (http://localhost:3000) using the `ui-craft` skill system: the deterministic anti-slop detector (`ui-craft-detect`), the audit lens (a11y / performance / responsive), and the heuristic lens (Nielsen 10 + 6 design laws → UsabilityScore). Scope covered the main reachable surfaces of this single-route SPA.

**Visual capture.** Seven live states were captured and analyzed via Chrome MCP in a dedicated tab: (1) PreCall empty state, collapsed icon rail — `precall-collapsed-desktop`; (2) PreCall, sidebar expanded showing Tools / Groups / 4 completed sessions — `precall-expanded-desktop`; (3) PostCall **Briefing** tab, two-column outcome/objective/opportunity/risk layout — `postcall-briefing-desktop`; (4) PostCall **Insights** tab, six-card metric row — `postcall-insights-desktop`; (5) **Administration** (Agents 8/8 / Transcription & Audio / API Keys) — `admin-desktop`; (6) **New Session** modal — `newsession-modal-desktop`; (7) Escape-to-close verified on the modal. **Limitation:** the Chrome MCP build here did not return disk paths for `save_to_disk` captures (images are sandboxed in the extension) and window-resize did not change the captured viewport, so per-viewport PNGs could not be persisted to `design-review/screenshots/app/` and **true mobile/tablet screenshots could not be taken**. Responsive behavior and dark-mode support were therefore assessed from source (Tailwind breakpoints, layout widths, theme config) and are marked accordingly. Desktop findings are from live capture; this is **not** a code-only review.

---

## Anti-slop detector results

`npx ui-craft-detect frontend/src --json` → **137 findings across 36 of 46 files: 100 critical (errors), 37 major (warnings), 0 auto-fixed.** Triaged below; the destructive-action rule was hand-verified against the source (the detector only sees inline `window.confirm`).

| Rule | Count | Sev | Triage — worst offenders (file:line) |
| --- | --- | --- | --- |
| `a11y/outline-none-no-replacement` | 62 | Critical | `outline-none` stripped with **no** `:focus-visible` replacement anywhere. OfferingsManager.tsx (14: 108,127,205,272…), Layout.tsx (9), AdminPanel.tsx (7), KnowledgeManager.tsx (6), MeetingChat.tsx (3). |
| `no-focus-visible` | 31 | Critical | Same root cause, counted per interactive component that has `:hover` but no `:focus-visible` (ActiveCallView:189, DirectiveBar:37, QuestionCard:93, QuestionList:112, SpeakerSelector:23…). Confirmed: **0** `focus-visible` occurrences in the whole `src`; `index.css` defines no global focus fallback. |
| `transition-all` | 15 | Major | Layout.tsx (138,154,222), AudioIndicator:37, PostProcessingProgress:69, QuestionCard:52, SpeakerSelector:20, KnowledgeManager:379. Most animate hover bg/color or opacity — should name the property. |
| `uppercase-heading` | 10 | Major | ALL-CAPS text marked up as `<h2>`: BriefingView.tsx (14,140,159), PostCallView.tsx (354,382), ActiveCallView:271, TranscriptPanel:65. Some are 12–13px labels (borderline-acceptable) but they are `<h2>` headings — the tell. |
| `dark-pattern/destructive-no-confirm` | 10 | Critical | **~40% false positive.** 6 genuine unguarded destructive actions (see below), 4 false (detector missed confirms inside the onClick handler). |
| `tables/no-overflow-handling` | 2 | Major | KnowledgeManager.tsx:526, OfferingsManager.tsx:572 — wide tables, no `overflow-x` wrapper / no sticky `thead`. |
| `layout/eyebrow-flood` | 2 | Major | Layout.tsx:492, QuestionSummary.tsx:126 — stacked `uppercase tracking-wide` eyebrow labels. |
| `a11y/heading-order-skip` | 1 | — | KnowledgeManager.tsx:412 — `h1 → h3`, no h2. |
| `left-top-animation` | 1 | — | Layout.tsx:382 — sidebar animates `width` (layout reflow), not `transform`. |
| `a11y/icon-only-button-no-label` | 1 | — | Layout.tsx:212 (most icon buttons DO have aria-labels — verified live; this one is the exception). |
| `a11y/modal-without-dialog` | 1 | — | NewSessionModal.tsx — custom overlay, no native `<dialog>`/focus-trap. |
| `state/missing-empty-or-error` | 1 | — | services/api.ts:6 — fetch with no error branch (API layer, low-signal). |

**Genuinely unconfirmed destructive actions (6):** ApiKeysCard.tsx:141 (remove API key), OfferingsManager.tsx:645 (delete offering), KnowledgeManager.tsx:554 (delete record), DirectiveList.tsx:160 (delete directive), DocumentUpload.tsx:200 (delete document), SpeakerSetup.tsx:123 (remove participant). Delete-session paths (Layout.tsx:149, PostCallView.tsx:276) and delete-lens (AdminPanel.tsx:214) **do** confirm — false positives.

**Highest-leverage fact:** one global `:focus-visible` base style clears **93 of 137 findings** (the 62 + 31 focus rules) at once.

### Stack facts (from source)
- **Styling:** Tailwind v3 (utility classes inline; one 12-line `index.css`). No CSS modules / CSS-in-JS.
- **Tokens:** partial — a single flat `theme.extend.colors.brand.*` primitive palette. No CSS variables, no semantic/component layer, no dark variants. ~79 raw hex values bypass it (status/type coloring), concentrated in OfferingsManager (20), QuestionSummary (12), QuestionCard (9).
- **Accent:** teal `#0d9488` primary (`teal-dark #0f766e`, `teal-light #2dd4bf`), amber `#f59e0b` secondary, slate neutrals. **Not default-blue** — a deliberate identity (good).
- **Icons:** hand-rolled inline SVG (consistent, fine). No icon library. **But** PostCallView.tsx:55-61 uses emoji as file-type glyphs (`🖼 📄 📃 📎` …) — the one real emoji-as-icon slop.
- **Font:** system stack only (`system-ui, -apple-system, Segoe UI…`) for **both** `display` and `body` — the "no type intent" tell; the display/body split is nominal.
- **Border radius:** varied (`sm/md/lg/xl/2xl/full`) but applied ad hoc — no inputs=md / cards=lg / modals=xl convention (e.g. `rounded-lg` cards next to `rounded-xl` cards).
- **Dark mode:** **none** — 0 `prefers-color-scheme` / `dark:` / `data-theme`, no `darkMode` in Tailwind config, no `color-scheme` declaration. Light-only.

---

## Audit findings

### Critical (blocks usability / a11y)

| Before | After | Why |
| --- | --- | --- |
| `outline-none` / `focus:outline-none` on ~93 interactive elements, **no `:focus-visible` anywhere** in `src` | Add one global base: `:focus-visible { outline: 2px solid theme(colors.brand.teal); outline-offset: 2px }` + `focus-visible:ring-2` on custom controls | Keyboard and switch users have **zero** visible focus indication across the entire app — cannot tell where they are. Single highest-impact fix. |
| 6 destructive actions fire instantly with no confirm/undo (remove API key, delete offering / record / directive / document / participant) | Confirm dialog (or undo toast) on each; ideally an undo toast over a modal | Irreversible data loss from a single mis-click; removing an API key silently breaks live transcription. |
| NewSessionModal is a custom `<div>` overlay with no focus trap / no `<dialog>` | Native `<dialog>` or a focus-trap; return focus to the trigger on close | Focus can escape behind the modal for keyboard/SR users. (Esc-to-close **does** work — verified live.) |
| No mobile layout: sidebar is fixed `w-16`/`w-64`, live-call panel fixed `w-80`; only 13 responsive utilities in 46 files | Add a mobile breakpoint: collapse sidebar to an off-canvas drawer < `md`; stack the live-call transcript/insight columns | On a 375px screen the `w-64` sidebar consumes ~68% of width; the app is desktop-only in practice. |

### High-impact (immediately noticeable)

| Before | After | Why |
| --- | --- | --- |
| Insights metric row uses **5 competing accent hues** at equal weight: Action Items red, Opportunities green, Observations purple, Questions teal, Enhanced teal-light | One accent (teal) for the primary metric; neutral slate for the rest; encode type with a small leading dot, not a full-color number | Violates "one accent, 3–5 placements" — the rainbow reads as a tie and the eye stalls; nothing is emphasized. |
| Colored ALL-CAPS `<h2>` section labels (TOP 3 OUTCOMES, OBJECTIVES, RISKS/BLOCKERS…) stacked per column | Sentence-case headings at normal weight; reserve small tracked caps for at most one eyebrow | Eyebrow-flood + uppercase-heading; template grammar, and the caps sit on `<h2>` so they inflate the a11y heading tree. |
| Action-item card carries a thick colored left border; "TOTAL 6" metric card uses a flat full black border | Use bg tint / layered shadow for emphasis; hairline neutral border on the metric card | Thick colored left borders and flat 1px black borders are two of the named AI tells; elevation reads as more considered. |
| Both `font-display` and `font-body` resolve to the identical system stack | Load one real face (e.g. Inter/Geist for body; optionally a tighter display face) with `tracking-tight` on large headings | System-font-only is the "no design intent" signal for a brand-facing product. |
| Emoji file-type glyphs (`🖼 📄 📎`) in PostCall documents | Reuse the existing inline-SVG icon set for file types | Emoji-as-icon is the one clear anti-slop icon violation. |

### Quick wins (polish)

| Before | After | Why |
| --- | --- | --- |
| 15 × `transition-all` | Name the property: `transition-colors` / `transition-opacity` | `all` animates unintended properties and can hit layout; also a perf win. |
| Sidebar `transition-[width]` (Layout.tsx:382) | Prefer `transform`-based reveal, or accept and scope it | Animating `width` triggers layout/reflow each frame. |
| 79 raw hex values for status/type color | Promote to named semantic tokens (`--insight-risk`, `--insight-opportunity`…) | Centralizes the palette; prerequisite for a future dark mode. |
| Wide tables (Offerings, Knowledge) have no overflow wrapper | Wrap in `overflow-x-auto`; sticky `thead` | Prevents page-level horizontal scroll on narrow widths. |
| No `color-scheme` declaration | Add `color-scheme: light` (and a dark token set later) | Correct native form-control/scrollbar theming. |

---

## Heuristic scorecard

## Heuristic Scorecard

| Heuristic | Score | Finding | Impact |
|-----------|-------|---------|--------|
| Visibility of system status | 4 | Active-tab underline, "Completed" status pills, briefing "Updated… / Status: completed", tab counts (Insights (6), Speakers (0)), PostProcessingProgress component. Solid. | minor-polish |
| Match system and real world | 4 | Human copy ("pick a type so the agents know what to listen for"); locale dates (7/8/2026, 10:36 PM); conventional icons. "Directives" is mild jargon but explained. | minor-polish |
| User control and freedom | 3 | Modal closes on Esc + Cancel + X (verified); session-delete confirms — but 6 destructive actions have no confirm and there is **no undo anywhere**. | reduces-trust |
| Consistency and standards | 4 | Primary action consistently teal-solid, right-aligned; Cancel is left/text throughout. Radius usage is ad hoc; "Delete/Remove" wording varies. | minor-polish |
| Error prevention | 3 | Session name optional-with-default is good prevention; but destructive confirms are freeform `window.confirm` (not typed-name) and 6 actions have none; no visible client-side validation. | reduces-trust |
| Recognition over recall | 4 | Sessions + status listed in sidebar; conversation type as visible pills; empty states suggest the next action. No command palette. | minor-polish |
| Flexibility and efficiency | 3 | Has groups + drag-drop (dnd-kit), but no keyboard shortcuts, no command palette, no bulk-select on insights/sessions for a tool users live in for hours. | adds-friction |
| Aesthetic and minimalist | 3 | Clean base and real whitespace, but the 5-color metric row + colored uppercase eyebrows + colored left-border cards dilute the focal point. | reduces-trust |
| Error recovery | 3 | No inline field-error pattern observed; `api.ts` fetch has no error branch. No broken error surfaced live, so uncertain — likely basic global handling. | reduces-trust |
| Help and documentation | 4 | Empty states double as onboarding; section subtitles explain intent; icon buttons carry aria-labels; external docs site. | minor-polish |

## Design Law Audit

| Law | Pass/Fail | Detail |
|-----|-----------|--------|
| Fitts's Law | FAIL | Destructive "Delete Session" sits immediately beside primary "Resume Call" / "Export"; and no ≥44px touch sizing since there is no mobile layout. |
| Hick's Law | PASS | PostCall tabs = 7 (Briefing…Directives), Admin = 3 tabs, conversation type = 6, sidebar Tools = 3. Within 7±2. |
| Doherty Threshold | PASS | Tab/section switches are client-side and instant; long AI work has a progress component. No blocking spinner observed. |
| Cleveland-McGill | PASS | No pie/3D; metrics are position/length (big numbers); color used for category, which is legitimate. |
| Miller's Law | PASS | New Session form chunked into 2 sections; tab bar at the 7 ceiling but chunked with counts. |
| Tesler's Law | PASS | Primary task (start a session) needs zero required input — name defaults, type defaults to "General / infer"; config complexity lives in the Admin area behind progressive disclosure. |

## Top findings (ranked by impact)

1. **User control / Error prevention (scores 3, reduces-trust)** — 6 destructive actions delete data with no confirm and the app has no undo anywhere; removing an API key silently breaks live transcription. Add confirm + undo-toast.
2. **Fitts's Law (FAIL, reduces-trust)** — destructive Delete sits adjacent to the primary CTA and nothing is sized/laid out for touch; separate destructive actions and add a mobile layout.
3. **Aesthetic & minimalist (score 3, reduces-trust)** — the 5-hue metric row + colored uppercase eyebrows compete for attention; collapse to one accent + neutral.
4. **Flexibility & efficiency (score 2→3, adds-friction)** — no shortcuts / command palette / bulk-select in a tool used for long sessions.
5. **Error recovery (score 3, reduces-trust)** — no inline error pattern and no fetch error branch; a failed save/import likely strands the user.

## UsabilityScore

**58 / F** (judged) · heuristic base 63 − law penalty 5

| Component | Value |
|-----------|-------|
| Nielsen mean (1–5) | 3.5 |
| Heuristic base (0–100) | 63 |
| Failed design laws | 1 (Fitts) |
| Law penalty | −5 |
| **UsabilityScore** | **58 / F** |

The F is driven less by the pure Nielsen mean (a competent internal tool, base 63 ≈ high-D) and more by the fact that the app's single most consequential problem — **no keyboard focus indication anywhere** (93 detector hits) — lands squarely on User Control and Freedom. The deterministic anti-slop signal (137 findings, 100 critical) corroborates: the code is functional but the *experience* has friction, mostly a11y and focus, that the happy-path visuals hide. Fix the focus system and guard the destructive actions and this jumps into the C/B band quickly.

---

## Top 5 things to fix to make this stand out

1. **Ship a focus system (one change, clears 93 findings).**
   - Before: `outline-none` on ~93 controls, `focus-visible` used 0 times, `index.css` has no focus rule.
   - After: a single base rule — `:where(a,button,[role=button],input,select,textarea,[tabindex]):focus-visible { outline: 2px solid var(--brand-teal); outline-offset: 2px }` — plus `focus-visible:ring-2 ring-brand-teal ring-offset-2` on custom pill/tab controls.
   - Why it stands out: instantly makes the whole app keyboard-navigable and is the difference between "AI-generated" and "an engineer who cares."

2. **Guard the 6 destructive actions with confirm + undo.**
   - Before: remove API key / delete offering / record / directive / document / participant fire instantly and irreversibly.
   - After: a lightweight confirm for the heavy ones, and an **undo toast** ("Directive deleted — Undo") for the frequent ones; return focus to the triggering row afterward.
   - Why: removes the only data-loss dark pattern and reads as a mature product.

3. **Collapse the rainbow metric row to one accent.**
   - Before: Action Items (red) / Opportunities (green) / Observations (purple) / Questions (teal) / Enhanced (teal-light) — five equal-weight colored numbers.
   - After: teal on the primary count only, slate `tabular-nums` numbers elsewhere, a small leading category dot for type; give "TOTAL" the accent tint instead of a flat black border.
   - Why: restores a single focal point and kills three AI tells (competing accents, colored borders, non-tabular numbers) at once.

4. **Give the product a typeface and a real token spine.**
   - Before: `font-display` and `font-body` both resolve to the system stack; 79 raw hex values; no dark mode.
   - After: load one web font (e.g. Inter/Geist body) with `tracking-tight` on 24px+ headings; promote the status/type hexes to semantic CSS variables so a dark theme (currently absent) becomes a token swap, not a rewrite.
   - Why: type + a semantic palette are what separate "themed Tailwind defaults" from a designed brand.

5. **Add a mobile/tablet layout and make it keyboard-fast.**
   - Before: 13 responsive utilities app-wide; fixed `w-64` sidebar and `w-80` live-call panel; no shortcuts or bulk-select.
   - After: off-canvas drawer sidebar < `md`, stacked live-call columns, `overflow-x-auto` on the wide tables; add a command palette (Cmd+K) and multi-select on the insight/session lists.
   - Why: the app is currently desktop-only and novice-paced; both are ceilings for a tool people run every meeting.

---

### Method notes
- Detector: `ui-craft-detect v0.11.0`, `--json`, 46 files scanned.
- Heuristic scoring per `references/heuristics.md`; UsabilityScore is **judged**, not deterministic — do not gate CI on it. The deterministic UICraftScore (`scripts/eval.mjs`) was not run here; the 137-finding detector output is the reproducible anti-slop signal.
- Responsive and dark-mode conclusions are code-derived (Tailwind breakpoints, layout widths, `tailwind.config.js`) because the browser tool could not change the captured viewport; desktop findings are from live capture.
