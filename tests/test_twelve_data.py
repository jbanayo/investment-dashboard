import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from portfolio.db import connect, migrate
from portfolio.fetch import (
    FetchFailure,
    PricePoint,
    TwelveDataAdapter,
    refresh_twelve_data_crypto_prices,
    reserve_twelve_data_request,
    twelve_data_usage,
)
from portfolio.instruments import create_instrument
from portfolio.transactions import record_buy


class FakeHttpClient:
    def __init__(self, response):
        self.response = response
        self.parameters = None

    def get_json(self, endpoint, parameters):
        self.parameters = parameters
        return self.response


class FakeAdapter:
    source_name = "twelve_data"

    def __init__(self, result):
        self.result = result
        self.calls = []

    def fetch_prices(self, symbol, start_date, end_date):
        self.calls.append((symbol, start_date, end_date))
        return self.result


class TwelveDataTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "portfolio.db"
        migrate(self.database)
        self.connection = connect(self.database)

    def tearDown(self):
        self.connection.close()
        self.temp_dir.cleanup()

    def test_adapter_scopes_symbol_to_pse_mic_and_parses_closes(self):
        client = FakeHttpClient({
            "status": "ok",
            "values": [
                {"datetime": "2026-09-25", "close": "98.90"},
                {"datetime": "2026-09-24", "close": "97.50"},
            ],
        })
        result = TwelveDataAdapter("secret", client).fetch_prices(
            "BPI:XPHS", date(2026, 9, 24), date(2026, 9, 25)
        )
        self.assertEqual([date(2026, 9, 24), date(2026, 9, 25)], [p.price_date for p in result])
        self.assertEqual("BPI", client.parameters["symbol"])
        self.assertEqual("XPHS", client.parameters["mic_code"])
        self.assertNotIn("quantity", client.parameters)

    def test_plan_error_stops_bulk_refresh(self):
        client = FakeHttpClient({
            "status": "error",
            "message": "This symbol is available starting with the Ultra or Enterprise plan.",
        })
        result = TwelveDataAdapter("secret", client).fetch_prices(
            "BPI:XPHS", date(2026, 9, 24), date(2026, 9, 25)
        )
        self.assertIsInstance(result, FetchFailure)
        self.assertTrue(result.stop_refresh)

    def test_daily_guardrail_never_reserves_request_801(self):
        now = datetime.fromisoformat("2026-09-26T10:00:00+08:00")
        self.connection.execute(
            "INSERT INTO price_fetch_usage VALUES ('twelve_data', '2026-09-26', 799)"
        )
        self.connection.commit()
        self.assertEqual(0, reserve_twelve_data_request(self.connection, now))
        with self.assertRaisesRegex(RuntimeError, "800/800"):
            reserve_twelve_data_request(self.connection, now)
        self.assertEqual((800, 0), twelve_data_usage(self.connection, now))

    def test_minute_guardrail_never_reserves_request_9(self):
        now = datetime.fromisoformat("2026-09-26T10:00:00+08:00")
        self.connection.execute(
            "INSERT INTO price_fetch_usage VALUES ('twelve_data_minute', '2026-09-26T02:00', 7)"
        )
        self.connection.commit()
        reserve_twelve_data_request(self.connection, now)
        with self.assertRaisesRegex(RuntimeError, "8/8"):
            reserve_twelve_data_request(self.connection, now)

    def test_refresh_writes_prices_and_skips_complete_range(self):
        instrument = create_instrument(self.connection, {
            "name": "Bitcoin", "ticker": "BTC",
            "asset_class": "crypto", "platform": "Kraken",
            "native_currency": "USD", "sector": "", "notes": "",
            "price_source": "twelve_data", "source_symbol": "BTC/USD",
        })
        record_buy(self.connection, {
            "instrument_id": str(instrument), "trade_date": "2026-09-24",
            "quantity": "10", "unit_price": "90", "fees": "0",
            "currency": "USD", "note": "", "zero_price_reason": "",
        })
        adapter = FakeAdapter([
            PricePoint(date(2026, 9, 24), 97500, "USD"),
            PricePoint(date(2026, 9, 25), 98900, "USD"),
        ])
        result = refresh_twelve_data_crypto_prices(
            self.connection, "secret", end_date=date(2026, 9, 25), adapter=adapter
        )
        self.assertEqual((1, 2, 1), (
            result.instruments_updated, result.prices_written, result.requests_used
        ))
        self.assertEqual(2, self.connection.execute(
            "SELECT COUNT(*) FROM prices WHERE source = 'Twelve Data daily close'"
        ).fetchone()[0])
        again = refresh_twelve_data_crypto_prices(
            self.connection, "secret", end_date=date(2026, 9, 25), adapter=adapter
        )
        self.assertEqual(0, again.requests_used)


if __name__ == "__main__":
    unittest.main()
