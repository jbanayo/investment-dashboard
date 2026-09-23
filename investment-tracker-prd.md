# Product Requirements Document: Local Portfolio Dashboard

**Status:** Draft v4
**Owner:** J
**Last updated:** 2026-09-23

*Changes from v3: the three open questions are answered. Platforms are known (Kraken, BDO Securities, IBKR), dividends are in scope as part of return, and the stack is decided (Flask). Each answer has been carried through the sections it affects rather than left in section 14.*

---

## 1. Summary

A standalone, local application that consolidates holdings across every platform J uses — PH equities at BDO Securities, US equities at IBKR, crypto at Kraken — into one dashboard. It shows what is held, what it is worth now in a configurable base currency, how that changed today, and how total portfolio value and total return have moved over time.

Market data is fetched on demand, when J clicks, and never on a schedule. Analyst rating, consensus, and target price are shown per holding where a source covers it, pulled either from a live lookup or from a broker research document J uploads.

The dashboard is the product. Everything else in this document exists to keep the numbers on it correct.

## 2. Problem Statement

Positions sit across three platforms in two currencies with no combined view. Total net worth in investments is a manual exercise across several apps, so it gets done rarely and is wrong in between. Position-level context — what analysts rate a stock, what the target price is — lives in yet another set of places.

There is also no record of portfolio value over time. Without daily or at least regular valuation history, "am I up or down this year" is unanswerable, and it stays unanswerable until the history starts being kept. Dividends compound the problem: income received in the past leaves no trace in a price-only view, so a portfolio can look flat while having actually paid out.

## 3. Goals

- One local dashboard listing every holding across all platforms and asset classes, valued in a configurable base currency (default PHP).
- Total portfolio value, plus today's change in value and percent.
- A portfolio value chart covering as much history as the data allows, reaching a full year and beyond, with a total-return view that includes dividend income.
- Per-holding current market value that updates when prices are refreshed, with the price timestamp visible next to it.
- Analyst rating, consensus, and target price where coverage exists, with uncovered holdings marked as uncovered rather than blank.
- Every figure traceable to a dated source: a manual entry, a fetch, a parsed export, or an uploaded document.

## 4. Non-Goals

- **No automated trading.** The app never places orders.
- **No brokerage API integrations.** Positions are entered manually, or read from statement and activity files J exports and hands to the app. Nothing authenticates to a broker.
- **No remote access.** Local machine only, no tunnel, no hosting.
- **No scheduled background jobs.** All fetching is user-triggered.
- **No real-time or streaming quotes.** End-of-day granularity.
- **No price prediction or AI-generated buy/sell verdicts.** Ratings shown are third-party analyst data with attribution, not model output. A generated verdict would be the least reliable number on a screen full of sourced ones.
- **No multi-user, auth, or sharing.**
- **No tax reporting** in v1, though the transaction model must not preclude it. Withholding tax is captured per dividend because the cash arrives net and the ledger has to balance, not because the app computes a tax position.
- **No performance attribution or benchmark comparison** in v1. Total return against a benchmark is a P2 question; getting own-portfolio return correct comes first.

## 5. User and Scope

Single user (J). Product owner writing this himself, taking on the build hands-on. Comfortable with CLI and local tooling. No existing app or schema to extend; this starts from zero.

**Platforms in scope at v1:**

| Platform | Asset classes | Native currency | Price source outlook | Export format |
|---|---|---|---|---|
| BDO Securities | PH equities (PSE-listed) | PHP | Weakest. Free programmatic PSE coverage is the open risk `[VERIFY]` | PDF statements only → OCR, P2 |
| IBKR | US equities, ETFs | USD | Strong. US listings are the best-covered instruments that exist | Flex Query / activity statement CSV → structured parse, P1 |
| Kraken | Crypto | USD (and USD-quoted stablecoin pairs) | Strong. Public OHLC endpoint, free, no key, with history | Ledger and trade history CSV → structured parse, P1 |

This table is the most load-bearing addition in v4. It says the fetch layer is not one problem but three, of very different difficulty, and it says the statement-import problem is only hard for one platform.

**Currency consequence.** Two currencies, one pair. Every holding is PHP-native or USD-native, so v1 needs USD→PHP and nothing else. That collapses the FX surface to a single series and makes the reconciliation risk in section 13 tractable. It stops being true the moment a third currency appears, so the FX table is still built as a general pair series, not a single USD/PHP column.

## 6. Stack — Decided

Nothing here was inherited, so v3 carried proposals. v4 decides.

**Storage: SQLite.** The one choice that is expensive to reverse. A single file, no server, trivially backed up, and adequate for one user's transaction and price history for decades.

**Backend and UI: Python, Flask, server-rendered templates, Chart.js for the value graph.** Suits a dashboard with CRUD forms and file upload, and keeps the whole thing one process serving `localhost`.

**Streamlit was the alternative and is now rejected.** It reaches a working dashboard with charts and file upload in a fraction of the code. The cost is that transaction entry and editing forms are awkward in it, and this app is half forms — and the dividend handling in section 7 adds a confirm-before-write step to almost every input path, which is exactly the interaction Streamlit's rerun model handles worst. This is a tool meant to be used daily for years, so the form ergonomics matter more than the first week of build speed.

The SQLite schema remains portable, so the decision stays cheap to revisit if the Flask UI proves slower to build than expected. The schema still lands first.

## 7. How Data Gets In

Four input paths, and they are not competing options for the same job. Each fills different fields.

| Path | Fills | Trigger | Priority |
|---|---|---|---|
| Manual entry | Transactions, positions, cost basis, and prices for anything unfetchable | Always available | P0 |
| Live fetch on click | Current and historical prices, FX rates, analyst rating / consensus / target price where covered | Button per holding, or refresh-all | P0 for prices, P1 for ratings |
| Structured file import | Transactions and positions from IBKR Flex Query CSV and Kraken ledger CSV | On upload | P1 |
| Document upload with OCR | Analyst rating and target price from broker research PDFs; BDO positions from PDF statements | On upload | P1 for research docs, P2 for statements |

Manual entry is the only path that cannot be skipped, so it is built first and every other path writes into the same tables it does.

**Two timestamps, never one.** Any manually entered, imported, or uploaded figure stores both the date the figure refers to and the moment it was entered. Collapsing these is how a three-week-old price silently becomes "current value."

**Structured import is not OCR and should not be priced like it.** Knowing the platforms changes this. IBKR and Kraken both export machine-readable CSV with stable columns — a parser for each is a day of work, is deterministic, and either reads a row correctly or fails loudly. That covers two of three platforms and most of the transaction volume, which is why it is P1 and sits ahead of ratings in the phase order. Each import is still keyed on a broker-supplied transaction id so that re-importing an overlapping date range updates rather than duplicates.

**On the OCR question.** Splitting it in two changes the answer, and the platform list sharpens both halves. OCR of broker *research documents* is worth building, because for PH equities the analyst rating and target price genuinely live in PDFs issued to clients and are not reliably on the open web `[VERIFY: check what PSE-listed coverage a live lookup actually returns before committing to the live path for PH names]`. OCR of broker *statements* now applies to BDO Securities alone, since IBKR and Kraken are handled by the import path above. It stays P2, and when built, it produces a draft that J confirms field by field before anything is written. A confidently mis-parsed quantity is worse than a typed one.

**On "automatically."** With no scheduler, market value updates when prices are refreshed on click, not continuously. Every value on the dashboard carries its price date, and anything older than the last trading day is visibly marked stale.

## 8. The Value History Problem

Today's change needs yesterday's price. The year chart needs a year of them. If history accumulates only from app opens, then the chart has holes wherever J didn't open the app, and a month away leaves a permanent gap that cannot be repaired later.

The fix is to store price *series* rather than latest price. On a fetch, pull available history for that instrument, not just the current quote. Portfolio value on any past date is then computed from transactions held on that date multiplied by the stored price for that date, which means:

- The chart works from day one instead of taking a year to become useful.
- Skipping the app for a month costs nothing; the next fetch backfills.
- Correcting a wrong transaction retroactively corrects the whole curve.

This is the single most consequential design decision in the document, and getting it wrong is unrecoverable.

Note what backfill does *not* fix: prices can be recovered from a source months later, but a dividend that was received and never recorded cannot be. Nothing on the open web knows what landed in J's BDO account. Transaction history is the one thing that has to be entered close to when it happens, which is the argument for the CSV import path carrying as much of that burden as possible.

## 9. Dividends and Total Return

Dividends are in scope as part of return. That answer is cheap to give and easy to implement wrongly, so the rule is stated once here and referenced everywhere else.

**The double-counting trap.** A dividend is income *and* it becomes cash. Count both and return is overstated by exactly the dividend. Count neither correctly and a portfolio that pays out looks like one that went nowhere. The fix is to make dividends flow through the ledger rather than be added on top of it:

1. A `dividend` transaction records gross amount, withholding tax, and net amount, against the instrument that paid it.
2. That transaction automatically credits the net amount to the platform's cash instrument. The cash leg is generated, not typed, so it cannot be forgotten or entered twice.
3. Portfolio value is the market value of everything held, cash instruments included. Dividends therefore appear in the value line the day they land, by the ordinary path, with no special case.
4. Money moving in or out of the household — a deposit to IBKR, a withdrawal from Kraken — is a `transfer`, and transfers are the only thing that changes invested capital.

**Total return** is then the change in portfolio value over a period, adjusted for transfers in and out. Cumulative dividend income stays available as its own figure, read off the dividend transactions, and is displayed as income — never added to value, because it is already in there.

**Withholding tax is not optional to model.** J is PH-resident holding US equities through IBKR, so US dividends arrive with tax already deducted, and PH dividends arrive net as well. If the ledger records gross, the cash balance drifts from the broker's by the tax every single payment. Gross, tax, and net are three stored fields; the cash leg uses net.

`[VERIFY: confirm how Kraken staking or reward income should be modelled — as dividend-type income at the value on receipt, or as a quantity increase with zero cost basis. The two produce different cost bases and different total-return curves, and the answer depends on what J actually holds.]`

## 10. Requirements

### P0 — no dashboard without these

**10.1 Instruments and transactions**
- [ ] Instrument record: name, ticker, asset class (ph_equity / us_equity / crypto / etf / fund / cash / other), platform, native currency, sector, notes.
- [ ] Transactions as the source of truth: buy, sell, dividend, fee, transfer, with date, quantity, unit price, fees, currency.
- [ ] Position quantity and average cost are computed from transactions, never stored as an editable number.
- [ ] A partial sell leaves remaining quantity and average cost correct.
- [ ] Editing or deleting a past transaction recomputes every derived figure, including historical portfolio value.
- [ ] A dividend transaction stores gross, withholding tax, and net, and generates a cash leg for the net amount against the platform's cash instrument per section 9.
- [ ] Generated cash legs are visible, traceable to their parent transaction, and cannot be edited independently of it.

**10.2 Prices and FX**
- [ ] Price series per instrument: date, price, native currency, source, fetched_at.
- [ ] FX rate series per currency pair against base currency, same structure. v1 populates USD/PHP; the table stays general.
- [ ] Manual price entry for any instrument no source covers, storing both the price date and the entry timestamp.
- [ ] A failed fetch leaves the last good data in place and marks it stale. It never blanks a value or writes a zero.
- [ ] Base currency is a config value, defaulting to PHP.

**10.3 Dashboard**
- [ ] Total portfolio value in base currency, with today's change in absolute terms and percent.
- [ ] Every holding listed with quantity, average cost, last price and its date, market value in base and native currency, unrealised gain/loss, and allocation percent.
- [ ] Grouping togglable by platform and by asset class, each group showing its own subtotal and share of the whole.
- [ ] Per-holding refresh button and a refresh-all that states how many lookups it will perform before running.
- [ ] Stale prices visually distinct from current ones.
- [ ] Cumulative dividend income displayed for the selected period, labelled as income already included in value.

**10.4 Value chart**
- [ ] Portfolio value over time in base currency, computed from transactions joined to the price series.
- [ ] Total-return view: value change adjusted for transfers in and out, so a deposit does not read as a gain.
- [ ] Transfers in and out marked on the chart, since an unexplained step in the line is indistinguishable from a data error.
- [ ] Range selector covering month, year to date, year, and all time.
- [ ] Dates with no price data shown as a break in the line rather than interpolated, so a gap reads as missing data instead of a flat portfolio.

### P1 — the context layer

**10.5 Structured file import**
- [ ] Import IBKR Flex Query / activity statement CSV into transactions.
- [ ] Import Kraken ledger and trade history CSV into transactions.
- [ ] Rows are keyed on the broker's own transaction id, so re-importing an overlapping range updates instead of duplicating.
- [ ] Anything the parser cannot map to a known instrument or transaction type is surfaced as a rejected row, never silently dropped.
- [ ] Import produces a summary — rows read, rows applied, rows rejected — before it commits.

**10.6 Ratings and target prices**
- [ ] Per instrument: analyst rating or consensus, target price with its currency, source name, and the date the rating was issued.
- [ ] Implied upside against the current price, computed locally.
- [ ] Instruments with no coverage display "no coverage" explicitly. Crypto has no analyst consensus in this sense and should say so rather than show an empty cell.
- [ ] Ratings are never overwritten; a new rating appends, so the previous one and its date remain visible.

**10.7 Research document upload**
- [ ] Upload a PDF or image of a broker research note, extract issuer, subject instrument, rating, target price, and date.
- [ ] Extracted values are presented as a draft for confirmation before they are stored.
- [ ] The source file is retained and linked from the rating, so any figure can be checked against the original.

**10.8 Position notes**
- [ ] Free-text dated notes per instrument, for recording why a position was opened, held, or trimmed.

### P2 — later, but not designed out

BDO statement OCR for bulk position import, a structured decision log linking notes to ratings and subsequent outcomes, tax lot tracking, benchmark comparison, CSV export, alerts on target-price crossings.

## 11. Data Model

**instruments** — id, name, ticker, asset_class, platform, native_currency, sector, notes

**transactions** — id, instrument_id fk, type, trade_date, quantity, unit_price, fees, currency, gross_amount, tax_withheld, net_amount, parent_transaction_id fk nullable, external_id nullable, source_type (manual / import / document), note, entered_at

**prices** — id, instrument_id fk, price_date, price, currency, source, fetched_at

**fx_rates** — id, base_currency, quote_currency, rate_date, rate, source, fetched_at

**ratings** — id, instrument_id fk, issuer, rating, target_price, target_currency, issued_date, source_type (fetch / document / manual), document_id fk nullable, recorded_at

**documents** — id, filename, stored_path, uploaded_at, doc_type, extraction_status, raw_text

**notes** — id, instrument_id fk, note_date, body, created_at

Three fields carry the v4 decisions. `tax_withheld` and `net_amount` let a dividend balance against the cash the broker actually credited. `parent_transaction_id` links a generated cash leg to the dividend or trade that produced it, so the pair is edited and deleted as a unit. `external_id` is the broker's own identifier, unique per platform, and it is what makes re-importing an overlapping CSV range idempotent.

Positions, portfolio totals, and the value chart are all computed views over these tables. Cash is an instrument with asset_class `cash`, one per platform per currency, so cash ratio and total assets need no special case — and IBKR holding both USD and PHP cash is handled by the same rule.

## 12. Privacy Boundary

Position sizes, cost basis, platform names, totals, and notes stay on the machine. Nothing is sent anywhere to render the dashboard.

Two operations reach the network, both user-triggered. Price and FX lookups disclose which instruments are held, though not how much. Rating lookups do the same. Neither request may include quantity, cost, or portfolio context, and any response referring to position size means the request leaked.

Two operations that look like network operations are not. Structured file import and document OCR should run locally where the tooling allows, since broker statements, IBKR activity files, and research notes carry account numbers and names. An IBKR Flex Query CSV is a more sensitive file than anything else this app will touch; it should never leave the machine to be parsed.

## 13. Success Criteria

- Total portfolio value matches a hand-built spreadsheet check across BDO Securities, IBKR, and Kraken, on the same prices, to the peso.
- A partial sell followed by a re-buy produces the correct average cost and unrealised gain, verified by hand.
- A dividend with withholding tax leaves a cash balance matching the broker's to the centavo, and appears exactly once in total return.
- The value chart renders a correct curve for a past month that predates first use, reconstructed from backfilled prices.
- A deposit to IBKR moves the value line and leaves the total-return line flat.
- Re-importing the same IBKR CSV twice changes no figure on the dashboard.
- Every value on the dashboard shows a price date, and no stale value is presented as current.
- A full refresh across all holdings completes in under 30 seconds.
- Opened on at least 10 of any 14 consecutive days, three weeks after the dashboard ships.

## 14. Risks

**PH equity price coverage.** BDO Securities holdings are PSE-listed, and free programmatic PSE price history is the least certain input in this document `[VERIFY: test coverage against the actual holding list before building the fetch layer]`. IBKR and Kraken are close to solved problems; this one is not. Where coverage fails, manual price entry is the fallback, and it needs to be fast enough to not be abandoned. A portfolio total is only as current as its worst-covered holding, so an unsolved PSE source makes the whole dashboard stale, not just one row.

**Dividend double-counting.** The failure mode in section 9 is quiet and flattering — return reads high, and nothing looks broken. The generated cash leg is the control, and the success criterion above is the test. Neither is optional.

**Silent staleness.** A dashboard showing yesterday's or last month's price with no visual difference from a fresh one is worse than no dashboard, because it will be trusted. Controls are in 10.2 and 10.3 and should not be traded away for visual tidiness.

**FX rounding across currencies.** USD and PHP holdings converted at different snapshot dates produce totals that don't reconcile against any single moment. Every conversion stores the rate and its date, and the dashboard states which FX date the total uses. Two currencies make this tractable now; the discipline is what keeps a third currency from breaking it later.

**Import duplication.** A CSV re-imported over an overlapping date range without `external_id` deduplication silently doubles positions, and the error is invisible until a total is checked by hand. Cheap to prevent in the schema, expensive to unwind afterwards.

**OCR scope.** Covered in section 7, and now narrowed to BDO statements alone. Still the likely sinkhole, which is the argument for leaving it at P2 behind the CSV path.

**Rating coverage gaps read as bad news.** An empty rating column next to a holding looks like a signal. Explicit "no coverage" labelling is a correctness requirement, not polish.

## 15. Decisions Made

- **Which platforms and instruments.** BDO Securities (PH equities, PHP), IBKR (US equities and ETFs, USD), Kraken (crypto, USD). Carried into section 5, and it is what makes the fetch layer and the import path designable.
- **Dividends are part of return.** Modelled per section 9: gross, tax, net, with a generated cash leg, and total return adjusted for transfers. The chart is total return, not price-only.
- **Flask over Streamlit.** Section 6. The schema still lands first, so the decision stays reversible.

## 16. Open Questions

- Does IBKR hold anything outside US listings — LSE, HK, or other markets? A single non-USD, non-PHP holding reopens the FX surface closed in section 5. Non-blocking; answer before section 10.2.
- How should Kraken staking and reward income be modelled? See the verify note in section 9. Blocking for Kraken import, not for anything else.
- Are there holdings on none of these three platforms — a fund, an insurance-linked product, cash outside the brokers? These have no fetchable price by definition and would land entirely on the manual path. Non-blocking, but it changes how much manual price entry has to be optimised.

## 17. Phases

**Phase 1 — Ledger and dashboard on manual prices.** Instruments, transactions including dividends with their cash legs, manual price entry, positions view, totals, grouping.
*Done when:* the dashboard total matches a hand-checked spreadsheet, a partial sell computes correctly, and a taxed dividend leaves a cash balance matching the broker.

**Phase 2 — Fetch layer.** On-click price and FX lookups with historical backfill, staleness indicators. Kraken and US equities first, PSE coverage resolved or fallen back to manual.
*Done when:* a fetch on a new instrument populates enough history to chart the prior year, and a deliberately broken response leaves existing data untouched.

**Phase 3 — Value chart and total return.** Computed portfolio value over time, total-return view, transfer markers, range selector, gap handling.
*Done when:* a correct curve renders for a period predating first use, and a deposit moves the value line without moving the return line.

**Phase 4 — Structured import.** IBKR Flex Query CSV and Kraken ledger CSV parsers, rejected-row reporting, idempotent re-import.
*Done when:* a month of real broker activity imports with no manual typing, and importing it a second time changes nothing.

**Phase 5 — Ratings.** Live rating lookup where covered, explicit no-coverage states, implied upside.
*Done when:* every holding shows either a dated rating with a named source or a no-coverage label.

**Phase 6 — Research document OCR.** Upload, extract, confirm, link to source file.
*Done when:* a real broker PDF yields a rating and target price that J confirms without retyping them.
