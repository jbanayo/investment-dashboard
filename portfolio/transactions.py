"""Manual buy and sell entries, including their generated cash ledger legs."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
import sqlite3

from .cash import get_or_create_cash_instrument


class TransactionError(ValueError):
    pass


def _decimal(value: str, label: str, *, allow_zero: bool = False) -> Decimal:
    try:
        number = Decimal(value)
    except (InvalidOperation, TypeError):
        raise TransactionError(f"Enter a valid {label}.") from None
    if number < 0 or (number == 0 and not allow_zero):
        raise TransactionError(f"{label.capitalize()} must be greater than zero.")
    return number


def _trade_values(connection: sqlite3.Connection, values, transaction_type: str):
    instrument_id = int(values.get("instrument_id", 0))
    instrument = connection.execute(
        "SELECT * FROM instruments WHERE id = ?", (instrument_id,)
    ).fetchone()
    if instrument is None or instrument["asset_class"] == "cash":
        raise TransactionError("Choose a non-cash instrument.")

    trade_date = values.get("trade_date", "")
    try:
        parsed_date = date.fromisoformat(trade_date)
    except ValueError:
        raise TransactionError("Enter a valid trade date.") from None
    if parsed_date > date.today():
        raise TransactionError("Trade date cannot be in the future.")

    quantity = _decimal(values.get("quantity", ""), "quantity")
    unit_price = _decimal(values.get("unit_price", ""), "unit price", allow_zero=True)
    if unit_price == 0 and not values.get("zero_price_reason", "").strip():
        raise TransactionError("Explain why this trade has a zero unit price.")
    fees = _decimal(values.get("fees", "0"), "fees", allow_zero=True)
    currency = values.get("currency", instrument["native_currency"]).strip().upper()
    if len(currency) != 3 or not currency.isalpha():
        raise TransactionError("Enter a three-letter currency code.")
    return instrument, trade_date, quantity, unit_price, fees, currency


def position_as_of(
    connection: sqlite3.Connection, instrument_id: int, as_of: str
) -> tuple[Decimal, Decimal]:
    """Return (quantity, average cost) from parent trades up to a date."""
    rows = connection.execute(
        """
        SELECT type, quantity, unit_price, fees FROM transactions
        WHERE instrument_id = ? AND parent_transaction_id IS NULL
          AND type IN ('buy', 'sell') AND trade_date <= ?
        ORDER BY trade_date, id
        """,
        (instrument_id, as_of),
    ).fetchall()
    quantity, average_cost = Decimal("0"), Decimal("0")
    for row in rows:
        row_quantity = Decimal(str(row["quantity"] or 0))
        if row["type"] == "buy":
            total_cost = (quantity * average_cost) + (
                row_quantity * Decimal(str(row["unit_price"] or 0))
            ) + Decimal(str(row["fees"] or 0))
            quantity += row_quantity
            average_cost = total_cost / quantity if quantity else Decimal("0")
        else:
            quantity -= row_quantity
            if quantity == 0:
                average_cost = Decimal("0")
    return quantity, average_cost


def record_buy(connection: sqlite3.Connection, values) -> int:
    instrument, trade_date, quantity, unit_price, fees, currency = _trade_values(
        connection, values, "buy"
    )
    cursor = connection.execute(
        """
        INSERT INTO transactions
          (instrument_id, type, trade_date, quantity, unit_price, fees, currency,
           source_type, note, entered_at, platform)
        VALUES (?, 'buy', ?, ?, ?, ?, ?, 'manual', ?, CURRENT_TIMESTAMP, ?)
        """,
        (instrument["id"], trade_date, float(quantity), float(unit_price), float(fees),
         currency, values.get("note", "").strip() or None, instrument["platform"]),
    )
    parent_id = cursor.lastrowid
    cash_id = get_or_create_cash_instrument(connection, instrument["platform"], currency)
    consideration = (quantity * unit_price) + fees
    connection.execute(
        """
        INSERT INTO transactions
          (instrument_id, type, trade_date, currency, net_amount, parent_transaction_id,
           source_type, note, entered_at, platform)
        VALUES (?, 'buy', ?, ?, ?, ?, 'manual', 'Generated cash leg', CURRENT_TIMESTAMP, ?)
        """,
        (cash_id, trade_date, currency, float(-consideration), parent_id, instrument["platform"]),
    )
    return parent_id


def record_sell(connection: sqlite3.Connection, values) -> tuple[int, Decimal]:
    instrument, trade_date, quantity, unit_price, fees, currency = _trade_values(
        connection, values, "sell"
    )
    held, average_cost = position_as_of(connection, instrument["id"], trade_date)
    if quantity > held:
        raise TransactionError(
            f"Only {held.normalize()} held on {trade_date}. A later buy does not cover an earlier sale."
        )
    proceeds = (quantity * unit_price) - fees
    realised_gain_loss = proceeds - (quantity * average_cost)
    cursor = connection.execute(
        """
        INSERT INTO transactions
          (instrument_id, type, trade_date, quantity, unit_price, fees, currency,
           source_type, note, entered_at, realised_gain_loss, platform)
        VALUES (?, 'sell', ?, ?, ?, ?, ?, 'manual', ?, CURRENT_TIMESTAMP, ?, ?)
        """,
        (instrument["id"], trade_date, float(quantity), float(unit_price), float(fees),
         currency, values.get("note", "").strip() or None, float(realised_gain_loss),
         instrument["platform"]),
    )
    parent_id = cursor.lastrowid
    cash_id = get_or_create_cash_instrument(connection, instrument["platform"], currency)
    connection.execute(
        """
        INSERT INTO transactions
          (instrument_id, type, trade_date, currency, net_amount, parent_transaction_id,
           source_type, note, entered_at, platform)
        VALUES (?, 'sell', ?, ?, ?, ?, 'manual', 'Generated cash leg', CURRENT_TIMESTAMP, ?)
        """,
        (cash_id, trade_date, currency, float(proceeds), parent_id, instrument["platform"]),
    )
    return parent_id, realised_gain_loss


def record_dividend(connection: sqlite3.Connection, values) -> int:
    instrument_id = int(values.get("instrument_id", 0))
    instrument = connection.execute(
        "SELECT * FROM instruments WHERE id = ?", (instrument_id,)
    ).fetchone()
    if instrument is None or instrument["asset_class"] == "cash":
        raise TransactionError("Choose a non-cash instrument.")
    payment_date = values.get("payment_date", "")
    try:
        parsed_date = date.fromisoformat(payment_date)
    except ValueError:
        raise TransactionError("Enter a valid payment date.") from None
    if parsed_date > date.today():
        raise TransactionError("Payment date cannot be in the future.")
    gross_amount = _decimal(values.get("gross_amount", ""), "gross amount")
    tax_withheld = _decimal(
        values.get("tax_withheld", "0"), "withholding tax", allow_zero=True
    )
    if tax_withheld > gross_amount:
        raise TransactionError("Withholding tax cannot exceed the gross amount.")
    currency = values.get("currency", instrument["native_currency"]).strip().upper()
    if len(currency) != 3 or not currency.isalpha():
        raise TransactionError("Enter a three-letter currency code.")
    net_amount = gross_amount - tax_withheld
    cursor = connection.execute(
        """
        INSERT INTO transactions
          (instrument_id, type, trade_date, currency, gross_amount, tax_withheld,
           net_amount, source_type, note, entered_at, platform)
        VALUES (?, 'dividend', ?, ?, ?, ?, ?, 'manual', ?, CURRENT_TIMESTAMP, ?)
        """,
        (instrument["id"], payment_date, currency, float(gross_amount),
         float(tax_withheld), float(net_amount), values.get("note", "").strip() or None,
         instrument["platform"]),
    )
    parent_id = cursor.lastrowid
    cash_id = get_or_create_cash_instrument(connection, instrument["platform"], currency)
    connection.execute(
        """
        INSERT INTO transactions
          (instrument_id, type, trade_date, currency, net_amount, parent_transaction_id,
           source_type, note, entered_at, platform)
        VALUES (?, 'dividend', ?, ?, ?, ?, 'manual', 'Generated cash leg', CURRENT_TIMESTAMP, ?)
        """,
        (cash_id, payment_date, currency, float(net_amount), parent_id, instrument["platform"]),
    )
    return parent_id


def dividend_income(
    connection: sqlite3.Connection, *, instrument_id: int | None = None,
    platform: str | None = None, start_date: str | None = None,
    end_date: str | None = None,
) -> sqlite3.Row:
    """Return gross income, withheld tax, and net cash for a chosen period."""
    clauses = ["t.type = 'dividend'", "t.parent_transaction_id IS NULL"]
    parameters: list[object] = []
    if instrument_id is not None:
        clauses.append("t.instrument_id = ?")
        parameters.append(instrument_id)
    if platform is not None:
        clauses.append("t.platform = ?")
        parameters.append(platform)
    if start_date is not None:
        clauses.append("t.trade_date >= ?")
        parameters.append(start_date)
    if end_date is not None:
        clauses.append("t.trade_date <= ?")
        parameters.append(end_date)
    return connection.execute(
        f"""
        SELECT COALESCE(SUM(t.gross_amount), 0) AS gross_amount,
               COALESCE(SUM(t.tax_withheld), 0) AS tax_withheld,
               COALESCE(SUM(t.net_amount), 0) AS net_amount
        FROM transactions t WHERE {' AND '.join(clauses)}
        """,
        parameters,
    ).fetchone()


def list_transactions(connection: sqlite3.Connection):
    return connection.execute(
        """
        SELECT t.*, i.name AS instrument_name, i.ticker, parent.id AS parent_id
        FROM transactions t
        JOIN instruments i ON i.id = t.instrument_id
        LEFT JOIN transactions parent ON parent.id = t.parent_transaction_id
        ORDER BY t.trade_date DESC, t.id DESC
        """
    ).fetchall()
