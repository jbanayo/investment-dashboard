import sqlite3
import tempfile
import unittest
from pathlib import Path

from portfolio.db import MIGRATIONS_DIR, connect, migrate


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
                    "price_fetch_usage", "instrument_source_mappings",
                    "research_runs", "research_items", "research_sources",
                    "research_events", "research_imports",
                    "research_import_previews", "watchlist",
                }.issubset(tables)
            )
            self.assertEqual(
                14,
                connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0],
            )

    def test_research_import_artifact_and_preview_constraints(self):
        migrate(self.database)
        with connect(self.database) as connection:
            instrument_id = connection.execute(
                "INSERT INTO instruments "
                "(name, ticker, asset_class, platform, native_currency) "
                "VALUES ('Apple', 'AAPL', 'us_equity', 'IBKR', 'USD')"
            ).lastrowid
            item_id = connection.execute(
                """INSERT INTO research_items
                   (instrument_id, origin, status, stance, research_date, summary)
                   VALUES (?, 'ai', 'draft', 'hold', '2026-09-28', 'Test thesis')""",
                (instrument_id,),
            ).lastrowid
            connection.execute(
                """INSERT INTO research_imports
                   (research_item_id, format_version, filename, raw_content,
                    normalized_payload_json)
                   VALUES (?, 1, 'apple.md', '# Thesis', '{}')""",
                (item_id,),
            )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    """INSERT INTO research_imports
                       (research_item_id, format_version, filename, raw_content,
                        normalized_payload_json)
                       VALUES (?, 1, 'duplicate.md', '# Thesis', '{}')""",
                    (item_id,),
                )
            connection.execute(
                """INSERT INTO research_import_previews
                   (id, instrument_id, filename, raw_content,
                    normalized_payload_json, expires_at)
                   VALUES ('preview-token', ?, 'apple.md', '# Thesis', '{}',
                           '2026-09-28 12:00:00')""",
                (instrument_id,),
            )

            connection.execute("DELETE FROM research_items WHERE id = ?", (item_id,))
            self.assertEqual(
                0,
                connection.execute("SELECT COUNT(*) FROM research_imports").fetchone()[0],
            )
            connection.execute("DELETE FROM instruments WHERE id = ?", (instrument_id,))
            self.assertEqual(
                0,
                connection.execute("SELECT COUNT(*) FROM research_import_previews").fetchone()[0],
            )

    def test_upgrade_from_migration_13_preserves_existing_research(self):
        with connect(self.database) as connection:
            connection.execute(
                """CREATE TABLE schema_migrations (
                       version TEXT PRIMARY KEY,
                       applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                   )"""
            )
            for migration_path in sorted(MIGRATIONS_DIR.glob("*.sql")):
                version = migration_path.stem.split("_", 1)[0]
                if int(version) >= 14:
                    continue
                connection.executescript(migration_path.read_text())
                connection.execute(
                    "INSERT INTO schema_migrations (version) VALUES (?)", (version,)
                )
            instrument_id = connection.execute(
                "INSERT INTO instruments "
                "(name, ticker, asset_class, platform, native_currency) "
                "VALUES ('Apple', 'AAPL', 'us_equity', 'IBKR', 'USD')"
            ).lastrowid
            item_id = connection.execute(
                """INSERT INTO research_items
                   (instrument_id, origin, status, stance, research_date, summary)
                   VALUES (?, 'manual', 'saved', 'hold', '2026-09-28',
                           'Existing thesis')""",
                (instrument_id,),
            ).lastrowid

        migrate(self.database)

        with connect(self.database) as connection:
            item = connection.execute(
                "SELECT status, summary FROM research_items WHERE id = ?", (item_id,)
            ).fetchone()
            self.assertEqual(("saved", "Existing thesis"), tuple(item))
            self.assertEqual(
                14,
                connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0],
            )
            tables = {
                row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            self.assertIn("research_imports", tables)
            self.assertIn("research_import_previews", tables)

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
