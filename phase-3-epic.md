# Epic: Phase 3 — Value Chart and Total Return

**Parent:** [investment-tracker-prd.md](investment-tracker-prd.md) §17, Phase 3
**Design reference:** [dashboard.html](dashboard.html), [style-guide.md](style-guide.md)
**Owner:** J
**Status:** Not started
**Created:** 2026-09-24

---

## Epic goal

Answer "am I up or down this year" correctly. Portfolio value on any past date is computed from the transactions held on that date, the stored price for that date, and the stored FX rate for that date. Total return removes the effect of deposits and withdrawals, so that money moved in never reads as a gain.

## Why this phase now

Phase 2 made the price series exist. This phase is where the series-based design from PRD §8 pays off. It is also where the dividend and transfer model from Phase 1 is tested for real: a dividend has to appear exactly once, and a deposit has to move value without moving return.

## In scope

PRD 10.4 in full, the dividend income KPI from 10.3, and the total-return rules in PRD §9.

## Out of scope

Benchmark comparison and performance attribution (P2 non-goals). Tax-lot returns. Per-holding return charts.

## Definition of done

- A correct curve renders for a past month that predates first use, reconstructed from backfilled prices and verified by hand at three dates.
- A deposit to IBKR moves the value line and leaves the total-return line flat.
- A taxed dividend appears once in total return, and the dividend KPI labels it as already included in value.
- Editing a mid-history transaction changes the curve from that date forward, and only from that date.

## Open decision (blocks S3)

**Return method.** PRD §9 defines total return as "change in portfolio value over a period, adjusted for transfers in and out." The mockup computes a **time-weighted return**: daily returns chained together, with each day's flow removed. It also shows an absolute gain of end value minus start value minus net transfers. These two figures answer different questions, and they diverge whenever a large deposit lands before a rise or fall.

Recommendation: keep both, as the mockup does. Use time-weighted return for the percentage, because it is what "how did the portfolio do" means and a deposit can't distort it. Use absolute gain net of transfers for the peso figure, because it is what "how much did I make" means. Label each so neither is mistaken for the other. Record the decision in the PRD.

## Sequencing

```
S1 ──► S2 ──► S3 ──┬──► S4 ──► S5 ──► S6 ──► S7 ──► S8
                   └──► S9
S10 closes the phase
```

---

## User stories

### S1 — Daily valuation engine

**As J, I want** portfolio value computed for every date in a range, **so that** the chart is a calculation over the ledger and not a stored number that can drift from it.

**Acceptance criteria**
- [ ] For each date, value equals the sum over holdings of quantity held at end of day × price in effect on that date × FX rate in effect on that date. Cash instruments are included at 1.0.
- [ ] "Price in effect" is the latest close on or before that date, using the Phase 2 precedence rule. Carrying a close forward over a weekend or market holiday is not interpolation.
- [ ] FX is looked up per date. The chart never converts history at today's rate.
- [ ] The output is a series of `(date, value_base, net_external_flow_base, status)`, where status is `ok` or `gap` (see S2).
- [ ] Computation reuses the Phase 1 positions logic (`positions_as_of`) instead of reimplementing quantity math.
- [ ] Nothing is cached across requests unless the cache is keyed on a ledger and price version, so Phase 1 S12's "no stale derived figure" rule still holds.
- [ ] Two years of daily points for the real holding list compute in under 2 seconds.

**Size:** 8

---

### S2 — Gap rule

**As J, I want** dates with genuinely missing price data shown as a break, **so that** a gap reads as missing data instead of a flat portfolio.

**Acceptance criteria**
- [ ] A date is a gap when any non-cash holding held on that date has no price in effect within a tolerance window. Proposed tolerance: 5 trading days for its market.
- [ ] A gap date has no value. It is never zero and never interpolated.
- [ ] Weekends and market holidays are not gaps.
- [ ] The rule is written down with its tolerance, because it decides what the chart shows as missing.
- [ ] Holdings excluded for having no price at all follow the Phase 1 exclusion rule and are listed, not silently dropped.

**Notes:** The mockup treats a gap as portfolio-wide and doesn't say what triggers one. This story defines the trigger.

**Size:** 3

---

### S3 — Transfer-adjusted return

**As J, I want** return figures that exclude money I moved in or out, **so that** a ₱500,000 deposit doesn't read as a ₱500,000 gain.

**Acceptance criteria**
- [ ] The return method is settled per the open decision above and recorded in the PRD.
- [ ] Only external transfers (`is_external_transfer = 1`) count as flows. Generated cash legs, dividends, fees, and internal platform-to-platform transfer pairs (sharing a `transfer_group_id`) do not.
- [ ] USD transfers are converted at the FX rate on the transfer date.
- [ ] Dividends are not added to return. They are already in value through their cash leg.
- [ ] Fees reduce return, since they reduce value and are not a flow.
- [ ] Return across a gap is computed from the last valid value before the gap to the first valid value after it. The gap is never treated as a 0% day.
- [ ] Unit tests cover: a deposit on a flat day (return 0%), a withdrawal, a taxed dividend (counted once), an internal transfer (no effect), and a range that starts inside a gap.

**Size:** 5

---

### S4 — Value chart

**As J, I want** a line chart of portfolio value in base currency, **so that** I can see the shape of the last year at a glance.

**Acceptance criteria**
- [ ] Rendered to the style guide's chart spec: one 2px accent line over an `--accent-wash` area, `--grid` gridlines, 11px tabular ticks, and short-money Y labels (`₱4.5M`).
- [ ] The line breaks across gap dates, and each gap draws a `--surface-2` band labelled "no data".
- [ ] X ticks fall on month boundaries (week boundaries in 1M), thinned to fit the width.
- [ ] The card title and sub-line read "Portfolio value" and "{start} to {end} · computed from transactions × stored price series".
- [ ] The legend shows the value line, the transfer marker, and the gap swatch.
- [ ] The chart redraws on resize, and is 240px tall under 560px.
- [ ] The series is computed server-side. The browser only draws it.

**Notes:** PRD §6 names Chart.js. The style guide and the mockup use hand-drawn inline SVG, and the style guide says the mockup wins. Recommendation: follow the mockup. The gap bands, transfer triangles, and tooltip note rows are custom work in either library, and the mockup's renderer is already about 150 lines. Update PRD §6 to match.

**Size:** 5

---

### S5 — Total return mode

**As J, I want** to switch the chart to total return, **so that** I can see performance with deposits and withdrawals removed.

**Acceptance criteria**
- [ ] A `Value / Total return` `.seg` control switches the mode.
- [ ] Return mode plots cumulative return from the range start, with a 0% baseline, no area fill, and percent ticks.
- [ ] The title, legend ("Total return, transfer-adjusted"), and `aria-label` update with the mode.
- [ ] Across a deposit, the return line shows no step. Verified with a test fixture.

**Size:** 3

---

### S6 — Range selector

**As J, I want** 1M, YTD, 1Y, and All ranges, **so that** I can answer "this month", "this year", and "since I started".

**Acceptance criteria**
- [ ] A `.seg` control with `1M`, `YTD`, `1Y`, and `All`, defaulting to `1Y`.
- [ ] YTD starts from the prior year's final value (Dec 31), so the first day of the year has a return.
- [ ] All starts at the first transaction date.
- [ ] The chosen range and mode persist between sessions in `app_settings`, as grouping does.
- [ ] The range name appears in the KPI labels ("Total return · 1 year").

**Size:** 2

---

### S7 — Transfer markers

**As J, I want** deposits and withdrawals marked on the chart, **so that** a step in the value line is explained rather than looking like a data error.

**Acceptance criteria**
- [ ] Each external transfer draws a hollow triangle on the baseline: pointing up for in, down for out. A dashed `--axis` leader runs from the triangle to the line.
- [ ] Same-day transfers merge into one marker with their notes joined.
- [ ] Internal platform-to-platform pairs are not marked.
- [ ] A transfer dated inside a gap still gets its marker.

**Size:** 3

---

### S8 — Tooltip and table alternative

**As J, I want** to hover a date and see its value and anything that happened on it, **so that** I can check a single point against a statement.

**Acceptance criteria**
- [ ] Hovering or tapping shows a crosshair, a dot, and a tooltip with the date, the value, and the day's change in Value mode, or the return since range start in Return mode.
- [ ] On a transfer date, the tooltip adds a note row with the amount and "Moves value, not return" or "Excluded from return".
- [ ] On a gap date, the tooltip reads "No price data. Missing, not flat. Refetching backfills this range."
- [ ] A "View chart data as a table" `<details>` lists month-end points, with gaps shown as "no data".
- [ ] The chart has `role="img"` and an `aria-label` that updates with the range and mode.

**Size:** 3

---

### S9 — Return and dividend KPIs

**As J, I want** total return and dividend income shown as KPIs for the selected range, **so that** the headline figures and the chart agree.

**Acceptance criteria**
- [ ] The Total return KPI shows the percentage from S3, then the absolute gain with "net of {±transfers} transfers", then a foot reading "Adjusted for transfers in and out".
- [ ] The Dividend income KPI shows net dividends in base currency for the range, the payment count, and total withheld tax. Its foot reads "Already included in value. Not added on top."
- [ ] Dividends are converted at the FX rate on their payment date.
- [ ] The Unrealised gain/loss KPI shows gain over cost, excluding cash, with the percentage on cost.
- [ ] KPI figures reconcile exactly with the chart's first and last points for the same range.

**Notes:** The Unrealised G/L KPI is a mockup addition not listed in PRD 10.3. It is cheap and useful, and kept here.

**Size:** 3

---

### S10 — Phase verification

**As J, I want** the curve checked against hand-computed values, **so that** the chart is trusted for the right reason.

**Acceptance criteria**
- [ ] Three past dates predating first use are valued by hand from statements and stored prices, and match the chart to the peso.
- [ ] A real deposit is checked: the value line steps, the return line does not.
- [ ] A real taxed dividend is checked to appear once.
- [ ] A mid-history transaction edit is made and reverted. The curve changes from that date forward and then returns exactly to the original.
- [ ] Results are written into [docs/reconciliation.md](docs/reconciliation.md) next to the Phase 1 baseline.

**Size:** 3

---

## Total: 10 stories, 38 points

## Prototype alignment

**Covered by the mockup and followed here:** the Value/Total return toggle; the 1M/YTD/1Y/All selector; transfer triangles with leaders; gap band and broken line; tooltip with transfer and gap notes; table alternative; the three KPIs, with feet that state what is included; a dividend KPI tied to the chart range.

**Differences from the mockup:**
- **Chart library.** PRD §6 says Chart.js. The mockup and style guide use inline SVG. This epic follows the mockup and asks for the PRD to be updated.
- **Return method.** The mockup's time-weighted percentage is not what PRD §9's wording describes. This is flagged above as a decision to make, not silently adopted.
- **Gap trigger.** The mockup hard-codes a gap week. S2 defines the rule that produces one.
- **FX.** The mockup converts all history at one rate. S1 converts each date at its own rate.

**Not in the mockup:** nothing blocking. The chart card is the most fully specified part of the design.

## Risks carried into this phase

- **Return method ambiguity.** Choosing the method after the UI is built means relabelling every figure. Decide before S3.
- **Internal transfers counted as flows.** A move from IBKR to Kraken would show as a withdrawal and a deposit, with zero net effect on value but two markers and noise in the return. S3 and S7 exclude these pairs.
- **Performance.** Recomputing positions per day over two years is the slowest query in the app. S1 sets a budget, and caching is allowed only with ledger versioning.
