CREATE TABLE research_runs (
    id INTEGER PRIMARY KEY,
    requested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'partial', 'failed')),
    scope_json TEXT,
    focus_prompt TEXT,
    provider TEXT,
    model TEXT,
    prompt_version TEXT,
    error_summary TEXT
);

CREATE TABLE research_items (
    id INTEGER PRIMARY KEY,
    instrument_id INTEGER NOT NULL REFERENCES instruments(id) ON DELETE RESTRICT,
    run_id INTEGER REFERENCES research_runs(id) ON DELETE SET NULL,
    origin TEXT NOT NULL CHECK (origin IN ('ai', 'manual')),
    status TEXT NOT NULL CHECK (status IN ('draft', 'monitoring', 'saved', 'archived')),
    stance TEXT NOT NULL CHECK (stance IN ('buy', 'hold', 'reduce', 'sell', 'watch', 'avoid')),
    research_date TEXT NOT NULL,
    market_price REAL,
    market_price_date TEXT,
    trigger_type TEXT NOT NULL DEFAULT 'none' CHECK (
        trigger_type IN ('at_or_below', 'at_or_above', 'event', 'none')
    ),
    trigger_price REAL,
    trigger_currency TEXT,
    event_trigger TEXT,
    time_horizon TEXT,
    expires_on TEXT,
    summary TEXT NOT NULL,
    supporting_points_json TEXT NOT NULL DEFAULT '[]',
    risks_json TEXT NOT NULL DEFAULT '[]',
    confidence TEXT CHECK (confidence IS NULL OR confidence IN ('low', 'medium', 'high')),
    confidence_reason TEXT,
    source_target REAL,
    source_target_currency TEXT,
    source_target_issuer TEXT,
    original_payload_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX research_one_monitoring_per_instrument
    ON research_items(instrument_id) WHERE status = 'monitoring';
CREATE INDEX research_items_status_date ON research_items(status, research_date DESC);
CREATE INDEX research_items_instrument ON research_items(instrument_id, research_date DESC);

CREATE TABLE research_sources (
    id INTEGER PRIMARY KEY,
    research_item_id INTEGER NOT NULL REFERENCES research_items(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    publisher TEXT,
    url TEXT NOT NULL,
    published_at TEXT,
    accessed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE research_events (
    id INTEGER PRIMARY KEY,
    research_item_id INTEGER NOT NULL REFERENCES research_items(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL CHECK (event_type IN (
        'generated', 'edited', 'monitoring', 'saved', 'archived', 'restored',
        'trigger_met', 'trigger_cleared', 'expired'
    )),
    event_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    detail TEXT
);

CREATE TABLE watchlist (
    id INTEGER PRIMARY KEY,
    instrument_id INTEGER NOT NULL REFERENCES instruments(id) ON DELETE CASCADE,
    research_item_id INTEGER REFERENCES research_items(id) ON DELETE SET NULL,
    added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (instrument_id)
);
