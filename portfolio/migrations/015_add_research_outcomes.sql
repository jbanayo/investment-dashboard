CREATE TABLE research_outcomes (
    id INTEGER PRIMARY KEY,
    research_item_id INTEGER NOT NULL REFERENCES research_items(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL CHECK (event_type IN ('trigger_reached', 'archived')),
    event_date TEXT NOT NULL,
    price REAL,
    currency TEXT,
    price_date TEXT,
    recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (research_item_id, event_type)
);

CREATE INDEX research_outcomes_item ON research_outcomes(research_item_id, event_date);
