import tempfile
import unittest
from pathlib import Path

from portfolio.db import connect, migrate
from portfolio.instruments import (
    InstrumentError, create_instrument, delete_instrument, list_instruments,
    update_instrument,
)


class InstrumentTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "portfolio.db"
        migrate(self.database)
        self.connection = connect(self.database)

    def tearDown(self):
        self.connection.close()
        self.temp_dir.cleanup()

    def test_create_and_filter_instruments(self):
        create_instrument(self.connection, {"name": "Apple", "ticker": "aapl", "asset_class": "us_equity", "platform": "IBKR", "native_currency": "usd", "sector": "Technology", "notes": ""})
        create_instrument(self.connection, {"name": "Bitcoin", "ticker": "btc", "asset_class": "crypto", "platform": "Kraken", "native_currency": "usd", "sector": "", "notes": ""})
        self.connection.commit()
        instruments = list_instruments(self.connection, platform="IBKR")
        self.assertEqual(["Apple"], [record["name"] for record in instruments])
        self.assertEqual("USD", instruments[0]["native_currency"])

    def test_currency_change_and_delete_are_blocked_after_transaction(self):
        instrument_id = create_instrument(self.connection, {"name": "Apple", "ticker": "AAPL", "asset_class": "us_equity", "platform": "IBKR", "native_currency": "USD", "sector": "", "notes": ""})
        self.connection.execute("INSERT INTO transactions (instrument_id, type, trade_date, currency, source_type, platform) VALUES (?, 'buy', '2026-09-24', 'USD', 'manual', 'IBKR')", (instrument_id,))
        with self.assertRaisesRegex(InstrumentError, "Native currency"):
            update_instrument(self.connection, instrument_id, {"name": "Apple", "ticker": "AAPL", "asset_class": "us_equity", "platform": "IBKR", "native_currency": "PHP", "sector": "", "notes": ""})
        with self.assertRaisesRegex(InstrumentError, "transaction"):
            delete_instrument(self.connection, instrument_id)
