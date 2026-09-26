"""Import an IBKR Activity Statement CSV and reconcile its ending NAV.

The statement deposit is recorded as a matched Kraken-to-IBKR transfer, so it
does not count as new portfolio capital. Trade cash legs, paid dividends,
withholding tax, ending cash, and unpaid dividend accruals are reconciled to the
statement totals. Yahoo daily closes are optional chart history; the statement
close remains the ending valuation source.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import ssl
import sqlite3
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import uuid4

try:
    import certifi
except ModuleNotFoundError:
    certifi = None

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from portfolio.cash import get_or_create_cash_instrument
from portfolio.db import connect, migrate
from portfolio.positions import portfolio_snapshot, positions_as_of

DATABASE = ROOT / "instance" / "portfolio.db"
PLATFORM = "IBKR"
PREFIX = "ibkr-activity-2026-09-25:"
STATEMENT_DATE = "2026-09-25"
DESCRIPTION_TICKER = re.compile(r"^([A-Z.]+)\(")


def decimal(value: str | int | float | None) -> Decimal:
    return Decimal(str(value or "0").replace(",", ""))


def read_sections(csv_path: Path) -> dict[str, list[dict[str, str]]]:
    sections: dict[str, list[dict[str, str]]] = defaultdict(list)
    headers: dict[str, list[str]] = {}
    with csv_path.open(encoding="utf-8-sig", newline="") as source:
        for row in csv.reader(source):
            if len(row) < 2:
                continue
            section, kind, *values = row
            if kind == "Header":
                headers[section] = values
            elif kind == "Data" and section in headers:
                names = headers[section]
                sections[section].append({
                    name: values[index] if index < len(values) else ""
                    for index, name in enumerate(names)
                })
    return sections


def statement_value(sections, section: str, field: str) -> Decimal:
    for row in sections[section]:
        if row.get("Field Name") == field:
            return decimal(row.get("Field Value"))
    raise RuntimeError(f"{section} is missing {field}.")


def section_metric(sections, section: str, key: str, value_column: str) -> Decimal:
    for row in sections[section]:
        if next(iter(row.values()), None) == key:
            return decimal(row.get(value_column))
    raise RuntimeError(f"{section} is missing {key}.")


def parsed_statement(csv_path: Path) -> dict:
    sections = read_sections(csv_path)
    period = next(
        row["Field Value"] for row in sections["Statement"]
        if row.get("Field Name") == "Period"
    )
    statement_date = datetime.strptime(period.rsplit(" - ", 1)[1], "%B %d, %Y").date().isoformat()
    if statement_date != STATEMENT_DATE:
        raise RuntimeError(f"Expected statement ending {STATEMENT_DATE}; found {statement_date}.")

    security_info = {
        row["Symbol"]: row for row in sections["Financial Instrument Information"]
        if row.get("Symbol")
    }
    trades = []
    for index, row in enumerate(sections["Trades"], 1):
        if row.get("DataDiscriminator") != "Order" or not row.get("Symbol"):
            continue
        signed_quantity = decimal(row["Quantity"])
        trades.append({
            "index": index,
            "ticker": row["Symbol"],
            "date": row["Date/Time"].split(",", 1)[0],
            "type": "buy" if signed_quantity > 0 else "sell",
            "quantity": abs(signed_quantity),
            "price": decimal(row["T. Price"]),
            "fees": abs(decimal(row["Comm/Fee"])),
            "proceeds": decimal(row["Proceeds"]),
            "realised": decimal(row["Realized P/L"]),
            "currency": row["Currency"],
        })

    tax_by_key = {}
    for row in sections["Withholding Tax"]:
        match = DESCRIPTION_TICKER.match(row.get("Description", ""))
        if match:
            tax_by_key[(match.group(1), row["Date"])] = abs(decimal(row["Amount"]))
    dividends = []
    for index, row in enumerate(sections["Dividends"], 1):
        match = DESCRIPTION_TICKER.match(row.get("Description", ""))
        if not match:
            continue
        ticker = match.group(1)
        gross = decimal(row["Amount"])
        tax = tax_by_key.get((ticker, row["Date"]), Decimal("0"))
        dividends.append({
            "index": index, "ticker": ticker, "date": row["Date"],
            "gross": gross, "tax": tax, "currency": row["Currency"],
            "description": row["Description"],
        })

    deposits = [
        row for row in sections["Deposits & Withdrawals"]
        if row.get("Currency") == "USD" and decimal(row.get("Amount")) > 0
    ]
    if len(deposits) != 1:
        raise RuntimeError(f"Expected one USD deposit; found {len(deposits)}.")

    open_positions = {
        row["Symbol"]: {
            "quantity": decimal(row["Quantity"]),
            "close": decimal(row["Close Price"]),
            "value": decimal(row["Value"]),
        }
        for row in sections["Open Positions"]
        if row.get("DataDiscriminator") == "Summary" and row.get("Symbol")
    }
    accruals = [
        row for row in sections["Change in Dividend Accruals"]
        if row.get("Asset Category") == "Stocks" and row.get("Code") == "Po"
        and row.get("Pay Date", "") > statement_date
    ]
    ending_accrual = sum((decimal(row["Net Amount"]) for row in accruals), Decimal("0"))

    return {
        "statement_date": statement_date,
        "security_info": security_info,
        "trades": trades,
        "dividends": dividends,
        "deposit": {
            "date": deposits[0]["Settle Date"],
            "amount": decimal(deposits[0]["Amount"]),
            "currency": deposits[0]["Currency"],
        },
        "open_positions": open_positions,
        "ending_cash": section_metric(sections, "Net Asset Value", "Cash ", "Current Total"),
        "ending_stock": section_metric(sections, "Net Asset Value", "Stock", "Current Total"),
        "ending_accrual": ending_accrual,
        "ending_nav": statement_value(sections, "Change in NAV", "Ending Value"),
    }


def fetch_chart(symbol: str, start_date: str) -> dict[str, float]:
    start = int(datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc).timestamp())
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
                datetime.fromtimestamp(timestamp, timezone.utc).date().isoformat(): float(close)
                for timestamp, close in zip(result["timestamp"], closes)
                if close is not None
            }
        except Exception:
            if attempt == 2:
                return {}
            time.sleep(2 ** attempt)
    return {}


def instrument_id(connection: sqlite3.Connection, ticker: str, info: dict) -> int:
    existing = connection.execute(
        "SELECT id FROM instruments WHERE platform=? AND ticker=?", (PLATFORM, ticker)
    ).fetchone()
    if existing:
        return existing["id"]
    asset_class = "etf" if info.get("Type") == "ETF" else "us_equity"
    return connection.execute(
        """INSERT INTO instruments
           (name,ticker,asset_class,platform,native_currency,notes,price_source,source_symbol,coverage_status)
           VALUES (?,?,?,?,'USD',?,'twelve_data',?,?)""",
        (
            info.get("Description") or ticker, ticker, asset_class, PLATFORM,
            f"Imported from IBKR statement ending {STATEMENT_DATE}. Conid {info.get('Conid', '')}.",
            ticker,
            "not_applicable_index_etf" if asset_class == "etf" else "no_coverage",
        ),
    ).lastrowid


def import_statement(
    csv_path: Path, database: Path = DATABASE,
    histories: dict[str, dict[str, float]] | None = None,
) -> dict:
    data = parsed_statement(csv_path)
    database.parent.mkdir(parents=True, exist_ok=True)
    migrate(database)
    histories = histories or {}

    with connect(database) as connection:
        if connection.execute(
            "SELECT 1 FROM transactions WHERE external_id LIKE ? LIMIT 1", (PREFIX + "%",)
        ).fetchone():
            raise RuntimeError("IBKR statement import is already present; no changes made.")

        tickers = sorted(data["security_info"])
        ids = {
            ticker: instrument_id(connection, ticker, data["security_info"][ticker])
            for ticker in tickers
        }
        ibkr_cash = get_or_create_cash_instrument(connection, PLATFORM, "USD")
        kraken_cash = get_or_create_cash_instrument(connection, "Kraken", "USD")

        transfer_group = str(uuid4())
        amount = data["deposit"]["amount"]
        day = data["deposit"]["date"]
        connection.execute(
            """INSERT INTO transactions
               (instrument_id,type,trade_date,currency,net_amount,external_id,source_type,note,
                platform,is_external_transfer,transfer_group_id)
               VALUES (?,'transfer',?,'USD',?,?, 'import',?,'IBKR',0,?)""",
            (ibkr_cash, day, float(amount), PREFIX + "transfer-in",
             "IBKR electronic deposit matched to Kraken withdrawal.", transfer_group),
        )
        connection.execute(
            """INSERT INTO transactions
               (instrument_id,type,trade_date,currency,net_amount,external_id,source_type,note,
                platform,is_external_transfer,transfer_group_id)
               VALUES (?,'transfer',?,'USD',?,?, 'import',?,'Kraken',0,?)""",
            (kraken_cash, day, float(-amount), PREFIX + "transfer-out",
             "Matched transfer to IBKR; funded from Kraken proceeds.", transfer_group),
        )
        # The earlier Kraken screenshot import stored the ending $42.39 cash as a
        # standalone point-in-time balance. Offset the newly recognized historic
        # withdrawal on the screenshot date so that current Kraken cash stays $42.39.
        kraken_snapshot = connection.execute(
            """SELECT trade_date FROM transactions
               WHERE platform='Kraken' AND external_id='kraken-screenshot-2026-09-26:usd-balance'"""
        ).fetchone()
        if kraken_snapshot:
            connection.execute(
                """INSERT INTO transactions
                   (instrument_id,type,trade_date,currency,net_amount,external_id,source_type,note,
                    platform,is_external_transfer)
                   VALUES (?,'transfer',?,'USD',?,?, 'import',?,'Kraken',0)""",
                (kraken_cash, kraken_snapshot["trade_date"], float(amount),
                 PREFIX + "kraken-cash-reconciliation",
                 "Cash reconciliation after recognizing the June Kraken-to-IBKR transfer."),
            )

        for trade in data["trades"]:
            cursor = connection.execute(
                """INSERT INTO transactions
                   (instrument_id,type,trade_date,quantity,unit_price,fees,currency,realised_gain_loss,
                    external_id,source_type,note,platform)
                   VALUES (?,?,?,?,?,?,?,?,?,'import',?,'IBKR')""",
                (
                    ids[trade["ticker"]], trade["type"], trade["date"], float(trade["quantity"]),
                    float(trade["price"]), float(trade["fees"]), trade["currency"],
                    float(trade["realised"]), PREFIX + f"trade-{trade['index']}",
                    "IBKR Activity Statement trade execution.",
                ),
            )
            cash_change = trade["proceeds"] - trade["fees"]
            connection.execute(
                """INSERT INTO transactions
                   (instrument_id,type,trade_date,currency,net_amount,parent_transaction_id,
                    external_id,source_type,note,platform)
                   VALUES (?,?,?,?,?,?,?,'import','Generated from IBKR proceeds and commission.','IBKR')""",
                (
                    ibkr_cash, trade["type"], trade["date"], trade["currency"],
                    float(cash_change), cursor.lastrowid,
                    PREFIX + f"trade-{trade['index']}-cash",
                ),
            )
            connection.execute(
                """INSERT OR IGNORE INTO prices
                   (instrument_id,price_date,price,currency,source,fetched_at)
                   VALUES (?,?,?,'USD','IBKR trade execution',CURRENT_TIMESTAMP)""",
                (ids[trade["ticker"]], trade["date"], float(trade["price"])),
            )

        for dividend in data["dividends"]:
            net = dividend["gross"] - dividend["tax"]
            cursor = connection.execute(
                """INSERT INTO transactions
                   (instrument_id,type,trade_date,currency,gross_amount,tax_withheld,net_amount,
                    external_id,source_type,note,platform)
                   VALUES (?,'dividend',?,?,?,?,?,?,'import',?,'IBKR')""",
                (
                    ids[dividend["ticker"]], dividend["date"], dividend["currency"],
                    float(dividend["gross"]), float(dividend["tax"]), float(net),
                    PREFIX + f"dividend-{dividend['index']}", dividend["description"],
                ),
            )
            connection.execute(
                """INSERT INTO transactions
                   (instrument_id,type,trade_date,currency,net_amount,parent_transaction_id,
                    external_id,source_type,note,platform)
                   VALUES (?,'dividend',?,'USD',?,?,?,'import','Generated paid-dividend cash leg.','IBKR')""",
                (ibkr_cash, dividend["date"], float(net), cursor.lastrowid,
                 PREFIX + f"dividend-{dividend['index']}-cash"),
            )

        accrual_id = connection.execute(
            """INSERT INTO instruments
               (name,ticker,asset_class,platform,native_currency,notes,price_source,coverage_status)
               VALUES ('Dividend accruals','DIV-ACCRUAL','other','IBKR','USD',?,
                       'statement','no_coverage')""",
            (f"Net dividends declared but unpaid at {data['statement_date']}.",),
        ).lastrowid
        connection.execute(
            """INSERT INTO transactions
               (instrument_id,type,trade_date,quantity,unit_price,fees,currency,net_amount,
                external_id,source_type,note,platform,is_external_transfer)
               VALUES (?,'transfer',?,?,1,0,'USD',0,?,'import',?,'IBKR',0)""",
            (accrual_id, data["statement_date"], float(data["ending_accrual"]),
             PREFIX + "dividend-accrual",
             "Pending MDT and NKE dividends; included in IBKR ending NAV."),
        )
        connection.execute(
            """INSERT INTO prices
               (instrument_id,price_date,price,currency,source,fetched_at)
               VALUES (?,?,1,'USD','IBKR statement accrual',CURRENT_TIMESTAMP)""",
            (accrual_id, data["statement_date"]),
        )

        for ticker, history in histories.items():
            if ticker not in ids:
                continue
            for price_date, price in history.items():
                if price_date <= data["statement_date"]:
                    connection.execute(
                        """INSERT OR IGNORE INTO prices
                           (instrument_id,price_date,price,currency,source,fetched_at)
                           VALUES (?,?,?,'USD','Yahoo US daily close',CURRENT_TIMESTAMP)""",
                        (ids[ticker], price_date, price),
                    )
        for ticker, position in data["open_positions"].items():
            connection.execute(
                """INSERT INTO prices
                   (instrument_id,price_date,price,currency,source,fetched_at)
                   VALUES (?,?,?,'USD','IBKR statement ending position',CURRENT_TIMESTAMP)""",
                (ids[ticker], data["statement_date"], float(position["close"])),
            )

        actual_positions = {
            item["instrument"]["ticker"]: item["quantity"]
            for item in positions_as_of(connection, data["statement_date"], platform=PLATFORM)
            if item["instrument"]["ticker"] != "USD"
        }
        expected_positions = {
            ticker: values["quantity"] for ticker, values in data["open_positions"].items()
        }
        expected_positions["DIV-ACCRUAL"] = data["ending_accrual"]
        if actual_positions != expected_positions:
            raise RuntimeError(
                f"IBKR ending quantity mismatch: {actual_positions!r} != {expected_positions!r}"
            )

        cash = connection.execute(
            "SELECT COALESCE(SUM(net_amount),0) FROM transactions WHERE instrument_id=? AND trade_date<=?",
            (ibkr_cash, data["statement_date"]),
        ).fetchone()[0]
        if abs(decimal(cash) - data["ending_cash"]) > Decimal("0.000001"):
            raise RuntimeError(f"IBKR cash mismatch: {cash} != {data['ending_cash']}")

        snapshot = portfolio_snapshot(connection, "USD", data["statement_date"], platform=PLATFORM)
        if abs(snapshot["total"] - data["ending_nav"]) > Decimal("0.01"):
            raise RuntimeError(
                f"IBKR NAV mismatch: {snapshot['total']} != {data['ending_nav']}"
            )
        return {
            "trades": len(data["trades"]), "dividends": len(data["dividends"]),
            "positions": len(data["open_positions"]), "cash": cash,
            "nav": snapshot["total"], "statement_date": data["statement_date"],
        }


def main(csv_path: Path, database: Path) -> None:
    data = parsed_statement(csv_path)
    first_trade: dict[str, str] = {}
    for trade in data["trades"]:
        first_trade[trade["ticker"]] = min(first_trade.get(trade["ticker"], trade["date"]), trade["date"])
    histories = {}
    for ticker in sorted(data["security_info"]):
        print(f"Fetching {ticker} daily closes...")
        histories[ticker] = fetch_chart(ticker, first_trade.get(ticker, "2026-01-01"))
    result = import_statement(csv_path, database, histories)
    print(
        f"Imported {result['trades']} trades, {result['dividends']} paid dividends, and "
        f"{result['positions']} open positions."
    )
    print(
        f"IBKR reconciles to USD {result['nav']:,.2f}, including USD {result['cash']:,.2f} "
        f"cash, on {result['statement_date']}."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("csv", type=Path)
    parser.add_argument("--database", type=Path, default=DATABASE)
    args = parser.parse_args()
    main(args.csv, args.database)
