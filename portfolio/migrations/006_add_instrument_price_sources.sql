ALTER TABLE instruments ADD COLUMN price_source TEXT NOT NULL DEFAULT 'manual';
ALTER TABLE instruments ADD COLUMN source_symbol TEXT;

CREATE INDEX instruments_price_source ON instruments(price_source);
