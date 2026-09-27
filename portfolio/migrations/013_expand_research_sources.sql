ALTER TABLE research_sources ADD COLUMN document_id INTEGER REFERENCES documents(id) ON DELETE RESTRICT;
ALTER TABLE research_sources ADD COLUMN source_type TEXT NOT NULL DEFAULT 'other'
    CHECK (source_type IN ('filing', 'company', 'exchange', 'news', 'research', 'other'));

ALTER TABLE research_events ADD COLUMN from_status TEXT;
ALTER TABLE research_events ADD COLUMN to_status TEXT;
