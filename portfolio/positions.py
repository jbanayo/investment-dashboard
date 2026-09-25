"""Derived positions and valuations. Nothing in this module writes a balance."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
import sqlite3

from .cash import cash_balance


def _decimal(value) -> Decimal:
    return Decimal(str(value or 0))


def positions_as_of(
    connection: sqlite3.Connection, as_of: str | None = None, *, include_zero: bool = False
) -> list[dict]:
    """Compute quantity and average cost for every instrument at a date."""
    as_of = as_of or date.today().isoformat()
    instruments = connection.execute("SELECT * FROM instruments ORDER BY platform, name").fetchall()
    positions = []
    for instrument in instruments:
        if instrument["asset_class"] == "cash":
            quantity, average_cost = _decimal(cash_balance(connection, instrument["id"], as_of)), Decimal("1")
        else:
            quantity, average_cost = Decimal("0"), Decimal("0")
            transactions = connection.execute(
                """
                SELECT type, quantity, unit_price, fees FROM transactions
                WHERE instrument_id = ? AND parent_transaction_id IS NULL
                  AND type IN ('buy', 'sell', 'reward') AND trade_date <= ?
                ORDER BY trade_date, id
                """,
                (instrument["id"], as_of),
            ).fetchall()
            for transaction in transactions:
                transaction_quantity = _decimal(transaction["quantity"])
                if transaction["type"] in ("buy", "reward"):
                    cost = quantity * average_cost + transaction_quantity * _decimal(transaction["unit_price"]) + _decimal(transaction["fees"])
                    quantity += transaction_quantity
                    average_cost = cost / quantity if quantity else Decimal("0")
                else:
                    quantity -= transaction_quantity
                    if quantity == 0:
                        average_cost = Decimal("0")
        if include_zero or quantity != 0:
            positions.append({"instrument": instrument, "quantity": quantity, "average_cost": average_cost, "as_of": as_of})
    return positions


def position_transactions(connection: sqlite3.Connection, instrument_id: int, as_of: str | None = None):
    as_of = as_of or date.today().isoformat()
    return connection.execute(
        """
        SELECT * FROM transactions WHERE instrument_id = ? AND trade_date <= ?
        ORDER BY trade_date, id
        """,
        (instrument_id, as_of),
    ).fetchall()


def _latest_price(connection: sqlite3.Connection, instrument_id: int, as_of: str):
    return connection.execute(
        """
        SELECT * FROM prices WHERE instrument_id = ? AND price_date <= ?
        ORDER BY price_date DESC, fetched_at DESC LIMIT 1
        """,
        (instrument_id, as_of),
    ).fetchone()


def _previous_price(connection: sqlite3.Connection, instrument_id: int, current_date: str):
    return connection.execute(
        """
        SELECT * FROM prices WHERE instrument_id = ? AND price_date < ?
        ORDER BY price_date DESC, fetched_at DESC LIMIT 1
        """,
        (instrument_id, current_date),
    ).fetchone()


def _fx_rate(connection: sqlite3.Connection, source_currency: str, base_currency: str, as_of: str):
    if source_currency == base_currency:
        return Decimal("1"), None
    direct = connection.execute(
        """
        SELECT * FROM fx_rates WHERE base_currency = ? AND quote_currency = ? AND rate_date <= ?
        ORDER BY rate_date DESC, fetched_at DESC LIMIT 1
        """,
        (source_currency, base_currency, as_of),
    ).fetchone()
    if direct:
        return _decimal(direct["rate"]), direct
    inverse = connection.execute(
        """
        SELECT * FROM fx_rates WHERE base_currency = ? AND quote_currency = ? AND rate_date <= ?
        ORDER BY rate_date DESC, fetched_at DESC LIMIT 1
        """,
        (base_currency, source_currency, as_of),
    ).fetchone()
    if inverse:
        return Decimal("1") / _decimal(inverse["rate"]), inverse
    return None, None


def last_trading_day(today: date | None = None) -> date:
    today = today or date.today()
    offset = 3 if today.weekday() == 0 else 2 if today.weekday() == 6 else 1
    return today - timedelta(days=offset)


def portfolio_snapshot(
    connection: sqlite3.Connection, base_currency: str = "PHP", as_of: str | None = None
) -> dict:
    """Value all positions, preserving missing data rather than assigning zero."""
    as_of = as_of or date.today().isoformat()
    base_currency = base_currency.upper()
    valued, excluded = [], []
    total, daily_change = Decimal("0"), Decimal("0")
    for position in positions_as_of(connection, as_of):
        instrument = position["instrument"]
        if instrument["asset_class"] == "cash":
            price = {"price": 1, "price_date": as_of, "currency": instrument["native_currency"], "source": "cash"}
            previous = None
        else:
            price = _latest_price(connection, instrument["id"], as_of)
            previous = _previous_price(connection, instrument["id"], price["price_date"]) if price else None
        if price is None:
            excluded.append({**position, "reason": "No price"})
            continue
        fx, fx_row = _fx_rate(connection, price["currency"], base_currency, as_of)
        if fx is None:
            excluded.append({**position, "reason": f"No {price['currency']}/{base_currency} FX rate"})
            continue
        market_value_native = position["quantity"] * _decimal(price["price"])
        market_value_base = market_value_native * fx
        cost_base = position["quantity"] * position["average_cost"] * fx
        change = Decimal("0")
        if previous:
            change = position["quantity"] * (_decimal(price["price"]) - _decimal(previous["price"])) * fx
        item = {**position, "price": price, "previous_price": previous, "fx": fx, "fx_row": fx_row, "market_value_native": market_value_native, "market_value_base": market_value_base, "unrealised_gain_loss": market_value_base - cost_base, "daily_change": change, "stale": instrument["asset_class"] != "cash" and date.fromisoformat(price["price_date"]) < last_trading_day()}
        valued.append(item)
        total += market_value_base
        daily_change += change
    for item in valued:
        item["allocation"] = item["market_value_base"] / total if total else Decimal("0")
    previous_total = total - daily_change
    return {"as_of": as_of, "base_currency": base_currency, "positions": valued, "excluded": excluded, "total": total, "daily_change": daily_change, "daily_change_percent": daily_change / previous_total if previous_total else None}


def daily_valuations(
    connection: sqlite3.Connection, start_date: str, end_date: str,
    base_currency: str = "PHP",
) -> list[dict]:
    """Calculate a non-cached end-of-day portfolio value series.

    Each point is derived from `positions_as_of`, then valued with the most
    recent recorded close and FX rate on or before that date. Missing inputs
    produce a gap rather than a made-up zero. Phase 3 S2 will refine the
    permitted carry-forward window for market holidays.
    """
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    if end < start:
        raise ValueError("End date must not precede start date.")
    values = []
    current = start
    while current <= end:
        point_date = current.isoformat()
        snapshot = portfolio_snapshot(connection, base_currency, point_date)
        flow = _external_flow_on_date(connection, point_date, base_currency)
        stale = [item for item in snapshot["positions"] if item["instrument"]["asset_class"] != "cash" and _trading_days_between(item["price"]["price_date"], point_date) > 5]
        excluded = snapshot["excluded"] + [{**item, "reason": "Price older than 5 trading days"} for item in stale]
        values.append({
            "date": point_date,
            "value_base": snapshot["total"] if not excluded else None,
            "net_external_flow_base": flow,
            "status": "ok" if not excluded else "gap",
            "excluded": excluded,
            "transfers": _external_transfers_on_date(connection, point_date),
        })
        current += timedelta(days=1)
    return values


def _external_transfers_on_date(connection, flow_date: str):
    return connection.execute(
        """SELECT net_amount, currency, note FROM transactions
           WHERE type = 'transfer' AND is_external_transfer = 1 AND trade_date = ?""",
        (flow_date,),
    ).fetchall()


def _trading_days_between(start_date: str, end_date: str) -> int:
    """Weekdays elapsed after a close; weekends do not make a gap."""
    start, end = date.fromisoformat(start_date), date.fromisoformat(end_date)
    days, cursor = 0, start + timedelta(days=1)
    while cursor <= end:
        if cursor.weekday() < 5:
            days += 1
        cursor += timedelta(days=1)
    return days


def transfer_adjusted_returns(points: list[dict]) -> dict:
    """Time-weighted return and peso gain, never treating a gap as a flat day."""
    previous = None
    chained = Decimal("1")
    flows_since_previous = Decimal("0")
    total_flows = Decimal("0")
    first_value = last_value = None
    for point in points:
        flow = point["net_external_flow_base"] or Decimal("0")
        total_flows += flow
        flows_since_previous += flow
        if point["status"] != "ok":
            point["cumulative_return"] = None
            continue
        value = point["value_base"]
        if first_value is None:
            first_value = value
            point["cumulative_return"] = Decimal("0")
        else:
            period_return = (value - flows_since_previous - previous) / previous if previous else Decimal("0")
            chained *= Decimal("1") + period_return
            point["cumulative_return"] = chained - Decimal("1")
        previous, last_value, flows_since_previous = value, value, Decimal("0")
    gain = (last_value - first_value - total_flows) if first_value is not None else None
    return {"return_percent": chained - Decimal("1") if first_value is not None else None, "gain_base": gain, "net_flows": total_flows, "first_value": first_value, "last_value": last_value}


def _external_flow_on_date(
    connection: sqlite3.Connection, flow_date: str, base_currency: str
) -> Decimal | None:
    rows = connection.execute(
        """
        SELECT net_amount, currency FROM transactions
        WHERE type = 'transfer' AND is_external_transfer = 1 AND trade_date = ?
        """,
        (flow_date,),
    ).fetchall()
    total = Decimal("0")
    for row in rows:
        fx, _ = _fx_rate(connection, row["currency"], base_currency.upper(), flow_date)
        if fx is None:
            return None
        total += _decimal(row["net_amount"]) * fx
    return total
