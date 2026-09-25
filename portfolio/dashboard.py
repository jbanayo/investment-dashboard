"""View model for the dashboard: KPIs, allocation, holdings groups, recent activity."""

from __future__ import annotations

from decimal import Decimal
import sqlite3

from .positions import _fx_rate
from .ratings import COVERAGE_LABELS, current_rating

SERIES = ["var(--s1)", "var(--s2)", "var(--s3)", "var(--s4)", "var(--s5)", "var(--s6)"]
ASSET_CLASSES = {
    "ph_equity": ("PH equities", "var(--s1)"),
    "us_equity": ("US equities", "var(--s2)"),
    "etf": ("ETFs", "var(--s3)"),
    "fund": ("Funds", "var(--s6)"),
    "crypto": ("Crypto", "var(--s4)"),
    "other": ("Other", "var(--muted)"),
    "cash": ("Cash", "var(--s5)"),
}
RANGE_NAMES = {"1M": "1 month", "YTD": "year to date", "1Y": "1 year", "All": "all time"}
RECENT_TRANSACTIONS = 10


def _decimal(value) -> Decimal:
    return Decimal(str(value or 0))


def dividend_income_base(connection: sqlite3.Connection, start_date: str, end_date: str, base_currency: str) -> dict:
    """Net dividends and withheld tax in the base currency, at each payment date's FX rate."""
    rows = connection.execute(
        """SELECT trade_date, currency, tax_withheld, net_amount FROM transactions
           WHERE type = 'dividend' AND parent_transaction_id IS NULL
             AND trade_date > ? AND trade_date <= ?""",
        (start_date, end_date),
    ).fetchall()
    net = tax = Decimal("0")
    unconverted = 0
    for row in rows:
        fx, _ = _fx_rate(connection, row["currency"], base_currency, row["trade_date"])
        if fx is None:
            unconverted += 1
            continue
        net += _decimal(row["net_amount"]) * fx
        tax += _decimal(row["tax_withheld"]) * fx
    return {"net": net, "tax": tax, "count": len(rows), "unconverted": unconverted}


def _group_label(grouping: str, key: str) -> str:
    return key if grouping == "platform" else ASSET_CLASSES.get(key, (key, ""))[0]


def holdings_groups(connection: sqlite3.Connection, snapshot: dict, grouping: str) -> list[dict]:
    """Group valued positions, ordered by value, with a stable colour per group."""
    groups: dict[str, list] = {}
    for item in snapshot["positions"]:
        instrument = item["instrument"]
        key = instrument["platform"] if grouping == "platform" else instrument["asset_class"]
        item["is_cash"] = instrument["asset_class"] == "cash"
        item["rating"] = None if item["is_cash"] else current_rating(connection, instrument["id"])
        item["coverage_label"] = COVERAGE_LABELS.get(instrument["coverage_status"], "No coverage")
        if item["rating"] and item["rating"]["target_price"] and item["price"]["price"]:
            item["implied_upside"] = _decimal(item["rating"]["target_price"]) / _decimal(item["price"]["price"]) - 1
        else:
            item["implied_upside"] = None
        cost_base = item["quantity"] * item["average_cost"] * item["fx"]
        item["gain_loss_percent"] = item["unrealised_gain_loss"] / cost_base if cost_base and not item["is_cash"] else None
        item["side_label"] = (
            ASSET_CLASSES.get(instrument["asset_class"], (instrument["asset_class"], ""))[0]
            if grouping == "platform" else instrument["platform"]
        )
        groups.setdefault(key, []).append(item)

    platforms = sorted({item["instrument"]["platform"] for item in snapshot["positions"]})
    result = []
    for key, items in groups.items():
        items.sort(key=lambda i: (i["is_cash"], -i["market_value_base"]))
        colour = (
            SERIES[platforms.index(key) % len(SERIES)] if grouping == "platform"
            else ASSET_CLASSES.get(key, ("", "var(--muted)"))[1]
        )
        result.append({
            "key": key,
            "label": _group_label(grouping, key),
            "colour": colour,
            "holdings": items,
            "value": sum((i["market_value_base"] for i in items), Decimal("0")),
            "gain_loss": sum((i["unrealised_gain_loss"] for i in items if not i["is_cash"]), Decimal("0")),
            "allocation": sum((i["allocation"] for i in items), Decimal("0")),
        })
    result.sort(key=lambda g: -g["value"])
    return result


def unrealised_totals(snapshot: dict) -> dict:
    """Unrealised gain/loss on non-cash holdings, and its share of their cost."""
    gain = cost = Decimal("0")
    for item in snapshot["positions"]:
        if item["instrument"]["asset_class"] == "cash":
            continue
        gain += item["unrealised_gain_loss"]
        cost += item["quantity"] * item["average_cost"] * item["fx"]
    return {"gain": gain, "percent": gain / cost if cost else None}


def fx_summary(connection: sqlite3.Connection, snapshot: dict) -> dict | None:
    """The FX rate used for the total, and how exposed the total is to it."""
    rows = [item["fx_row"] for item in snapshot["positions"] if item["fx_row"]]
    if not rows:
        return None
    row = max(rows, key=lambda r: (r["rate_date"], r["fetched_at"]))
    foreign = sum(
        (item["market_value_base"] for item in snapshot["positions"] if item["fx_row"]), Decimal("0")
    )
    rate = _decimal(row["rate"])
    return {
        "pair": f"{row['base_currency']}/{row['quote_currency']}",
        "rate": rate,
        "date": row["rate_date"],
        "source": row["source"],
        "foreign_share": foreign / snapshot["total"] if snapshot["total"] else Decimal("0"),
        # A one-unit move in the rate shifts the total by the foreign-currency amount held.
        "sensitivity": foreign / rate if rate else Decimal("0"),
    }


def last_price_refresh(connection: sqlite3.Connection) -> str | None:
    return connection.execute("SELECT MAX(fetched_at) FROM prices").fetchone()[0]


def recent_transactions(connection: sqlite3.Connection, limit: int = RECENT_TRANSACTIONS) -> dict:
    """Latest parent transactions, each with its generated cash legs."""
    parents = connection.execute(
        """SELECT t.*, i.name AS instrument_name, i.ticker, i.asset_class
           FROM transactions t JOIN instruments i ON i.id = t.instrument_id
           WHERE t.parent_transaction_id IS NULL
           ORDER BY t.trade_date DESC, t.id DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    total = connection.execute(
        "SELECT COUNT(*) FROM transactions WHERE parent_transaction_id IS NULL"
    ).fetchone()[0]
    legs: dict[int, list] = {}
    if parents:
        placeholders = ",".join("?" * len(parents))
        for leg in connection.execute(
            f"""SELECT t.*, i.name AS instrument_name FROM transactions t
                JOIN instruments i ON i.id = t.instrument_id
                WHERE t.parent_transaction_id IN ({placeholders}) ORDER BY t.id""",
            [p["id"] for p in parents],
        ):
            legs.setdefault(leg["parent_transaction_id"], []).append(leg)
    return {"rows": [{"tx": p, "legs": legs.get(p["id"], [])} for p in parents], "total": total}


def recent_notes(connection: sqlite3.Connection, limit: int = 6):
    return connection.execute(
        """SELECT n.note_date, n.body, i.name AS instrument_name, i.ticker
           FROM notes n JOIN instruments i ON i.id = n.instrument_id
           ORDER BY n.note_date DESC, n.id DESC LIMIT ?""",
        (limit,),
    ).fetchall()
