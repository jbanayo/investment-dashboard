import io
import tempfile
import unittest
from pathlib import Path

from portfolio import create_app
from portfolio.db import connect, migrate
from portfolio.instruments import create_instrument


class ResearchImportTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "portfolio.db"
        migrate(self.database)
        self.connection = connect(self.database)
        self.instrument_id = create_instrument(self.connection, {
            "name": "Apple", "ticker": "AAPL", "asset_class": "us_equity",
            "platform": "IBKR", "native_currency": "USD", "sector": "", "notes": "",
        })

    def tearDown(self):
        self.connection.close()
        self.temp_dir.cleanup()

    def test_import_page_saves_a_draft(self):
        self.connection.commit()
        self.connection.close()
        app = create_app({"TESTING": True, "DATABASE": str(self.database)})
        client = app.test_client()
        markdown = (
            Path(__file__).parent / "fixtures" / "research" / "apple-hold-v1.md"
        ).read_bytes()
        staged = client.post("/research/import", data={
            "instrument_id": str(self.instrument_id), "agent_name": "Codex",
            "research_file": (io.BytesIO(markdown), "apple.md"),
        })
        self.assertEqual(302, staged.status_code)
        self.assertIn("/research/import/preview/", staged.headers["Location"])
        preview = client.get(staged.headers["Location"])
        self.assertEqual(200, preview.status_code)
        self.assertIn(b"Preview AI findings", preview.data)
        self.assertIn(b"Apple&#39;s services growth", preview.data)
        with connect(self.database) as connection:
            self.assertEqual(0, connection.execute("SELECT COUNT(*) FROM research_items").fetchone()[0])

        response = client.post(f"{staged.headers['Location']}/confirm", follow_redirects=True)
        self.assertEqual(200, response.status_code)
        self.assertIn(b"AI-assisted research imported", response.data)
        self.assertIn(b"Apple&#39;s services growth", response.data)
        with connect(self.database) as connection:
            self.assertEqual(1, connection.execute("SELECT COUNT(*) FROM research_imports").fetchone()[0])
            self.assertEqual(0, connection.execute("SELECT COUNT(*) FROM research_import_previews").fetchone()[0])

        repeated = client.post(f"{staged.headers['Location']}/confirm", follow_redirects=True)
        self.assertIn(b"expired or was already used", repeated.data)
        with connect(self.database) as connection:
            self.assertEqual(1, connection.execute("SELECT COUNT(*) FROM research_items").fetchone()[0])
        self.connection = connect(self.database)


if __name__ == "__main__":
    unittest.main()
