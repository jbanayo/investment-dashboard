import sqlite3
import tempfile
import unittest
from pathlib import Path

from portfolio.db import connect, migrate


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "portfolio.db"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_initial_migration_creates_required_tables_and_is_idempotent(self):
        migrate(self.database)
        migrate(self.database)

        with connect(self.database) as connection:
            tables = {
                row["name"]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            self.assertTrue(
                {
                    "instruments", "transactions", "prices", "fx_rates",
                    "ratings", "documents", "notes", "schema_migrations",
                }.issubset(tables)
            )
            self.assertEqual(
                2,
                connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0],
            )

    def test_foreign_keys_and_platform_scoped_external_ids_are_enforced(self):
        migrate(self.database)
        with connect(self.database) as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO prices (instrument_id, price_date, price, currency, source) "
                    "VALUES (999, '2026-09-24', 1, 'PHP', 'manual')"
                )

            instrument_id = connection.execute(
                "INSERT INTO instruments (name, asset_class, platform, native_currency) "
                "VALUES ('Test asset', 'us_equity', 'IBKR', 'USD')"
            ).lastrowid
            values = (instrument_id, "buy", "2026-09-24", "USD", "import", "IBKR-1", "IBKR")
            connection.execute(
                "INSERT INTO transactions "
                "(instrument_id, type, trade_date, currency, source_type, external_id, platform) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                values,
            )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO transactions "
                    "(instrument_id, type, trade_date, currency, source_type, external_id, platform) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    values,
                )
