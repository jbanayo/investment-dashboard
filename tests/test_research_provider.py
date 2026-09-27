import json
import tempfile
import unittest
from pathlib import Path

from portfolio.db import connect, migrate
from portfolio.instruments import create_instrument
from portfolio.research import run_ai_research
from portfolio.research_provider import OpenAIWebResearchProvider


def result_payload(summary="Balanced sourced thesis"):
    return {
        "stance": "hold", "summary": summary,
        "supporting_points": ["Revenue is growing"], "risks": ["Valuation is elevated"],
        "confidence": "medium", "confidence_reason": "Evidence is mixed",
        "time_horizon": "12 months", "trigger_type": "at_or_below",
        "trigger_price": 180, "trigger_currency": "USD", "event_trigger": None,
        "source_target": None, "source_target_currency": None,
        "source_target_issuer": None,
        "sources": [{
            "title": "Apple investor update", "publisher": "Apple", "url": "https://apple.com/news",
            "published_at": "2026-09-20", "source_type": "company",
        }],
    }


class FakeHttpClient:
    def __init__(self):
        self.payload = None

    def post_json(self, endpoint, payload, headers):
        self.payload = payload
        result = result_payload()
        return {
            "status": "completed",
            "output": [{
                "type": "message", "content": [{
                    "type": "output_text", "text": json.dumps(result),
                    "annotations": [{
                        "type": "url_citation", "url": "https://apple.com/news",
                        "title": "Apple investor update",
                    }],
                }],
            }],
        }


class FakeProvider:
    provider_name = "test"
    model = "test-model"
    api_key = "super-secret"

    def research(self, instrument, focus_prompt=""):
        if instrument["ticker"] == "FAIL":
            raise RuntimeError("provider failed with super-secret")
        return result_payload(f"Research for {instrument['ticker']}")


class ResearchProviderTests(unittest.TestCase):
    def test_openai_adapter_uses_web_search_schema_and_keeps_verified_citations(self):
        client = FakeHttpClient()
        provider = OpenAIWebResearchProvider("key", "gpt-test", client)
        result = provider.research({
            "name": "Apple", "ticker": "AAPL", "asset_class": "us_equity",
            "platform": "IBKR", "native_currency": "USD", "market_price": 200,
            "market_price_date": "2026-09-25", "current_thesis": None,
        }, "Focus on earnings")

        self.assertEqual("hold", result["stance"])
        self.assertEqual("https://apple.com/news", result["sources"][0]["url"])
        self.assertEqual("web_search", client.payload["tools"][0]["type"])
        self.assertEqual("json_schema", client.payload["text"]["format"]["type"])
        prompt = client.payload["input"]
        self.assertIn("Focus on earnings", prompt)
        self.assertNotIn("quantity", prompt.lower())
        self.assertNotIn("cost basis", prompt.lower())

    def test_partial_run_keeps_successful_draft_and_redacts_credentials(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "portfolio.db"
            migrate(database)
            with connect(database) as connection:
                apple = create_instrument(connection, {
                    "name": "Apple", "ticker": "AAPL", "asset_class": "us_equity",
                    "platform": "IBKR", "native_currency": "USD", "sector": "", "notes": "",
                })
                failed = create_instrument(connection, {
                    "name": "Failed", "ticker": "FAIL", "asset_class": "us_equity",
                    "platform": "IBKR", "native_currency": "USD", "sector": "", "notes": "",
                })
                outcome = run_ai_research(connection, FakeProvider(), [apple, failed], "quality")
                self.assertEqual(1, outcome.created)
                self.assertEqual(1, len(outcome.failures))
                self.assertNotIn("super-secret", outcome.failures[0])
                run = connection.execute("SELECT * FROM research_runs WHERE id = ?", (outcome.run_id,)).fetchone()
                self.assertEqual("partial", run["status"])
                item = connection.execute("SELECT * FROM research_items").fetchone()
                self.assertEqual("ai", item["origin"])
                self.assertEqual("draft", item["status"])
                self.assertEqual(1, connection.execute("SELECT COUNT(*) FROM research_sources").fetchone()[0])


if __name__ == "__main__":
    unittest.main()
