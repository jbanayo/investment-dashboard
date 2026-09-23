-- Epic 1, Story S1: stable ledger schema. SQLite foreign keys are enabled on
-- every connection by portfolio.db.connect().

CREATE TABLE instruments (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    ticker TEXT,
    asset_class TEXT NOT NULL CHECK (asset_class IN (
        'ph_equity', 'us_equity', 'crypto', 'etf', 'fund', 'cash', 'other'
    )),
    platform TEXT NOT NULL,
    native_currency TEXT NOT NULL,
    sector TEXT,
    notes TEXT
);

CREATE TABLE transactions (
    id INTEGER PRIMARY KEY,
    instrument_id INTEGER NOT NULL REFERENCES instruments(id) ON DELETE RESTRICT,
    type TEXT NOT NULL CHECK (type IN ('buy', 'sell', 'dividend', 'fee', 'transfer')),
    trade_date TEXT NOT NULL,
    quantity REAL,
    unit_price REAL,
    fees REAL NOT NULL DEFAULT 0,
    currency TEXT NOT NULL,
    gross_amount REAL,
    tax_withheld REAL,
    net_amount REAL,
    parent_transaction_id INTEGER REFERENCES transactions(id) ON DELETE RESTRICT,
    external_id TEXT,
    source_type TEXT NOT NULL CHECK (source_type IN ('manual', 'import', 'document')),
    note TEXT,
    entered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    realised_gain_loss REAL,
    -- Kept with each transaction so imported broker IDs can be unique per
    -- platform without requiring a cross-table uniqueness constraint.
    platform TEXT NOT NULL
);

CREATE UNIQUE INDEX transactions_platform_external_id_unique
    ON transactions(platform, external_id)
    WHERE external_id IS NOT NULL;

CREATE INDEX transactions_instrument_trade_date
    ON transactions(instrument_id, trade_date);
CREATE INDEX transactions_parent_transaction
    ON transactions(parent_transaction_id);

CREATE TABLE prices (
    id INTEGER PRIMARY KEY,
    instrument_id INTEGER NOT NULL REFERENCES instruments(id) ON DELETE RESTRICT,
    price_date TEXT NOT NULL,
    price REAL NOT NULL,
    currency TEXT NOT NULL,
    source TEXT NOT NULL,
    fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (instrument_id, price_date, source)
);

CREATE TABLE fx_rates (
    id INTEGER PRIMARY KEY,
    base_currency TEXT NOT NULL,
    quote_currency TEXT NOT NULL,
    rate_date TEXT NOT NULL,
    rate REAL NOT NULL,
    source TEXT NOT NULL,
    fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (base_currency, quote_currency, rate_date, source)
);

CREATE TABLE documents (
    id INTEGER PRIMARY KEY,
    filename TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    uploaded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    doc_type TEXT NOT NULL,
    extraction_status TEXT NOT NULL,
    raw_text TEXT
);

CREATE TABLE ratings (
    id INTEGER PRIMARY KEY,
    instrument_id INTEGER NOT NULL REFERENCES instruments(id) ON DELETE RESTRICT,
    issuer TEXT NOT NULL,
    rating TEXT,
    target_price REAL,
    target_currency TEXT,
    issued_date TEXT NOT NULL,
    source_type TEXT NOT NULL CHECK (source_type IN ('fetch', 'document', 'manual')),
    document_id INTEGER REFERENCES documents(id) ON DELETE RESTRICT,
    recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE notes (
    id INTEGER PRIMARY KEY,
    instrument_id INTEGER NOT NULL REFERENCES instruments(id) ON DELETE RESTRICT,
    note_date TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
