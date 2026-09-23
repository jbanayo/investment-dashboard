import tempfile
import unittest
from pathlib import Path

from portfolio.cash import ensure_cash_instruments
from portfolio.db import connect, migrate
from portfolio.instruments import create_instrument
from portfolio.prices import record_manual_price
from portfolio.reconciliation import record_reconciliation
from portfolio.transactions import record_buy


class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "portfolio.db"
        migrate(self.database)
        self.connection = connect(self.database)
        ensure_cash_instruments(self.connection)
        self.instrument = create_instrument(self.connection, {"name": "PSE", "ticker": "PSE", "asset_class": "ph_equity", "platform": "BDO Securities", "native_currency": "PHP", "sector": "", "notes": ""})
        record_buy(self.connection, {"instrument_id": str(self.instrument), "trade_date": "2026-09-20", "quantity": "10", "unit_price": "100", "fees": "0", "currency": "PHP", "note": "", "zero_price_reason": ""})
        record_manual_price(self.connection, {"instrument_id": str(self.instrument), "price_date": "2026-09-20", "price": "110", "currency": "PHP"})

    def tearDown(self):
        self.connection.close()
        self.temp_dir.cleanup()

    def test_reconciliation_records_exact_difference(self):
        record_id = record_reconciliation(self.connection, "100", reconciliation_date="2026-09-20")
        row = self.connection.execute("SELECT dashboard_total, spreadsheet_total, difference FROM reconciliation_records WHERE id = ?", (record_id,)).fetchone()
        self.assertEqual((100, 100, 0), tuple(row))
