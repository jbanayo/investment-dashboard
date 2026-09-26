import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from portfolio.db import connect, migrate
from portfolio.fetch import BoundedHttpClient, lookup_count, refreshable_instruments
from portfolio.instruments import create_instrument


class FetchContractTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "portfolio.db"
        migrate(self.database)
        self.connection = connect(self.database)

    def tearDown(self):
        self.connection.close()
        self.temp_dir.cleanup()

    def test_only_live_source_mappings_are_counted_for_refresh(self):
        base = {"ticker": "", "asset_class": "crypto", "platform": "Kraken", "native_currency": "USD", "sector": "", "notes": ""}
        create_instrument(self.connection, {**base, "name": "Manual", "price_source": "manual", "source_symbol": "BTCUSD"})
        create_instrument(self.connection, {**base, "name": "Live", "price_source": "kraken", "source_symbol": "XBTUSD"})
        self.assertEqual(1, lookup_count(self.connection))
        self.assertEqual("XBTUSD", refreshable_instruments(self.connection)[0]["source_symbol"])

    def test_http_boundary_sends_only_adapter_parameters_with_a_timeout(self):
        captured = {}

        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self): return b'{"ok": true}'

        def fake_urlopen(url, timeout, context):
            captured.update(url=url, timeout=timeout)
            return Response()

        with patch("portfolio.fetch.urlopen", fake_urlopen):
            BoundedHttpClient(timeout_seconds=7).get_json(
                "https://prices.example.test/ohlc",
                {"symbol": "XBTUSD", "start": "2026-01-01", "end": "2026-09-24"},
            )
        self.assertEqual(7, captured["timeout"])
        self.assertIn("symbol=XBTUSD", captured["url"])
        for forbidden in ("quantity", "cost", "total", "platform", "account"):
            self.assertNotIn(forbidden, captured["url"])
