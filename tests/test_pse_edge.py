import tempfile
import unittest
from datetime import date
from pathlib import Path

from portfolio.db import connect, migrate
from portfolio.instruments import create_instrument
from portfolio.positions import portfolio_snapshot
from portfolio.pse_edge import PseEdgeClient, refresh_pse_edge_prices
from portfolio.transactions import record_buy, record_sell
from portfolio.fetch import PricePoint


class FakePseClient:
    def __init__(self):
        self.requests_used = 0
        self.resolutions = []
        self.fetches = []

    def resolve(self, symbol):
        self.requests_used += 2
        self.resolutions.append(symbol)
        return "234", "101"

    def fetch_history(self, company_id, security_id, start_date, end_date):
        self.requests_used += 1
        self.fetches.append((company_id, security_id, start_date, end_date))
        return [
            PricePoint(date(2026, 6, 16), 96.25, "PHP"),
            PricePoint(date(2026, 6, 17), 97.50, "PHP"),
        ]


class FakeHttpClient(PseEdgeClient):
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests_used = 0

    def _request(self, request):
        self.requests_used += 1
        return next(self.responses)


class PseEdgeTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "portfolio.db"
        migrate(self.database)
        self.connection = connect(self.database)

    def tearDown(self):
        self.connection.close()
        self.temp_dir.cleanup()

    def instrument(self, ticker, platform="BDO Securities"):
        return create_instrument(self.connection, {
            "name": ticker, "ticker": ticker, "asset_class": "ph_equity",
            "platform": platform, "native_currency": "PHP", "sector": "",
            "notes": "", "price_source": "manual", "source_symbol": ticker,
        })

    def buy(self, instrument, day="2026-06-15", quantity="10"):
        record_buy(self.connection, {
            "instrument_id": str(instrument), "trade_date": day,
            "quantity": quantity, "unit_price": "90", "fees": "0",
            "currency": "PHP", "note": "", "zero_price_reason": "",
        })

    def test_client_parses_exact_ticker_security_and_chart(self):
        client = FakeHttpClient([
            b'[{"cmpyId":"234","symbol":"BPI"}]',
            b'<select name="security_id"><option value="101">BPI Common</option></select>',
            b'{"chartData":[{"CHART_DATE":"Jun 17, 2026 00:00:00","CLOSE":98.9}]}',
        ])
        self.assertEqual(("234", "101"), client.resolve("BPI"))
        points = client.fetch_history("234", "101", date(2026, 6, 1), date(2026, 6, 17))
        self.assertEqual((date(2026, 6, 17), 98.9, "PHP"), (
            points[0].price_date, points[0].close, points[0].currency
        ))

    def test_refresh_fetches_only_bdo_ledger_instruments_and_caches_mappings(self):
        current = self.instrument("BPI")
        sold = self.instrument("ALI")
        other = self.instrument("AC", platform="Other Broker")
        self.buy(current)
        self.buy(sold)
        record_sell(self.connection, {
            "instrument_id": str(sold), "trade_date": "2026-06-16",
            "quantity": "10", "unit_price": "95", "fees": "0",
            "currency": "PHP", "note": "", "zero_price_reason": "",
        })
        self.buy(other)
        client = FakePseClient()

        result = refresh_pse_edge_prices(
            self.connection, end_date=date(2026, 6, 17), client=client
        )

        self.assertEqual((2, 4, 6), (
            result.instruments_updated, result.prices_written, result.requests_used
        ))
        self.assertEqual(["ALI", "BPI"], client.resolutions)
        self.assertEqual(2, self.connection.execute(
            "SELECT COUNT(*) FROM instrument_source_mappings"
        ).fetchone()[0])
        self.assertEqual("pse_edge", self.connection.execute(
            "SELECT price_source FROM instruments WHERE id = ?", (current,)
        ).fetchone()[0])

        again = refresh_pse_edge_prices(
            self.connection, end_date=date(2026, 6, 17), client=client
        )
        self.assertEqual(0, again.requests_used)

    def test_statement_price_wins_over_fetched_close_on_same_date(self):
        instrument = self.instrument("BPI")
        self.buy(instrument)
        refresh_pse_edge_prices(
            self.connection, end_date=date(2026, 6, 17), client=FakePseClient()
        )
        self.connection.execute(
            """INSERT INTO prices (instrument_id, price_date, price, currency, source)
               VALUES (?, '2026-06-17', 98.90, 'PHP', 'BDO statement ending position')""",
            (instrument,),
        )

        snapshot = portfolio_snapshot(self.connection, "PHP", "2026-06-17")

        position = next(
            item for item in snapshot["positions"]
            if item["instrument"]["id"] == instrument
        )
        self.assertEqual(98.9, position["price"]["price"])
        self.assertEqual(
            "BDO statement ending position", position["price"]["source"]
        )


if __name__ == "__main__":
    unittest.main()
