# Style Guide: Portfolio Dashboard

**Source of truth:** `dashboard.html` (the mockup). Where the two disagree, the mockup wins, and this file should be updated to match.
**Applies to:** the Flask app's templates and CSS, per PRD v4 §6.
**Last updated:** 2026-09-24

---

## 1. Principles

1. **The numbers are the interface.** No decoration competes with a figure. Colour marks meaning: up, down, stale, failed, or a series. Nothing else gets colour.
2. **Every figure shows where it came from.** A price shows its date and source. A total shows the FX rate and the date of that rate. A generated cash leg shows its parent.
3. **Show when data is missing, never hide it.** Stale prices get a badge. Gaps in the chart are a visible band, not an interpolated line. A failed fetch keeps the last good value and says so. No coverage is written out as "No coverage", never left as an empty cell.
4. **Show the write before it happens.** Any form that writes to the ledger previews what it will write, including the generated legs and the cash balance after the write.
5. **Quiet by default.** Flat surfaces, hairline borders, and a single accent. The only shadow is on the tooltip.

---

## 2. Colour tokens

All colour comes from CSS custom properties on `:root`. Never hard-code a hex value in a component.

| Token | Light | Dark | Use |
|---|---|---|---|
| `--page` | `#f9f9f7` | `#0d0d0d` | Page background; also the fill of input fields |
| `--surface` | `#fcfcfb` | `#1a1a19` | Cards, dialogs, tooltips, sticky table headers |
| `--surface-2` | `#f3f2ee` | `#232321` | Group rows, segmented-control track, info boxes, previews, chart gap band |
| `--ink` | `#0b0b0b` | `#ffffff` | Primary text and figures |
| `--ink-2` | `#52514e` | `#c3c2b7` | Labels, secondary text |
| `--muted` | `#898781` | `#898781` | Captions, hints, axis ticks, table headers |
| `--grid` | `#e1e0d9` | `#2c2c2a` | Chart gridlines |
| `--axis` | `#c3c2b7` | `#383835` | Chart baseline, table header rule, dashed banner border |
| `--border` | `rgba(11,11,11,.10)` | `rgba(255,255,255,.10)` | Every hairline border |
| `--accent` | `#2a78d6` | `#3987e5` | Primary button, value line, focus ring, links |
| `--accent-wash` | `rgba(42,120,214,.10)` | `rgba(57,135,229,.16)` | Chart area fill, new-row flash |
| `--up` | `#006300` | `#0ca30c` | Gains, positive deltas |
| `--down` | `#d03b3b` | `#e66767` | Losses, negative deltas, validation errors, failed fetch |
| `--warning` | `#fab219` | — | Reserved |
| `--warning-ink` | `#8a5a00` | `#fab219` | Stale price text, preview warnings |
| `--warning-wash` | `rgba(250,178,25,.16)` | `rgba(250,178,25,.14)` | Stale badge fill |
| `--critical-wash` | `rgba(208,59,59,.10)` | `rgba(230,103,103,.14)` | Failed-fetch badge fill |

### Series palette (allocation, group swatches)

| Token | Light | Dark | Assigned to |
|---|---|---|---|
| `--s1` | `#2a78d6` | `#3987e5` | BDO Securities · PH equities |
| `--s2` | `#eb6834` | `#d95926` | IBKR · US equities |
| `--s3` | `#1baf7a` | `#199e70` | Kraken · ETFs |
| `--s4` | `#eda100` | `#c98500` | Crypto · 1st user-added platform |
| `--s5` | `#e87ba4` | `#d55181` | Cash · 2nd user-added platform |
| `--s6` | `#7b61d9` | `#8f79e0` | Funds · 3rd user-added platform |
| `--muted` | — | — | Other |

Rules:
- A series colour always means the same thing within one view. Platform colours and asset-class colours share tokens, but they never appear in the same view, because the grouping toggle swaps one set for the other.
- `--up` and `--down` are only for signed financial change. Never use them for a series.
- Direction is always shown two ways: colour plus a sign or arrow (`+`, `−`, `▲`, `▼`). Colour alone is never enough.

### Dark mode

Dark values are defined twice: under `@media (prefers-color-scheme: dark)` guarded by `:root:not([data-theme="light"])`, and again under `:root[data-theme="dark"]`. The Theme button sets `data-theme` on `<html>`. Set `color-scheme` in both themes so native controls (date pickers, selects, scrollbars) match.

---

## 3. Typography

System stack only: `system-ui, -apple-system, "Segoe UI", sans-serif`. Base size is `14px/1.45`, with `-webkit-font-smoothing: antialiased`.

| Role | Size | Weight | Notes |
|---|---|---|---|
| Page title (`h1`) | 20px | 650 | `letter-spacing: -0.01em` |
| Hero KPI value | 34px (30px under 560px) | 650 | `letter-spacing: -0.02em`, `line-height: 1.15` |
| KPI value | 26px | 650 | same |
| Dialog title (`h3`) | 16px | 600 (default) | |
| Card title (`h2`) | 14px | 600 | |
| Body, table cells | 14px | 400 | |
| Instrument ticker | 14px | 600 | `.inst-name` |
| Button, segmented control | 14px / 12.5px | 550 | |
| Labels, meta, KPI label | 13px / 12.5px | 400–550 | `--ink-2` |
| Captions, hints, sub-lines | 12–12.5px | 400 | `--muted` |
| Table header | 11.5px | 600 | uppercase, `letter-spacing: .04em`, `--muted` |
| Section label in forms | 11.5px | 600 | same treatment as table header |
| Badge, tx-type chip | 11px | 600 | |

- **Every figure gets `.num`** (`font-variant-numeric: tabular-nums`), so digits line up in columns and don't jitter when values update.
- Weights are the variable-font steps 400 / 550 / 600 / 650. Don't use 700.

---

## 4. Spacing, radius, layout

- **Spacing:** multiples of 2 and 4. The common values are 4, 6, 8, 10, 12, 16, and 20px. Card padding is 16px, dialog padding is 20px, and the gap between cards is 12px.
- **Radius:** 12px for cards and dialogs; 8px for buttons, inputs, tooltips, info boxes, the banner, and the segmented track; 6px for segmented buttons and icon buttons; 4px for chips and bar segments; 3px for swatches; 999px for badges.
- **Borders:** 1px `--border` everywhere. The table header uses a 1px `--axis` bottom rule. The banner is the only dashed border.
- **Page:** `max-width: 1280px`, centred, with padding `24px 16px 64px`.

### Grid

| Section | Desktop | ≤1000px | ≤560px |
|---|---|---|---|
| KPI row | `1.4fr 1fr 1fr 1fr` | 2 columns | 1 column |
| Chart + allocation | `2fr 1fr` | stacked | stacked |
| Transactions + notes | `1.6fr 1fr` | stacked | stacked |
| Form grid | 2 columns | 2 columns | 1 column |

When grid columns stack, children get `min-width: 0` so wide tables scroll inside `.table-wrap` and don't push the page wider. The page must never scroll horizontally at 390px.

---

## 5. Components

### Buttons
- `.btn`: surface fill, hairline border, 8px radius, padding `7px 12px`, weight 550. Hover switches to `--surface-2`.
- `.btn.primary`: accent fill, white text, no border. Hover is `brightness(1.08)`. **One primary per view:** "Refresh all prices" in the header, and the submit button in a dialog.
- `.btn` with an icon: a 14px inline SVG stroke icon, placed before the label, with `margin-right: 4px`.
- `.icon-btn`: a 28×28 transparent button in `--muted` that gains a surface and border on hover. Adding `.spin` rotates its SVG while work is in flight. It always needs an `aria-label`.
- `.link`: an accent-coloured underlined text button, for low-stakes inline actions such as "Reset sample data".
- Disabled buttons use `opacity: .55` and change their label while working ("Refreshing…").

### Segmented control (`.seg`)
A `--surface-2` track with 2px padding. The selected button gets `--surface` with a 1px border ring. State lives in `aria-pressed`. Use it for mutually exclusive view state: Value / Total return, the range, the grouping, dialog tabs, and transaction type.

### Card (`.card`)
`--surface`, hairline border, 12px radius, 16px padding. A `.card-head` holds the `h2` and a `.sub` line on the left, and controls on the right, and it wraps on narrow screens.

### KPI (`.kpi`)
A label (13px, `--ink-2`), then the value, then a delta (13px, weight 550, coloured by sign), then a foot (12px, `--muted`). The foot says what the number includes or excludes. Examples: "Adjusted for transfers in and out", "Already included in value. Not added on top."

### Tables
- Right-aligned numbers, a left-aligned first column, `white-space: nowrap`, and cell padding of `8px 10px`.
- The header is sticky, on a `--surface` background.
- **Group row** (`tr.group`): a `--surface-2` fill, weight 600, a 10px swatch, a count in `--muted`, and the group's subtotals in the value columns.
- **Two-line cells:** the primary figure, then a 12px `--muted` sub-line (`.inst-sub`) for date, source, or name.
- **Generated cash leg** (`tr.leg`): indented with `↳` and a 🔒 whose title reads "Generated; edit the parent transaction". Text is `--ink-2` at 12.5px.
- Wrap tables in `.table-wrap` so they scroll horizontally inside the card.
- Tables longer than about 10 rows show the latest rows plus a closing line such as "Showing the latest 10 of N".

### Badges
| Class | Look | Meaning |
|---|---|---|
| `.badge.stale` | warning wash + warning ink, `⚠ stale` | Price older than the last trading day. The price text itself also turns `--warning-ink`. |
| `.badge.fail` | critical wash + down, `✕ fetch failed` | Last fetch failed; the last good price is kept |
| `.badge.manual` | surface-2 + border, `manual` | Price was typed. The title attribute holds the entry timestamp. |

### Empty and no-coverage states
`.nocov`: italic `--muted`. Always name the reason: "No coverage", "No coverage · index ETF", "N/A · no analyst consensus for crypto". Cash shows `—`.

### Chart
- Inline SVG. There is one accent line, 2px with round joins, over an `--accent-wash` area in Value mode. Total-return mode has no area and adds a baseline at 0%.
- `--grid` gridlines, an `--axis` baseline, and 11px `--muted` tabular ticks. Y ticks are short money (`₱4.5M`, `₱850k`).
- **Gaps:** a `--surface-2` band labelled "no data". The line breaks across the gap and is never interpolated.
- **Transfers:** a hollow triangle on the baseline (pointing up for in, down for out), plus a dashed `--axis` leader up to the line.
- **Hover:** crosshair, a 4.5px dot with a surface stroke, and a tooltip. The tooltip shows the date, the value, the day change, and a note row for transfers ("Moves value, not return").
- Every chart has a legend and a "View chart data as a table" `<details>` for accessibility.

### Tooltip
`--surface`, hairline border, 8px radius, shadow `0 4px 16px rgba(0,0,0,.10)` (the only shadow in the system), min-width 170px. The date line is 11.5px `--muted`, the value is 14px weight 650, and the note sits below a hairline.

### Info box (`.fx-box`)
A `--surface-2` block at 12.5px in `--ink-2`, with key figures in bold `--ink`. Use it to explain a figure's dependencies, for example the FX rate and sensitivity under the allocation.

### Banner
A dashed `--axis` border at 12.5px in `--ink-2`. Reserved for environment notices ("Mockup with sample data…"). Not for errors.

### Toast
Inverted colours (`--ink` background, `--page` text), 8px radius, fixed bottom-centre. It slides up 20px on show and dismisses after 3.2s. Toasts confirm what was written, in figures: "Sold 5 SOL · realised +$260.00". Failure toasts say what was kept and what to do next.

### Dialog
- Native `<dialog>` with `showModal()`, so Esc closes it and focus is trapped. The backdrop is `rgba(0,0,0,.35)`.
- **Small** (confirmations): max-width 420px, 20px padding. Its purpose is to state the cost of an action before running it: "This will perform 13 lookups: …", plus a privacy line.
- **Large** (`dialog.lg`, entry forms): max-width 620px, with three zones:
  - `.dlg-head`: title, then the tab control, then a hairline.
  - `.dlg-body`: scrolls, with max height `min(64vh, 640px)`.
  - `.dlg-foot`: a hairline, a caption on the left, and Cancel + primary on the right.
- The primary button's label names the action and updates live: "Add asset", "Record sell", "Save 3 prices".

### Forms
- `.form-grid`: 2 columns with a 12px gap. `.full` spans both columns. Fields that don't apply are removed with `hidden`, not disabled.
- `.field` holds, in order:
  - a label (12.5px, weight 550, `--ink-2`), optionally followed by `.opt` in `--muted` ("optional", or the currency code)
  - the `.input`
  - a `.hint` (12px, `--muted`) that says what happens by default ("Defaults to the unit price", "Added to cost basis")
- `.input`: a `--page` fill inside the surface dialog (it reads as inset), hairline border, 8px radius, padding `7px 10px`, min-height 34px, and a 2px accent outline on focus. Numeric inputs get `.num`, `type="number" step="any"`, and `inputmode="decimal"`.
- `.form-section`: an uppercase label with a hairline above it, used to split a form into parts ("Opening buy").
- `.check`: a checkbox and a label, with the hint inside the label. The checkbox uses `accent-color: var(--accent)`.
- **Validation** happens on submit, and the messages are inline:
  - `.field.invalid` turns the border `--down`, and a `.err` line (12px, `--down`) appears below the field.
  - Focus moves to the first invalid field.
  - Messages say what's wrong and what to do: "Already held on BDO Securities. Record a buy instead.", "Only 20 held on Sep 10. A later buy doesn't cover an earlier sale."
- **Preview** (`.preview`): a `--surface-2` block at the bottom of the dialog body that updates on every input. It states what the save will write and what it leaves unchanged: the cash leg, the new average cost, the cash balance after. Warnings inside it use `.warn` (`--warning-ink`, prefixed with ⚠) and name the fix. The block hides itself when empty.
- **New-row flash:** after a save, the affected row fades from `--accent-wash` to transparent over 2.4s (`tr.flash`).

---

## 6. Formatting rules

| Thing | Rule | Example |
|---|---|---|
| Minus sign | U+2212 `−`, never a hyphen | `−₱25` |
| Positive change | explicit `+` | `+₱47,578` |
| Currency | symbol prefix, no space; `₱` for PHP, `$` for USD | `₱912.50`, `$97,840` |
| Base-currency totals | whole pesos | `₱5,953,893` |
| Native values, cash | 2 decimals | `$3,412.55` |
| Unit prices | 2 decimals; 0 if ≥ 1,000; 4 if < 1 | `₱241.60`, `$97,840`, `$0.1834` |
| Quantities | up to 4 decimals (equities), 6 (crypto), no trailing zeros | `0.18`, `2,500` |
| Percent | 2 decimals for returns and KPIs, 1 for allocation and implied upside | `+0.81%`, `56.7%` |
| Dates in UI | `Sep 22` in tables, `Sep 22, 2026` in headers and tooltips | |
| Timestamps | `2026-09-23 08:12` (ISO date, 24h) for "entered at" and "last refreshed" | |
| Separators | a middle dot `·` between metadata items | `Sep 22 · Yahoo Finance` |

---

## 7. Voice

- Short, declarative sentences, in plain words. Say what the figure is and what it excludes.
- Name the source and the date rather than saying "latest" or "current".
- Errors and warnings give the reason and the next step. Never "Something went wrong."
- Describe what was done in the past tense with figures ("Deposit of ₱50,000.00 recorded on BDO Securities"), not "Success!"
- No exclamation marks, and no emoji other than the functional glyphs ⚠ ✕ ▲ ▼ ↳ 🔒.

---

## 8. Accessibility checklist

- Interactive controls are real `<button>`s. Toggle state uses `aria-pressed`.
- Icon-only buttons carry `aria-label` and `title`.
- The chart has `role="img"`, an `aria-label` that updates with the range, and a table alternative.
- The form preview is `aria-live="polite"`.
- Inputs are tied to their labels with `for`/`id`. Price-table inputs, which have no visible label, get `aria-label`.
- Contrast: body text on `--surface` is `--ink`, and secondary text is `--ink-2`. Keep `--muted` for text 12px and up, not for anything a decision depends on on its own.
- Layout is checked at 390px, with no horizontal page scroll.

---

## 9. Screens planned beyond the mockup

The phase epics add screens the mockup doesn't show. Build them from the components above, and mock each one before its story starts. Once a screen is mocked, add it to `dashboard.html` or a sibling mockup, so the mockup stays the source of truth.

| Screen | Epic | Notes |
|---|---|---|
| Import page | [Phase 4](phase-4-epic.md) S2, S10 | Its own page, not a dialog tab. Upload card, summary counts, then a staged-rows table grouped as create / update / unchanged / rejected. One primary button: "Commit N rows". Opened from an "Import file" `.btn` on the holdings card. |
| Import history | [Phase 4](phase-4-epic.md) S9 | A table of past imports with counts, file link, and rollback. |
| `reward` transaction | [Phase 4](phase-4-epic.md) S1 | A `.tx-type` chip like the others. There is no cash leg row, because rewards move no cash. |
| Rating refresh | [Phase 5](phase-5-epic.md) S7 | Uses the small confirmation dialog and the privacy line, as price refresh does. |
| Manual rating form, rating history | [Phase 5](phase-5-epic.md) S5, S8 | The form follows §5 Forms, with an implied-upside preview. |
| Document confirmation | [Phase 6](phase-6-epic.md) S4 | Two panes: the document beside the draft fields. Low-confidence fields use `.warn`, and the preview states what the save writes. |

**Return KPI wording** (PRD v5 §9). The percentage is time-weighted. The delta line shows the peso gain "net of ±₱X transfers". Don't label the percentage as a simple gain over the start value.
