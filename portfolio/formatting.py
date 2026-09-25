"""Jinja filters implementing the style guide's formatting rules (section 6)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

MINUS = "−"
SYMBOLS = {"PHP": "₱", "USD": "$"}


def _number(value) -> Decimal:
    return Decimal(str(value or 0))


def _symbol(currency: str) -> str:
    currency = (currency or "PHP").upper()
    return SYMBOLS.get(currency, currency + " ")


def _grouped(value: Decimal, dp: int) -> str:
    return f"{abs(value):,.{dp}f}"


def money(value, currency: str = "PHP", dp: int = 0) -> str:
    number = _number(value)
    return (MINUS if number < 0 else "") + _symbol(currency) + _grouped(number, dp)


def signed(value, currency: str = "PHP", dp: int = 0) -> str:
    number = _number(value)
    sign = "+" if number > 0 else MINUS if number < 0 else ""
    return sign + _symbol(currency) + _grouped(number, dp)


def pct(value, dp: int = 2) -> str:
    if value is None:
        return "—"
    number = _number(value) * 100
    sign = "+" if number > 0 else MINUS if number < 0 else ""
    return sign + _grouped(number, dp) + "%"


def share(value, dp: int = 1) -> str:
    """An unsigned share of a total, such as allocation."""
    return _grouped(_number(value) * 100, dp) + "%"


def unit_price(value, currency: str = "PHP") -> str:
    number = _number(value)
    dp = 0 if abs(number) >= 1000 else 4 if abs(number) < 1 else 2
    return money(number, currency, dp)


def quantity(value, asset_class: str = "") -> str:
    places = 6 if asset_class == "crypto" else 4
    text = f"{_number(value):,.{places}f}".rstrip("0").rstrip(".")
    return text.replace("-", MINUS)


def direction(value) -> str:
    """CSS class for a signed figure."""
    if value is None:
        return ""
    number = _number(value)
    return "up" if number > 0 else "down" if number < 0 else ""


def arrow(value) -> str:
    number = _number(value)
    return "▲ " if number > 0 else "▼ " if number < 0 else ""


def _date(value) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def short_date(value) -> str:
    parsed = _date(value)
    return f"{parsed:%b} {parsed.day}" if parsed else "—"


def long_date(value) -> str:
    parsed = _date(value)
    return f"{parsed:%b} {parsed.day}, {parsed.year}" if parsed else "—"


def timestamp(value) -> str:
    if not value:
        return "—"
    return datetime.fromisoformat(str(value)).strftime("%Y-%m-%d %H:%M")


FILTERS = {
    "money": money, "signed": signed, "pct": pct, "share": share,
    "unit_price": unit_price, "quantity": quantity, "direction": direction,
    "arrow": arrow, "short_date": short_date, "long_date": long_date,
    "timestamp": timestamp,
}
