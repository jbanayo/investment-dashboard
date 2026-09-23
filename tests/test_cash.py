import sqlite3
import tempfile
import unittest
from pathlib import Path

from portfolio.cash import cash_balance, ensure_cash_instruments, instrument_price
from portfolio.db import connect, migrate


class CashInstrumentTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "portfolio.db"
        migrate(self.database)
        self.connection = connect(self.database)
        ensure_cash_instruments(self.connection)

    def tearDown(self):
        self.connection.close()
        self.temp_dir.cleanup()

    def test_expected_cash_instruments_are_created_once(self):
        ensure_cash_instruments(self.connection)
        cash = self.connection.execute(
            "SELECT platform, native_currency FROM instruments WHERE asset_class = 'cash' ORDER BY platform, native_currency"
        ).fetchall()
        self.assertEqual(
            [("BDO Securities", "PHP"), ("IBKR", "PHP"), ("IBKR", "USD"), ("Kraken", "USD")],
            [(row["platform"], row["native_currency"]) for row in cash],
        )

    def test_cash_is_one_and_balance_is_derived_from_ledger_amounts(self):
        cash_id = self.connection.execute(
            "SELECT id FROM instruments WHERE platform = 'IBKR' AND native_currency = 'USD' AND asset_class = 'cash'"
        ).fetchone()[0]
        self.connection.execute(
            "INSERT INTO transactions (instrument_id, type, trade_date, currency, net_amount, source_type, platform) VALUES (?, 'transfer', '2026-09-24', 'USD', 500, 'manual', 'IBKR')",
            (cash_id,),
        )
        self.connection.execute(
            "INSERT INTO transactions (instrument_id, type, trade_date, currency, net_amount, source_type, platform) VALUES (?, 'buy', '2026-09-24', 'USD', -125.25, 'manual', 'IBKR')",
            (cash_id,),
        )
        self.assertEqual(374.75, cash_balance(self.connection, cash_id))
        self.assertEqual(1.0, instrument_price(self.connection, cash_id))
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute(
                "INSERT INTO prices (instrument_id, price_date, price, currency, source) VALUES (?, '2026-09-24', 1, 'USD', 'manual')",
                (cash_id,),
            )
