import tempfile
import unittest
from datetime import date
from pathlib import Path

from portfolio import create_app
from portfolio.db import connect, migrate
from portfolio.instruments import create_instrument
from portfolio.research import (
    ResearchError, create_manual_research, monitored_research,
    transition_research_item, update_research_item,
)


class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "portfolio.db"
        migrate(self.database)
        self.connection = connect(self.database)
        self.apple_id = create_instrument(self.connection, {
            "name": "Apple", "ticker": "AAPL", "asset_class": "us_equity",
            "platform": "IBKR", "native_currency": "USD", "sector": "Technology",
            "notes": "",
        })

    def tearDown(self):
        self.connection.close()
        self.temp_dir.cleanup()

    def values(self, summary="Hold while services growth remains durable"):
        return {
            "instrument_id": str(self.apple_id), "research_date": "2026-09-26",
            "stance": "hold", "trigger_type": "at_or_above", "trigger_price": "250",
            "trigger_currency": "USD", "summary": summary,
            "supporting_points": "Services revenue growth\nStrong balance sheet",
            "risks": "Valuation compression", "confidence": "medium",
            "initial_status": "draft",
        }

    def test_manual_research_keeps_structured_evidence_and_audit_event(self):
        item_id = create_manual_research(self.connection, self.values())
        item = self.connection.execute(
            "SELECT * FROM research_items WHERE id = ?", (item_id,)
        ).fetchone()
        self.assertEqual("manual", item["origin"])
        self.assertEqual("draft", item["status"])
        self.assertIn("Services revenue growth", item["supporting_points_json"])
        self.assertEqual("generated", self.connection.execute(
            "SELECT event_type FROM research_events WHERE research_item_id = ?", (item_id,)
        ).fetchone()[0])

    def test_new_monitored_thesis_saves_the_previous_one(self):
        first = create_manual_research(self.connection, self.values("First thesis"))
        second = create_manual_research(self.connection, self.values("Updated thesis"))
        transition_research_item(self.connection, first, "monitoring")
        transition_research_item(self.connection, second, "monitoring")
        statuses = dict(self.connection.execute(
            "SELECT id, status FROM research_items ORDER BY id"
        ).fetchall())
        self.assertEqual({first: "saved", second: "monitoring"}, statuses)

    def test_price_trigger_requires_a_positive_price(self):
        values = self.values()
        values["trigger_price"] = ""
        with self.assertRaisesRegex(ResearchError, "trigger price"):
            create_manual_research(self.connection, values)

    def test_monitoring_reports_when_latest_price_meets_trigger(self):
        item_id = create_manual_research(self.connection, self.values())
        transition_research_item(self.connection, item_id, "monitoring")
        self.connection.execute(
            "INSERT INTO prices (instrument_id, price_date, price, currency, source) VALUES (?, '2026-09-26', 260, 'USD', 'manual')",
            (self.apple_id,),
        )
        item = monitored_research(self.connection, today=date(2026, 9, 28))[0]
        self.assertTrue(item["trigger_met"])
        self.assertEqual("review_due", item["monitoring_status"])
        self.assertEqual(260, item["current_price"])

    def test_monitoring_states_and_priority_order(self):
        stale_values = self.values("Stale thesis")
        stale_values["trigger_price"] = "400"
        stale = create_manual_research(self.connection, stale_values)
        second_instrument = create_instrument(self.connection, {
            "name": "Nvidia", "ticker": "NVDA", "asset_class": "us_equity",
            "platform": "IBKR", "native_currency": "USD", "sector": "Technology",
            "notes": "",
        })
        due_values = self.values("Due thesis")
        due_values["instrument_id"] = str(second_instrument)
        due = create_manual_research(self.connection, due_values)
        for item_id in (due, stale):
            transition_research_item(self.connection, item_id, "monitoring")
        self.connection.execute(
            "INSERT INTO prices (instrument_id, price_date, price, currency, source) "
            "VALUES (?, '2026-09-25', 260, 'USD', 'manual')", (second_instrument,)
        )
        self.connection.execute(
            "INSERT INTO prices (instrument_id, price_date, price, currency, source) "
            "VALUES (?, '2026-09-20', 200, 'USD', 'manual')", (self.apple_id,)
        )
        items = monitored_research(self.connection, today=date(2026, 9, 28))
        self.assertEqual(["review_due", "price_stale"], [item["monitoring_status"] for item in items])

    def test_expired_and_missing_price_states(self):
        expired = create_manual_research(self.connection, self.values("Expired thesis"))
        transition_research_item(self.connection, expired, "monitoring")
        self.connection.execute(
            "UPDATE research_items SET expires_on = '2026-09-26' WHERE id = ?", (expired,)
        )
        self.connection.execute(
            "INSERT INTO prices (instrument_id, price_date, price, currency, source) "
            "VALUES (?, '2026-09-25', 200, 'USD', 'manual')", (self.apple_id,)
        )
        item = monitored_research(self.connection, today=date(2026, 9, 28))[0]
        self.assertEqual("expired", item["monitoring_status"])
        self.connection.execute("DELETE FROM prices WHERE instrument_id = ?", (self.apple_id,))
        item = monitored_research(self.connection, today=date(2026, 9, 28))[0]
        self.assertEqual("expired", item["monitoring_status"])

    def test_edit_updates_working_thesis_and_records_event(self):
        item_id = create_manual_research(self.connection, self.values())
        updated = self.values("Revised thesis after earnings")
        updated["stance"] = "reduce"
        update_research_item(self.connection, item_id, updated)
        item = self.connection.execute(
            "SELECT * FROM research_items WHERE id = ?", (item_id,)
        ).fetchone()
        self.assertEqual("reduce", item["stance"])
        self.assertEqual("Revised thesis after earnings", item["summary"])
        self.assertEqual("edited", self.connection.execute(
            "SELECT event_type FROM research_events WHERE research_item_id = ? "
            "ORDER BY id DESC", (item_id,)
        ).fetchone()[0])

    def test_research_page_and_manual_form_are_functional(self):
        self.connection.commit()
        self.connection.close()
        app = create_app({"TESTING": True, "DATABASE": str(self.database)})
        client = app.test_client()
        response = client.post("/research/new", data=self.values(), follow_redirects=True)
        self.assertEqual(200, response.status_code)
        self.assertIn(b"Hold while services growth", response.data)
        self.assertIn(b"Research saved", response.data)
        with connect(self.database) as check:
            item_id = check.execute("SELECT id FROM research_items").fetchone()[0]
        edited = self.values("Edited from the browser")
        edited["stance"] = "sell"
        response = client.post(
            f"/research/{item_id}/edit", data=edited, follow_redirects=True
        )
        self.assertEqual(200, response.status_code)
        self.assertIn(b"Edited from the browser", response.data)
        self.assertIn(b"original imported Markdown was preserved", response.data)
        self.connection = connect(self.database)


if __name__ == "__main__":
    unittest.main()
