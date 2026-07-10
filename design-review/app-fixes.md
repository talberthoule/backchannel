# Backchannel Web App - Design Fixes

Implementation of the six-stage fix pipeline from `app-review.md`. Scope was
`frontend/` only. Every stage ends green on `npm run build` (tsc + vite). Light
and dark themes were verified live in Chrome (welcome shell), including the
theme toggle and the keyboard focus ring.

## Stage 1 - Token spine + typeface (foundational)

- `frontend/src/index.css`: rebuilt as a 3-layer token spine. Primitives are
  brand + slate RGB channels; semantics (`--surface`, `--surface-raised`,
  `--border-subtle`, `--text-primary/secondary/tertiary`, `--accent*`,
  `--focus`) map to them. Authored light **and** dark sets plus a
  `prefers-color-scheme: dark` block for users without an explicit choice.
  `color-scheme` declared per theme.
- `frontend/tailwind.config.js`: `brand.*` colors now resolve through the
  semantic CSS vars via `rgb(var(--x) / <alpha-value>)` (so `bg-brand-teal/10`
  opacity utilities still work and a theme swap re-skins the whole app without
  touching components). Added semantic `surface` / `canvas` colors and
  `darkMode: ["selector", '[data-theme="dark"]']`.
- Typeface: self-hosted **Inter Variable** via `@fontsource-variable/inter`
  (new dependency), imported in `frontend/src/main.tsx`; wired into the
  `display`/`body` font stacks. One face for both roles (kept minimal).
- Kept the teal accent (no switch to blue).

## Stage 2 - Global focus-visible system + outline-none sweep

- `frontend/src/index.css`: one global base rule gives every interactive
  element a 2px `:focus-visible` ring from `--focus` (teal in light, teal-light
  in dark). Mouse clicks stay quiet.
- Swept **62** `outline-none` / `focus:outline-none` tokens out of 21
  components (scripted). Existing per-control `focus:ring` styles were left as
  enhancements. Confirmed 0 leftover `outline-none` and no dangling `focus:`.
  Verified live: Tab shows a teal ring.

## Stage 3 - Insights metric-row palette collapse

- `frontend/src/components/PostCall/QuestionSummary.tsx`: the 5-hue `StatCard`
  row collapses to one accent - numbers are neutral slate `tabular-nums`, the
  active card gets the teal ring/tint, and each type carries a small leading
  category dot instead of a full-color number. `SummaryCard` lost its colored
  `border-l-4` (bg-tint state emphasis only).
- `frontend/src/components/ActiveCall/QuestionCard.tsx`: removed the colored
  `border-l-4`/`borderLeftColor`; neutral hairline border, teal tint for the
  strategic-signal state (was stray `bg-blue-50`), `transition-all` -> `transition`.
  Type still encoded by the existing colored pill.

## Stage 4 - Destructive-action guards + confirm/toast

- New `frontend/src/components/ConfirmProvider.tsx`: one small reusable
  primitive - `useConfirm()` exposes `confirm({...}): Promise<boolean>` (an
  accessible modal: `role="dialog"`, `aria-modal`, Escape + backdrop close,
  autofocused confirm button, danger tone) and `toast(msg)` for feedback.
  Wrapped `<App/>` in `main.tsx`.
- Guarded the 6 genuinely-unguarded actions at their handler root (one guard
  per shared handler, so every caller is covered): remove API key
  (`ApiKeysCard`), delete offering (`OfferingsManager`), delete record
  (`KnowledgeManager`), delete directive (`PreCall/DirectiveList`), delete
  document (`PreCall/DocumentUpload`), remove participant
  (`PreCall/SpeakerSetup`). Each shows the confirm then a success toast.
- Did **not** double-guard the 4 false positives (session delete in
  `Layout`/`PostCallView`, delete-lens in `AdminPanel` already confirm).
- Bonus: upgraded `KnowledgeManager` delete-source (a real destructive action
  that used bare `window.confirm`) to the same primitive.
- **Deliberately deferred: true undo.** The report suggested undo toasts. The
  delete endpoints are destructive server-side and restore plumbing differs per
  entity (a deleted document's file and a cleared API secret cannot be
  re-created client-side), so a uniform undo would be half-working. The confirm
  dialog removes the actual data-loss dark pattern; the toast gives feedback.

## Stage 5 - Responsive mobile/tablet layout

- `frontend/src/components/Layout.tsx`: sidebar is now an off-canvas drawer
  below `md` (fixed, `-translate-x-full` -> `translate-x-0`, backdrop, hamburger
  in the header, closes on navigation) and the in-flow collapsible rail at
  `md+`. A `matchMedia` hook forces the full drawer (never the icon rail) on
  mobile. Header/main padding is `px-4 md:px-6` / `p-4 md:p-6`.
- `frontend/src/components/ActiveCall/ActiveCallView.tsx`: two columns stack on
  mobile (`flex-col md:flex-row`); the transcript panel is a bottom section
  (`h-64`, top border) on mobile and the `md:w-80 xl:w-96` side column on
  desktop.
- Wide tables wrapped in `overflow-x-auto` with a `min-w` so they scroll inside
  their own container instead of the page: `OfferingsManager`, `KnowledgeManager`.
- Touch targets on the drawer/nav controls are >=44px (existing `h-11 w-11`).

## Stage 6 - Dark mode

- `frontend/src/components/Layout.tsx`: theme toggle (sun/moon) in the header.
  Explicit choice persists to `localStorage` and stamps `data-theme` on
  `documentElement`; OS preference is the initial default. Because stage-1
  tokens do the theming, this swaps every primary surface (PreCall, ActiveCall,
  PostCall, Admin, modals, drawer) at once.
- Swept **92** `bg-white` -> `bg-surface` across 28 components so panels swap.
  Toggle knobs pinned to fixed `bg-slate-50` (contrast in both themes).
- Converted stray light-only classes that would break dark: `bg-blue-50`,
  `bg-gray-100/200`, `text-gray-500`, and hardcoded `text-[#333]` -> brand/teal
  tokens. Status pills (green "Answered", amber follow-up, red destructive) were
  intentionally left literal - they are self-contained and legible on both
  themes.
- Verified live: both themes render coherently (dark = slate-900 canvas /
  slate-800 panels / teal accent / light text); no half-broken surface found.

## Not done (out of scope / intentional)

- Remaining raw hex values are data colors, not styling: speaker avatar colors
  (user-chosen), agent/offering category dot palettes, and the insight
  `typeColor` map. These are legitimate categorical encodings, not theme
  surfaces, and were left as-is.
- Uppercase `<h2>` section labels and most `transition-all` instances were not
  swept (not in the six-stage scope; low severity).
- The 15 `transition-all` findings: only the one in `QuestionCard` was addressed
  incidentally.

## New dependency

- `@fontsource-variable/inter` (self-hosted Inter Variable woff2, bundled).
