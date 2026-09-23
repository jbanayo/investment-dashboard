import tempfile
import unittest
from pathlib import Path

from portfolio.cash import cash_balance, ensure_cash_instruments
from portfolio.db import connect, migrate
from portfolio.instruments import create_instrument
from portfolio.ledger import record_fee, record_transfer
from portfolio.prices import record_bulk_prices, record_manual_fx_rate, record_manual_price
from portfolio.transactions import TransactionError


class LedgerAndPriceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "portfolio.db"
        migrate(self.database)
        self.connection = connect(self.database)
        ensure_cash_instruments(self.connection)
        self.apple = create_instrument(self.connection, {"name": "Apple", "ticker": "AAPL", "asset_class": "us_equity", "platform": "IBKR", "native_currency": "USD", "sector": "", "notes": ""})
        self.bitcoin = create_instrument(self.connection, {"name": "Bitcoin", "ticker": "BTC", "asset_class": "crypto", "platform": "Kraken", "native_currency": "USD", "sector": "", "notes": ""})

    def tearDown(self):
        self.connection.close()
        self.temp_dir.cleanup()

    def test_fee_debits_cash_and_transfer_pairs_are_matched(self):
        record_fee(self.connection, {"platform": "IBKR", "fee_date": "2026-09-20", "amount": "10", "currency": "USD", "related_instrument_id": str(self.apple)})
        cash_id = self.connection.execute("SELECT id FROM instruments WHERE platform = 'IBKR' AND asset_class = 'cash' AND native_currency = 'USD'").fetchone()[0]
        self.assertEqual(-10, cash_balance(self.connection, cash_id))
        transfer_ids = record_transfer(self.connection, {"platform": "IBKR", "transfer_date": "2026-09-21", "amount": "50", "currency": "USD", "direction": "out", "counterparty_platform": "Kraken", "counterparty_currency": "USD"})
        self.assertEqual(2, len(transfer_ids))
        rows = self.connection.execute("SELECT net_amount, is_external_transfer, transfer_group_id FROM transactions WHERE id IN (?, ?) ORDER BY id", transfer_ids).fetchall()
        self.assertEqual((-50, 50), (rows[0]["net_amount"], rows[1]["net_amount"]))
        self.assertEqual((0, 0), (rows[0]["is_external_transfer"], rows[1]["is_external_transfer"]))
        self.assertEqual(rows[0]["transfer_group_id"], rows[1]["transfer_group_id"])

    def test_external_transfer_is_marked_as_capital_movement(self):
        [transfer_id] = record_transfer(self.connection, {"platform": "IBKR", "transfer_date": "2026-09-21", "amount": "50", "currency": "USD", "direction": "in"})
        row = self.connection.execute("SELECT net_amount, is_external_transfer FROM transactions WHERE id = ?", (transfer_id,)).fetchone()
        self.assertEqual((50, 1), (row["net_amount"], row["is_external_transfer"]))

    def test_manual_prices_keep_series_and_revisions(self):
        first_id = record_manual_price(self.connection, {"instrument_id": str(self.apple), "price_date": "2026-09-20", "price": "200", "currency": "USD"})
        same_id = record_manual_price(self.connection, {"instrument_id": str(self.apple), "price_date": "2026-09-20", "price": "201", "currency": "USD"})
        record_manual_price(self.connection, {"instrument_id": str(self.apple), "price_date": "2026-09-21", "price": "202", "currency": "USD"})
        self.assertEqual(first_id, same_id)
        self.assertEqual(2, self.connection.execute("SELECT COUNT(*) FROM prices WHERE instrument_id = ?", (self.apple,)).fetchone()[0])
        self.assertEqual(200, self.connection.execute("SELECT previous_price FROM price_revisions WHERE price_id = ?", (first_id,)).fetchone()[0])

    def test_bulk_prices_and_fx_revisions(self):
        self.assertEqual(2, record_bulk_prices(self.connection, "2026-09-20", {f"price_{self.apple}": "200", f"currency_{self.apple}": "USD", f"price_{self.bitcoin}": "65000", f"currency_{self.bitcoin}": "USD"}))
        first_id = record_manual_fx_rate(self.connection, {"rate_date": "2026-09-20", "rate": "58"})
        self.assertEqual(first_id, record_manual_fx_rate(self.connection, {"rate_date": "2026-09-20", "rate": "58.5"}))
        self.assertEqual(58, self.connection.execute("SELECT previous_rate FROM fx_rate_revisions WHERE fx_rate_id = ?", (first_id,)).fetchone()[0])

    def test_cash_has_no_manual_price(self):
        cash_id = self.connection.execute("SELECT id FROM instruments WHERE asset_class = 'cash' LIMIT 1").fetchone()[0]
        with self.assertRaisesRegex(TransactionError, "Cash"):
            record_manual_price(self.connection, {"instrument_id": str(cash_id), "price_date": "2026-09-20", "price": "1", "currency": "PHP"})
