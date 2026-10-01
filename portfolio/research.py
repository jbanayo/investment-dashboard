"""Research thesis storage, validation, and review workflow."""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from urllib.parse import urlparse


STANCES = ("buy", "hold", "reduce", "sell", "watch", "avoid")
STATUSES = ("draft", "monitoring", "saved", "archived")
TRIGGER_TYPES = ("none", "at_or_below", "at_or_above", "event")
CONFIDENCE_LEVELS = ("low", "medium", "high")
SOURCE_TYPES = ("filing", "company", "exchange", "news", "research", "other")


class ResearchError(ValueError):
    pass


def _optional_number(value: str | None, label: str) -> float | None:
    if not value or not value.strip():
        return None
    try:
        number = float(value)
    except ValueError as error:
        raise ResearchError(f"{label} must be a number.") from error
    if number <= 0:
        raise ResearchError(f"{label} must be greater than zero.")
    return number


def _lines(value: str | None) -> str:
    return json.dumps([line.strip(" •-") for line in (value or "").splitlines() if line.strip(" •-")])


def _valid_date(value: str, label: str, allow_future: bool = False) -> str:
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError) as error:
        raise ResearchError(f"Enter a valid {label.lower()}.") from error
    if not allow_future and parsed > date.today():
        raise ResearchError(f"{label} cannot be in the future.")
    return value


def create_manual_research(connection: sqlite3.Connection, values) -> int:
    try:
        instrument_id = int(values.get("instrument_id", ""))
    except (TypeError, ValueError) as error:
        raise ResearchError("Choose an investment.") from error
    instrument = connection.execute(
        "SELECT * FROM instruments WHERE id = ? AND asset_class != 'cash'", (instrument_id,)
    ).fetchone()
    if not instrument:
        raise ResearchError("Choose an investment that exists in the portfolio.")

    stance = (values.get("stance") or "").lower()
    if stance not in STANCES:
        raise ResearchError("Choose a valid stance.")
    trigger_type = values.get("trigger_type") or "none"
    if trigger_type not in TRIGGER_TYPES:
        raise ResearchError("Choose a valid trigger type.")
    research_date = _valid_date(values.get("research_date", ""), "Research date")
    expires_on = (values.get("expires_on") or "").strip() or None
    if expires_on:
        _valid_date(expires_on, "Review date", allow_future=True)
    summary = (values.get("summary") or "").strip()
    if not summary:
        raise ResearchError("Add a research summary.")
    trigger_price = _optional_number(values.get("trigger_price"), "Trigger price")
    event_trigger = (values.get("event_trigger") or "").strip() or None
    if trigger_type in ("at_or_below", "at_or_above") and trigger_price is None:
        raise ResearchError("Enter the trigger price.")
    if trigger_type == "event" and not event_trigger:
        raise ResearchError("Describe the event trigger.")
    trigger_currency = (values.get("trigger_currency") or instrument["native_currency"]).strip().upper()
    if len(trigger_currency) != 3:
        raise ResearchError("Trigger currency must use a three-letter code.")
    confidence = (values.get("confidence") or "").lower() or None
    if confidence and confidence not in CONFIDENCE_LEVELS:
        raise ResearchError("Choose a valid confidence level.")

    source_url = (values.get("source_url") or "").strip()
    if source_url and urlparse(source_url).scheme not in ("http", "https"):
        raise ResearchError("Source URL must start with http:// or https://.")

    latest = connection.execute(
        "SELECT price, price_date FROM prices WHERE instrument_id = ? ORDER BY price_date DESC, id DESC LIMIT 1",
        (instrument_id,),
    ).fetchone()
    cursor = connection.execute(
        """
        INSERT INTO research_items (
            instrument_id, origin, status, stance, research_date, market_price,
            market_price_date, trigger_type, trigger_price, trigger_currency,
            event_trigger, time_horizon, expires_on, summary, supporting_points_json,
            risks_json, confidence, confidence_reason
        ) VALUES (?, 'manual', 'draft', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            instrument_id, stance, research_date,
            latest["price"] if latest else None, latest["price_date"] if latest else None,
            trigger_type, trigger_price, trigger_currency, event_trigger,
            (values.get("time_horizon") or "").strip() or None, expires_on, summary,
            _lines(values.get("supporting_points")), _lines(values.get("risks")),
            confidence, (values.get("confidence_reason") or "").strip() or None,
        ),
    )
    item_id = cursor.lastrowid
    connection.execute(
        "INSERT INTO research_events (research_item_id, event_type, detail) VALUES (?, 'generated', 'Manual research created')",
        (item_id,),
    )
    if source_url:
        connection.execute(
            "INSERT INTO research_sources (research_item_id, title, publisher, url, published_at) VALUES (?, ?, ?, ?, ?)",
            (
                item_id, (values.get("source_title") or source_url).strip(),
                (values.get("source_publisher") or "").strip() or None, source_url,
                (values.get("source_published_at") or "").strip() or None,
            ),
        )
    initial_status = values.get("initial_status") or "draft"
    if initial_status != "draft":
        transition_research_item(connection, item_id, initial_status)
    return item_id


def update_research_item(connection: sqlite3.Connection, item_id: int, values) -> None:
    """Update the working thesis while preserving any original imported artifact."""
    item = connection.execute(
        "SELECT * FROM research_items WHERE id = ?", (item_id,)
    ).fetchone()
    if not item:
        raise ResearchError("Research item not found.")
    stance = (values.get("stance") or "").lower()
    if stance not in STANCES:
        raise ResearchError("Choose a valid stance.")
    trigger_type = values.get("trigger_type") or "none"
    if trigger_type not in TRIGGER_TYPES:
        raise ResearchError("Choose a valid trigger type.")
    trigger_price = _optional_number(values.get("trigger_price"), "Trigger price")
    event_trigger = (values.get("event_trigger") or "").strip() or None
    if trigger_type in ("at_or_below", "at_or_above") and trigger_price is None:
        raise ResearchError("Enter the trigger price.")
    if trigger_type == "event" and not event_trigger:
        raise ResearchError("Describe the event trigger.")
    trigger_currency = (values.get("trigger_currency") or "").strip().upper()
    if trigger_type in ("at_or_below", "at_or_above") and len(trigger_currency) != 3:
        raise ResearchError("Trigger currency must use a three-letter code.")
    summary = (values.get("summary") or "").strip()
    if not summary:
        raise ResearchError("Add a research summary.")
    expires_on = (values.get("expires_on") or "").strip() or None
    if expires_on:
        _valid_date(expires_on, "Review date", allow_future=True)
    confidence = (values.get("confidence") or "").lower() or None
    if confidence and confidence not in CONFIDENCE_LEVELS:
        raise ResearchError("Choose a valid confidence level.")
    connection.execute(
        """UPDATE research_items SET stance = ?, trigger_type = ?, trigger_price = ?,
           trigger_currency = ?, event_trigger = ?, time_horizon = ?, expires_on = ?,
           summary = ?, supporting_points_json = ?, risks_json = ?, confidence = ?,
           confidence_reason = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?""",
        (
            stance, trigger_type, trigger_price, trigger_currency or None, event_trigger,
            (values.get("time_horizon") or "").strip() or None, expires_on, summary,
            _lines(values.get("supporting_points")), _lines(values.get("risks")),
            confidence, (values.get("confidence_reason") or "").strip() or None, item_id,
        ),
    )
    connection.execute(
        "INSERT INTO research_events (research_item_id, event_type, detail) "
        "VALUES (?, 'edited', 'Working thesis edited')",
        (item_id,),
    )



def transition_research_item(connection: sqlite3.Connection, item_id: int, new_status: str) -> None:
    if new_status not in STATUSES:
        raise ResearchError("Choose a valid research status.")
    item = connection.execute("SELECT * FROM research_items WHERE id = ?", (item_id,)).fetchone()
    if not item:
        raise ResearchError("Research item not found.")
    if item["status"] == new_status:
        return
    if new_status == "monitoring":
        previous = connection.execute(
            "SELECT id FROM research_items WHERE instrument_id = ? AND status = 'monitoring' AND id != ?",
            (item["instrument_id"], item_id),
        ).fetchone()
        if previous:
            connection.execute(
                "UPDATE research_items SET status = 'saved', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (previous["id"],),
            )
            connection.execute(
                "INSERT INTO research_events (research_item_id, event_type, detail) VALUES (?, 'saved', 'Replaced by a newer monitored thesis')",
                (previous["id"],),
            )
    event_type = {
        "monitoring": "monitoring", "saved": "saved", "archived": "archived",
        "draft": "restored",
    }[new_status]
    connection.execute(
        "UPDATE research_items SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (new_status, item_id),
    )
    connection.execute(
        """INSERT INTO research_events
           (research_item_id, event_type, from_status, to_status, detail)
           VALUES (?, ?, ?, ?, ?)""",
        (item_id, event_type, item["status"], new_status, f"Status changed from {item['status']} to {new_status}"),
    )


def list_research(connection: sqlite3.Connection, status: str = "draft", platform: str | None = None):
    parameters: list[object] = [status]
    condition = "WHERE r.status = ?"
    if platform:
        condition += " AND i.platform = ?"
        parameters.append(platform)
    rows = connection.execute(
        f"""
        SELECT r.*, i.name AS instrument_name, i.ticker, i.platform, i.native_currency,
               imported.filename AS import_filename, imported.agent_name AS import_agent_name,
               imported.format_version AS import_format_version,
               imported.raw_content AS import_raw_content
        FROM research_items r JOIN instruments i ON i.id = r.instrument_id
        LEFT JOIN research_imports imported ON imported.research_item_id = r.id
        {condition} ORDER BY r.research_date DESC, r.id DESC
        """,
        parameters,
    ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["supporting_points"] = json.loads(item.pop("supporting_points_json"))
        item["risks"] = json.loads(item.pop("risks_json"))
        item["sources"] = connection.execute(
            "SELECT * FROM research_sources WHERE research_item_id = ? ORDER BY id", (row["id"],)
        ).fetchall()
        item["comparison"] = (
            research_comparison(connection, item) if item["status"] == "draft" else None
        )
        result.append(item)
    return result


def _trigger_description(item) -> str:
    if item["trigger_type"] == "event":
        return item["event_trigger"] or "Event trigger"
    if item["trigger_type"] in ("at_or_below", "at_or_above"):
        direction = "At or below" if item["trigger_type"] == "at_or_below" else "At or above"
        return f"{direction} {item['trigger_price']:g} {item['trigger_currency'] or ''}".strip()
    return "No trigger"


def research_comparison(connection: sqlite3.Connection, draft) -> dict | None:
    """Compare a Draft with the currently monitored thesis for its instrument."""
    current = connection.execute(
        """SELECT * FROM research_items
           WHERE instrument_id = ? AND status = 'monitoring' AND id != ?
           ORDER BY updated_at DESC, id DESC LIMIT 1""",
        (draft["instrument_id"], draft["id"]),
    ).fetchone()
    if not current:
        return None
    fields = (
        ("Stance", current["stance"], draft["stance"]),
        ("Review condition", _trigger_description(current), _trigger_description(draft)),
        ("Time horizon", current["time_horizon"] or "Not set", draft["time_horizon"] or "Not set"),
        ("Confidence", current["confidence"] or "Not set", draft["confidence"] or "Not set"),
    )
    changes = [
        {"label": label, "current": old, "draft": new}
        for label, old, new in fields if old != new
    ]
    return {
        "current_id": current["id"],
        "current_date": current["research_date"],
        "current_summary": current["summary"],
        "draft_summary": draft["summary"],
        "summary_changed": current["summary"] != draft["summary"],
        "changes": changes,
    }


def research_counts(connection: sqlite3.Connection) -> dict[str, int]:
    counts = {status: 0 for status in STATUSES}
    counts.update({row["status"]: row["count"] for row in connection.execute(
        "SELECT status, COUNT(*) AS count FROM research_items GROUP BY status"
    )})
    return counts


def export_research_markdown(connection: sqlite3.Connection, item_id: int) -> tuple[str, str]:
    item = connection.execute(
        """SELECT r.*, i.name AS instrument_name, i.ticker
           FROM research_items r JOIN instruments i ON i.id = r.instrument_id
           WHERE r.id = ?""",
        (item_id,),
    ).fetchone()
    if not item:
        raise ResearchError("Research item not found.")
    frontmatter = [
        "---", "format_version: 1",
        f"instrument: {json.dumps(item['instrument_name'])}",
        f"ticker: {json.dumps(item['ticker'] or '')}",
        f"research_date: {item['research_date']}", f"stance: {item['stance']}",
        f"confidence: {item['confidence'] or 'medium'}",
        f"time_horizon: {json.dumps(item['time_horizon'] or 'Not set')}",
        f"trigger_type: {item['trigger_type']}",
    ]
    if item["trigger_type"] in ("at_or_below", "at_or_above"):
        frontmatter.extend([
            f"trigger_price: {item['trigger_price']:g}",
            f"trigger_currency: {item['trigger_currency']}",
        ])
    elif item["trigger_type"] == "event":
        frontmatter.append(f"event_trigger: {json.dumps(item['event_trigger'] or '')}")
    frontmatter.append("---")
    supporting = json.loads(item["supporting_points_json"])
    risks = json.loads(item["risks_json"])
    sources = connection.execute(
        "SELECT * FROM research_sources WHERE research_item_id = ? ORDER BY id", (item_id,)
    ).fetchall()
    source_lines = []
    for source in sources:
        title = source["title"].replace("[", "\\[").replace("]", "\\]")
        metadata = [source["publisher"] or "", source["published_at"] or "", source["source_type"]]
        source_lines.append(f"- [{title}]({source['url']}) — " + " | ".join(metadata))
    body = [
        "# Thesis", "", item["summary"], "", "## Supporting points", "",
        *[f"- {point}" for point in supporting], "", "## Risks", "",
        *[f"- {risk}" for risk in risks], "", "## Sources", "",
        *(source_lines or ["<!-- No verified sources were stored. -->"]), "",
    ]
    ticker = (item["ticker"] or item["instrument_name"]).lower().replace(" ", "-")
    return f"{ticker}-research-{item['research_date']}.md", "\n".join(frontmatter + [""] + body)


def monitored_research(
    connection: sqlite3.Connection, platform: str | None = None, today: date | None = None
):
    parameters: list[object] = []
    platform_condition = ""
    if platform:
        platform_condition = " AND i.platform = ?"
        parameters.append(platform)
    rows = connection.execute(
        f"""
        SELECT r.*, i.name AS instrument_name, i.ticker, i.platform, i.native_currency,
               p.price AS current_price, p.price_date AS current_price_date,
               p.currency AS current_price_currency
        FROM research_items r
        JOIN instruments i ON i.id = r.instrument_id
        LEFT JOIN prices p ON p.id = (
            SELECT p2.id FROM prices p2 WHERE p2.instrument_id = r.instrument_id
            ORDER BY p2.price_date DESC, p2.id DESC LIMIT 1
        )
        WHERE r.status = 'monitoring'{platform_condition}
        ORDER BY r.research_date DESC, r.id DESC
        """,
        parameters,
    ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        price = item["current_price"]
        target = item["trigger_price"]
        compatible_price = bool(
            price is not None and (
                not item["trigger_currency"]
                or item["trigger_currency"] == item["current_price_currency"]
            )
        )
        item["trigger_met"] = bool(
            compatible_price and target is not None and (
                (item["trigger_type"] == "at_or_below" and price <= target)
                or (item["trigger_type"] == "at_or_above" and price >= target)
            )
        )
        today_value = today or date.today()
        stale = bool(
            item["current_price_date"]
            and date.fromisoformat(item["current_price_date"]) < _research_last_trading_day(today_value)
        )
        expired = bool(item["expires_on"] and item["expires_on"] < today_value.isoformat())
        if item["trigger_met"] and not stale:
            item["monitoring_status"] = "review_due"
            item["monitoring_label"] = "Review due"
        elif stale:
            item["monitoring_status"] = "price_stale"
            item["monitoring_label"] = "Price stale"
        elif expired:
            item["monitoring_status"] = "expired"
            item["monitoring_label"] = "Expired"
        elif not compatible_price:
            item["monitoring_status"] = "no_price"
            item["monitoring_label"] = "No price"
        else:
            item["monitoring_status"] = "watching"
            item["monitoring_label"] = "Watching"
        if compatible_price and target is not None and price:
            if item["trigger_type"] == "at_or_above":
                item["distance_to_trigger"] = (target - price) / price
            else:
                item["distance_to_trigger"] = (price - target) / price
        else:
            item["distance_to_trigger"] = None
        items.append(item)
    rank = {"review_due": 0, "price_stale": 1, "expired": 2, "watching": 3, "no_price": 4}
    items.sort(key=lambda item: (
        rank[item["monitoring_status"]],
        abs(item["distance_to_trigger"]) if item["distance_to_trigger"] is not None else float("inf"),
        item["instrument_name"],
    ))
    return items


def _research_last_trading_day(today: date) -> date:
    offset = 3 if today.weekday() == 0 else 2 if today.weekday() == 6 else 1
    from datetime import timedelta
    return today - timedelta(days=offset)
