# Epic: Phase 5 — Ratings

**Parent:** [investment-tracker-prd.md](investment-tracker-prd.md) §17, Phase 5
**Design reference:** [dashboard.html](dashboard.html), [style-guide.md](style-guide.md)
**Owner:** J
**Status:** Not started
**Created:** 2026-09-24

---

## Epic goal

Show, per holding, what analysts say: a rating or consensus, a target price, and the implied upside against the current price. Each comes with a named source and an issue date. Holdings no one covers say so in words. A new rating never erases the old one.

## Why this phase now

The dashboard is correct after Phase 4. This phase adds context without touching valuation. It is placed after import because ratings don't feed any figure the earlier phases verified. A rating bug can mislead, but it can't break a total.

## In scope

PRD 10.6 in full. PRD 10.8 position notes, which is P1 but not assigned to any phase in PRD §17 (see Prototype alignment). Manual rating entry, using the `source_type = 'manual'` value the schema already allows.

## Out of scope

Extracting ratings from research PDFs (Phase 6). Alerts on target-price crossings and the structured decision log (both P2). Any generated buy/sell verdict (a PRD non-goal).

## Definition of done

- Every holding shows either a dated rating with a named source, or an explicit coverage label. No rating cell is empty.
- Implied upside is computed locally, in the target's currency, against the price in effect.
- Recording a new rating for a covered holding leaves the previous rating visible, with its date.

## Sequencing

```
S1 ──► S2 ──┬──► S3 ──┐
            ├──► S4 ──┼──► S6 ──► S7 ──► S8 ──► S10
            └──► S5 ──┘
S9 (independent, any time)
```

---

## User stories

### S1 — Append-only rating history

**As J, I want** every rating stored as a new row, **so that** a downgrade doesn't erase what the rating was before.

**Acceptance criteria**
- [ ] Ratings are inserted, never updated in place. The `ratings` table from Phase 1 is used as is.
- [ ] Each row records issuer, rating text, target price, target currency, issue date, source type, and `recorded_at`.
- [ ] The "current" rating per instrument and issuer is the one with the latest `issued_date`. An older rating fetched later doesn't displace a newer one.
- [ ] A fetch that returns the same rating, target, and issue date as the latest stored row writes nothing.
- [ ] Rating text is stored as the source gives it ("Strong Buy", "Outperform"). An optional normalised scale is kept separately, so the original wording is never lost.

**Size:** 3

---

### S2 — Coverage status per instrument

**As J, I want** a stated reason when a holding has no rating, **so that** an empty cell never reads as bad news (PRD §14).

**Acceptance criteria**
- [ ] Each instrument has a coverage status: `covered`, `no_coverage`, `not_applicable_crypto`, `not_applicable_index_etf`, or `cash`.
- [ ] Defaults are set by asset class (crypto → not applicable, cash → dash), and J can override any of them. An ETF with real analyst coverage can be marked covered.
- [ ] The labels match the mockup exactly: "No coverage", "No coverage · index ETF", "N/A · no analyst consensus for crypto", and "—" for cash.
- [ ] A covered instrument whose lookup returns nothing shows "No coverage" with the date of the last attempt, not a blank.

**Size:** 2

---

### S3 — Live consensus lookup for US equities

**As J, I want** consensus rating and target price fetched for my US holdings, **so that** the best-covered part of the portfolio needs no typing.

**Acceptance criteria**
- [ ] Source chosen and written down, with its terms and limits. `[VERIFY: the mockup shows "Consensus · 41 analysts"; confirm the chosen source exposes analyst count, and drop it from the display if not.]`
- [ ] Uses the Phase 2 adapter pattern. Requests carry the symbol only (PRD §12).
- [ ] Stores consensus rating, mean target, currency, analyst count where available, and the source's own as-of date as `issued_date`.
- [ ] Failure handling follows Phase 2 S6: the last good rating is kept, and the row is marked as failed.

**Size:** 5

---

### S4 — PSE rating lookup check

**As J, I want** to know whether any live source rates my PH holdings, **so that** I don't build a lookup that returns nothing.

**Acceptance criteria**
- [ ] Every BDO holding is tested against candidate sources (PRD §7 verify note).
- [ ] The result is recorded per ticker.
- [ ] Tickers with no live coverage are left for manual entry (S5) and document extraction (Phase 6), and are marked as such.

**Notes:** PRD §7 expects PH ratings to live mainly in broker PDFs. The mockup agrees: every PH rating in it is sourced "BDO Securities research (PDF)". Expect this story to conclude that there is no live source.

**Size:** 2

---

### S5 — Manual rating entry

**As J, I want** to type a rating from a research note I've read, **so that** PH holdings have ratings before Phase 6 automates it.

**Acceptance criteria**
- [ ] A form with instrument, issuer, rating, target price, target currency, and issue date, plus an optional note.
- [ ] Stored with `source_type = 'manual'` and appended per S1.
- [ ] The preview shows the implied upside against the current price before saving.
- [ ] The issue date can't be in the future, and the target price must be above zero.

**Notes:** Without this, the phase's definition of done can't be met for PH holdings until Phase 6.

**Size:** 2

---

### S6 — Rating cell and implied upside

**As J, I want** the rating, target, and upside in the holdings table, **so that** context sits next to the position it describes.

**Acceptance criteria**
- [ ] Cell line 1: rating in bold · target price · implied upside with sign and colour ("Buy · ₱1,100 (+20.5% implied)").
- [ ] Cell line 2: source · issue date · previous rating when one exists ("BDO Securities research (PDF) · Aug 14 · prev Buy · 2026-04-18").
- [ ] Implied upside equals target / price in effect − 1. It is computed only when the target currency matches the price currency. Otherwise it shows "currency mismatch" instead of a figure.
- [ ] If the price behind the upside is stale, the upside inherits the stale styling, since it is only as current as that price.
- [ ] Coverage labels from S2 use `.nocov` styling.
- [ ] The column wraps at 200–260px, as in the mockup, so the table doesn't widen.

**Size:** 3

---

### S7 — Refresh ratings action

**As J, I want** ratings refreshed on request, separately from prices, **so that** a daily price refresh doesn't also run a dozen rating lookups.

**Acceptance criteria**
- [ ] A "Refresh ratings" action. Placement needs a decision: a secondary button on the holdings card, or a checkbox in the refresh-all dialog.
- [ ] A confirmation dialog states the lookup count by source, with the same privacy line as price refresh.
- [ ] Only `covered` instruments with a live source are counted.
- [ ] The result toast states how many ratings changed, and names any downgrades.

**Size:** 2

---

### S8 — Rating history per instrument

**As J, I want** to see every rating an instrument has had, **so that** I can see which way a broker has moved.

**Acceptance criteria**
- [ ] The instrument's position detail page lists all ratings, newest first, with issuer, rating, target, issue date, source type, and recorded date.
- [ ] The rating cell links to this list.
- [ ] Document-sourced ratings (from Phase 6) link to their source file. This is a placeholder until Phase 6.

**Size:** 2

---

### S9 — Position notes

**As J, I want** dated notes per instrument, **so that** I can record why I opened, held, or trimmed a position (PRD 10.8).

**Acceptance criteria**
- [ ] Add a note with instrument, date, and body. Stored in `notes` with `created_at`.
- [ ] The dashboard's "Position notes" card lists recent notes newest first, as "{ticker} · {date}" then the body.
- [ ] The position detail page lists all notes for that instrument.
- [ ] The note field on the Add asset form (mockup: "Position note, optional") writes here.
- [ ] Notes can be edited and deleted. They are free text and feed no figure.

**Size:** 3

---

### S10 — Phase verification

**As J, I want** every holding checked for a rating or a label, **so that** no empty cell ships.

**Acceptance criteria**
- [ ] Every real holding shows a dated rating with a named source, or a coverage label.
- [ ] At least one US holding's consensus is checked by hand against the source site.
- [ ] One rating change is recorded, and the previous rating stays visible.

**Size:** 1

---

## Total: 10 stories, 25 points

## Prototype alignment

**Covered by the mockup and followed here:** the rating column with rating, target, and implied upside; source, date, and previous rating on the second line; three distinct no-coverage labels; the Position notes card on the dashboard; the note field on Add asset.

**Differences from the mockup:**
- The mockup infers coverage from asset class (every ETF is "index ETF", with no override). S2 stores it per instrument, so an ETF with analyst coverage can show it.
- The mockup computes upside without checking currency. S6 guards against a target currency that differs from the price currency.

**Gaps in the PRD that the mockup exposes:**
- **Position notes (10.8) have no phase.** PRD §17 lists six phases and none includes 10.8, yet the mockup puts notes on the main dashboard. This epic takes them as S9. Add them to PRD §17 Phase 5.
- **No manual rating path is specified.** Without S5, PH holdings can't meet the Phase 5 definition of done until Phase 6.

**Not in the mockup and needs design:**
- The trigger for a rating refresh (S7).
- A manual rating form (S5).
- A rating history view (S8). The mockup shows only one "prev" inline.

## Risks carried into this phase

- **Coverage gaps read as bad news** (PRD §14). S2 makes the label a stored fact, not a missing value.
- **Stale upside.** Implied upside computed from a stale price looks precise and isn't. S6 carries the stale styling through.
- **Source licensing.** Consensus data is often behind terms that forbid scraping. Record the source's terms in S3 before relying on it.
