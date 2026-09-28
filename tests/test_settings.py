import sqlite3
import tempfile
import unittest
from pathlib import Path

from portfolio import create_app
from portfolio.cash import ensure_cash_instruments
from portfolio.db import connect, migrate
from portfolio.instruments import create_instrument
from portfolio.settings import portfolio_preferences, reset_portfolio_data, save_portfolio_preferences
from portfolio.research import create_manual_research
from portfolio.transactions import record_buy


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "portfolio.db"
        migrate(self.database)
        self.connection = connect(self.database)
        ensure_cash_instruments(self.connection)

    def tearDown(self):
        self.connection.close()
        self.temp_dir.cleanup()

    def test_preferences_are_saved(self):
        save_portfolio_preferences(self.connection, "Long-term Fund", "usd", "dark")
        self.assertEqual(
            {"display_name": "Long-term Fund", "base_currency": "USD", "theme": "dark"},
            portfolio_preferences(self.connection),
        )

    def test_reset_removes_linked_data_and_retains_preferences(self):
        save_portfolio_preferences(self.connection, "My Portfolio", "PHP", "light")
        instrument_id = create_instrument(self.connection, {
            "name": "Apple", "ticker": "AAPL", "asset_class": "us_equity",
            "platform": "IBKR", "native_currency": "USD", "sector": "", "notes": "",
        })
        record_buy(self.connection, {
            "instrument_id": str(instrument_id), "trade_date": "2026-09-20",
            "quantity": "1", "unit_price": "100", "fees": "0", "currency": "USD",
            "note": "", "zero_price_reason": "",
        })
        research_id = create_manual_research(self.connection, {
            "instrument_id": str(instrument_id), "research_date": "2026-09-20",
            "stance": "hold", "trigger_type": "none", "summary": "Test thesis",
            "supporting_points": "", "risks": "", "confidence": "medium",
            "time_horizon": "12 months", "initial_status": "draft",
        })
        self.connection.execute(
            """INSERT INTO research_imports
               (research_item_id, format_version, filename, raw_content,
                normalized_payload_json)
               VALUES (?, 1, 'test.md', '# Thesis', '{}')""",
            (research_id,),
        )
        self.connection.execute(
            """INSERT INTO research_import_previews
               (id, instrument_id, filename, raw_content,
                normalized_payload_json, expires_at)
               VALUES ('test-preview', ?, 'test.md', '# Thesis', '{}',
                       '2026-09-28 12:00:00')""",
            (instrument_id,),
        )

        reset_portfolio_data(self.connection)

        self.assertEqual(0, self.connection.execute("SELECT COUNT(*) FROM transactions").fetchone()[0])
        self.assertEqual(0, self.connection.execute("SELECT COUNT(*) FROM instruments").fetchone()[0])
        self.assertEqual(0, self.connection.execute("SELECT COUNT(*) FROM research_imports").fetchone()[0])
        self.assertEqual(0, self.connection.execute("SELECT COUNT(*) FROM research_import_previews").fetchone()[0])
        self.assertEqual("My Portfolio", portfolio_preferences(self.connection)["display_name"])

    def test_settings_page_export_and_reset_confirmation(self):
        self.connection.close()
        app = create_app({"TESTING": True, "DATABASE": str(self.database)})
        client = app.test_client()

        response = client.post("/settings", data={
            "display_name": "Catherine's Portfolio", "base_currency": "USD", "theme": "dark",
        }, follow_redirects=True)
        self.assertEqual(200, response.status_code)
        self.assertIn(b"Catherine&#39;s Portfolio", response.data)
        self.assertIn(b'data-theme="dark"', response.data)
        self.assertIn(b"1.1.0", response.data)

        export = client.get("/settings/database/export")
        self.assertEqual(200, export.status_code)
        self.assertIn("portfolio-backup.db", export.headers["Content-Disposition"])
        exported = Path(self.temp_dir.name) / "exported.db"
        exported.write_bytes(export.data)
        with sqlite3.connect(exported) as backup:
            self.assertEqual("USD", backup.execute(
                "SELECT value FROM app_settings WHERE key = 'portfolio_base_currency'"
            ).fetchone()[0])
        export.close()

        rejected = client.post("/settings/database/reset", data={"confirmation": "reset"})
        self.assertEqual(302, rejected.status_code)

    def test_database_export_includes_research_import_artifacts(self):
        instrument_id = create_instrument(self.connection, {
            "name": "Apple", "ticker": "AAPL", "asset_class": "us_equity",
            "platform": "IBKR", "native_currency": "USD", "sector": "", "notes": "",
        })
        research_id = create_manual_research(self.connection, {
            "instrument_id": str(instrument_id), "research_date": "2026-09-20",
            "stance": "hold", "trigger_type": "none", "summary": "Test thesis",
            "supporting_points": "", "risks": "", "confidence": "medium",
            "time_horizon": "12 months", "initial_status": "draft",
        })
        self.connection.execute(
            """INSERT INTO research_imports
               (research_item_id, format_version, filename, raw_content,
                normalized_payload_json)
               VALUES (?, 1, 'apple.md', '# Thesis', '{}')""",
            (research_id,),
        )
        self.connection.commit()
        self.connection.close()

        app = create_app({"TESTING": True, "DATABASE": str(self.database)})
        export = app.test_client().get("/settings/database/export")
        exported = Path(self.temp_dir.name) / "research-export.db"
        exported.write_bytes(export.data)
        export.close()
        with sqlite3.connect(exported) as backup:
            artifact = backup.execute(
                "SELECT filename, raw_content FROM research_imports"
            ).fetchone()
        self.assertEqual(("apple.md", "# Thesis"), artifact)
        self.connection = connect(self.database)


if __name__ == "__main__":
    unittest.main()
