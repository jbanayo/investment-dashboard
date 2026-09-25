"""Cash instruments and balances.

Cash uses the same instruments and transactions tables as every other asset.
Generated legs record signed net amounts: a positive value credits cash and a
negative value debits it.
"""

from __future__ import annotations

import sqlite3

DEFAULT_CASH_INSTRUMENTS = (
    ("BDO Securities", "PHP"),
    ("IBKR", "USD"),
    ("IBKR", "PHP"),
    ("Kraken", "USD"),
)


def ensure_cash_instruments(connection: sqlite3.Connection) -> None:
    """Create the initial platform/currency cash set without duplicating it."""
    for platform, currency in DEFAULT_CASH_INSTRUMENTS:
        existing = connection.execute(
            """
            SELECT id FROM instruments
            WHERE asset_class = 'cash' AND platform = ? AND native_currency = ?
            """,
            (platform, currency),
        ).fetchone()
        if existing is None:
            connection.execute(
                """
                INSERT INTO instruments
                    (name, ticker, asset_class, platform, native_currency, sector, notes, coverage_status)
                VALUES (?, ?, 'cash', ?, ?, NULL, 'Created automatically for ledger cash legs.', 'cash')
                """,
                (f"{platform} {currency} cash", currency, platform, currency),
            )


def get_or_create_cash_instrument(
    connection: sqlite3.Connection, platform: str, currency: str
) -> int:
    existing = connection.execute(
        """
        SELECT id FROM instruments
        WHERE asset_class = 'cash' AND platform = ? AND native_currency = ?
        """,
        (platform, currency),
    ).fetchone()
    if existing:
        return existing["id"]
    return connection.execute(
        """
        INSERT INTO instruments
            (name, ticker, asset_class, platform, native_currency, notes, coverage_status)
        VALUES (?, ?, 'cash', ?, ?, 'Created automatically for ledger cash legs.', 'cash')
        """,
        (f"{platform} {currency} cash", currency, platform, currency),
    ).lastrowid


def cash_balance(
    connection: sqlite3.Connection, instrument_id: int, as_of: str | None = None
) -> float:
    """Return a balance derived from cash-ledger entries, never typed directly."""
    row = connection.execute(
        "SELECT asset_class FROM instruments WHERE id = ?", (instrument_id,)
    ).fetchone()
    if row is None or row["asset_class"] != "cash":
        raise ValueError("Cash balance can only be calculated for a cash instrument.")
    if as_of:
        return connection.execute(
            "SELECT COALESCE(SUM(net_amount), 0) FROM transactions WHERE instrument_id = ? AND trade_date <= ?",
            (instrument_id, as_of),
        ).fetchone()[0]
    return connection.execute(
        "SELECT COALESCE(SUM(net_amount), 0) FROM transactions WHERE instrument_id = ?",
        (instrument_id,),
    ).fetchone()[0]


def instrument_price(connection: sqlite3.Connection, instrument_id: int) -> float | None:
    """Cash is always valued at 1 in its native currency; other assets use prices."""
    instrument = connection.execute(
        "SELECT asset_class FROM instruments WHERE id = ?", (instrument_id,)
    ).fetchone()
    if instrument is None:
        return None
    if instrument["asset_class"] == "cash":
        return 1.0
    return None
