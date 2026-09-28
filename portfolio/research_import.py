"""Parse and validate external-agent Markdown research without database writes."""

from __future__ import annotations

import html
import json
import re
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from .research import CONFIDENCE_LEVELS, SOURCE_TYPES, STANCES, TRIGGER_TYPES


MAX_IMPORT_BYTES = 1024 * 1024
FORMAT_VERSION = 1
REQUIRED_FRONTMATTER = {
    "format_version", "instrument", "ticker", "research_date", "stance",
    "confidence", "time_horizon", "trigger_type",
}
SECTION_HEADINGS = {
    "thesis": (1, "thesis"),
    "supporting points": (2, "supporting_points"),
    "risks": (2, "risks"),
    "sources": (2, "sources"),
}
SOURCE_RE = re.compile(
    r"^\s*[-*]\s+\[([^]]+)]\(([^)]+)\)"
    r"(?:\s*[—-]\s*([^|\n]+))?"
    r"(?:\s*\|\s*([^|\n]+))?"
    r"(?:\s*\|\s*([^|\n]+))?\s*$"
)


class ResearchImportError(ValueError):
    """A user-correctable Markdown contract error."""


@dataclass(frozen=True)
class ParsedResearchImport:
    payload: dict
    warnings: tuple[str, ...]


def _plain_text(value: str) -> str:
    value = re.sub(r"<script\b[^>]*>.*?</script\s*>", "", value, flags=re.I | re.S)
    value = re.sub(r"<!--.*?-->", "", value, flags=re.S)
    value = re.sub(r"!\[[^]]*]\([^)]*\)", "", value)
    value = re.sub(r"<[^>]+>", "", value)
    return html.unescape(value).strip()


def _frontmatter_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1]
    return _plain_text(value).strip()


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.startswith("---\n"):
        raise ResearchImportError("Add YAML frontmatter between opening and closing --- lines.")
    closing = normalized.find("\n---\n", 4)
    if closing < 0:
        raise ResearchImportError("Close the YAML frontmatter with a --- line.")
    values: dict[str, str] = {}
    for line_number, line in enumerate(normalized[4:closing].splitlines(), start=2):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            raise ResearchImportError(f"Frontmatter line {line_number} must use key: value.")
        key, value = line.split(":", 1)
        key = key.strip().lower()
        if not re.fullmatch(r"[a-z][a-z0-9_]*", key):
            raise ResearchImportError(f"Frontmatter line {line_number} has an invalid field name.")
        if key in values:
            raise ResearchImportError(f"Frontmatter field '{key}' appears more than once.")
        values[key] = _frontmatter_value(value)
    missing = sorted(REQUIRED_FRONTMATTER - values.keys())
    if missing:
        raise ResearchImportError(f"Missing frontmatter field(s): {', '.join(missing)}.")
    return values, normalized[closing + 5:]


def _parse_sections(body: str) -> dict[str, str]:
    matches: list[tuple[int, int, str]] = []
    seen: set[str] = set()
    for match in re.finditer(r"(?m)^(#{1,6})\s+(.+?)\s*$", body):
        label = _plain_text(match.group(2)).strip().lower()
        definition = SECTION_HEADINGS.get(label)
        if not definition or len(match.group(1)) != definition[0]:
            continue
        key = definition[1]
        if key in seen:
            raise ResearchImportError(f"The '{label}' section appears more than once.")
        seen.add(key)
        matches.append((match.start(), match.end(), key))
    missing = [label for label, (_, key) in SECTION_HEADINGS.items() if key not in seen]
    if missing:
        raise ResearchImportError(f"Missing required section(s): {', '.join(missing)}.")
    matches.sort()
    sections: dict[str, str] = {}
    for index, (_, content_start, key) in enumerate(matches):
        content_end = matches[index + 1][0] if index + 1 < len(matches) else len(body)
        sections[key] = body[content_start:content_end].strip()
    return sections


def _list_items(value: str) -> list[str]:
    cleaned = _plain_text(value)
    items = []
    for line in cleaned.splitlines():
        line = re.sub(r"^\s*[-*+]\s+", "", line).strip()
        if line:
            items.append(line)
    return items


def _parse_date(value: str, label: str, *, future_allowed: bool = False) -> str:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ResearchImportError(f"{label} must use YYYY-MM-DD.") from error
    if not future_allowed and parsed > date.today():
        raise ResearchImportError(f"{label} cannot be in the future.")
    return value


def _positive_number(value: str, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ResearchImportError(f"{label} must be a number.") from error
    if number <= 0:
        raise ResearchImportError(f"{label} must be greater than zero.")
    return number


def _parse_sources(value: str) -> tuple[list[dict], list[str]]:
    sources: list[dict] = []
    warnings: list[str] = []
    seen_urls: set[str] = set()
    value = re.sub(r"<!--.*?-->", "", value, flags=re.S)
    for line in value.splitlines():
        if not line.strip():
            continue
        match = SOURCE_RE.match(line)
        if not match:
            raise ResearchImportError(
                "Each source must use: - [Title](https://url) — Publisher | YYYY-MM-DD | type."
            )
        title, url, publisher, published_at, source_type = (
            _plain_text(part or "") for part in match.groups()
        )
        parsed_url = urlparse(url)
        if parsed_url.scheme not in ("http", "https") or not parsed_url.netloc:
            raise ResearchImportError("Each source needs a valid HTTP or HTTPS URL.")
        source_type = (source_type or "other").lower()
        if source_type not in SOURCE_TYPES:
            raise ResearchImportError(f"Source type '{source_type}' is not supported.")
        if published_at:
            _parse_date(published_at, "Source publication date", future_allowed=True)
        if url in seen_urls:
            warnings.append(f"Duplicate source ignored: {url}")
            continue
        seen_urls.add(url)
        sources.append({
            "title": title or url,
            "publisher": publisher or None,
            "url": url,
            "published_at": published_at or None,
            "source_type": source_type,
        })
    if not sources:
        warnings.append("No verified sources were included; this draft will be marked incomplete.")
    return sources, warnings


def parse_research_markdown(
    content: bytes,
    filename: str,
    expected_ticker: str,
) -> ParsedResearchImport:
    """Validate one Markdown upload and return normalized fields without writing."""
    if Path(filename).suffix.lower() not in (".md", ".markdown"):
        raise ResearchImportError("Choose a .md or .markdown file.")
    if len(content) > MAX_IMPORT_BYTES:
        raise ResearchImportError("The Markdown file must be 1 MB or smaller.")
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ResearchImportError("The Markdown file must use UTF-8 encoding.") from error
    frontmatter, body = _parse_frontmatter(text)
    try:
        format_version = int(frontmatter["format_version"])
    except ValueError as error:
        raise ResearchImportError("format_version must be the number 1.") from error
    if format_version != FORMAT_VERSION:
        raise ResearchImportError(f"Unsupported format_version {format_version}; use 1.")
    ticker = frontmatter["ticker"].upper()
    if ticker != expected_ticker.strip().upper():
        raise ResearchImportError(
            f"Ticker {ticker or '(blank)'} does not match selected instrument {expected_ticker.upper()}."
        )
    stance = frontmatter["stance"].lower()
    confidence = frontmatter["confidence"].lower()
    trigger_type = frontmatter["trigger_type"].lower()
    if stance not in STANCES:
        raise ResearchImportError(f"Stance '{stance}' is not supported.")
    if confidence not in CONFIDENCE_LEVELS:
        raise ResearchImportError(f"Confidence '{confidence}' is not supported.")
    if trigger_type not in TRIGGER_TYPES:
        raise ResearchImportError(f"Trigger type '{trigger_type}' is not supported.")
    research_date = _parse_date(frontmatter["research_date"], "Research date")
    if not frontmatter["instrument"]:
        raise ResearchImportError("Instrument cannot be blank.")
    if not frontmatter["time_horizon"]:
        raise ResearchImportError("Time horizon cannot be blank.")

    trigger_price = None
    trigger_currency = None
    event_trigger = None
    if trigger_type in ("at_or_below", "at_or_above"):
        if not frontmatter.get("trigger_price") or not frontmatter.get("trigger_currency"):
            raise ResearchImportError("A numeric trigger needs trigger_price and trigger_currency.")
        trigger_price = _positive_number(frontmatter["trigger_price"], "Trigger price")
        trigger_currency = frontmatter["trigger_currency"].upper()
        if not re.fullmatch(r"[A-Z]{3}", trigger_currency):
            raise ResearchImportError("Trigger currency must use a three-letter code.")
    elif trigger_type == "event":
        event_trigger = frontmatter.get("event_trigger", "").strip()
        if not event_trigger:
            raise ResearchImportError("An event trigger needs event_trigger text.")

    sections = _parse_sections(body)
    summary = _plain_text(sections["thesis"])
    supporting_points = _list_items(sections["supporting_points"])
    risks = _list_items(sections["risks"])
    if not summary:
        raise ResearchImportError("The Thesis section cannot be empty.")
    if not supporting_points:
        raise ResearchImportError("The Supporting points section needs at least one point.")
    if not risks:
        raise ResearchImportError("The Risks section needs at least one risk.")
    sources, warnings = _parse_sources(sections["sources"])
    source_target = (
        _positive_number(frontmatter["source_target"], "Source target")
        if frontmatter.get("source_target") else None
    )
    source_target_currency = frontmatter.get("source_target_currency") or None
    source_target_issuer = frontmatter.get("source_target_issuer") or None
    if source_target is not None:
        if not source_target_currency or not re.fullmatch(r"[A-Za-z]{3}", source_target_currency):
            raise ResearchImportError("A source target needs a three-letter source_target_currency.")
        if not source_target_issuer:
            raise ResearchImportError("A source target needs source_target_issuer.")
        source_target_currency = source_target_currency.upper()
    payload = {
        "format_version": format_version,
        "instrument": frontmatter["instrument"],
        "ticker": ticker,
        "research_date": research_date,
        "stance": stance,
        "confidence": confidence,
        "confidence_reason": frontmatter.get("confidence_reason") or None,
        "time_horizon": frontmatter["time_horizon"],
        "trigger_type": trigger_type,
        "trigger_price": trigger_price,
        "trigger_currency": trigger_currency,
        "event_trigger": event_trigger,
        "source_target": source_target,
        "source_target_currency": source_target_currency,
        "source_target_issuer": source_target_issuer,
        "summary": summary,
        "supporting_points": supporting_points,
        "risks": risks,
        "sources": sources,
    }
    return ParsedResearchImport(payload=payload, warnings=tuple(warnings))


def stage_research_import(
    connection: sqlite3.Connection,
    instrument_id: int,
    filename: str,
    agent_name: str,
    content: bytes,
) -> str:
    instrument = connection.execute(
        "SELECT * FROM instruments WHERE id = ? AND asset_class != 'cash'",
        (instrument_id,),
    ).fetchone()
    if not instrument:
        raise ResearchImportError("Choose an investment that exists in the portfolio.")
    if not instrument["ticker"]:
        raise ResearchImportError("The selected investment needs a ticker before research can be imported.")
    parsed = parse_research_markdown(content, filename, instrument["ticker"])
    now = datetime.now(timezone.utc)
    connection.execute(
        "DELETE FROM research_import_previews WHERE expires_at <= ?", (now.isoformat(),)
    )
    token = secrets.token_urlsafe(32)
    connection.execute(
        """INSERT INTO research_import_previews
           (id, instrument_id, filename, agent_name, raw_content,
            normalized_payload_json, warnings_json, created_at, expires_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            token, instrument_id, Path(filename).name,
            agent_name.strip()[:80] or None, content.decode("utf-8"),
            json.dumps(parsed.payload), json.dumps(parsed.warnings),
            now.isoformat(), (now + timedelta(hours=1)).isoformat(),
        ),
    )
    return token


def research_import_preview(connection: sqlite3.Connection, token: str):
    now = datetime.now(timezone.utc).isoformat()
    connection.execute("DELETE FROM research_import_previews WHERE expires_at <= ?", (now,))
    row = connection.execute(
        """SELECT preview.*, instrument.name AS instrument_name,
                  instrument.ticker, instrument.platform
           FROM research_import_previews preview
           JOIN instruments instrument ON instrument.id = preview.instrument_id
           WHERE preview.id = ?""",
        (token,),
    ).fetchone()
    if not row:
        return None
    return {
        **dict(row),
        "payload": json.loads(row["normalized_payload_json"]),
        "warnings": json.loads(row["warnings_json"]),
    }


def discard_research_import_preview(connection: sqlite3.Connection, token: str) -> None:
    connection.execute("DELETE FROM research_import_previews WHERE id = ?", (token,))


def confirm_research_import(connection: sqlite3.Connection, token: str) -> int:
    """Atomically convert one unexpired staged preview into an auditable Draft."""
    preview = research_import_preview(connection, token)
    if not preview:
        raise ResearchImportError("This import preview expired or was already used.")
    parsed = parse_research_markdown(
        preview["raw_content"].encode("utf-8"), preview["filename"], preview["ticker"]
    )
    payload = parsed.payload
    latest = connection.execute(
        "SELECT price, price_date FROM prices WHERE instrument_id = ? "
        "ORDER BY price_date DESC, id DESC LIMIT 1",
        (preview["instrument_id"],),
    ).fetchone()
    cursor = connection.execute(
        """INSERT INTO research_items (
            instrument_id, origin, status, stance, research_date, market_price,
            market_price_date, trigger_type, trigger_price, trigger_currency,
            event_trigger, time_horizon, summary, supporting_points_json, risks_json,
            confidence, confidence_reason, source_target, source_target_currency,
            source_target_issuer, original_payload_json
        ) VALUES (?, 'ai', 'draft', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            preview["instrument_id"], payload["stance"], payload["research_date"],
            latest["price"] if latest else None, latest["price_date"] if latest else None,
            payload["trigger_type"], payload["trigger_price"], payload["trigger_currency"],
            payload["event_trigger"], payload["time_horizon"], payload["summary"],
            json.dumps(payload["supporting_points"]), json.dumps(payload["risks"]),
            payload["confidence"], payload["confidence_reason"], payload["source_target"],
            payload["source_target_currency"], payload["source_target_issuer"],
            json.dumps(payload),
        ),
    )
    item_id = cursor.lastrowid
    for source in payload["sources"]:
        connection.execute(
            """INSERT INTO research_sources
               (research_item_id, title, publisher, url, published_at, source_type)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                item_id, source["title"], source["publisher"], source["url"],
                source["published_at"], source["source_type"],
            ),
        )
    connection.execute(
        """INSERT INTO research_imports
           (research_item_id, format_version, filename, agent_name, raw_content,
            normalized_payload_json)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            item_id, payload["format_version"], preview["filename"], preview["agent_name"],
            preview["raw_content"], json.dumps(payload),
        ),
    )
    agent_name = preview["agent_name"] or "External AI agent"
    connection.execute(
        """INSERT INTO research_events
           (research_item_id, event_type, to_status, detail)
           VALUES (?, 'generated', 'draft', ?)""",
        (item_id, f"Imported from {agent_name}"),
    )
    connection.execute("DELETE FROM research_import_previews WHERE id = ?", (token,))
    return item_id
