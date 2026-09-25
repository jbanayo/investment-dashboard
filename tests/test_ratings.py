import tempfile
import unittest
from pathlib import Path

from portfolio.db import connect, migrate
from portfolio.instruments import create_instrument
from portfolio.ratings import append_rating, current_rating, rating_history


class RatingTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "portfolio.db"
        migrate(self.database)
        self.connection = connect(self.database)
        self.instrument = create_instrument(self.connection, {"name":"Apple","ticker":"AAPL","asset_class":"us_equity","platform":"IBKR","native_currency":"USD","sector":"","notes":"","coverage_status":"covered"})

    def tearDown(self):
        self.connection.close(); self.temp_dir.cleanup()

    def rating(self, issued_date, rating="Buy", target="250"):
        return {"instrument_id":str(self.instrument),"issuer":"Consensus","rating":rating,"target_price":target,"target_currency":"USD","issued_date":issued_date,"source_type":"manual"}

    def test_history_is_append_only_and_older_entry_does_not_become_current(self):
        newest = append_rating(self.connection, self.rating("2026-09-20"))
        append_rating(self.connection, self.rating("2026-08-01", "Hold", "220"))
        self.assertEqual(newest, current_rating(self.connection, self.instrument)["id"])
        self.assertEqual(2, len(rating_history(self.connection, self.instrument)))

    def test_identical_latest_rating_is_not_written_twice(self):
        append_rating(self.connection, self.rating("2026-09-20"))
        self.assertIsNone(append_rating(self.connection, self.rating("2026-09-20")))
