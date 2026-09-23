CREATE TABLE app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE reconciliation_records (
    id INTEGER PRIMARY KEY,
    reconciliation_date TEXT NOT NULL,
    base_currency TEXT NOT NULL,
    dashboard_total REAL NOT NULL,
    spreadsheet_total REAL NOT NULL,
    difference REAL NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    note TEXT
);
