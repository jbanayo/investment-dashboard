ALTER TABLE transactions ADD COLUMN related_instrument_id INTEGER
    REFERENCES instruments(id) ON DELETE RESTRICT;
ALTER TABLE transactions ADD COLUMN is_external_transfer INTEGER NOT NULL DEFAULT 0
    CHECK (is_external_transfer IN (0, 1));
ALTER TABLE transactions ADD COLUMN transfer_group_id TEXT;

CREATE INDEX transactions_transfer_group ON transactions(transfer_group_id);
