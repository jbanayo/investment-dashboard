# Epic: Phase 1 — Ledger and Dashboard on Manual Prices

**Parent:** [investment-tracker-prd.md](investment-tracker-prd.md) §17, Phase 1
**Owner:** J
**Status:** Not started
**Created:** 2026-09-23

---

## Epic goal

Stand up the ledger and a working dashboard that values it, using manually entered prices only. No network calls, no file imports, no OCR. Every number on screen is either typed by J or computed from something typed by J.

## Why this phase first

Manual entry is the only input path that cannot be skipped, and every later path — fetch, CSV import, OCR — writes into the same tables this phase creates. If the transaction model is wrong, every subsequent phase inherits the error. Building the dashboard on manual prices also proves the valuation math before the fetch layer can be blamed for a wrong total.

## In scope

PRD requirements 10.1 in full, the manual-entry portions of 10.2, and 10.3 except the refresh buttons. The dividend model from PRD §9, including withholding tax and the generated cash leg.

## Out of scope

Live price and FX fetching (Phase 2), the value chart and total-return line (Phase 3), CSV import (Phase 4), ratings (Phase 5), OCR (Phase 6). Position notes (10.8) are P1 and not in this phase.

## Definition of done

- The dashboard total matches a hand-checked spreadsheet across BDO Securities, IBKR, and Kraken, on the same prices, to the peso.
- A partial sell followed by a re-buy produces the correct average cost and unrealised gain, verified by hand.
- A dividend with withholding tax leaves a cash balance matching the broker's, to the centavo.
- Every value displayed carries the date of the price it was computed from.

## Sequencing

```
S1 ──► S2 ──► S3 ──► S4 ──┬──► S5 ──► S6 ──► S7 ──► S8 ──► S9 ──► S10 ──► S11
                          └──► S12 (any time after S4)
```

Stories S1–S4 are the foundation and are strictly ordered. S5 onward can overlap once transactions exist.

---

## User stories

### S1 — Database schema and migrations

**As J, I want** the SQLite schema created and versioned, **so that** every later feature writes into a stable shape rather than reshaping tables under live data.

**Acceptance criteria**
- [ ] SQLite database file created at a configurable path, with the location documented.
- [ ] Tables created per PRD §11: `instruments`, `transactions`, `prices`, `fx_rates`, `ratings`, `documents`, `notes`.
- [ ] `transactions` includes `gross_amount`, `tax_withheld`, `net_amount`, `parent_transaction_id`, `external_id`, and `source_type`, even though only manual entry populates them this phase.
- [ ] Foreign keys enforced, not merely declared.
- [ ] `external_id` is unique per platform where present, so Phase 4 import is idempotent by construction.
- [ ] A migration mechanism exists and the initial schema is migration 001.
- [ ] Re-running migrations on an existing database is a no-op.

**Notes:** The columns for later phases are created now because altering a table under real transaction history is the expensive version of this work. Cost is near zero today.

**Size:** 3

---

### S2 — Create and manage instruments

**As J, I want** to add and edit instruments, **so that** every transaction has something to attach to.

**Acceptance criteria**
- [ ] Create an instrument with name, ticker, asset class, platform, native currency, sector, and notes.
- [ ] Asset class constrained to `ph_equity`, `us_equity`, `crypto`, `etf`, `fund`, `cash`, `other`.
- [ ] Platform constrained to the known set (BDO Securities, IBKR, Kraken) with room to add more.
- [ ] Edit any field; changing native currency is blocked once transactions exist against the instrument.
- [ ] List view of all instruments, filterable by platform and asset class.
- [ ] Deleting an instrument with transactions is refused with an explanation, not cascaded.

**Size:** 3

---

### S3 — Cash instruments per platform and currency

**As J, I want** a cash instrument for each platform and currency combination, **so that** cash balances are part of the portfolio rather than a special case bolted on beside it.

**Acceptance criteria**
- [ ] Cash instruments are ordinary instruments with asset class `cash`, one per platform per currency.
- [ ] The app creates the expected set on first run: BDO Securities PHP, IBKR USD, IBKR PHP, Kraken USD.
- [ ] A cash instrument's price is always 1.0 in its own currency and is not manually editable.
- [ ] Cash appears in the holdings list and counts toward total portfolio value.
- [ ] Cash balance for a platform is computed from transactions, never typed directly.

**Notes:** PRD §11. Making cash an instrument is what lets cash ratio and total assets fall out of the same query as everything else.

**Size:** 2

---

### S4 — Record buy transactions

**As J, I want** to record a purchase, **so that** a position exists and has a cost basis.

**Acceptance criteria**
- [ ] Enter trade date, instrument, quantity, unit price, fees, and currency.
- [ ] Transaction stores both `trade_date` and `entered_at`; the form never collapses them into one field.
- [ ] A buy generates a cash leg debiting the platform's cash instrument for consideration plus fees.
- [ ] The cash leg is linked to its parent via `parent_transaction_id` and is visible in the transaction list.
- [ ] The cash leg cannot be edited or deleted on its own.
- [ ] Currency defaults to the instrument's native currency.
- [ ] Validation rejects negative quantity, zero price without an explicit reason, and a trade date in the future.

**Size:** 5

---

### S5 — Record sell transactions with correct average cost

**As J, I want** to record a sale, including a partial one, **so that** remaining quantity, average cost, and realised gain stay correct.

**Acceptance criteria**
- [ ] Enter the same fields as a buy; quantity is limited to the quantity held on that date.
- [ ] A partial sell leaves remaining quantity correct and leaves average cost unchanged.
- [ ] Realised gain or loss is computed and stored against the sale.
- [ ] A sell generates a cash leg crediting the platform's cash instrument for proceeds less fees.
- [ ] A full sell leaves the position at zero, visible in history but not in the holdings list.
- [ ] Selling more than is held on that date is refused, including when a later buy would have covered it.

**Notes:** The "including when a later buy would have covered it" case is the one that silently passes a naive implementation. Test it.

**Size:** 5

---

### S6 — Record dividends with withholding tax

**As J, I want** to record a dividend with its withholding tax, **so that** cash matches the broker and income is counted exactly once.

**Acceptance criteria**
- [ ] Enter instrument, payment date, gross amount, withholding tax, and currency; net is computed and shown before saving.
- [ ] The dividend generates a cash leg for the **net** amount against the platform's cash instrument.
- [ ] The dividend does not change position quantity or average cost.
- [ ] Cumulative dividend income is queryable per instrument, per platform, and per period.
- [ ] Income is labelled in the UI as already included in portfolio value, not added on top of it.
- [ ] A dividend with zero withholding tax is accepted; a negative one is refused.

**Notes:** PRD §9. This is the story with the quiet failure mode — overstated return that looks fine. The cash-leg-uses-net rule is the whole control.

**Size:** 5

---

### S7 — Record fees and transfers

**As J, I want** to record platform fees and money moving in or out, **so that** cash reconciles and Phase 3 can tell a deposit apart from a gain.

**Acceptance criteria**
- [ ] Fee transaction debits a platform's cash instrument, optionally linked to an instrument.
- [ ] Transfer transaction records money in or out of a platform, with direction and currency.
- [ ] Transfers are marked as external capital movement, distinct from internal cash legs.
- [ ] A transfer between two platforms can be recorded as a matched pair.
- [ ] Transfers do not appear as gains anywhere in this phase's figures.

**Notes:** Transfers do nothing visible on a Phase 1 dashboard. They are recorded now because Phase 3 total return is unbuildable without them, and reconstructing them later means reading old statements.

**Size:** 3

---

### S8 — Manual price entry

**As J, I want** to enter a price for any instrument, **so that** holdings no source covers can still be valued.

**Acceptance criteria**
- [ ] Enter instrument, price date, price, and currency; `source` is recorded as manual and `fetched_at` as the entry moment.
- [ ] Price date and entry timestamp are stored separately and both are retained.
- [ ] Entering a price for a date that already has one updates it and keeps a record that it was changed.
- [ ] Prices are a series: entering a new price never overwrites the previous date's.
- [ ] Bulk entry screen for updating prices across several holdings in one pass.
- [ ] Manual FX rate entry for USD/PHP with the same date and timestamp handling.

**Notes:** This is the screen that decides whether the app gets abandoned. If PSE coverage fails in Phase 2, J uses this weekly forever. Bulk entry is not a nice-to-have.

**Size:** 5

---

### S9 — Computed positions view

**As J, I want** positions derived from transactions, **so that** no quantity or cost basis is ever a stored number someone can edit into being wrong.

**Acceptance criteria**
- [ ] Position quantity and average cost computed from transactions on demand, never stored.
- [ ] Positions correct as at any given date, not only today.
- [ ] Zero-quantity positions excluded from holdings but retained in history.
- [ ] Computation covers all three platforms and all asset classes including cash.
- [ ] A position's figures can be traced back to the exact transactions that produced them.

**Size:** 5

---

### S10 — Dashboard with totals in base currency

**As J, I want** one screen showing every holding and the portfolio total in PHP, **so that** the question this app exists to answer is answered.

**Acceptance criteria**
- [ ] Total portfolio value in base currency, with today's change in absolute terms and percent.
- [ ] Each holding shows quantity, average cost, last price with its date, market value in base and native currency, unrealised gain/loss, and allocation percent.
- [ ] USD holdings converted using the stored USD/PHP rate, with the FX date stated on the screen.
- [ ] Base currency read from config, defaulting to PHP.
- [ ] Every value displays the date of the price behind it.
- [ ] Prices older than the last trading day are visually distinct from current ones.
- [ ] A holding with no price at all reads as "no price" and is excluded from the total with the exclusion stated, rather than valued at zero.

**Notes:** The last criterion matters more than it looks. A missing price valued at zero produces a total that is wrong and confident.

**Size:** 8

---

### S11 — Grouping and subtotals

**As J, I want** to group holdings by platform or asset class, **so that** concentration is visible without exporting anything.

**Acceptance criteria**
- [ ] Toggle grouping between platform and asset class.
- [ ] Each group shows its own subtotal in base currency and its share of the whole.
- [ ] Subtotals sum to the portfolio total, verified by the same excluded-holdings rule as S10.
- [ ] Grouping choice persists between sessions.

**Size:** 3

---

### S12 — Edit and delete with full recomputation

**As J, I want** correcting a past transaction to correct everything downstream of it, **so that** a typo found in three months does not leave a permanently wrong history.

**Acceptance criteria**
- [ ] Editing a past transaction recomputes position quantity, average cost, realised gain, and cash balance from that date forward.
- [ ] Deleting a transaction removes its generated cash leg with it.
- [ ] Deleting a buy that a later sell depends on is refused with the conflict named.
- [ ] Recomputation is verified by a test that edits a mid-history transaction and checks the resulting position against a hand-computed figure.
- [ ] No derived figure anywhere in the app survives a recompute as a stale cached value.

**Notes:** PRD §8 — retroactive correction is one of the three things the series-based design buys. It only holds if recomputation is genuinely complete.

**Size:** 5

---

### S13 — Spreadsheet reconciliation

**As J, I want** to check the dashboard total against a spreadsheet built by hand, **so that** the phase is verified rather than assumed.

**Acceptance criteria**
- [ ] Real holdings from all three platforms entered into the app.
- [ ] A spreadsheet built independently, using the same prices and the same FX rate.
- [ ] Totals match to the peso; any difference is traced to its cause and fixed, not rounded away.
- [ ] Partial-sell case verified by hand per the epic's definition of done.
- [ ] Dividend cash balance verified against a real broker statement.
- [ ] The reconciliation is written down, so Phase 2 has a known-good baseline to regress against.

**Notes:** This is the story that closes the phase. It is deliberately last and deliberately not optional.

**Size:** 3

---

## Total: 13 stories, 55 points

## Risks carried into this phase

- **Dividend double-counting** (PRD §14). Controlled by S6's generated cash leg and tested in S13.
- **Manual price entry friction** (PRD §14). Controlled by S8's bulk entry. If S8 ships without it, the app is abandoned in month two and the cause will be misattributed.
- **Incomplete recomputation** (S12). The failure is silent and appears months later as a total that will not reconcile.
