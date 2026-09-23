"""Persist a comparison between the dashboard and an independently built sheet."""

from __future__ import annotations

from decimal import Decimal
import sqlite3

from .positions import portfolio_snapshot
from .transactions import TransactionError, _decimal


def record_reconciliation(
    connection: sqlite3.Connection, spreadsheet_total: str, *, base_currency: str = "PHP",
    reconciliation_date: str | None = None, note: str = "",
) -> int:
    expected = _decimal(spreadsheet_total, "spreadsheet total", allow_zero=True)
    snapshot = portfolio_snapshot(connection, base_currency, reconciliation_date)
    if snapshot["excluded"]:
        raise TransactionError("Enter prices and FX for every holding before reconciling the total.")
    actual = snapshot["total"]
    return connection.execute(
        """INSERT INTO reconciliation_records
          (reconciliation_date, base_currency, dashboard_total, spreadsheet_total, difference, note)
          VALUES (?, ?, ?, ?, ?, ?)""",
        (snapshot["as_of"], snapshot["base_currency"], float(actual), float(expected),
         float(actual - expected), note.strip() or None),
    ).lastrowid
