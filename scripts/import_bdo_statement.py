"""Import the BDO Securities statement ending 2026-06-17.

Trade instructions are imported once; later OR/CV settlement lines are ignored as
duplicates. Dividend "Representing" rows are imported without their matching
"Payment" row. Ending quantities and statement-date prices are reconciled to the
page-11 Ending Security Position table.
"""

from __future__ import annotations

import argparse
import json
import re
import ssl
import sqlite3
import sys
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from pypdf import PdfReader

try:
    import certifi
except ModuleNotFoundError:
    certifi = None

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from portfolio.cash import ensure_cash_instruments
from portfolio.db import connect, migrate
from portfolio.positions import positions_as_of, portfolio_snapshot

DATABASE = ROOT / "instance" / "portfolio.db"
PREFIX = "bdo-soa-2026-06-17:"
STATEMENT_DATE = "2026-06-17"

ENDING = {
    "AC": (160, 399.60), "ACEN": (216, 3.16), "ALI": (1700, 13.00),
    "BPI": (800, 98.90), "CNVRG": (600, 9.99), "MM": (800, 0.435),
    "MPI": (24, 5.18), "UBP": (635, 25.55),
}
NAMES = {
    "AC": "Ayala Corporation", "ACEN": "ACEN Corporation", "ALI": "Ayala Land",
    "AXLM": "Axelum Resources", "BDO": "BDO Unibank", "BPI": "Bank of the Philippine Islands",
    "CHP": "Cemex Holdings Philippines", "CNVRG": "Converge ICT Solutions",
    "DITO": "DITO CME Holdings", "FB": "San Miguel Food and Beverage",
    "ICT": "International Container Terminal Services", "ISM": "ISM Communications",
    "JFC": "Jollibee Foods", "MAC": "MacroAsia", "MBT": "Metropolitan Bank and Trust",
    "MEG": "Megaworld", "MM": "MerryMart Consumer", "MPI": "Metro Pacific Investments",
    "MWIDE": "Megawide Construction", "PGOLD": "Puregold Price Club",
    "PHR": "PH Resorts Group", "PXP": "PXP Energy", "RLC": "Robinsons Land",
    "RRHI": "Robinsons Retail Holdings", "SECB": "Security Bank", "SMC": "San Miguel Corporation",
    "UBP": "Union Bank of the Philippines",
}

INITIAL_TRADES = (
    ("2018-10-29", "MBT", 10, 65.0, 672.47),
    ("2018-10-29", "BPI", 10, 81.95, 841.98),
    ("2018-11-05", "RRHI", 10, 75.0, 772.48),
    ("2018-11-05", "BPI", 50, 82.25, 4135.31),
    ("2018-11-06", "MBT", 30, 66.2, 2008.60),
    ("2018-12-12", "SMC", 10, 155.0, 1572.56),
)

# Quantity-only corporate actions that are necessary to reproduce the statement.
CORPORATE_ACTIONS = (
    ("2019-10-04", "AXLM", 1000, 5.0, "IPO allotment"),
    ("2020-03-03", "CHP", 3000, 1.54, "Stock rights"),
    ("2020-04-01", "ISM", -400, 0.0, "Ticker conversion to DITO"),
    ("2020-04-01", "DITO", 400, 6.37, "Ticker conversion from ISM"),
    ("2022-12-29", "BDO", 100, 0.0, "Stock dividend"),
    ("2023-09-08", "ACEN", 216, 0.0, "Property dividend received"),
    ("2024-01-04", "UBP", 135, 0.0, "Stock dividend"),
    ("2025-03-06", "MPI", -11976, 0.0, "Reverse split 12,000 shares to 24"),
)

TRADE_RE = re.compile(
    r"^(\d{2}/\d{2}/\d{4})(BI|SI)#(\S+?)(BUY|SELL) INSTRUCTION\(([^)]+)\)\s+"
    r"([\d,]+)\s+(\d+\.\d{4})\s*([\d,]+\.\d{2})\s+([\d,]+\.\d{2})",
    re.M,
)
DIVIDEND_RE = re.compile(
    r"^(\d{2}/\d{2}/\d{4})CA#([A-Z]+)CD\S*Representing Cash Dividend on\s+"
    r"([\d,]+)\s+shares of .*? at PHP([.\d]+)",
    re.M,
)
DIVIDEND_ALIASES = {"BDOSD": "BDO", "ACENPD": "ACEN"}


def iso(value: str) -> str:
    return datetime.strptime(value, "%m/%d/%Y").date().isoformat()


def number(value: str) -> float:
    return float(value.replace(",", ""))


def fetch_chart(symbol: str, period1: str = "2018-01-01") -> dict[str, float]:
    start = int(datetime.fromisoformat(period1).replace(tzinfo=timezone.utc).timestamp())
    end = int((datetime.now(timezone.utc) + timedelta(days=2)).timestamp())
    query = urlencode({"period1": start, "period2": end, "interval": "1d", "events": "history"})
    request = Request(
        f"https://query2.finance.yahoo.com/v8/finance/chart/{symbol}?{query}",
        headers={"User-Agent": "Mozilla/5.0"},
    )
    context = ssl.create_default_context(cafile=certifi.where() if certifi else None)
    for attempt in range(3):
        try:
            with urlopen(request, timeout=15, context=context) as response:
                result = json.load(response)["chart"]["result"][0]
            closes = result["indicators"]["quote"][0]["close"]
            return {
                datetime.fromtimestamp(ts, timezone.utc).date().isoformat(): float(close)
                for ts, close in zip(result["timestamp"], closes) if close is not None
            }
        except Exception:
            if attempt == 2:
                return {}
            time.sleep(2 ** attempt)
    return {}


def instrument_id(connection: sqlite3.Connection, ticker: str) -> int:
    row = connection.execute(
        "SELECT id FROM instruments WHERE platform='BDO Securities' AND ticker=?", (ticker,)
    ).fetchone()
    if row:
        return row["id"]
    return connection.execute(
        """INSERT INTO instruments
           (name,ticker,asset_class,platform,native_currency,notes,price_source,source_symbol,coverage_status)
           VALUES (?,?,'ph_equity','BDO Securities','PHP',?,'manual',?,'no_coverage')""",
        (NAMES.get(ticker, ticker), ticker, "Imported from BDO Securities statement ending 2026-06-17.", ticker),
    ).lastrowid


def parse_statement(pdf_path: Path):
    text = "\n".join(page.extract_text() or "" for page in PdfReader(pdf_path).pages)
    trades = []
    for match in TRADE_RE.finditer(text):
        posted, _code, reference, action, ticker, quantity, price, debit, credit = match.groups()
        quantity, price, debit, credit = map(number, (quantity, price, debit, credit))
        gross = quantity * price
        fees = max(0.0, debit - gross) if action == "BUY" else max(0.0, gross - credit)
        trades.append({
            "date": iso(posted), "reference": reference, "type": action.lower(),
            "ticker": ticker, "quantity": quantity, "price": price, "fees": fees,
        })
    dividends = []
    for match in DIVIDEND_RE.finditer(text):
        posted, reference_ticker, shares, per_share = match.groups()
        ticker = DIVIDEND_ALIASES.get(reference_ticker, reference_ticker)
        gross = number(shares) * number(per_share)
        tax_rate = 0.0 if reference_ticker == "ACENPD" else 0.10
        dividends.append({
            "date": iso(posted), "ticker": ticker, "gross": gross,
            "tax": gross * tax_rate, "reference": match.group(0).split("Representing", 1)[0],
        })
    if len(trades) != 120 or len(dividends) != 73:
        raise RuntimeError(f"Unexpected parse result: {len(trades)} trades, {len(dividends)} dividends")
    return trades, dividends


def main(pdf_path: Path) -> None:
    trades, dividends = parse_statement(pdf_path)
    DATABASE.parent.mkdir(parents=True, exist_ok=True)
    migrate(DATABASE)
    all_tickers = sorted(
        {x["ticker"] for x in trades} | {x["ticker"] for x in dividends}
        | {x[1] for x in CORPORATE_ACTIONS} | set(ENDING)
    )
    # Yahoo currently returns 404 for PSE symbols. Trade-date executions and the
    # statement's ending prices remain authoritative; instruments are marked no coverage.
    histories = {ticker: {} for ticker in all_tickers}
    print("Fetching USD/PHP daily FX...")
    fx_history = fetch_chart("PHP=X")

    with connect(DATABASE) as connection:
        ensure_cash_instruments(connection)
        if connection.execute(
            "SELECT 1 FROM transactions WHERE external_id LIKE ? LIMIT 1", (PREFIX + "%",)
        ).fetchone():
            raise SystemExit("BDO statement import is already present; no changes made.")
        ids = {ticker: instrument_id(connection, ticker) for ticker in all_tickers}

        for index, (day, ticker, quantity, price, total) in enumerate(INITIAL_TRADES, 1):
            connection.execute(
                """INSERT INTO transactions
                   (instrument_id,type,trade_date,quantity,unit_price,fees,currency,external_id,
                    source_type,note,platform)
                   VALUES (?,'buy',?,?,?,?,?,?,'import',?,'BDO Securities')""",
                (ids[ticker], day, quantity, price, total - quantity * price, "PHP",
                 PREFIX + f"initial-{index}", "Initial purchase reconstructed from settlement description."),
            )

        for row in trades:
            connection.execute(
                """INSERT INTO transactions
                   (instrument_id,type,trade_date,quantity,unit_price,fees,currency,external_id,
                    source_type,note,platform)
                   VALUES (?,?,?,?,?,?,'PHP',?,'import',?,'BDO Securities')""",
                (ids[row["ticker"]], row["type"], row["date"], row["quantity"], row["price"],
                 row["fees"], PREFIX + row["reference"],
                "Imported from BDO trade instruction; settlement duplicate omitted."),
            )
            connection.execute(
                """INSERT OR IGNORE INTO prices
                   (instrument_id,price_date,price,currency,source,fetched_at)
                   VALUES (?,?,?,'PHP','BDO trade execution',CURRENT_TIMESTAMP)""",
                (ids[row["ticker"]], row["date"], row["price"]),
            )

        for index, (day, ticker, quantity, price, description) in enumerate(CORPORATE_ACTIONS, 1):
            connection.execute(
                """INSERT INTO transactions
                   (instrument_id,type,trade_date,quantity,unit_price,fees,currency,net_amount,
                    external_id,source_type,note,platform,is_external_transfer)
                   VALUES (?,'transfer',?,?,?,0,'PHP',0,?,'import',?,'BDO Securities',0)""",
                (ids[ticker], day, quantity, price, PREFIX + f"corporate-{index}", description),
            )

        for index, row in enumerate(dividends, 1):
            connection.execute(
                """INSERT INTO transactions
                   (instrument_id,type,trade_date,currency,gross_amount,tax_withheld,net_amount,
                    external_id,source_type,note,platform)
                   VALUES (?,'dividend',?,'PHP',?,?,?,?,'import',?,'BDO Securities')""",
                (ids[row["ticker"]], row["date"], row["gross"], row["tax"],
                 row["gross"] - row["tax"], PREFIX + f"dividend-{index}",
                 "BDO dividend; matching Payment row omitted as a duplicate. Cash payout not retained in broker balance."),
            )

        current = {
            item["instrument"]["ticker"]: float(item["quantity"])
            for item in positions_as_of(connection, STATEMENT_DATE, include_zero=True)
            if item["instrument"]["platform"] == "BDO Securities"
        }
        for ticker in all_tickers:
            target = float(ENDING.get(ticker, (0, 0))[0])
            delta = target - current.get(ticker, 0.0)
            if abs(delta) < 1e-9:
                continue
            price = ENDING.get(ticker, (0, 0))[1]
            connection.execute(
                """INSERT INTO transactions
                   (instrument_id,type,trade_date,quantity,unit_price,fees,currency,net_amount,
                    external_id,source_type,note,platform,is_external_transfer)
                   VALUES (?,'transfer',?,?,?,0,'PHP',0,?,'import',?,'BDO Securities',0)""",
                (ids[ticker], STATEMENT_DATE, delta, price, PREFIX + f"reconcile-{ticker}",
                 "Quantity reconciliation to page-11 Ending Security Position."),
            )

        for ticker, history in histories.items():
            for day, price in history.items():
                connection.execute(
                    """INSERT OR IGNORE INTO prices
                       (instrument_id,price_date,price,currency,source,fetched_at)
                       VALUES (?,?,?,'PHP','Yahoo PSE daily close',CURRENT_TIMESTAMP)""",
                    (ids[ticker], day, price),
                )
        for ticker, (_quantity, price) in ENDING.items():
            connection.execute(
                """INSERT OR REPLACE INTO prices
                   (instrument_id,price_date,price,currency,source,fetched_at)
                   VALUES (?,?,?,'PHP','BDO statement ending position',CURRENT_TIMESTAMP)""",
                (ids[ticker], STATEMENT_DATE, price),
            )
        for day, rate in fx_history.items():
            connection.execute(
                """INSERT OR IGNORE INTO fx_rates
                   (base_currency,quote_currency,rate_date,rate,source,fetched_at)
                   VALUES ('USD','PHP',?,?, 'Yahoo USD/PHP daily close',CURRENT_TIMESTAMP)""",
                (day, rate),
            )

        final = {
            item["instrument"]["ticker"]: float(item["quantity"])
            for item in positions_as_of(connection, STATEMENT_DATE)
            if item["instrument"]["platform"] == "BDO Securities"
        }
        expected = {ticker: float(values[0]) for ticker, values in ENDING.items()}
        if final != expected:
            raise RuntimeError(f"Ending quantity mismatch: {final!r} != {expected!r}")
        snapshot = portfolio_snapshot(connection, "PHP", STATEMENT_DATE)
        bdo_value = sum(
            item["market_value_base"] for item in snapshot["positions"]
            if item["instrument"]["platform"] == "BDO Securities"
        )
        expected_value = sum(Decimal(str(quantity)) * Decimal(str(price)) for quantity, price in ENDING.values())
        if bdo_value != expected_value:
            raise RuntimeError(f"Ending value mismatch: {bdo_value} != {expected_value}")
        print(f"Imported {len(trades)} trades and {len(dividends)} dividends.")
        print(f"Ending positions reconcile exactly to PHP {bdo_value:,.2f} on {STATEMENT_DATE}.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", type=Path)
    args = parser.parse_args()
    main(args.pdf)
