"""Manual price and FX series entry with an auditable revision trail."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
import sqlite3

from .transactions import TransactionError, _decimal


def _price_date(value: str) -> str:
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise TransactionError("Enter a valid price date.") from None
    if parsed > date.today():
        raise TransactionError("Price date cannot be in the future.")
    return value


def record_manual_price(connection: sqlite3.Connection, values) -> int:
    instrument_id = int(values.get("instrument_id", 0))
    instrument = connection.execute(
        "SELECT * FROM instruments WHERE id = ?", (instrument_id,)
    ).fetchone()
    if instrument is None:
        raise TransactionError("Choose an instrument.")
    if instrument["asset_class"] == "cash":
        raise TransactionError("Cash is always valued at 1.0 and does not accept manual prices.")
    price_date = _price_date(values.get("price_date", ""))
    price = _decimal(values.get("price", ""), "price")
    currency = values.get("currency", instrument["native_currency"]).strip().upper()
    if len(currency) != 3 or not currency.isalpha():
        raise TransactionError("Enter a three-letter currency code.")
    existing = connection.execute(
        "SELECT * FROM prices WHERE instrument_id = ? AND price_date = ? AND source = 'manual'",
        (instrument_id, price_date),
    ).fetchone()
    if existing:
        connection.execute(
            """
            INSERT INTO price_revisions
              (price_id, previous_price, previous_currency, previous_source, previous_fetched_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (existing["id"], existing["price"], existing["currency"], existing["source"], existing["fetched_at"]),
        )
        connection.execute(
            "UPDATE prices SET price = ?, currency = ?, fetched_at = CURRENT_TIMESTAMP WHERE id = ?",
            (float(price), currency, existing["id"]),
        )
        return existing["id"]
    return connection.execute(
        """
        INSERT INTO prices (instrument_id, price_date, price, currency, source, fetched_at)
        VALUES (?, ?, ?, ?, 'manual', CURRENT_TIMESTAMP)
        """,
        (instrument_id, price_date, float(price), currency),
    ).lastrowid


def record_bulk_prices(connection: sqlite3.Connection, price_date: str, entries: dict[str, str]) -> int:
    _price_date(price_date)
    written = 0
    for key, value in entries.items():
        if not key.startswith("price_") or not value.strip():
            continue
        instrument_id = key.removeprefix("price_")
        instrument = connection.execute(
            "SELECT native_currency FROM instruments WHERE id = ? AND asset_class != 'cash'",
            (instrument_id,),
        ).fetchone()
        if instrument is None:
            continue
        record_manual_price(connection, {
            "instrument_id": instrument_id, "price_date": price_date, "price": value,
            "currency": entries.get(f"currency_{instrument_id}", instrument["native_currency"]),
        })
        written += 1
    if not written:
        raise TransactionError("Enter at least one price.")
    return written


def record_manual_fx_rate(connection: sqlite3.Connection, values) -> int:
    rate_date = _price_date(values.get("rate_date", ""))
    rate = _decimal(values.get("rate", ""), "FX rate")
    existing = connection.execute(
        """
        SELECT * FROM fx_rates
        WHERE base_currency = 'USD' AND quote_currency = 'PHP'
          AND rate_date = ? AND source = 'manual'
        """,
        (rate_date,),
    ).fetchone()
    if existing:
        connection.execute(
            """
            INSERT INTO fx_rate_revisions
              (fx_rate_id, previous_rate, previous_source, previous_fetched_at)
            VALUES (?, ?, ?, ?)
            """,
            (existing["id"], existing["rate"], existing["source"], existing["fetched_at"]),
        )
        connection.execute(
            "UPDATE fx_rates SET rate = ?, fetched_at = CURRENT_TIMESTAMP WHERE id = ?",
            (float(rate), existing["id"]),
        )
        return existing["id"]
    return connection.execute(
        """
        INSERT INTO fx_rates
          (base_currency, quote_currency, rate_date, rate, source, fetched_at)
        VALUES ('USD', 'PHP', ?, ?, 'manual', CURRENT_TIMESTAMP)
        """,
        (rate_date, float(rate)),
    ).lastrowid
