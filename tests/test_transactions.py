import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from portfolio.cash import cash_balance, ensure_cash_instruments
from portfolio.db import connect, migrate
from portfolio.instruments import create_instrument
from portfolio.transactions import (
    TransactionError, dividend_income, position_as_of, record_buy,
    record_dividend, record_reward, reward_income, record_sell,
)


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "portfolio.db"
        migrate(self.database)
        self.connection = connect(self.database)
        ensure_cash_instruments(self.connection)
        self.apple = create_instrument(self.connection, {"name": "Apple", "ticker": "AAPL", "asset_class": "us_equity", "platform": "IBKR", "native_currency": "USD", "sector": "", "notes": ""})

    def tearDown(self):
        self.connection.close()
        self.temp_dir.cleanup()

    def values(self, **overrides):
        result = {"instrument_id": str(self.apple), "trade_date": "2026-09-20", "quantity": "10", "unit_price": "100", "fees": "5", "currency": "USD", "note": "", "zero_price_reason": ""}
        result.update(overrides)
        return result

    def test_buy_creates_linked_cash_debit(self):
        parent_id = record_buy(self.connection, self.values())
        leg = self.connection.execute("SELECT * FROM transactions WHERE parent_transaction_id = ?", (parent_id,)).fetchone()
        self.assertEqual("buy", leg["type"])
        self.assertEqual(-1005, leg["net_amount"])
        cash_id = leg["instrument_id"]
        self.assertEqual(-1005, cash_balance(self.connection, cash_id))

    def test_partial_sell_preserves_average_cost_and_records_realised_gain(self):
        record_buy(self.connection, self.values(quantity="10", unit_price="100", fees="0"))
        sale_id, gain = record_sell(self.connection, self.values(trade_date="2026-09-21", quantity="4", unit_price="150", fees="10"))
        quantity, average_cost = position_as_of(self.connection, self.apple, "2026-09-21")
        self.assertEqual(Decimal("6.0"), quantity)
        self.assertEqual(Decimal("100.0"), average_cost)
        self.assertEqual(Decimal("190"), gain)
        self.assertEqual(190, self.connection.execute("SELECT realised_gain_loss FROM transactions WHERE id = ?", (sale_id,)).fetchone()[0])

    def test_sale_cannot_use_a_later_buy_to_cover_it(self):
        record_buy(self.connection, self.values(trade_date="2026-09-22"))
        with self.assertRaisesRegex(TransactionError, "later buy"):
            record_sell(self.connection, self.values(trade_date="2026-09-21"))

    def test_buy_rejects_future_dates_and_unexplained_zero_prices(self):
        with self.assertRaisesRegex(TransactionError, "future"):
            record_buy(self.connection, self.values(trade_date="2099-01-01"))
        with self.assertRaisesRegex(TransactionError, "Explain"):
            record_buy(self.connection, self.values(unit_price="0"))

    def test_dividend_credits_only_net_cash_and_has_income_filters(self):
        dividend_id = record_dividend(self.connection, {
            "instrument_id": str(self.apple), "payment_date": "2026-09-21",
            "gross_amount": "100", "tax_withheld": "15", "currency": "USD", "note": "",
        })
        parent = self.connection.execute("SELECT * FROM transactions WHERE id = ?", (dividend_id,)).fetchone()
        leg = self.connection.execute("SELECT * FROM transactions WHERE parent_transaction_id = ?", (dividend_id,)).fetchone()
        self.assertEqual((100, 15, 85), (parent["gross_amount"], parent["tax_withheld"], parent["net_amount"]))
        self.assertEqual(85, leg["net_amount"])
        self.assertEqual((0, 0), position_as_of(self.connection, self.apple, "2026-09-21"))
        summary = dividend_income(self.connection, instrument_id=self.apple, start_date="2026-09-21", end_date="2026-09-21")
        self.assertEqual((100, 15, 85), (summary["gross_amount"], summary["tax_withheld"], summary["net_amount"]))

    def test_dividend_rejects_negative_or_excessive_tax(self):
        values = {"instrument_id": str(self.apple), "payment_date": "2026-09-21", "gross_amount": "10", "tax_withheld": "-1", "currency": "USD"}
        with self.assertRaisesRegex(TransactionError, "Withholding tax"):
            record_dividend(self.connection, values)
        values["tax_withheld"] = "11"
        with self.assertRaisesRegex(TransactionError, "cannot exceed"):
            record_dividend(self.connection, values)

    def test_reward_adds_quantity_and_value_to_average_cost_without_cash(self):
        crypto = create_instrument(self.connection, {"name": "Ether", "ticker": "ETH", "asset_class": "crypto", "platform": "Kraken", "native_currency": "USD", "sector": "", "notes": ""})
        record_buy(self.connection, {"instrument_id": str(crypto), "trade_date": "2026-09-20", "quantity": "2", "unit_price": "100", "fees": "0", "currency": "USD", "note": "", "zero_price_reason": ""})
        reward_id = record_reward(self.connection, {"instrument_id": str(crypto), "trade_date": "2026-09-21", "quantity": "1", "unit_price": "130", "fees": "0", "currency": "USD", "note": "", "zero_price_reason": ""})
        quantity, average_cost = position_as_of(self.connection, crypto, "2026-09-21")
        self.assertEqual(Decimal("3.0"), quantity)
        self.assertEqual(Decimal("110.0"), average_cost)
        self.assertIsNone(self.connection.execute("SELECT id FROM transactions WHERE parent_transaction_id = ?", (reward_id,)).fetchone())
        self.assertEqual(130, reward_income(self.connection, instrument_id=crypto)["gross_amount"])
