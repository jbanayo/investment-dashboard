-- Cash is valued at exactly one in its own native currency. It has no editable
-- market price; the ledger balance supplies its quantity/value.
CREATE TRIGGER prevent_cash_price_insert
BEFORE INSERT ON prices
WHEN (SELECT asset_class FROM instruments WHERE id = NEW.instrument_id) = 'cash'
BEGIN
    SELECT RAISE(ABORT, 'cash price is always 1.0 and cannot be entered');
END;

CREATE TRIGGER prevent_cash_price_update
BEFORE UPDATE ON prices
WHEN (SELECT asset_class FROM instruments WHERE id = NEW.instrument_id) = 'cash'
BEGIN
    SELECT RAISE(ABORT, 'cash price is always 1.0 and cannot be edited');
END;
