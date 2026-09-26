import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from portfolio.cash import ensure_cash_instruments
from portfolio.db import connect, migrate
from portfolio.instruments import create_instrument
from portfolio.positions import portfolio_snapshot, positions_as_of
from portfolio.prices import record_manual_fx_rate, record_manual_price
from portfolio.transactions import record_buy, record_sell


class PositionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "portfolio.db"
        migrate(self.database)
        self.connection = connect(self.database)
        ensure_cash_instruments(self.connection)
        self.apple = create_instrument(self.connection, {"name": "Apple", "ticker": "AAPL", "asset_class": "us_equity", "platform": "IBKR", "native_currency": "USD", "sector": "", "notes": ""})
        self.pse = create_instrument(self.connection, {"name": "PSE stock", "ticker": "PSE", "asset_class": "ph_equity", "platform": "BDO Securities", "native_currency": "PHP", "sector": "", "notes": ""})

    def tearDown(self):
        self.connection.close()
        self.temp_dir.cleanup()

    def trade(self, trade_date, quantity, unit_price, fees="0"):
        return {"instrument_id": str(self.apple), "trade_date": trade_date, "quantity": quantity, "unit_price": unit_price, "fees": fees, "currency": "USD", "note": "", "zero_price_reason": ""}

    def test_positions_are_date_aware_and_zero_positions_are_hidden(self):
        record_buy(self.connection, self.trade("2026-09-20", "10", "100"))
        record_sell(self.connection, self.trade("2026-09-21", "10", "120"))
        before_sale = positions_as_of(self.connection, "2026-09-20")
        self.assertEqual(Decimal("10.0"), before_sale[0]["quantity"])
        visible = positions_as_of(self.connection, "2026-09-21")
        self.assertFalse(any(p["instrument"]["id"] == self.apple for p in visible))
        all_positions = positions_as_of(self.connection, "2026-09-21", include_zero=True)
        apple = next(p for p in all_positions if p["instrument"]["id"] == self.apple)
        self.assertEqual(Decimal("0"), apple["quantity"])

    def test_dashboard_values_usd_with_fx_and_excludes_missing_prices(self):
        record_buy(self.connection, self.trade("2026-09-20", "10", "100"))
        record_manual_price(self.connection, {"instrument_id": str(self.apple), "price_date": "2026-09-20", "price": "110", "currency": "USD"})
        record_manual_price(self.connection, {"instrument_id": str(self.apple), "price_date": "2026-09-21", "price": "120", "currency": "USD"})
        record_manual_fx_rate(self.connection, {"rate_date": "2026-09-21", "rate": "50"})
        record_buy(self.connection, {"instrument_id": str(self.pse), "trade_date": "2026-09-20", "quantity": "2", "unit_price": "10", "fees": "0", "currency": "PHP", "note": "", "zero_price_reason": ""})
        snapshot = portfolio_snapshot(self.connection, "PHP", "2026-09-21")
        apple = next(item for item in snapshot["positions"] if item["instrument"]["id"] == self.apple)
        self.assertEqual(Decimal("60000.0"), apple["market_value_base"])
        self.assertEqual(Decimal("5000.0"), apple["daily_change"])
        self.assertTrue(any(item["instrument"]["id"] == self.pse and item["reason"] == "No price" for item in snapshot["excluded"]))

    def test_non_cash_transfer_changes_asset_quantity(self):
        self.connection.execute(
            """INSERT INTO transactions
               (instrument_id,type,trade_date,quantity,unit_price,currency,source_type,
                note,platform,is_external_transfer)
               VALUES (?,'transfer','2026-09-20',2.5,100,'USD','import',
                       'External asset deposit','IBKR',1)""",
            (self.apple,),
        )
        position = next(
            item for item in positions_as_of(self.connection, "2026-09-20")
            if item["instrument"]["id"] == self.apple
        )
        self.assertEqual(Decimal("2.5"), position["quantity"])
        self.assertEqual(Decimal("100"), position["average_cost"])

    def test_platform_filter_limits_snapshot_to_one_account(self):
        record_buy(self.connection, self.trade("2026-09-20", "10", "100"))
        record_manual_price(self.connection, {
            "instrument_id": str(self.apple), "price_date": "2026-09-21",
            "price": "120", "currency": "USD",
        })
        record_manual_fx_rate(self.connection, {"rate_date": "2026-09-21", "rate": "50"})
        record_buy(self.connection, {
            "instrument_id": str(self.pse), "trade_date": "2026-09-20",
            "quantity": "2", "unit_price": "10", "fees": "0",
            "currency": "PHP", "note": "", "zero_price_reason": "",
        })
        record_manual_price(self.connection, {
            "instrument_id": str(self.pse), "price_date": "2026-09-21",
            "price": "15", "currency": "PHP",
        })

        snapshot = portfolio_snapshot(
            self.connection, "PHP", "2026-09-21", platform="IBKR"
        )

        self.assertTrue(snapshot["positions"])
        self.assertTrue(all(
            item["instrument"]["platform"] == "IBKR" for item in snapshot["positions"]
        ))
        self.assertFalse(any(
            item["instrument"]["id"] == self.pse for item in snapshot["positions"]
        ))

    def test_ibkr_statement_close_overrides_same_day_yahoo_close(self):
        record_buy(self.connection, self.trade("2026-09-20", "1", "100"))
        self.connection.execute(
            """INSERT INTO prices
               (instrument_id,price_date,price,currency,source)
               VALUES (?,'2026-09-21',115,'USD','Yahoo US daily close')""",
            (self.apple,),
        )
        self.connection.execute(
            """INSERT INTO prices
               (instrument_id,price_date,price,currency,source)
               VALUES (?,'2026-09-21',120,'USD','IBKR statement ending position')""",
            (self.apple,),
        )

        snapshot = portfolio_snapshot(self.connection, "USD", "2026-09-21", platform="IBKR")
        apple = next(
            item for item in snapshot["positions"]
            if item["instrument"]["id"] == self.apple
        )
        self.assertEqual(Decimal("120.0"), apple["market_value_base"])
        self.assertEqual("IBKR statement ending position", apple["price"]["source"])
