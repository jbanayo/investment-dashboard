import tempfile
import unittest
import io
from datetime import date
from pathlib import Path

from portfolio import create_app
from portfolio.db import connect, migrate
from portfolio.instruments import create_instrument
from portfolio.research import (
    ResearchError, create_manual_research, export_research_markdown, list_research, monitored_research,
    transition_research_item, update_research_item,
)
from portfolio.research_import import parse_research_markdown


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

    def test_draft_compares_with_current_monitored_thesis(self):
        current = create_manual_research(self.connection, self.values("Current thesis"))
        transition_research_item(self.connection, current, "monitoring")
        draft_values = self.values("New evidence changes the thesis")
        draft_values.update({
            "stance": "reduce", "trigger_price": "225", "confidence": "high",
        })
        draft = create_manual_research(self.connection, draft_values)

        items = list_research(self.connection, "draft")

        self.assertEqual(draft, items[0]["id"])
        comparison = items[0]["comparison"]
        self.assertEqual(current, comparison["current_id"])
        self.assertTrue(comparison["summary_changed"])
        self.assertEqual(
            ["Stance", "Review condition", "Confidence"],
            [change["label"] for change in comparison["changes"]],
        )

    def test_draft_without_monitored_thesis_has_no_comparison(self):
        create_manual_research(self.connection, self.values())
        self.assertIsNone(list_research(self.connection, "draft")[0]["comparison"])

    def test_research_page_renders_draft_comparison(self):
        current = create_manual_research(self.connection, self.values("Current thesis"))
        transition_research_item(self.connection, current, "monitoring")
        proposed = self.values("Proposed replacement thesis")
        proposed["stance"] = "reduce"
        create_manual_research(self.connection, proposed)
        self.connection.commit()
        self.connection.close()
        app = create_app({"TESTING": True, "DATABASE": str(self.database)})

        response = app.test_client().get("/research?status=draft")

        self.assertEqual(200, response.status_code)
        self.assertIn(b"Compare with monitored thesis", response.data)
        self.assertIn(b"Current thesis", response.data)
        self.assertIn(b"Proposed replacement thesis", response.data)
        self.connection = connect(self.database)

    def test_monitored_thesis_prefills_replacement_prompt(self):
        item_id = create_manual_research(self.connection, self.values("Current Apple thesis"))
        transition_research_item(self.connection, item_id, "monitoring")
        self.connection.commit()
        self.connection.close()
        app = create_app({"TESTING": True, "DATABASE": str(self.database)})
        client = app.test_client()

        monitoring = client.get("/research?status=monitoring")
        prompt = client.get(f"/research/import?replace={item_id}")

        self.assertIn(b"Research an update", monitoring.data)
        self.assertEqual(200, prompt.status_code)
        self.assertIn(b"Reassess the current hold thesis", prompt.data)
        self.assertIn(b"Current Apple thesis", prompt.data)
        self.assertIn(b'value="1" data-name="Apple"', prompt.data)
        self.connection = connect(self.database)

    def test_exported_research_is_a_parseable_markdown_download(self):
        values = self.values("Portable Apple thesis")
        values.update({
            "source_url": "https://investor.apple.com/",
            "source_title": "Apple Investor Relations", "source_publisher": "Apple",
        })
        item_id = create_manual_research(self.connection, values)
        filename, markdown = export_research_markdown(self.connection, item_id)
        parsed = parse_research_markdown(markdown.encode(), filename, "AAPL")
        self.assertEqual("Portable Apple thesis", parsed.payload["summary"])
        self.assertEqual("Apple Investor Relations", parsed.payload["sources"][0]["title"])
        self.connection.commit()
        self.connection.close()
        app = create_app({"TESTING": True, "DATABASE": str(self.database)})

        response = app.test_client().get(f"/research/{item_id}/export")

        self.assertEqual(200, response.status_code)
        self.assertIn("aapl-research-2026-09-26.md", response.headers["Content-Disposition"])
        self.assertEqual(markdown.encode(), response.data)
        self.connection = connect(self.database)

    def test_research_attachment_is_validated_stored_downloaded_and_reset(self):
        item_id = create_manual_research(self.connection, self.values())
        self.connection.commit()
        self.connection.close()
        upload_dir = Path(self.temp_dir.name) / "uploads"
        app = create_app({
            "TESTING": True, "DATABASE": str(self.database),
            "RESEARCH_UPLOAD_DIR": str(upload_dir),
        })
        client = app.test_client()
        png = b"\x89PNG\r\n\x1a\n" + b"test image content"

        invalid = client.post(f"/research/{item_id}/attachments", data={
            "return_status": "draft", "attachment": (io.BytesIO(b"not an image"), "fake.png"),
        }, follow_redirects=True)
        self.assertIn(b"Choose a PDF, PNG, JPEG, GIF, or WebP", invalid.data)
        response = client.post(f"/research/{item_id}/attachments", data={
            "return_status": "draft", "attachment": (io.BytesIO(png), "chart.png"),
        }, follow_redirects=True)
        self.assertIn(b"Attached chart.png", response.data)
        with connect(self.database) as connection:
            document = connection.execute(
                "SELECT * FROM documents WHERE doc_type = 'research_attachment'"
            ).fetchone()
        stored = Path(document["stored_path"])
        self.assertTrue(stored.is_file())
        download = client.get(f"/research/documents/{document['id']}")
        self.assertEqual(png, download.data)
        self.assertIn("chart.png", download.headers["Content-Disposition"])
        download.close()

        client.post("/settings/database/reset", data={"confirmation": "RESET"})
        self.assertFalse(stored.exists())
        self.connection = connect(self.database)

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
        outcome = self.connection.execute(
            "SELECT * FROM research_outcomes WHERE research_item_id = ?", (item_id,)
        ).fetchone()
        self.assertEqual("trigger_reached", outcome["event_type"])
        self.assertEqual(260, outcome["price"])
        # Re-evaluation does not duplicate the first reached event.
        monitored_research(self.connection, today=date(2026, 9, 28))
        self.assertEqual(1, self.connection.execute(
            "SELECT COUNT(*) FROM research_outcomes WHERE research_item_id = ?", (item_id,)
        ).fetchone()[0])

    def test_archive_records_price_and_later_performance_as_context(self):
        item_id = create_manual_research(self.connection, self.values())
        self.connection.execute(
            "INSERT INTO prices (instrument_id, price_date, price, currency, source) "
            "VALUES (?, '2026-09-26', 200, 'USD', 'manual')", (self.apple_id,)
        )
        transition_research_item(self.connection, item_id, "archived")
        self.connection.execute(
            "INSERT INTO prices (instrument_id, price_date, price, currency, source) "
            "VALUES (?, '2026-10-01', 220, 'USD', 'manual')", (self.apple_id,)
        )

        item = list_research(self.connection, "archived")[0]

        self.assertEqual("archived", item["outcomes"][0]["event_type"])
        self.assertEqual(200, item["outcomes"][0]["price"])
        self.assertAlmostEqual(0.1, item["outcomes"][0]["later_performance"])

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
