import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from portfolio.cash import ensure_cash_instruments
from portfolio.db import connect, migrate
from portfolio.instruments import create_instrument
from portfolio.ledger import record_transfer
from portfolio.positions import daily_valuations, transfer_adjusted_returns
from portfolio.prices import record_manual_fx_rate, record_manual_price
from portfolio.transactions import record_buy


class DailyValuationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "portfolio.db"
        migrate(self.database)
        self.connection = connect(self.database)
        ensure_cash_instruments(self.connection)
        self.instrument = create_instrument(self.connection, {"name": "Apple", "ticker": "AAPL", "asset_class": "us_equity", "platform": "IBKR", "native_currency": "USD", "sector": "", "notes": ""})
        record_transfer(self.connection, {"platform": "IBKR", "transfer_date": "2026-09-20", "amount": "1000", "currency": "USD", "direction": "in"})
        record_buy(self.connection, {"instrument_id": str(self.instrument), "trade_date": "2026-09-20", "quantity": "10", "unit_price": "100", "fees": "0", "currency": "USD", "note": "", "zero_price_reason": ""})
        record_manual_price(self.connection, {"instrument_id": str(self.instrument), "price_date": "2026-09-20", "price": "100", "currency": "USD"})
        record_manual_price(self.connection, {"instrument_id": str(self.instrument), "price_date": "2026-09-21", "price": "110", "currency": "USD"})
        record_manual_fx_rate(self.connection, {"rate_date": "2026-09-20", "rate": "50"})
        record_manual_fx_rate(self.connection, {"rate_date": "2026-09-21", "rate": "51"})

    def tearDown(self):
        self.connection.close()
        self.temp_dir.cleanup()

    def test_daily_values_use_historical_prices_and_fx_with_external_flow(self):
        points = daily_valuations(self.connection, "2026-09-20", "2026-09-21")
        self.assertEqual("ok", points[0]["status"])
        self.assertEqual(Decimal("50000.0"), points[0]["value_base"])
        self.assertEqual(Decimal("50000.0"), points[0]["net_external_flow_base"])
        self.assertEqual(Decimal("56100.0"), points[1]["value_base"])
        self.assertEqual(Decimal("0"), points[1]["net_external_flow_base"])

    def test_missing_historical_price_is_a_gap(self):
        self.connection.execute("DELETE FROM prices WHERE instrument_id = ?", (self.instrument,))
        points = daily_valuations(self.connection, "2026-09-20", "2026-09-20")
        self.assertEqual("gap", points[0]["status"])
        self.assertIsNone(points[0]["value_base"])

    def test_old_weekday_close_becomes_gap_but_weekend_does_not(self):
        self.connection.execute("DELETE FROM prices WHERE instrument_id = ? AND price_date = '2026-09-21'", (self.instrument,))
        points = daily_valuations(self.connection, "2026-09-26", "2026-09-28")
        self.assertEqual("ok", points[0]["status"])
        self.assertEqual("gap", points[-1]["status"])

    def test_time_weighted_return_removes_deposit_and_skips_gaps(self):
        points = [
            {"status": "ok", "value_base": Decimal("100"), "net_external_flow_base": Decimal("0")},
            {"status": "ok", "value_base": Decimal("200"), "net_external_flow_base": Decimal("100")},
            {"status": "gap", "value_base": None, "net_external_flow_base": Decimal("0")},
            {"status": "ok", "value_base": Decimal("220"), "net_external_flow_base": Decimal("0")},
        ]
        result = transfer_adjusted_returns(points)
        self.assertEqual(Decimal("0.1"), result["return_percent"])
        self.assertEqual(Decimal("20"), result["gain_base"])
