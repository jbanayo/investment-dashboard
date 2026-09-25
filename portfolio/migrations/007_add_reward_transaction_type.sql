PRAGMA foreign_keys = OFF;
ALTER TABLE transactions RENAME TO transactions_before_rewards;
CREATE TABLE transactions (
 id INTEGER PRIMARY KEY, instrument_id INTEGER NOT NULL REFERENCES instruments(id) ON DELETE RESTRICT,
 type TEXT NOT NULL CHECK (type IN ('buy','sell','dividend','fee','transfer','reward')),
 trade_date TEXT NOT NULL, quantity REAL, unit_price REAL, fees REAL NOT NULL DEFAULT 0,
 currency TEXT NOT NULL, gross_amount REAL, tax_withheld REAL, net_amount REAL,
 parent_transaction_id INTEGER REFERENCES transactions(id) ON DELETE RESTRICT,
 external_id TEXT, source_type TEXT NOT NULL CHECK (source_type IN ('manual','import','document')),
 note TEXT, entered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, realised_gain_loss REAL,
 platform TEXT NOT NULL, related_instrument_id INTEGER REFERENCES instruments(id) ON DELETE RESTRICT,
 is_external_transfer INTEGER NOT NULL DEFAULT 0 CHECK (is_external_transfer IN (0,1)),
 transfer_group_id TEXT
);
INSERT INTO transactions SELECT id,instrument_id,type,trade_date,quantity,unit_price,fees,currency,
 gross_amount,tax_withheld,net_amount,parent_transaction_id,external_id,source_type,note,entered_at,
 realised_gain_loss,platform,related_instrument_id,is_external_transfer,transfer_group_id
 FROM transactions_before_rewards;
DROP TABLE transactions_before_rewards;
CREATE UNIQUE INDEX transactions_platform_external_id_unique ON transactions(platform,external_id) WHERE external_id IS NOT NULL;
CREATE INDEX transactions_instrument_trade_date ON transactions(instrument_id,trade_date);
CREATE INDEX transactions_parent_transaction ON transactions(parent_transaction_id);
CREATE INDEX transactions_transfer_group ON transactions(transfer_group_id);
PRAGMA foreign_keys = ON;
