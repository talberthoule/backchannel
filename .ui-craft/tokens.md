# Backchannel UI Tokens

## Primitive

- Color: existing light/dark values in `site/style.css`; teal is the only accent.
- Type: system UI for interface text; system monospace for email, dates, counts, and versions.
- Spacing: 4, 8, 12, 16, and 24 pixels.
- Radius: 6 pixels controls, 8 pixels bounded regions, 10 pixels dialogs.
- Elevation: existing layered `--shadow`; borders carry most grouping.
- Target: 44 pixels minimum interactive height.

## Semantic

- Ink, muted, paper, surface, border, accent, accent-strong, accent-soft, and danger reuse `site/style.css`.
- Success, warning, danger, and info reuse `site/admin/admin.css` status colors.
- Status always includes text; color is supplementary.

## Admin Components

- Navigation rail: 208 pixels desktop; route tabs below 760 pixels.
- List/detail: two panes desktop; one pane below 640 pixels.
- Minimum verification width: 320 CSS pixels with no page-level overflow.
- Motion: focus, hover, and immediate state changes only; no list/form animation.
