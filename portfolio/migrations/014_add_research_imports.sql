CREATE TABLE research_imports (
    id INTEGER PRIMARY KEY,
    research_item_id INTEGER NOT NULL UNIQUE
        REFERENCES research_items(id) ON DELETE CASCADE,
    format TEXT NOT NULL DEFAULT 'markdown' CHECK (format = 'markdown'),
    format_version INTEGER NOT NULL CHECK (format_version > 0),
    filename TEXT NOT NULL,
    agent_name TEXT,
    raw_content TEXT NOT NULL,
    normalized_payload_json TEXT NOT NULL,
    imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE research_import_previews (
    id TEXT PRIMARY KEY,
    instrument_id INTEGER NOT NULL REFERENCES instruments(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    agent_name TEXT,
    raw_content TEXT NOT NULL,
    normalized_payload_json TEXT NOT NULL,
    warnings_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TEXT NOT NULL
);

CREATE INDEX research_import_previews_expiry
    ON research_import_previews(expires_at);
