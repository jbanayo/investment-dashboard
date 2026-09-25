# Epic: Phase 6 — Research Document OCR

**Parent:** [investment-tracker-prd.md](investment-tracker-prd.md) §17, Phase 6
**Design reference:** [dashboard.html](dashboard.html), [style-guide.md](style-guide.md)
**Owner:** J
**Status:** Not started
**Created:** 2026-09-24

---

## Epic goal

Turn a broker research PDF into a stored rating without retyping it. J uploads the note. The app extracts issuer, instrument, rating, target price, and date. J confirms each field before anything is written. The stored rating links back to the file it came from.

## Why this phase now

Phase 5 is expected to find no live rating source for PH equities, which leaves them on manual entry. PRD §7 argues that research-document OCR is worth building because that's where PH ratings actually live. It comes last because it is the least deterministic input path. Everything before it had to be correct without it.

## In scope

PRD 10.7 in full. Research notes only, as PDF or image.

## Out of scope

BDO statement OCR for positions (P2, and deliberately separate per PRD §7). Any cloud OCR or extraction service, which PRD §12 rules out for these files.

## Definition of done

- A real broker PDF yields a rating and target price that J confirms without retyping either value.
- The stored rating links to the original file, and the file opens from the rating.
- No file content leaves the machine during extraction.

## Sequencing

```
S1 ──► S2 ──► S3 ──► S4 ──► S5 ──► S8
                     ├──► S6
                     └──► S7
```

---

## User stories

### S1 — Upload and store research documents

**As J, I want** to upload a research note and have it kept, **so that** every rating from a document can be checked against the original.

**Acceptance criteria**
- [ ] Accepts PDF, PNG, and JPEG, with a stated size limit.
- [ ] Stored under a local documents directory with a content-hash filename, and recorded in `documents` with the original filename, `doc_type = 'research'`, and `extraction_status = 'pending'`.
- [ ] Uploading the same file twice is detected by hash. J is offered the existing record instead of a duplicate.
- [ ] The documents directory is next to the database and covered by the same backup instructions in the README.

**Size:** 3

---

### S2 — Local text extraction

**As J, I want** text pulled from the document on this machine, **so that** a note carrying my name and account number is never uploaded anywhere (PRD §12).

**Acceptance criteria**
- [ ] PDFs with a text layer are read directly, without OCR.
- [ ] Scanned PDFs and images go through a local OCR engine. `[VERIFY: pick the engine (Tesseract or similar) and confirm it installs on this Mac without a network service.]`
- [ ] Raw text is stored in `documents.raw_text`, and `extraction_status` moves to `extracted` or `failed`.
- [ ] A test asserts no network call is made during extraction.
- [ ] Extraction of a typical 5-page note finishes in under 15 seconds.

**Size:** 5

---

### S3 — Field extraction

**As J, I want** the app to find the issuer, instrument, rating, target price, and date in the text, **so that** I confirm values instead of typing them.

**Acceptance criteria**
- [ ] Extracts issuer, subject instrument, rating, target price with currency, and report date.
- [ ] Each field carries a confidence level and the text snippet it came from.
- [ ] The instrument is matched against existing instruments by ticker and name. A note on something J doesn't hold is flagged, not auto-created.
- [ ] Rules are tuned to the formats of the brokers J actually receives notes from, starting with BDO Securities. The supported issuers are listed.
- [ ] A field that can't be found is left empty and marked "not found". It is never guessed.

**Notes:** PRD §7: a confidently mis-parsed figure is worse than a typed one. An empty field J has to fill is the safe failure.

**Size:** 5

---

### S4 — Draft confirmation

**As J, I want** to review each extracted field against the source before saving, **so that** nothing OCR got wrong enters the rating history.

**Acceptance criteria**
- [ ] The confirmation screen shows the document on one side and the draft fields on the other. Each field shows its source snippet.
- [ ] Low-confidence and not-found fields are marked with `.warn` and must be touched (confirmed or edited) before saving.
- [ ] The preview states what will be written: "Adds BDO Securities · Hold · ₱250 for JFC, issued Sep 2. Previous rating Buy stays in history."
- [ ] Saving writes a rating with `source_type = 'document'` and `document_id` set, and moves `extraction_status` to `confirmed`.
- [ ] J can discard the draft, which leaves the document stored with status `discarded`.

**Size:** 5

---

### S5 — Link rating to source file

**As J, I want** to open the original document from the rating, **so that** any figure can be checked against where it came from.

**Acceptance criteria**
- [ ] The rating cell's source line for a document-sourced rating ("BDO Securities research (PDF)") links to the stored file.
- [ ] The rating history (Phase 5 S8) links each document-sourced row to its file.
- [ ] The file is served from localhost only, through the Flask app.

**Size:** 2

---

### S6 — Multiple instruments in one note

**As J, I want** a sector note covering several stocks handled, **so that** one upload can update several ratings.

**Acceptance criteria**
- [ ] If more than one instrument and target are found, the draft shows one row per instrument, each confirmed separately.
- [ ] J can drop rows for instruments not held.

**Size:** 2

---

### S7 — Extraction failure states

**As J, I want** a failed extraction to say why and what to do, **so that** a bad scan doesn't leave me guessing.

**Acceptance criteria**
- [ ] Failure reasons are distinguished: unreadable file, no text found, OCR succeeded but no fields matched, instrument not held.
- [ ] Each failure offers the next step: "Enter the rating manually" (opens Phase 5 manual entry pre-linked to the document), or "Retry with OCR" for a PDF whose text layer is empty or garbled.
- [ ] A rating entered manually from a failed document still links to that document.

**Size:** 2

---

### S8 — Phase verification

**As J, I want** a real broker note run end to end, **so that** the phase is judged on a real document.

**Acceptance criteria**
- [ ] At least three real BDO Securities notes processed, including one scanned or image-only.
- [ ] For each, rating and target are confirmed without retyping.
- [ ] Each rating's link opens the right file.
- [ ] A network monitor shows no outbound traffic during extraction.

**Size:** 2

---

## Total: 8 stories, 26 points

## Prototype alignment

**Covered by the mockup:** only the result. PH ratings are sourced "BDO Securities research (PDF)" in the rating cell, and a note ("BDO research moved to Hold") shows how J uses them.

**Gaps in the mockup:**
- The source label isn't a link. PRD 10.7 requires the file to be reachable from the rating. S5 makes it one.
- There is no upload entry point, confirmation screen, or document list. All of this is new design work. The style guide's principle 4 ("show the write before it happens") and its preview pattern set the interaction, but the two-pane confirm layout in S4 has no precedent in the mockup and needs designing before S4 starts.

## Risks carried into this phase

- **OCR scope** (PRD §14). This is the likely sinkhole. S3 is scoped to the brokers J actually receives notes from, and S7 gives every failure a manual exit, so the phase can't block on edge cases.
- **Confident mis-parses.** Mitigated by S3 never guessing and S4 requiring a touch on every low-confidence field.
- **Sensitive files.** Research notes carry names and account numbers. S2's no-network test is the control.
