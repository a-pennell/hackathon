# Interface design system — Problem-Oriented Chart

Read this before building or changing any UI in `frontend/`. Tokens live in
`frontend/src/styles.css`; this file records the decisions behind them.

## Direction and feel

**A paper flowsheet read under clinic light.** The person is a clinician mid-clinic who needs
to read a problem's trajectory in seconds and then sign or reject what the system proposes.
Dense but calm; nothing decorative; every color carries meaning.

Domain the design draws from: Weed's problem-oriented record (the numbered problem list),
the flowsheet, the medication administration record (horizontal bars on a shared time axis),
the abnormal-result flag, the signing inbox, the chart citation.

**Signature: pencil versus ink.** Everything AI-proposed is *pencil* — dashed strokes, no fill,
amber tag — until a clinician signs it; then it is *ink*, solid and blue-black. This rule holds
everywhere: timeline bands and points, inbox cards, the problem list. It is the visible form of
non-negotiable 1 ("nothing AI-generated writes directly to the chart").

## Color

| Token | Value | Meaning |
|---|---|---|
| `--paper` | `#f6f3ec` | canvas (cream stock) |
| `--paper-2` | `#fbf9f4` | elevated surface: cards, menus, modal |
| `--paper-inset` | `#efebe1` | inset: segmented controls, wells |
| `--ink` / `--ink-2` | `#23262f` / `#4b4f5a` | primary / secondary text |
| `--graphite` / `--pencil` | `#7a7d86` / `#a7a59c` | tertiary / muted text, numbering |
| `--select` | `#1f4e79` | **the one accent**: selection, evidence chips, primary button |
| `--band` | `rgba(31,78,121,.09)` | reference-range shading on a lab lane |
| `--flag` | `#c2431f` | out-of-range result, "cause?" relation (the vermilion H flag) |
| `--pending` | `#a86b12` | proposed / unsigned (amber of an unsigned order) |
| `--accepted` | `#2f6b4f` | signed badge only |
| `--med-1…6` | desaturated blue/violet/ochre/teal/rose/slate | medication band fills, assigned by lane index |

Rules: one accent (`--select`). Red means abnormal, amber means unsigned, green appears only on
the "signed" badge. Surfaces share one hue and shift lightness only; sidebars use the same
canvas as the sheet, separated by a 1px rule.

Borders: `--rule` (rgba .12) standard, `--rule-soft` (.07) grid lines, `--rule-strong` (.28)
control edges. Depth strategy is **borders only** — no shadows except the tooltip and menu.

## Typography

- `--serif` `"Charter", "Iowan Old Style", Palatino, Georgia` — patient name, problem names,
  lane names, insight statements, note text, quotes (italic). The paper-chart voice.
- `--sans` system stack — UI chrome, labels, buttons, tooltips. Base 13px / 1.45.
- `--mono` `"SF Mono", Menlo` with `font-variant-numeric: tabular-nums` — every value, id, date,
  dose label, axis label. Never render a number in the sans.
- Section labels: 11px, 600, letter-spacing 0.08em, uppercase, `--graphite`.

## Spacing and shape

Base unit `--u: 4px`. Padding in multiples of the unit (2, 3, 4, 5, 6). Radii: `--r-sm 3px`
(chips, badges), `--r-md 5px` (cards, buttons, menus). Sharp enough to read as a tool.

## Layout

Three-pane chart desk on a CSS grid: `272px | 1fr | 372px`, header across the top.
Left: problem list (active problems with monitored series first, newest onset first; resolved
folded). Centre: the sheet — timeline for the selected problem. Right: review queue then
"Insights on chart".

## Timeline (`Timeline.tsx`)

- Gutter `GUTTER = 176px` is the flowsheet margin: lane name (serif), unit + count, latest
  value (mono, red if out of range), delta vs baseline with direction arrow.
- Lab lane `LANE_H = 92`, gap 10. Reference range drawn as `--band` rect; points r=3 ink-stroked
  on paper fill; out-of-range points filled `--flag`; highlighted points r=5 with `--select`
  stroke. Series ordered by absolute delta so the moving one leads.
- Medication lanes `MED_H = 22`, sorted suspected cause → treats → on board; relation printed in
  the gutter ("cause?" in flag red, "treats" in graphite). Dose change = white tick at the
  boundary. Pencil bands: `--pending-wash` fill, dashed `--pending` stroke.
- Encounters: 1px graphite ticks; encounters whose note produced findings get a 2px `--select`
  tick with a dot.
- Cursor: dashed `--select` vertical line with the date in mono under the axis.
- Tooltip: `--ink` background, paper text, quote in serif italic.

## Inbox cards (`Inbox.tsx`)

`.card` on `--paper-2` with `--rule` border. Proposed → `.pencil` (dashed amber border).
Kind badge top-left (amber; green "signed"; grey "rejected"), confidence mono top-right, what
line, then the verbatim quote in serif italic wrapped in typographic quotes, optional hint in
graphite, then Reject (ghost) / Sign (primary) right-aligned. Hovering a card highlights its
ids on the sheet; evidence chips (`.chip`, mono, `--select`) do the same per id.

## Controls

Buttons: `.btn` paper-2 with strong rule; `.primary` filled `--select`; `.ghost` borderless;
`.small` for card actions. Segmented window picker `.seg` on `--paper-inset`, active segment
lifts to `--paper-2` in `--select`. Dropdowns are custom `.menu` panels, never native selects.

## States to keep

Every interactive element has hover; buttons have disabled (opacity .5). Data states: "Opening
chart…", empty sheet copy ("No monitored lab series is linked to …"), empty queue copy, error
banner `.err` in `--flag-wash`. Busy state is a graphite italic line in the header.

## Do not

Add a second accent; put numbers in the sans; use shadows for elevation; give proposed items
solid fills; color surfaces with different hues; add icons that don't carry meaning.
