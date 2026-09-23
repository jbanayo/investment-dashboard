# Local Portfolio Dashboard

This is a local Flask portfolio dashboard. The current implementation contains
the database foundation for Epic 1, Story S1.

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
