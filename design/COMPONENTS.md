# Shared components

Build these once (phase 0) in `web/src/ui/`, on the global classes ported from
`mockups/style.css` into `web/src/styles.css`. Every colour is a `var(--fs-…)` from
`tokens.css`. Props are suggestions — keep them small; the mockup class in the right column
is the exact CSS to port.

| Component | Props | Mockup CSS | Notes |
|---|---|---|---|
| `AppHeader` | `page`, `onPage`, `connections`, `logCount` | `.app-header .brand .mode .actions` | Keeps the `Page` radiogroup semantics (see SPEC §0). |
| `StepRail` | `steps: {title, sub, state: 'todo'|'now'|'done'|'run', href}[]`, `actions: ReactNode` | `.rail .steps .step .n .t .s` | Lines between steps are `li.line`. |
| `Button` | `variant: 'default'|'primary'|'dark'`, `size: 'sm'|'md'|'lg'`, `icon?`, `count?`, `as: 'button'|'a'` | `.btn .primary .dark .sm .lg .count` | Mono uppercase 11.5 px, pill radius. Primary = accent fill with ink text. |
| `LinkButton` | `icon?` | `.link-btn` | Text-only action inside cards (Rows to read: all ⌄). |
| `Pill` | `tone: 'ok'|'warn'|'idle'|'run'`, `dot?` | `.pill .ok .warn .idle .run` | Status: Loaded · 0.3s, Not loaded, pairing… |
| `Chip` | `tone: 'default'|'key'|'a'|'b'|'neg'|'pos'` | `.chip` | Type chips, key chip (ink fill + key icon), side-coloured column names. |
| `Seg` | `options: {label, value, icon?}[]`, `value`, `onChange`, `mini?`, `aria-label` | `.seg .seg.mini` | `role="group"`; each option a `<button aria-pressed>`. Mini = 28 px, ink fill when on (used per table row). |
| `Select` | `tone: 'a'|'b'|'none'|'type'`, `value`, `options`, `onChange` | `.sel .sel.a .sel.b .sel.none .sel.type` | A real `<select>` visually wrapped as a chip with a chevron; `none` is dashed "no partner". |
| `Field`, `Input`, `Textarea` | `label`, `id`, `mono?`, `tiny?`, `grow?` | `.field .lbl .in .in.mono .in.tiny .in.grow .in.name` | Label is mono uppercase 10.5 px. Textarea for WHERE clauses. |
| `Check` | `label`, `checked` | `.check` | Accent-coloured native checkbox. |
| `Dropzone` | `accept`, `onFile`, `hint` | `.drop` | Dashed box, upload icon, "choose a file" link wraps a hidden `<input type=file>`. |
| `SideBadge` | `side: 'a'|'b'|'k'` | `.side-badge` | 28 px square: A blue, B clay, K ink (profile / config). |
| `Card` | `title?`, `head?`, `foot?` | `.card .card-head .card-foot` | White, 10 px radius, 16/20 px padding, 14 px gap. |
| `Panel` | `title`, `sub?`, `actions?`, `foot?` | `.panel .panel-head .panel-body .panel-foot` | Like Card but for tables: no inner padding around the table, `.tblwrap` scrolls horizontally. |
| `DataTable` | `columns: {key, label, align?, width?, swatch?: 'a'|'b'}[]`, `rows`, `compact?`, `minWidth` | `.tbl .tbl.compact th td .num .m .dim tr.muted` | Native `<table>`; mono uppercase headers; 46 px rows (40 compact). Keep TanStack Table for the big grids (paired rows) and render into the same classes. |
| `Bar` | `pct`, `tone: 'accent'|'ok'|'good'|'warn'`, `label?` | `.bar .bar i .barcell .v` | 8 px track. Match %: ok at 100, good ≥ 95, warn below. Distinct %: accent. |
| `Tabs` | `items: {label, href, count?, active}[]` | `.tabs .tabs a.on .count` | 44 px, 2 px accent underline. Results views. |
| `Tile` | `label`, `value`, `small?` | `.tiles .tile .v` | Serif 28 px number under a mono label. |
| `Callout` | `tone: 'default'|'warn'|'pos'`, `icon?` | `.callout .warn .pos` | One-line explanations and findings. Never a left border accent. |
| `DiffCell` | `a`, `b` | `.diff .a .b` | `A value → B value` on the diff tint; arrow in accent. Numbers in mono. |
| `FilterChip` | `label`, `count?`, `on` | `.fchip .fchip.on .n` | Column filters over the differing rows. |
| `Search` | `placeholder`, `value` | `.search` | Pill input with a search icon. |
| `Verdict` | `meta`, `children` | `.verdict .meta p code strong.neg` | Fraunces 30 px sentence; counts bold; differing counts in `neg`. |
| `OutcomeBar` | `segments: {label, n, color}[]` | `.outcome .stack .legend .c-full .c-diff .c-onlya .c-onlyb` | Stacked bar + legend. |
| `Drawer` | `title`, `onClose`, `width=420` | `.drawer-wrap .drawer` | Right-hand panel; traps focus; `Esc` closes. |
| `LogList` | `entries` | `.log .entry .at .kind .l .sub` | Mono 12.5 px; grid 76 / 96 / 1fr. |
| `RunningPanel` | `headline`, `line`, `step`, `of`, `elapsed`, `tasks: {label, state, time?}[]` | `.runbox .disc .tasks .progress` | SPEC §07. |
| `Pipeline` | `steps`, `onMove`, `onRemove`, `onParam` | `.pipe .pstep .op .sql` | SPEC §05. |
| `OpsPicker` | `ops: string[]`, `onPick` | `.ops` | Chips from `/api/setup/functions`. |
| `FileList` | `files: {name, description, fact, checked, disabled?}[]` | `.files` | SPEC §12. |
| `Histogram` | `bins: {lo, hi, n}[]` | `.hist .hist-x` | CSS bars, heights relative to the max bin; a `<title>` per bar. |
| `StatGrid` | `stats: {label, value, sub?}[]` | `.stat-grid .stat` | SPEC §16. |
| `Welcome` | `page` | `.hero .how` | SPEC §01 / §14. Only while nothing is loaded. |

## Icons (`web/src/ui/icons.tsx`)

Inline SVG, `viewBox="0 0 24 24"`, `fill="none"`, `stroke="currentColor"`, round caps and joins,
`aria-hidden="true"` unless the icon is the only content of a control (then the control gets an
`aria-label`). Sizes 14 px (default) and 12 px (`sm`). The set used by the mockups:

`check` `chevron` `arrow` `arrowl` `swap` `key` `plug` `search` `download` `upload` `sparkle`
`table` `plus` `x` `folder` `file` `play` `db` `zip` `refresh`

`design/icons.tsx` is a ready-made module with all of them — copy it to `web/src/ui/icons.tsx`.

## Type scale

| Use | Font | Size / weight |
|---|---|---|
| Wordmark | Fraunces | 21 px / 400, last word italic accent |
| Verdict, welcome headline, tile numbers | Fraunces | 30 px / 400 · 44 px / 400 · 28 px / 400 |
| Section titles | IBM Plex Sans | 17 px / 600 (panel titles 15 px / 600) |
| Body, table cells | IBM Plex Sans | 13–14 px / 400 |
| Labels, eyebrows, buttons | IBM Plex Mono | 10.5–11.5 px / 400–500, uppercase, 0.08–0.14 em tracking |
| Values, column names, code | IBM Plex Mono | 12–12.5 px / 400–500 |

## Spacing and shape

Page max-width 1384 px, side padding 28 px, section gap 24 px (20 px on results), card padding
16/20 px, panel head 14/20 px, table cell padding 12 px, radius 6 px (inputs, chips, cells) and
10 px (cards, panels), pills 999 px. Hit targets: 36 px buttons, 32 px controls inside rows,
44 px tabs and the big Compare button.
