import json
import tempfile
import unittest
from pathlib import Path

from portfolio import create_app
from portfolio.db import connect, migrate
from portfolio.instruments import create_instrument
from portfolio.research import ResearchError, import_ai_research


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

    def payload(self):
        return {
            "stance": "hold", "summary": "Growth remains durable, but valuation needs review.",
            "supporting_points": ["Services revenue increased."],
            "risks": ["Multiple compression."], "confidence": "medium",
            "confidence_reason": "The evidence is mixed.", "time_horizon": "12 months",
            "trigger_type": "at_or_above", "trigger_price": 250,
            "trigger_currency": "USD", "event_trigger": None,
            "source_target": None, "source_target_currency": None,
            "source_target_issuer": None,
            "sources": [{
                "title": "Apple investor relations", "publisher": "Apple",
                "url": "https://investor.apple.com", "published_at": "2026-09-20",
                "source_type": "company",
            }],
        }

    def values(self):
        return {
            "instrument_id": str(self.instrument_id), "research_date": "2026-09-27",
            "agent_name": "Codex", "research_json": json.dumps(self.payload()),
        }

    def test_import_creates_ai_draft_with_sources(self):
        item_id = import_ai_research(self.connection, self.values())
        item = self.connection.execute("SELECT * FROM research_items WHERE id = ?", (item_id,)).fetchone()
        self.assertEqual("ai", item["origin"])
        self.assertEqual("draft", item["status"])
        source = self.connection.execute("SELECT * FROM research_sources WHERE research_item_id = ?", (item_id,)).fetchone()
        self.assertEqual("company", source["source_type"])
        event = self.connection.execute("SELECT detail FROM research_events WHERE research_item_id = ?", (item_id,)).fetchone()
        self.assertEqual("Imported from Codex", event["detail"])

    def test_import_requires_valid_source_url(self):
        values = self.values()
        payload = self.payload()
        payload["sources"][0]["url"] = "not-a-url"
        values["research_json"] = json.dumps(payload)
        with self.assertRaisesRegex(ResearchError, "valid http"):
            import_ai_research(self.connection, values)

    def test_import_page_saves_a_draft(self):
        self.connection.commit()
        self.connection.close()
        app = create_app({"TESTING": True, "DATABASE": str(self.database)})
        response = app.test_client().post("/research/import", data=self.values(), follow_redirects=True)
        self.assertEqual(200, response.status_code)
        self.assertIn(b"AI-assisted research imported", response.data)
        self.assertIn(b"Growth remains durable", response.data)
        self.connection = connect(self.database)


if __name__ == "__main__":
    unittest.main()
