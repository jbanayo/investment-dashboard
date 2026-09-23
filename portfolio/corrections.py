"""Safe correction of parent ledger transactions and generated cash legs."""

from __future__ import annotations

import sqlite3
from decimal import Decimal

from .cash import get_or_create_cash_instrument
from .transactions import TransactionError, _trade_values


def _parent(connection: sqlite3.Connection, transaction_id: int):
    row = connection.execute("SELECT * FROM transactions WHERE id = ?", (transaction_id,)).fetchone()
    if row is None:
        raise TransactionError("That transaction no longer exists.")
    if row["parent_transaction_id"] is not None:
        raise TransactionError("Generated cash legs must be edited or deleted through their parent transaction.")
    return row


def _validate_trade_history(connection: sqlite3.Connection, instrument_id: int) -> None:
    quantity = 0.0
    rows = connection.execute(
        """
        SELECT id, type, quantity, trade_date FROM transactions
        WHERE instrument_id = ? AND parent_transaction_id IS NULL AND type IN ('buy', 'sell')
        ORDER BY trade_date, id
        """,
        (instrument_id,),
    ).fetchall()
    for row in rows:
        if row["type"] == "buy":
            quantity += row["quantity"]
        elif row["quantity"] > quantity:
            raise TransactionError(
                f"Cannot remove this buy: sell on {row['trade_date']} needs quantity it supplied."
            )
        else:
            quantity -= row["quantity"]


def delete_transaction(connection: sqlite3.Connection, transaction_id: int) -> None:
    parent = _parent(connection, transaction_id)
    connection.execute("SAVEPOINT delete_transaction")
    try:
        connection.execute("DELETE FROM transactions WHERE parent_transaction_id = ?", (transaction_id,))
        connection.execute("DELETE FROM transactions WHERE id = ?", (transaction_id,))
        if parent["type"] in ("buy", "sell"):
            _validate_trade_history(connection, parent["instrument_id"])
    except Exception:
        connection.execute("ROLLBACK TO delete_transaction")
        connection.execute("RELEASE delete_transaction")
        raise
    connection.execute("RELEASE delete_transaction")


def update_transaction(connection: sqlite3.Connection, transaction_id: int, values) -> None:
    parent = _parent(connection, transaction_id)
    if parent["type"] not in ("buy", "sell"):
        raise TransactionError("This transaction type cannot yet be edited from the ledger.")
    connection.execute("SAVEPOINT update_transaction")
    try:
        instrument, trade_date, quantity, unit_price, fees, currency = _trade_values(
            connection, values, parent["type"]
        )
        if instrument["id"] != parent["instrument_id"]:
            raise TransactionError("Changing the instrument on an existing trade is not supported. Delete it and record the new trade.")
        connection.execute(
            """UPDATE transactions SET instrument_id = ?, trade_date = ?, quantity = ?,
               unit_price = ?, fees = ?, currency = ?, note = ?, platform = ? WHERE id = ?""",
            (instrument["id"], trade_date, float(quantity), float(unit_price), float(fees),
             currency, values.get("note", "").strip() or None, instrument["platform"], transaction_id),
        )
        _validate_trade_history(connection, instrument["id"])
        connection.execute("DELETE FROM transactions WHERE parent_transaction_id = ?", (transaction_id,))
        amount = quantity * unit_price + fees if parent["type"] == "buy" else quantity * unit_price - fees
        cash_id = get_or_create_cash_instrument(connection, instrument["platform"], currency)
        connection.execute(
            """INSERT INTO transactions (instrument_id, type, trade_date, currency, net_amount,
               parent_transaction_id, source_type, note, entered_at, platform)
               VALUES (?, ?, ?, ?, ?, ?, 'manual', 'Generated cash leg', CURRENT_TIMESTAMP, ?)""",
            (cash_id, parent["type"], trade_date, currency,
             float(-amount if parent["type"] == "buy" else amount), transaction_id, instrument["platform"]),
        )
        _recompute_realised_gains(connection, instrument["id"])
    except Exception:
        connection.execute("ROLLBACK TO update_transaction")
        connection.execute("RELEASE update_transaction")
        raise
    connection.execute("RELEASE update_transaction")


def _recompute_realised_gains(connection: sqlite3.Connection, instrument_id: int) -> None:
    quantity, average_cost = Decimal("0"), Decimal("0")
    rows = connection.execute(
        """SELECT * FROM transactions WHERE instrument_id = ? AND parent_transaction_id IS NULL
           AND type IN ('buy', 'sell') ORDER BY trade_date, id""", (instrument_id,)
    ).fetchall()
    for row in rows:
        amount = Decimal(str(row["quantity"] or 0))
        price = Decimal(str(row["unit_price"] or 0))
        fees = Decimal(str(row["fees"] or 0))
        if row["type"] == "buy":
            cost = quantity * average_cost + amount * price + fees
            quantity += amount
            average_cost = cost / quantity if quantity else Decimal("0")
        else:
            realised = amount * price - fees - amount * average_cost
            connection.execute("UPDATE transactions SET realised_gain_loss = ? WHERE id = ?", (float(realised), row["id"]))
            quantity -= amount
            if quantity == 0:
                average_cost = Decimal("0")
