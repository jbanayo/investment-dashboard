"""Price-source contract shared by all on-demand fetch adapters.

Adapters receive only a source symbol and a date range. Portfolio information
must never cross this boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol, Sequence
from urllib.parse import urlencode
from urllib.request import urlopen
import json

DEFAULT_TIMEOUT_SECONDS = 10
MANUAL_SOURCE = "manual"


@dataclass(frozen=True)
class PricePoint:
    price_date: date
    close: float
    currency: str


@dataclass(frozen=True)
class FetchFailure:
    source: str
    message: str


class PriceAdapter(Protocol):
    source_name: str

    def fetch_prices(
        self, symbol: str, start_date: date, end_date: date
    ) -> Sequence[PricePoint] | FetchFailure: ...


class BoundedHttpClient:
    """Minimal HTTP boundary with a mandatory per-request timeout."""

    def __init__(self, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS):
        self.timeout_seconds = timeout_seconds

    def get_json(self, endpoint: str, parameters: dict[str, str]):
        url = f"{endpoint}?{urlencode(parameters)}"
        with urlopen(url, timeout=self.timeout_seconds) as response:  # nosec B310 - endpoint is adapter-owned
            return json.loads(response.read().decode("utf-8"))


def refreshable_instruments(connection):
    """Return only instruments that have a configured live source and symbol."""
    return connection.execute(
        """
        SELECT * FROM instruments
        WHERE asset_class != 'cash' AND price_source != ?
          AND source_symbol IS NOT NULL AND source_symbol != ''
        ORDER BY platform, name
        """,
        (MANUAL_SOURCE,),
    ).fetchall()


def lookup_count(connection) -> int:
    return len(refreshable_instruments(connection))
