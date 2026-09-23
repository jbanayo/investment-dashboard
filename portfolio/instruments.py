"""Instrument ledger operations used by the manual-entry UI."""

from __future__ import annotations

import sqlite3

ASSET_CLASSES = (
    "ph_equity", "us_equity", "crypto", "etf", "fund", "cash", "other",
)
KNOWN_PLATFORMS = ("BDO Securities", "IBKR", "Kraken")


class InstrumentError(ValueError):
    pass


def _clean(values: dict[str, str]) -> dict[str, str | None]:
    asset_class = values.get("asset_class", "").strip()
    if asset_class not in ASSET_CLASSES:
        raise InstrumentError("Choose a supported asset class.")

    name = values.get("name", "").strip()
    platform = values.get("platform", "").strip()
    currency = values.get("native_currency", "").strip().upper()
    if not name:
        raise InstrumentError("Enter an instrument name.")
    if not platform:
        raise InstrumentError("Enter a platform.")
    if len(currency) != 3 or not currency.isalpha():
        raise InstrumentError("Enter a three-letter native currency code.")

    return {
        "name": name,
        "ticker": values.get("ticker", "").strip().upper() or None,
        "asset_class": asset_class,
        "platform": platform,
        "native_currency": currency,
        "sector": values.get("sector", "").strip() or None,
        "notes": values.get("notes", "").strip() or None,
    }


def list_instruments(
    connection: sqlite3.Connection, platform: str | None = None,
    asset_class: str | None = None,
) -> list[sqlite3.Row]:
    clauses, parameters = [], []
    if platform:
        clauses.append("platform = ?")
        parameters.append(platform)
    if asset_class:
        clauses.append("asset_class = ?")
        parameters.append(asset_class)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    return connection.execute(
        f"SELECT * FROM instruments{where} ORDER BY platform, name", parameters
    ).fetchall()


def create_instrument(connection: sqlite3.Connection, values: dict[str, str]) -> int:
    data = _clean(values)
    cursor = connection.execute(
        """
        INSERT INTO instruments
            (name, ticker, asset_class, platform, native_currency, sector, notes)
        VALUES (:name, :ticker, :asset_class, :platform, :native_currency, :sector, :notes)
        """,
        data,
    )
    return cursor.lastrowid


def update_instrument(
    connection: sqlite3.Connection, instrument_id: int, values: dict[str, str]
) -> None:
    data = _clean(values)
    current = connection.execute(
        "SELECT native_currency FROM instruments WHERE id = ?", (instrument_id,)
    ).fetchone()
    if current is None:
        raise InstrumentError("That instrument no longer exists.")
    if data["native_currency"] != current["native_currency"]:
        has_transactions = connection.execute(
            "SELECT EXISTS(SELECT 1 FROM transactions WHERE instrument_id = ?)",
            (instrument_id,),
        ).fetchone()[0]
        if has_transactions:
            raise InstrumentError(
                "Native currency cannot change after transactions exist. Create a new instrument instead."
            )
    data["id"] = instrument_id
    connection.execute(
        """
        UPDATE instruments SET name = :name, ticker = :ticker, asset_class = :asset_class,
            platform = :platform, native_currency = :native_currency, sector = :sector,
            notes = :notes
        WHERE id = :id
        """,
        data,
    )


def delete_instrument(connection: sqlite3.Connection, instrument_id: int) -> None:
    transaction_count = connection.execute(
        "SELECT COUNT(*) FROM transactions WHERE instrument_id = ?", (instrument_id,)
    ).fetchone()[0]
    if transaction_count:
        raise InstrumentError(
            f"Cannot delete this instrument because {transaction_count} transaction(s) depend on it."
        )
    connection.execute("DELETE FROM instruments WHERE id = ?", (instrument_id,))
