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

## Run

Install Flask, then run the app:

```sh
python3 -m pip install -r requirements.txt
python3 app.py
```

## Test

```sh
python3 -m unittest discover -s tests -v
```
