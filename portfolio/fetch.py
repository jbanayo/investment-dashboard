"""Price-source contract shared by all on-demand fetch adapters.

Adapters receive only a source symbol and a date range. Portfolio information
must never cross this boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
import sqlite3
from typing import Protocol, Sequence
from urllib.parse import urlencode
from urllib.error import HTTPError
from urllib.request import urlopen
import json
import ssl

import certifi

DEFAULT_TIMEOUT_SECONDS = 10
MANUAL_SOURCE = "manual"
TWELVE_DATA_SOURCE = "twelve_data"
TWELVE_DATA_DAILY_REQUEST_LIMIT = 800
TWELVE_DATA_MINUTE_REQUEST_LIMIT = 8


@dataclass(frozen=True)
class PricePoint:
    price_date: date
    close: float
    currency: str


@dataclass(frozen=True)
class FetchFailure:
    source: str
    message: str
    stop_refresh: bool = False


@dataclass(frozen=True)
class RefreshResult:
    instruments_updated: int
    prices_written: int
    requests_used: int
    requests_remaining: int
    failures: tuple[FetchFailure, ...]
    instruments_pending: int = 0


class PriceAdapter(Protocol):
    source_name: str

    def fetch_prices(
        self, symbol: str, start_date: date, end_date: date
    ) -> Sequence[PricePoint] | FetchFailure: ...


class BoundedHttpClient:
    """Minimal HTTP boundary with a mandatory per-request timeout."""

    def __init__(self, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS):
        self.timeout_seconds = timeout_seconds
        self.ssl_context = ssl.create_default_context(cafile=certifi.where())

    def get_json(self, endpoint: str, parameters: dict[str, str]):
        url = f"{endpoint}?{urlencode(parameters)}"
        try:
            with urlopen(  # nosec B310 - endpoint is adapter-owned
                url, timeout=self.timeout_seconds, context=self.ssl_context
            ) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            # Twelve Data returns useful JSON for entitlement and symbol errors.
            try:
                return json.loads(error.read().decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                raise error


class TwelveDataAdapter:
    """Daily-close adapter for Twelve Data's time_series endpoint."""

    source_name = TWELVE_DATA_SOURCE
    endpoint = "https://api.twelvedata.com/time_series"

    def __init__(
        self,
        api_key: str,
        client: BoundedHttpClient | None = None,
        *,
        currency: str | None = None,
        exchange: str | None = None,
    ):
        self.api_key = api_key
        self.client = client or BoundedHttpClient()
        self.currency = currency
        self.exchange = exchange

    def fetch_prices(
        self, symbol: str, start_date: date, end_date: date
    ) -> Sequence[PricePoint] | FetchFailure:
        ticker, separator, mic_code = symbol.partition(":")
        try:
            parameters = {
                "symbol": ticker,
                "interval": "1day",
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "outputsize": "5000",
                "timezone": "Exchange",
                "apikey": self.api_key,
            }
            if separator:
                parameters["mic_code"] = mic_code
            if self.exchange:
                parameters["exchange"] = self.exchange
            payload = self.client.get_json(self.endpoint, parameters)
        except Exception as error:
            return FetchFailure(self.source_name, f"Network error: {error}")
        if payload.get("status") == "error" or "values" not in payload:
            message = str(payload.get("message") or "Twelve Data returned no price series.")
            return FetchFailure(
                self.source_name, message,
                stop_refresh="available starting with" in message.lower(),
            )
        points = []
        currency = self.currency or ("PHP" if mic_code == "XPHS" else payload.get("meta", {}).get("currency", "USD"))
        try:
            for row in payload["values"]:
                points.append(PricePoint(
                    price_date=date.fromisoformat(row["datetime"][:10]),
                    close=float(row["close"]),
                    currency=currency,
                ))
        except (KeyError, TypeError, ValueError) as error:
            return FetchFailure(self.source_name, f"Invalid Twelve Data response: {error}")
        return sorted(points, key=lambda point: point.price_date)


def _usage_date(now: datetime | None = None) -> str:
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return current.astimezone(UTC).date().isoformat()


def _usage_minute(now: datetime | None = None) -> str:
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return current.astimezone(UTC).strftime("%Y-%m-%dT%H:%M")


def twelve_data_usage(
    connection: sqlite3.Connection, now: datetime | None = None
) -> tuple[int, int]:
    row = connection.execute(
        "SELECT request_count FROM price_fetch_usage WHERE source = ? AND usage_date = ?",
        (TWELVE_DATA_SOURCE, _usage_date(now)),
    ).fetchone()
    used = int(row["request_count"]) if row else 0
    return used, max(0, TWELVE_DATA_DAILY_REQUEST_LIMIT - used)


def reserve_twelve_data_request(
    connection: sqlite3.Connection, now: datetime | None = None
) -> int:
    """Reserve one call before network I/O, so failures also count toward the cap."""
    usage_day, usage_minute = _usage_date(now), _usage_minute(now)
    connection.execute("BEGIN IMMEDIATE")
    minute_row = connection.execute(
        """INSERT INTO price_fetch_usage (source, usage_date, request_count)
           VALUES ('twelve_data_minute', ?, 1)
           ON CONFLICT(source, usage_date) DO UPDATE
             SET request_count = request_count + 1
             WHERE request_count < ?
           RETURNING request_count""",
        (usage_minute, TWELVE_DATA_MINUTE_REQUEST_LIMIT),
    ).fetchone()
    if minute_row is None:
        connection.rollback()
        raise RuntimeError("Twelve Data minute limit reached (8/8). Wait until the next minute.")
    row = connection.execute(
        """INSERT INTO price_fetch_usage (source, usage_date, request_count)
           VALUES (?, ?, 1)
           ON CONFLICT(source, usage_date) DO UPDATE
             SET request_count = request_count + 1
             WHERE request_count < ?
           RETURNING request_count""",
        (TWELVE_DATA_SOURCE, usage_day, TWELVE_DATA_DAILY_REQUEST_LIMIT),
    ).fetchone()
    if row is None:
        connection.rollback()
        raise RuntimeError("Twelve Data daily request limit reached (800/800). Try again tomorrow.")
    # Persist before HTTP I/O. Timeouts must consume capacity so retries cannot
    # bypass the local guardrail.
    connection.commit()
    return TWELVE_DATA_DAILY_REQUEST_LIMIT - int(row["request_count"])


def refresh_twelve_data_crypto_prices(
    connection: sqlite3.Connection,
    api_key: str,
    *,
    end_date: date | None = None,
    adapter: PriceAdapter | None = None,
) -> RefreshResult:
    """Fetch missing Kraken crypto closes, using at most one request per instrument."""
    if not api_key.strip():
        raise ValueError("Twelve Data API key is not configured.")
    # Start request accounting from a clean transaction boundary. Each network
    # reservation is then committed before the corresponding HTTP call.
    connection.commit()
    end_date = end_date or date.today()
    # Twelve Data's aggregate crypto feed is included in Basic. Naming Kraken as
    # the exchange makes otherwise valid pairs fail entitlement/symbol checks.
    adapter = adapter or TwelveDataAdapter(api_key, currency="USD")
    instruments = connection.execute(
        """SELECT i.*, MIN(t.trade_date) AS first_trade
           FROM instruments i
           JOIN transactions t ON t.instrument_id = i.id
           WHERE i.price_source = ? AND i.source_symbol IS NOT NULL
             AND i.source_symbol != '' AND i.asset_class = 'crypto'
           GROUP BY i.id
           ORDER BY i.ticker""",
        (TWELVE_DATA_SOURCE,),
    ).fetchall()
    updated = written = requests = completed = 0
    failures: list[FetchFailure] = []
    for instrument in instruments:
        latest = connection.execute(
            """SELECT MAX(price_date) AS price_date FROM prices
               WHERE instrument_id = ? AND source = 'Twelve Data daily close'""",
            (instrument["id"],),
        ).fetchone()["price_date"]
        start_date = (
            date.fromisoformat(latest) + timedelta(days=1)
            if latest else date.fromisoformat(instrument["first_trade"])
        )
        if start_date > end_date:
            completed += 1
            continue
        try:
            reserve_twelve_data_request(connection)
        except RuntimeError as error:
            failures.append(FetchFailure(TWELVE_DATA_SOURCE, str(error)))
            break
        requests += 1
        result = adapter.fetch_prices(instrument["source_symbol"], start_date, end_date)
        if isinstance(result, FetchFailure):
            failures.append(FetchFailure(
                result.source, f"{instrument['ticker']}: {result.message}", result.stop_refresh
            ))
            if result.stop_refresh:
                break
            continue
        for point in result:
            connection.execute(
                """INSERT INTO prices
                   (instrument_id, price_date, price, currency, source, fetched_at)
                   VALUES (?, ?, ?, ?, 'Twelve Data daily close', CURRENT_TIMESTAMP)
                   ON CONFLICT(instrument_id, price_date, source)
                   DO UPDATE SET price = excluded.price, currency = excluded.currency,
                                 fetched_at = CURRENT_TIMESTAMP""",
                (instrument["id"], point.price_date.isoformat(), point.close, point.currency),
            )
            written += 1
        connection.commit()
        updated += 1
        completed += 1
    _used, remaining = twelve_data_usage(connection)
    pending = max(0, len(instruments) - completed)
    return RefreshResult(updated, written, requests, remaining, tuple(failures), pending)


def refresh_twelve_data_ibkr_prices(
    connection: sqlite3.Connection,
    api_key: str,
    *,
    end_date: date | None = None,
    adapter: PriceAdapter | None = None,
) -> RefreshResult:
    """Fetch missing IBKR US-equity/ETF closes within each holding's active range."""
    if not api_key.strip():
        raise ValueError("Twelve Data API key is not configured.")
    connection.commit()
    if end_date is None:
        today = date.today()
        previous_close_offset = 3 if today.weekday() == 0 else 2 if today.weekday() == 6 else 1
        end_date = today - timedelta(days=previous_close_offset)
    adapter = adapter or TwelveDataAdapter(api_key, currency="USD")
    instruments = connection.execute(
        """SELECT i.*, MIN(t.trade_date) AS first_trade, MAX(t.trade_date) AS last_trade,
                  SUM(CASE
                    WHEN t.type IN ('buy','reward') THEN COALESCE(t.quantity,0)
                    WHEN t.type = 'sell' THEN -COALESCE(t.quantity,0)
                    WHEN t.type = 'transfer' THEN COALESCE(t.quantity,0)
                    ELSE 0
                  END) AS current_quantity
           FROM instruments i
           JOIN transactions t ON t.instrument_id = i.id
             AND t.parent_transaction_id IS NULL
           WHERE i.platform = 'IBKR' AND i.price_source = ?
             AND i.source_symbol IS NOT NULL AND i.source_symbol != ''
             AND i.asset_class IN ('us_equity','etf')
           GROUP BY i.id
           ORDER BY i.ticker""",
        (TWELVE_DATA_SOURCE,),
    ).fetchall()
    updated = written = requests = completed = 0
    failures: list[FetchFailure] = []
    for instrument in instruments:
        instrument_end = end_date
        is_closed = abs(float(instrument["current_quantity"] or 0)) < 1e-12
        if is_closed:
            instrument_end = min(instrument_end, date.fromisoformat(instrument["last_trade"]))
            latest_known = connection.execute(
                "SELECT MAX(price_date) AS price_date FROM prices WHERE instrument_id = ?",
                (instrument["id"],),
            ).fetchone()["price_date"]
            if latest_known and date.fromisoformat(latest_known) >= instrument_end:
                completed += 1
                continue
        latest = connection.execute(
            """SELECT MAX(price_date) AS price_date FROM prices
               WHERE instrument_id = ? AND source = 'Twelve Data daily close'""",
            (instrument["id"],),
        ).fetchone()["price_date"]
        start_date = (
            date.fromisoformat(latest) + timedelta(days=1)
            if latest else date.fromisoformat(instrument["first_trade"])
        )
        if start_date > instrument_end:
            completed += 1
            continue
        try:
            reserve_twelve_data_request(connection)
        except RuntimeError as error:
            failures.append(FetchFailure(TWELVE_DATA_SOURCE, str(error)))
            break
        requests += 1
        result = adapter.fetch_prices(
            instrument["source_symbol"], start_date, instrument_end
        )
        if isinstance(result, FetchFailure):
            failures.append(FetchFailure(
                result.source, f"{instrument['ticker']}: {result.message}", result.stop_refresh
            ))
            if result.stop_refresh:
                break
            continue
        for point in result:
            connection.execute(
                """INSERT INTO prices
                   (instrument_id, price_date, price, currency, source, fetched_at)
                   VALUES (?, ?, ?, ?, 'Twelve Data daily close', CURRENT_TIMESTAMP)
                   ON CONFLICT(instrument_id, price_date, source)
                   DO UPDATE SET price = excluded.price, currency = excluded.currency,
                                 fetched_at = CURRENT_TIMESTAMP""",
                (instrument["id"], point.price_date.isoformat(), point.close, point.currency),
            )
            written += 1
        connection.commit()
        updated += 1
        completed += 1
    _used, remaining = twelve_data_usage(connection)
    pending = max(0, len(instruments) - completed)
    return RefreshResult(updated, written, requests, remaining, tuple(failures), pending)


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
