# Epic: Phase 2 — Fetch Layer

**Parent:** [investment-tracker-prd.md](investment-tracker-prd.md) §17, Phase 2
**Design reference:** [dashboard.html](dashboard.html), [style-guide.md](style-guide.md)
**Owner:** J
**Status:** Not started
**Created:** 2026-09-24

---

## Epic goal

Replace typing prices by hand with on-click lookups for every instrument a source covers. Each lookup pulls history, not only the latest quote. A failed lookup keeps the last good data and says so. Manual entry from Phase 1 stays as the fallback for anything no source covers.

## Why this phase now

The value chart in Phase 3 needs a price series for every date it draws. PRD §8 says the series has to be backfilled from a source, because history that only accumulates from app opens has permanent holes. Phase 3 cannot start until this phase can fill a year of history for a new instrument.

## In scope

PRD 10.2 (fetch portions), the refresh controls in 10.3, and the privacy boundary in §12. Kraken and US equities come first. PSE coverage is either resolved or formally handed to manual entry.

## Out of scope

The value chart and total return (Phase 3). CSV import (Phase 4). Rating lookups (Phase 5), even though they use the same fetch adapter pattern. Scheduled or background refresh, which is a PRD non-goal.

## Definition of done

- A fetch on a new instrument stores enough daily history to chart the prior year.
- A deliberately broken response (timeout, HTTP error, malformed body, zero or negative price) leaves existing data untouched and marks the row as failed.
- A full refresh across all holdings finishes in under 30 seconds (PRD §13).
- No outbound request contains a quantity, cost, total, or platform name. This is verified by logging request URLs and bodies in a test.
- The Phase 1 reconciliation baseline ([docs/reconciliation.md](docs/reconciliation.md)) still matches when run on the same manual prices.

## Sequencing

```
S1 ──┬──► S2 ──┐
     ├──► S3 ──┼──► S6 ──► S7 ──► S8 ──► S9 ──► S12
     ├──► S4 ──┘                          ▲
     └──► S5 (spike, run first in parallel)│
S10 (any time) ────────────────────────────┘
S11 (any time after S1)
```

---

## User stories

### S1 — Fetch adapter contract and source mapping

**As J, I want** each instrument mapped to a named price source through one adapter interface, **so that** adding or swapping a source never touches valuation code.

**Acceptance criteria**
- [ ] One adapter interface: given a symbol and a date range, it returns dated closes in the instrument's native currency, or a typed failure.
- [ ] Each instrument stores its source and the symbol that source uses (for example `XBTUSD` on Kraken, `SM.PS` or the PSE code for BDO holdings). The symbol is separate from the display ticker.
- [ ] Instruments with no source are marked `manual only`. They are skipped by refresh and never counted as lookups.
- [ ] Requests carry the symbol and date range only. A test asserts that no quantity, cost, total, account, or platform name appears in any request (PRD §12).
- [ ] Every stored row records `source` and `fetched_at`. `price_date` is the date the close refers to, not the fetch date.
- [ ] Network timeouts are bounded per request, so one slow source can't stall a refresh-all.

**Notes:** The prices table is unique on `(instrument_id, price_date, source)`, so fetched and manual prices for the same date can coexist. S7 decides which one wins.

**Size:** 3

---

### S2 — Kraken OHLC fetch with backfill

**As J, I want** crypto prices from Kraken's public OHLC endpoint with history, **so that** my Kraken holdings value themselves and chart from day one.

**Acceptance criteria**
- [ ] Uses the public OHLC endpoint, with no API key and no account authentication.
- [ ] First fetch for an instrument backfills daily closes back to the instrument's first transaction date, or at least 365 days.
- [ ] Later fetches request only the dates after the last stored close, plus a small overlap to catch revised closes.
- [ ] The daily close is taken at a fixed, documented UTC cut-off, and that cut-off is applied the same way on every fetch.
- [ ] Stablecoin-quoted pairs are resolved to a USD price, or rejected with a stated reason. They are never silently treated as 1:1.

**Notes:** Kraken returns about 720 candles per request. A year of dailies fits in one call, but "all time" for a 2021 position does not, so the adapter has to page.

**Size:** 3

---

### S3 — US equity and ETF fetch with backfill

**As J, I want** IBKR holdings priced from a US market data source with history, **so that** the largest-covered part of the portfolio needs no typing.

**Acceptance criteria**
- [ ] Source chosen and written down, with its terms, rate limits, and whether it needs a key. `[VERIFY: the mockup shows "Yahoo Finance"; its unofficial endpoints change without notice. Pick a source with a documented API, or accept the breakage risk in writing.]`
- [ ] Backfill works the same way as S2: to the first transaction date, or at least 365 days.
- [ ] Split-adjusted and unadjusted closes are not mixed in one series. The choice is documented and applied everywhere.
- [ ] A holding outside US listings is refused at mapping time with a clear message, because it reopens the FX surface (PRD §16, first open question).

**Size:** 3

---

### S4 — USD/PHP FX fetch with backfill

**As J, I want** the USD/PHP rate fetched as a dated series, **so that** USD holdings convert at the rate for the date being valued, not today's rate.

**Acceptance criteria**
- [ ] FX series fetched into `fx_rates` with source and `fetched_at`, backfilled over the same span as prices.
- [ ] The table stays a general pair series. USD/PHP is data, not a column name.
- [ ] Refresh-all always includes one FX lookup per pair in use.
- [ ] The header and the allocation FX box show the pair, the rate, its date, and its source (mockup: `USD/PHP 58.42 · Sep 22`, `exchangerate.host`).
- [ ] If the FX fetch fails, the total still renders on the last good rate, and the FX date shown makes the age visible.

**Notes:** `[VERIFY: exchangerate.host, shown in the mockup, now requires an API key. The BSP reference rate is an alternative for PHP.]`

**Size:** 3

---

### S5 — PSE coverage spike and decision

**As J, I want** a tested answer on whether my BDO holdings can be fetched, **so that** the PH side of the dashboard isn't built on an assumed source.

**Acceptance criteria**
- [ ] Every current BDO Securities holding is tested against at least two candidate sources for a current close and 12 months of history.
- [ ] The result is written down per ticker: covered, partial (gaps or delays), or not covered.
- [ ] Decision recorded: build a PSE adapter for the covered tickers, or mark BDO holdings `manual only`.
- [ ] If manual, the Phase 1 bulk price entry is checked against the real BDO holding list. Entering a week of prices has to take under two minutes.

**Notes:** PRD §14 names this as the least certain input in the whole document. The mockup labels BDO prices "PSE feed" as if the source exists. Run this spike first, in parallel with S1, because its answer changes how much of S6–S10 applies to a third of the portfolio.

**Size:** 2

---

### S6 — Failed fetch keeps last good data

**As J, I want** a failed lookup to leave my existing prices alone and say it failed, **so that** a broken source never blanks or zeroes a value.

**Acceptance criteria**
- [ ] Timeouts, HTTP errors, malformed bodies, empty results, and zero or negative prices are all treated as failures. Nothing from a failed response is written.
- [ ] A partial response (some dates valid, some not) writes only the valid dates and reports the rest as failed.
- [ ] The row shows the last good price with the `✕ fetch failed` badge. The badge title says the last good price was kept.
- [ ] The failure reason is kept on the instrument until the next successful fetch, so it survives a page reload.
- [ ] The failure toast names what was kept and what to do next, for example "AREIT: no price returned. Kept last good price from Sep 15. Enter it manually if needed."
- [ ] A test feeds each broken-response type to each adapter and asserts the prices table is byte-identical afterwards.

**Size:** 3

---

### S7 — Price precedence between sources

**As J, I want** a clear rule for which price is used when a date has both a manual and a fetched price, **so that** a correction I typed isn't silently replaced by the next fetch.

**Acceptance criteria**
- [ ] Rule written down and enforced in one place. Proposed rule: for a given date, a manual price wins over a fetched one, and among fetched prices the most recent `fetched_at` wins.
- [ ] A refetch that returns a different close for an existing date updates it and writes a `price_revisions` row, as manual edits already do.
- [ ] The price cell shows which source supplied the price in use (`Sep 22 · Kraken OHLC`, or the `manual` badge with the entry time in its title).
- [ ] J can remove a manual override so the fetched price takes effect again.

**Notes:** `_latest_price` in [positions.py](portfolio/positions.py) currently orders by `fetched_at` only. That makes whichever row was written last win, which becomes the wrong rule once fetches run.

**Size:** 3

---

### S8 — Per-holding refresh

**As J, I want** a refresh button on each holding row, **so that** I can update one price without running every lookup.

**Acceptance criteria**
- [ ] A 28×28 `.icon-btn` in the last column of each non-cash row, with an `aria-label` of "Refresh {ticker} price". It spins while the lookup is in flight.
- [ ] `manual only` instruments show no refresh button, or show a disabled one whose title explains why.
- [ ] On success, the row updates in place and flashes. The toast reads "{ticker} refreshed · {source}".
- [ ] The header's "Prices last refreshed" timestamp updates.

**Size:** 2

---

### S9 — Refresh all with lookup count

**As J, I want** refresh-all to tell me how many lookups it will run before it runs them, **so that** I know what's about to go out over the network.

**Acceptance criteria**
- [ ] Clicking "Refresh all prices" opens the small confirmation dialog. It states the lookup count and breaks it down by source, plus the FX lookups (mockup: `confirmDlg`).
- [ ] The count includes only real network lookups. `manual only` instruments are listed separately as "skipped, manual only" and are not counted.
- [ ] The dialog carries the privacy line: "Requests contain tickers only. No quantities, costs or totals leave this machine."
- [ ] Lookups run concurrently, with a per-source concurrency cap that respects rate limits.
- [ ] The whole refresh completes in under 30 seconds for the real holding list (PRD §13), measured and recorded.
- [ ] The result toast states successes out of total and names every holding that kept its last good price.

**Size:** 3

---

### S10 — Staleness per market calendar

**As J, I want** "stale" to mean "older than that market's last trading day", **so that** crypto isn't marked fresh on Monday with Friday's price and PSE isn't marked stale on a PH holiday.

**Acceptance criteria**
- [ ] Each asset class maps to a calendar: crypto trades every day, US equities and ETFs use the NYSE calendar, PH equities use the PSE calendar.
- [ ] Market holidays are handled. A hand-maintained holiday list per market is acceptable. `[VERIFY: source for the PSE holiday list]`
- [ ] Stale rows show the `⚠ stale` badge, and the price text turns `--warning-ink`.
- [ ] The holdings sub-line reads either "⚠ N stale" or "all prices current as of {date}".
- [ ] The FX rate has its own staleness check against the FX source's publishing days.

**Notes:** `last_trading_day()` in [positions.py](portfolio/positions.py) skips weekends only, and applies one rule to everything. The mockup also uses a single `LAST_TRADING_DAY`. Both are wrong for crypto.

**Size:** 3

---

### S11 — Dashboard shell brought to the mockup

**As J, I want** the Flask dashboard to use the mockup's layout, tokens, and components, **so that** the fetch states in this phase render the way the design specifies.

**Acceptance criteria**
- [ ] The full token set from [style-guide.md](style-guide.md) §2 is used, including dark mode and the `data-theme` toggle. The hard-coded `#fff8e8` stale fill is removed.
- [ ] The header has the title, then a meta line (base currency, FX pair with rate and date, prices last refreshed), then the actions: Theme, Add, and the primary "Refresh all prices" button.
- [ ] The hero KPI shows the total, today's change with sign and arrow, and a foot stating the FX rate used.
- [ ] The allocation card has the stacked bar, the list, and the FX info box with USD share and rate sensitivity.
- [ ] The holdings table follows the mockup's columns, group rows, two-line cells, and the `stale`, `fail`, and `manual` badges.
- [ ] Formatting follows style-guide §6: `₱` and `$` prefixes, U+2212 minus, whole pesos for base totals.
- [ ] Grouping uses the `.seg` control with `aria-pressed` instead of two primary buttons, so the view keeps one primary action.
- [ ] Checked at 390px with no horizontal page scroll.

**Notes:** Phase 1 shipped a working but simplified dashboard: no KPI row, no allocation card, `PHP 1,234.00` formatting, 960px width. The rating column and the chart card are left as placeholders here and filled by Phases 3 and 5.

**Size:** 5

---

### S12 — Phase verification

**As J, I want** the definition of done checked on real holdings, **so that** Phase 3 starts from a verified series.

**Acceptance criteria**
- [ ] A new instrument added and fetched shows 365 days of stored closes.
- [ ] Each broken-response test from S6 passes against the real adapters, with the network mocked.
- [ ] A refresh-all on the real holding list is timed and comes in under 30 seconds.
- [ ] The Phase 1 reconciliation re-run on manual prices gives the same total.
- [ ] Request logs from one full refresh are reviewed for leaked position data.

**Size:** 2

---

## Total: 12 stories, 35 points

## Prototype alignment

**Covered by the mockup and followed here:** per-row refresh icon with spin state; refresh-all confirmation with a per-source count and privacy line; `stale`, `fetch failed`, and `manual` badges; a price cell showing date and source; "Prices last refreshed" and FX in the header; the FX info box; failure toasts that name what was kept.

**Differences from the mockup:**
- The mockup counts `manual only` instruments as lookups ("No source, manual only: N" inside "This will perform N lookups"). S9 excludes them from the count, since they make no request.
- The mockup assumes a working "PSE feed". S5 treats that as unproven, per PRD §14.
- The mockup uses one last-trading-day for every market. S10 splits it by calendar.

**Not in the mockup and needs a design decision:**
- How a first fetch that backfills a year of history shows its progress.
- Where J sets or edits an instrument's source symbol. This is probably a field on the instrument form.

## Risks carried into this phase

- **PSE coverage** (PRD §14). S5 settles it before the other stories depend on it. If BDO holdings end up manual, the dashboard total is only as fresh as the last bulk entry. The staleness badges have to make that obvious.
- **Unofficial data sources.** A source that changes shape without notice shows up as a failed fetch, not a wrong price. That is acceptable only because S6 holds.
- **Precedence bugs** (S7). A fetch that overwrites a manual correction is a quiet error that surfaces months later in a reconciliation.
