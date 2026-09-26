"""On-demand historical closes from the public PSE Edge chart endpoint."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import html
import json
import re
import sqlite3
import ssl
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import certifi

from .fetch import FetchFailure, PricePoint
from .positions import positions_as_of

PSE_EDGE_SOURCE = "pse_edge"
PSE_EDGE_PRICE_SOURCE = "PSE Edge daily close"
PSE_EDGE_BASE_URL = "https://edge.pse.com.ph"


@dataclass(frozen=True)
class PseRefreshResult:
    instruments_updated: int
    prices_written: int
    requests_used: int
    failures: tuple[FetchFailure, ...]


class PseEdgeError(RuntimeError):
    pass


class PseEdgeClient:
    """Small, rate-limited client for the endpoints used by PSE Edge charts."""

    def __init__(self, timeout_seconds: int = 20, *, sleep=time.sleep, monotonic=time.monotonic):
        self.timeout_seconds = timeout_seconds
        self.ssl_context = ssl.create_default_context(cafile=certifi.where())
        self.sleep = sleep
        self.monotonic = monotonic
        self.last_request_at: float | None = None
        self.requests_used = 0

    def _request(self, request: Request) -> bytes:
        if self.last_request_at is not None:
            wait = 1.0 - (self.monotonic() - self.last_request_at)
            if wait > 0:
                self.sleep(wait)
        try:
            with urlopen(request, timeout=self.timeout_seconds, context=self.ssl_context) as response:
                return response.read()
        except Exception as error:
            raise PseEdgeError(f"PSE Edge request failed: {error}") from error
        finally:
            self.last_request_at = self.monotonic()
            self.requests_used += 1

    def _get(self, path: str, parameters: dict[str, str]) -> bytes:
        request = Request(
            f"{PSE_EDGE_BASE_URL}{path}?{urlencode(parameters)}",
            headers={"User-Agent": "investment-dashboard/1.0 (personal portfolio)"},
        )
        return self._request(request)

    def resolve(self, symbol: str) -> tuple[str, str]:
        try:
            matches = json.loads(self._get(
                "/autoComplete/searchCompanyNameSymbol.ax", {"term": symbol}
            ).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise PseEdgeError("PSE Edge returned an invalid ticker lookup response.") from error
        match = next(
            (item for item in matches if str(item.get("symbol", "")).upper() == symbol.upper()),
            None,
        )
        if not match or not match.get("cmpyId"):
            raise PseEdgeError(f"No exact PSE Edge match for {symbol}.")
        company_id = str(match["cmpyId"])
        page = self._get("/companyPage/stockData.do", {"cmpy_id": company_id}).decode(
            "utf-8", errors="replace"
        )
        select = re.search(
            r"<select[^>]*name=[\"']security_id[\"'][^>]*>(.*?)</select>",
            page,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not select:
            raise PseEdgeError(f"PSE Edge did not list a security ID for {symbol}.")
        options = re.findall(
            r"<option[^>]*value=[\"']([^\"']+)[\"'][^>]*>(.*?)</option>",
            select.group(1),
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not options:
            raise PseEdgeError(f"PSE Edge did not list a security ID for {symbol}.")
        exact = next(
            (value for value, label in options if symbol.upper() in html.unescape(label).upper()),
            options[0][0],
        )
        return company_id, exact

    def fetch_history(
        self, company_id: str, security_id: str, start_date: date, end_date: date
    ) -> list[PricePoint]:
        payload = json.dumps({
            "cmpy_id": company_id,
            "security_id": security_id,
            "startDate": start_date.strftime("%m-%d-%Y"),
            "endDate": end_date.strftime("%m-%d-%Y"),
        }).encode("utf-8")
        request = Request(
            f"{PSE_EDGE_BASE_URL}/common/DisclosureCht.ax",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "investment-dashboard/1.0 (personal portfolio)",
            },
            method="POST",
        )
        try:
            result = json.loads(self._request(request).decode("utf-8"))
            rows = result["chartData"]
            points = [
                PricePoint(
                    datetime.strptime(row["CHART_DATE"], "%b %d, %Y %H:%M:%S").date(),
                    float(row["CLOSE"]),
                    "PHP",
                )
                for row in rows
                if row.get("CLOSE") is not None
            ]
        except (KeyError, TypeError, ValueError, json.JSONDecodeError, UnicodeDecodeError) as error:
            raise PseEdgeError("PSE Edge returned an invalid chart response.") from error
        return sorted(points, key=lambda point: point.price_date)


def refresh_pse_edge_prices(
    connection: sqlite3.Connection,
    *,
    end_date: date | None = None,
    client: PseEdgeClient | None = None,
) -> PseRefreshResult:
    """Fetch closes only for BDO equities that appear in the portfolio ledger.

    Open positions run through ``end_date``. Closed positions stop at their last
    transaction because later prices cannot affect the historical portfolio.
    """
    connection.commit()
    end_date = end_date or date.today()
    client = client or PseEdgeClient()
    current_positions = positions_as_of(
        connection, end_date.isoformat(), platform="BDO Securities"
    )
    open_ids = {
        position["instrument"]["id"] for position in current_positions
        if position["instrument"]["asset_class"] == "ph_equity"
    }
    instruments = connection.execute(
        """SELECT i.*, MIN(t.trade_date) AS first_trade,
                         MAX(t.trade_date) AS last_trade
           FROM instruments i
           JOIN transactions t ON t.instrument_id = i.id
           WHERE i.platform = 'BDO Securities' AND i.asset_class = 'ph_equity'
             AND i.ticker IS NOT NULL AND i.ticker != ''
             AND t.parent_transaction_id IS NULL
           GROUP BY i.id ORDER BY i.ticker"""
    ).fetchall()
    updated = written = 0
    failures: list[FetchFailure] = []
    initial_requests = client.requests_used
    for instrument in instruments:
        ticker = instrument["ticker"]
        try:
            mapping = connection.execute(
                """SELECT company_id, security_id FROM instrument_source_mappings
                   WHERE instrument_id = ? AND source = ?""",
                (instrument["id"], PSE_EDGE_SOURCE),
            ).fetchone()
            if mapping:
                company_id, security_id = mapping["company_id"], mapping["security_id"]
            else:
                company_id, security_id = client.resolve(ticker)
                connection.execute(
                    """INSERT INTO instrument_source_mappings
                       (instrument_id, source, company_id, security_id)
                       VALUES (?, ?, ?, ?)""",
                    (instrument["id"], PSE_EDGE_SOURCE, company_id, security_id),
                )
                connection.commit()
            latest = connection.execute(
                """SELECT MAX(price_date) AS price_date FROM prices
                   WHERE instrument_id = ? AND source = ?""",
                (instrument["id"], PSE_EDGE_PRICE_SOURCE),
            ).fetchone()["price_date"]
            start_date = (
                date.fromisoformat(latest) + timedelta(days=1)
                if latest else date.fromisoformat(instrument["first_trade"])
            )
            instrument_end = (
                end_date if instrument["id"] in open_ids
                else date.fromisoformat(instrument["last_trade"])
            )
            if start_date > instrument_end:
                continue
            points = client.fetch_history(company_id, security_id, start_date, instrument_end)
            for point in points:
                connection.execute(
                    """INSERT INTO prices
                       (instrument_id, price_date, price, currency, source, fetched_at)
                       VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                       ON CONFLICT(instrument_id, price_date, source)
                       DO UPDATE SET price = excluded.price, currency = excluded.currency,
                                     fetched_at = CURRENT_TIMESTAMP""",
                    (instrument["id"], point.price_date.isoformat(), point.close,
                     point.currency, PSE_EDGE_PRICE_SOURCE),
                )
                written += 1
            connection.execute(
                """UPDATE instruments SET price_source = ?, source_symbol = ? WHERE id = ?""",
                (PSE_EDGE_SOURCE, ticker, instrument["id"]),
            )
            connection.commit()
            updated += 1
        except PseEdgeError as error:
            connection.rollback()
            failures.append(FetchFailure(PSE_EDGE_SOURCE, f"{ticker}: {error}"))
    return PseRefreshResult(
        updated, written, client.requests_used - initial_requests, tuple(failures)
    )
