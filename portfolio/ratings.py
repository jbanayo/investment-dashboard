"""Append-only analyst rating history and explicit coverage states."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
import sqlite3


COVERAGE_LABELS = {
    "covered": "No coverage",
    "no_coverage": "No coverage",
    "not_applicable_crypto": "N/A · no analyst consensus for crypto",
    "not_applicable_index_etf": "No coverage · index ETF",
    "cash": "—",
}


class RatingError(ValueError):
    pass


def append_rating(connection: sqlite3.Connection, values) -> int | None:
    instrument_id = int(values.get("instrument_id", 0))
    if connection.execute("SELECT 1 FROM instruments WHERE id = ?", (instrument_id,)).fetchone() is None:
        raise RatingError("Choose an instrument.")
    issuer, rating = values.get("issuer", "").strip(), values.get("rating", "").strip()
    if not issuer or not rating:
        raise RatingError("Enter the issuer and rating exactly as the source states them.")
    issued_date = values.get("issued_date", "")
    try:
        parsed_date = date.fromisoformat(issued_date)
    except ValueError:
        raise RatingError("Enter a valid issue date.") from None
    if parsed_date > date.today():
        raise RatingError("Issue date cannot be in the future.")
    try:
        target = Decimal(values.get("target_price", ""))
    except InvalidOperation:
        raise RatingError("Enter a valid target price.") from None
    if target <= 0:
        raise RatingError("Target price must be above zero.")
    currency = values.get("target_currency", "").strip().upper()
    if len(currency) != 3:
        raise RatingError("Enter a three-letter target currency.")
    source_type = values.get("source_type", "manual")
    latest = connection.execute(
        """SELECT * FROM ratings WHERE instrument_id = ? AND issuer = ?
           ORDER BY issued_date DESC, id DESC LIMIT 1""", (instrument_id, issuer)
    ).fetchone()
    if latest and latest["rating"] == rating and latest["target_price"] == float(target) and latest["issued_date"] == issued_date:
        return None
    return connection.execute(
        """INSERT INTO ratings
           (instrument_id,issuer,rating,target_price,target_currency,issued_date,source_type,
            normalized_scale,analyst_count,note,recorded_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)""",
        (instrument_id, issuer, rating, float(target), currency, issued_date, source_type,
         values.get("normalized_scale") or None, values.get("analyst_count") or None,
         values.get("note", "").strip() or None),
    ).lastrowid


def current_rating(connection: sqlite3.Connection, instrument_id: int, issuer: str | None = None):
    sql = "SELECT * FROM ratings WHERE instrument_id = ?"
    params = [instrument_id]
    if issuer:
        sql += " AND issuer = ?"; params.append(issuer)
    return connection.execute(sql + " ORDER BY issued_date DESC, id DESC LIMIT 1", params).fetchone()


def rating_history(connection: sqlite3.Connection, instrument_id: int):
    return connection.execute(
        "SELECT * FROM ratings WHERE instrument_id = ? ORDER BY issued_date DESC, id DESC",
        (instrument_id,),
    ).fetchall()
