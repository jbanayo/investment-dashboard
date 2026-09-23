"""Manual fees and transfers recorded directly against cash instruments."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
import sqlite3
from uuid import uuid4

from .cash import get_or_create_cash_instrument
from .transactions import TransactionError, _decimal


def _valid_date(value: str, label: str) -> str:
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise TransactionError(f"Enter a valid {label}.") from None
    if parsed > date.today():
        raise TransactionError(f"{label.capitalize()} cannot be in the future.")
    return value


def _currency(value: str) -> str:
    currency = value.strip().upper()
    if len(currency) != 3 or not currency.isalpha():
        raise TransactionError("Enter a three-letter currency code.")
    return currency


def record_fee(connection: sqlite3.Connection, values) -> int:
    platform = values.get("platform", "").strip()
    if not platform:
        raise TransactionError("Enter a platform.")
    fee_date = _valid_date(values.get("fee_date", ""), "fee date")
    amount = _decimal(values.get("amount", ""), "fee amount")
    currency = _currency(values.get("currency", ""))
    related_instrument_id = values.get("related_instrument_id") or None
    if related_instrument_id:
        related = connection.execute(
            "SELECT platform FROM instruments WHERE id = ?", (related_instrument_id,)
        ).fetchone()
        if related is None or related["platform"] != platform:
            raise TransactionError("The related instrument must belong to the selected platform.")
    cash_id = get_or_create_cash_instrument(connection, platform, currency)
    return connection.execute(
        """
        INSERT INTO transactions
          (instrument_id, related_instrument_id, type, trade_date, currency, net_amount,
           source_type, note, entered_at, platform)
        VALUES (?, ?, 'fee', ?, ?, ?, 'manual', ?, CURRENT_TIMESTAMP, ?)
        """,
        (cash_id, related_instrument_id, fee_date, currency, float(-amount),
         values.get("note", "").strip() or None, platform),
    ).lastrowid


def record_transfer(connection: sqlite3.Connection, values) -> list[int]:
    platform = values.get("platform", "").strip()
    if not platform:
        raise TransactionError("Enter a platform.")
    transfer_date = _valid_date(values.get("transfer_date", ""), "transfer date")
    amount = _decimal(values.get("amount", ""), "transfer amount")
    currency = _currency(values.get("currency", ""))
    direction = values.get("direction")
    if direction not in ("in", "out"):
        raise TransactionError("Choose whether money moved in or out.")
    counterparty = values.get("counterparty_platform", "").strip()
    counterparty_currency = values.get("counterparty_currency", "").strip().upper() or currency
    if counterparty == platform:
        raise TransactionError("Choose a different platform for a matched transfer.")
    cash_id = get_or_create_cash_instrument(connection, platform, currency)
    signed_amount = amount if direction == "in" else -amount
    group_id = str(uuid4()) if counterparty else None
    first_id = connection.execute(
        """
        INSERT INTO transactions
          (instrument_id, type, trade_date, currency, net_amount, source_type, note,
           entered_at, platform, is_external_transfer, transfer_group_id)
        VALUES (?, 'transfer', ?, ?, ?, 'manual', ?, CURRENT_TIMESTAMP, ?, ?, ?)
        """,
        (cash_id, transfer_date, currency, float(signed_amount),
         values.get("note", "").strip() or None, platform, 0 if counterparty else 1, group_id),
    ).lastrowid
    transaction_ids = [first_id]
    if counterparty:
        counterparty_currency = _currency(counterparty_currency)
        counterparty_cash = get_or_create_cash_instrument(
            connection, counterparty, counterparty_currency
        )
        transaction_ids.append(connection.execute(
            """
            INSERT INTO transactions
              (instrument_id, type, trade_date, currency, net_amount, source_type, note,
               entered_at, platform, is_external_transfer, transfer_group_id)
            VALUES (?, 'transfer', ?, ?, ?, 'manual', ?, CURRENT_TIMESTAMP, ?, 0, ?)
            """,
            (counterparty_cash, transfer_date, counterparty_currency, float(-signed_amount),
             "Matched transfer", counterparty, group_id),
        ).lastrowid)
    return transaction_ids
