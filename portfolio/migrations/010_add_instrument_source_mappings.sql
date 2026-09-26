CREATE TABLE instrument_source_mappings (
    instrument_id INTEGER NOT NULL REFERENCES instruments(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    company_id TEXT NOT NULL,
    security_id TEXT NOT NULL,
    resolved_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (instrument_id, source)
);

