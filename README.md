# Local Portfolio Dashboard

This is a local Flask portfolio dashboard. Phase 1 (the ledger and a dashboard
on manual prices) is built. Its live reconciliation against real broker data is
still open; see [docs/reconciliation.md](docs/reconciliation.md).

## Documents

- [investment-tracker-prd.md](investment-tracker-prd.md) is the product
  requirements (v5).
- [dashboard.html](dashboard.html) is the design mockup, and
  [style-guide.md](style-guide.md) is extracted from it. Where they disagree,
  the mockup wins.
- The phase epics, with user stories:
  [1](phase-1-epic.md) ledger and dashboard ·
  [2](phase-2-epic.md) fetch layer ·
  [3](phase-3-epic.md) value chart and total return ·
  [4](phase-4-epic.md) structured import ·
  [5](phase-5-epic.md) ratings and notes ·
  [6](phase-6-epic.md) research document OCR

## Database location

The application database defaults to `instance/portfolio.db`, relative to the
project root. Set `PORTFOLIO_DATABASE` to an absolute or relative path to use a
different SQLite file:

```sh
PORTFOLIO_DATABASE=/path/to/portfolio.db python3 app.py
```

Migrations run when the Flask application starts. They are tracked in the
database's `schema_migrations` table and may safely be run repeatedly.

Dashboard totals default to PHP. Set `PORTFOLIO_BASE_CURRENCY` to use another
base currency once its matching FX series has been entered.

## Run

Install Flask, then run the app:

```sh
python3 -m pip install -r requirements.txt
python3 app.py
```

Open [http://127.0.0.1:5000](http://127.0.0.1:5000). For a clean manual test,
point the app at a temporary database instead of your normal local data:

```sh
PORTFOLIO_DATABASE=/private/tmp/portfolio-test.db python3 app.py
```

## Test

```sh
python3 -m unittest discover -s tests -v
```
