ALTER TABLE instruments ADD COLUMN coverage_status TEXT NOT NULL DEFAULT 'no_coverage'
    CHECK (coverage_status IN ('covered','no_coverage','not_applicable_crypto','not_applicable_index_etf','cash'));
ALTER TABLE instruments ADD COLUMN rating_last_attempt_at TEXT;
ALTER TABLE ratings ADD COLUMN normalized_scale TEXT;
ALTER TABLE ratings ADD COLUMN analyst_count INTEGER;
ALTER TABLE ratings ADD COLUMN note TEXT;

UPDATE instruments SET coverage_status = 'cash' WHERE asset_class = 'cash';
UPDATE instruments SET coverage_status = 'not_applicable_crypto' WHERE asset_class = 'crypto';
UPDATE instruments SET coverage_status = 'not_applicable_index_etf' WHERE asset_class = 'etf';
