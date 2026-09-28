import unittest
from pathlib import Path

from portfolio.research_import import (
    MAX_IMPORT_BYTES,
    ResearchImportError,
    parse_research_markdown,
)


FIXTURE = Path(__file__).parent / "fixtures" / "research" / "apple-hold-v1.md"


class ResearchMarkdownTests(unittest.TestCase):
    def valid_content(self) -> bytes:
        return FIXTURE.read_bytes()

    def parse(self, content: bytes | None = None, filename: str = "apple.md", ticker: str = "AAPL"):
        return parse_research_markdown(content or self.valid_content(), filename, ticker)

    def replace(self, old: str, new: str) -> bytes:
        return self.valid_content().decode().replace(old, new).encode()

    def test_valid_file_is_normalized_without_warnings(self):
        result = self.parse()
        self.assertEqual("AAPL", result.payload["ticker"])
        self.assertEqual("hold", result.payload["stance"])
        self.assertEqual(250, result.payload["trigger_price"])
        self.assertEqual(2, len(result.payload["supporting_points"]))
        self.assertEqual("company", result.payload["sources"][0]["source_type"])
        self.assertEqual((), result.warnings)

    def test_rejects_invalid_file_type_size_and_encoding(self):
        with self.assertRaisesRegex(ResearchImportError, r"\.md"):
            self.parse(filename="apple.txt")
        with self.assertRaisesRegex(ResearchImportError, "1 MB"):
            self.parse(b"x" * (MAX_IMPORT_BYTES + 1))
        with self.assertRaisesRegex(ResearchImportError, "UTF-8"):
            self.parse(b"\xff\xfe")

    def test_rejects_missing_and_duplicate_sections(self):
        missing = self.replace("## Risks", "## Other")
        with self.assertRaisesRegex(ResearchImportError, "risks"):
            self.parse(missing)
        duplicate = self.valid_content() + b"\n## Risks\n\n- Another risk\n"
        with self.assertRaisesRegex(ResearchImportError, "more than once"):
            self.parse(duplicate)

    def test_rejects_malformed_or_unsupported_frontmatter(self):
        malformed = self.replace("format_version: 1", "format_version 1")
        with self.assertRaisesRegex(ResearchImportError, "key: value"):
            self.parse(malformed)
        duplicate = self.replace("stance: hold", "stance: hold\nstance: buy")
        with self.assertRaisesRegex(ResearchImportError, "more than once"):
            self.parse(duplicate)
        unsupported = self.replace("format_version: 1", "format_version: 2")
        with self.assertRaisesRegex(ResearchImportError, "Unsupported"):
            self.parse(unsupported)

    def test_rejects_ticker_mismatch_and_bad_trigger(self):
        with self.assertRaisesRegex(ResearchImportError, "does not match"):
            self.parse(ticker="NVDA")
        missing_currency = self.replace("trigger_currency: USD\n", "")
        with self.assertRaisesRegex(ResearchImportError, "trigger_currency"):
            self.parse(missing_currency)

    def test_rejects_unsafe_or_malformed_source_urls(self):
        unsafe = self.replace("https://investor.apple.com/", "javascript:evil")
        with self.assertRaisesRegex(ResearchImportError, "HTTP or HTTPS"):
            self.parse(unsafe)

    def test_duplicate_sources_are_ignored_with_warning(self):
        source = "- [Apple Investor Relations](https://investor.apple.com/) — Apple | 2026-09-20 | company"
        duplicated = self.valid_content().decode().replace(source, f"{source}\n{source}").encode()
        result = self.parse(duplicated)
        self.assertEqual(1, len(result.payload["sources"]))
        self.assertIn("Duplicate source ignored", result.warnings[0])

    def test_no_sources_is_an_incomplete_warning(self):
        content = self.valid_content().decode()
        source = "- [Apple Investor Relations](https://investor.apple.com/) — Apple | 2026-09-20 | company"
        result = self.parse(content.replace(source, "").encode())
        self.assertEqual([], result.payload["sources"])
        self.assertIn("incomplete", result.warnings[0])

    def test_raw_html_scripts_and_embedded_media_are_discarded(self):
        content = self.replace(
            "Apple's services growth",
            "<script>alert('x')</script>![chart](https://bad.example/a.png)<b>Apple's</b> services growth",
        )
        result = self.parse(content)
        self.assertNotIn("script", result.payload["summary"])
        self.assertNotIn("chart", result.payload["summary"])
        self.assertIn("Apple's services growth", result.payload["summary"])

    def test_template_comments_after_sources_are_ignored(self):
        content = self.valid_content() + b"\n<!-- Help text that is not a source. -->\n"
        result = self.parse(content)
        self.assertEqual(1, len(result.payload["sources"]))


if __name__ == "__main__":
    unittest.main()
