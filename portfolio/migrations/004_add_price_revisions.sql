CREATE TABLE price_revisions (
    id INTEGER PRIMARY KEY,
    price_id INTEGER NOT NULL REFERENCES prices(id) ON DELETE RESTRICT,
    previous_price REAL NOT NULL,
    previous_currency TEXT NOT NULL,
    previous_source TEXT NOT NULL,
    previous_fetched_at TEXT NOT NULL,
    changed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE fx_rate_revisions (
    id INTEGER PRIMARY KEY,
    fx_rate_id INTEGER NOT NULL REFERENCES fx_rates(id) ON DELETE RESTRICT,
    previous_rate REAL NOT NULL,
    previous_source TEXT NOT NULL,
    previous_fetched_at TEXT NOT NULL,
    changed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
