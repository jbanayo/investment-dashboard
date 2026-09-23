import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from portfolio.cash import ensure_cash_instruments
from portfolio.corrections import delete_transaction, update_transaction
from portfolio.db import connect, migrate
from portfolio.instruments import create_instrument
from portfolio.positions import positions_as_of
from portfolio.transactions import TransactionError, record_buy, record_sell


class CorrectionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "portfolio.db"
        migrate(self.database)
        self.connection = connect(self.database)
        ensure_cash_instruments(self.connection)
        self.instrument = create_instrument(self.connection, {"name": "Apple", "ticker": "AAPL", "asset_class": "us_equity", "platform": "IBKR", "native_currency": "USD", "sector": "", "notes": ""})

    def tearDown(self):
        self.connection.close()
        self.temp_dir.cleanup()

    def values(self, date, quantity, price):
        return {"instrument_id": str(self.instrument), "trade_date": date, "quantity": quantity, "unit_price": price, "fees": "0", "currency": "USD", "note": "", "zero_price_reason": ""}

    def test_editing_mid_history_trade_recomputes_position_and_sale_gain(self):
        buy = record_buy(self.connection, self.values("2026-09-20", "10", "100"))
        sale, _ = record_sell(self.connection, self.values("2026-09-21", "4", "150"))
        update_transaction(self.connection, buy, self.values("2026-09-20", "10", "120"))
        position = next(p for p in positions_as_of(self.connection, "2026-09-21") if p["instrument"]["id"] == self.instrument)
        self.assertEqual((Decimal("6.0"), Decimal("120.0")), (position["quantity"], position["average_cost"]))
        self.assertEqual(120, self.connection.execute("SELECT realised_gain_loss FROM transactions WHERE id = ?", (sale,)).fetchone()[0])

    def test_generated_leg_and_required_buy_cannot_be_deleted_independently(self):
        buy = record_buy(self.connection, self.values("2026-09-20", "10", "100"))
        leg = self.connection.execute("SELECT id FROM transactions WHERE parent_transaction_id = ?", (buy,)).fetchone()[0]
        with self.assertRaisesRegex(TransactionError, "Generated"):
            delete_transaction(self.connection, leg)
        record_sell(self.connection, self.values("2026-09-21", "4", "150"))
        with self.assertRaisesRegex(TransactionError, "sell"):
            delete_transaction(self.connection, buy)
