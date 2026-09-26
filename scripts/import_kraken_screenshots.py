"""Import the 2026-09-26 Kraken screenshots using daily-close estimates.

The screenshots contain asset-side quantities, not execution prices. This import
therefore uses Yahoo's public daily USD close and marks every imported row as an
estimate. Current Kraken balances are reconciled from the supplied screenshots.
Fees, Earn movements, rewards, and Kraken Fee Credits are intentionally omitted.
"""

from __future__ import annotations

import json
import sqlite3
import ssl
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import certifi

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from portfolio.cash import ensure_cash_instruments
from portfolio.db import connect, migrate

DATABASE = ROOT / "instance" / "portfolio.db"
IMPORT_PREFIX = "kraken-screenshot-2026-09-26:"

NAMES = {
    "ADA": "Cardano", "ALGO": "Algorand", "BTC": "Bitcoin", "DOGE": "Dogecoin",
    "DOT": "Polkadot", "ETH": "Ether", "HYPE": "Hyperliquid", "LINK": "Chainlink",
    "LTC": "Litecoin", "MANA": "Decentraland", "NEAR": "NEAR Protocol",
    "OCEAN": "OCEAN Token", "PUMP": "PUMP", "QTUM": "Qtum", "SAND": "Sand",
    "SOL": "Solana", "XLM": "Lumen", "XRP": "XRP",
}
TARGETS = {
    "ADA": 0.0, "ALGO": 0.0, "DOT": 0.0, "OCEAN": 0.0, "XLM": 0.0,
    "ETH": 0.67573, "BTC": 0.01285444, "SOL": 5.95326, "NEAR": 102.17204,
    "DOGE": 3472.72, "XRP": 170.53820, "LINK": 16.64742, "LTC": 2.19727,
    "HYPE": 0.62147, "PUMP": 9532.8, "QTUM": 18.971787, "MANA": 39.83292,
    "SAND": 43.62915,
}
ZERO_RECONCILIATION_DATES = {
    "ADA": "2026-06-05", "ALGO": "2026-06-03", "DOT": "2026-06-02",
    "OCEAN": "2026-08-19", "XLM": "2021-07-11",
}
SCREENSHOT_PRICES = {
    # Derived from Kraken's displayed balance and estimated value so the local
    # current values reconcile to the screenshot despite rounded displayed prices.
    "ETH": 1819.33 / 0.67573, "BTC": 1079.32 / 0.01285444,
    "SOL": 723.08 / 5.95326, "NEAR": 516.54 / 102.17204,
    "DOGE": 338.91 / 3472.72, "XRP": 267.69 / 170.53820,
    "LINK": 231.14 / 16.64742, "LTC": 152.72 / 2.19727,
    "HYPE": 56.93 / 0.62147, "PUMP": 39.17 / 9532.8,
    "QTUM": 19.67 / 18.971787, "MANA": 3.67 / 39.83292,
    "SAND": 1.96 / 43.62915,
}

# date,ticker,signed quantity,kind. Duplicate screenshots and apparent tiny
# fill rows are consolidated below by date/ticker/direction.
ROWS = """
2020-08-06,BTC,0.0248458,deposit
2020-08-11,ETH,1.480412,deposit
2020-08-24,XRP,1066.85628,deposit
2021-02-17,XRP,377.5009,deposit
2021-03-11,XRP,650.759173,deposit
2021-07-11,XLM,3592.1842,deposit
2022-01-19,SOL,3.50648,deposit
2020-09-01,ETH,-1.48,trade
2020-09-16,ETH,0.69444444,trade
2020-09-17,ETH,-0.6930545,trade
2021-01-22,ETH,0.26086956,trade
2021-01-22,ETH,0.25531914,trade
2021-02-03,ETH,-0.12904717,trade
2021-02-03,ETH,-0.09678538,trade
2021-02-08,ETH,0.12642225,trade
2025-12-18,ETH,0.35714286,trade
2026-05-18,ETH,0.1,trade
2026-06-02,ETH,0.20640048,trade
2026-09-23,ETH,0.01837513,trade
2020-12-20,BTC,-0.00638844,trade
2020-12-21,BTC,0.00652173,trade
2020-12-30,BTC,-0.005,trade
2021-01-02,BTC,-0.005,trade
2021-01-08,BTC,-0.00486618,trade
2021-02-09,BTC,0.00652173,trade
2021-05-20,BTC,-0.00830585,trade
2021-05-26,BTC,-0.0051282,trade
2021-06-23,BTC,-0.00317766,trade
2026-06-02,BTC,0.00442576,trade
2026-06-09,BTC,0.00713561,trade
2026-09-10,BTC,0.00129307,trade
2021-02-23,ADA,274.72527472,trade
2021-05-17,ADA,-137.36263736,trade
2021-06-08,ADA,162.33766233,trade
2021-06-21,ADA,200,trade
2021-08-11,ADA,-181.16883134,trade
2025-12-08,ADA,236.92583984,trade
2025-12-14,ADA,250,trade
2026-04-09,ADA,398.58899496,trade
2026-06-05,ADA,-1238.86606933,trade
2021-06-18,ALGO,198.01980198,trade
2026-06-03,ALGO,-201.31896398,trade
2021-04-20,LINK,8.45070422,trade
2021-05-26,LINK,8.19672131,trade
2021-01-07,DOGE,20124.77359629,trade
2021-01-11,DOGE,-20124.7735962,trade
2021-01-18,DOGE,33185.84070796,trade
2021-01-21,DOGE,-33185.8407079,trade
2021-02-01,DOGE,7879.18581746,trade
2021-02-07,DOGE,-1477.34734077,trade
2021-02-08,DOGE,-3631.81221273,trade
2021-02-14,DOGE,4545.45454545,trade
2021-04-14,DOGE,-3657.7404047,trade
2021-04-16,DOGE,-1294.49838187,trade
2021-05-04,DOGE,-600,trade
2021-05-08,DOGE,-352.11267605,trade
2021-05-08,DOGE,384.61538461,trade
2021-05-11,DOGE,425.53191489,trade
2021-05-19,DOGE,800,trade
2021-05-20,DOGE,555.55555555,trade
2024-12-29,DOGE,-3397.99059174,trade
2025-05-31,DOGE,500,trade
2025-12-08,DOGE,713.71321433,trade
2026-06-02,DOGE,2080.1740689,trade
2021-03-14,LTC,1.15473441,trade
2021-03-15,LTC,-1.15473441,trade
2021-03-16,LTC,1.24378109,trade
2021-03-22,LTC,1.30890052,trade
2021-04-06,LTC,-1.27634079,trade
2021-04-11,LTC,-0.63817041,trade
2021-05-20,LTC,1.01265822,trade
2021-09-07,LTC,0.54644808,trade
2020-09-02,XLM,3306.815,trade
2020-09-06,XLM,-3306.815,trade
2020-09-13,XLM,2673,trade
2020-11-24,XLM,-2673,trade
2020-11-26,XLM,1207.36492604,trade
2021-01-05,XLM,-301.84123151,trade
2021-01-07,XLM,-270.27027027,trade
2021-01-11,XLM,-635.25342423,trade
2021-01-15,XLM,1025.64102564,trade
2021-02-01,XLM,-769.23076925,trade
2021-04-15,XLM,404.53074433,trade
2021-07-11,XLM,-3953.12520075,trade
2021-03-24,OCEAN,178.57142857,trade
2021-12-15,OCEAN,130.82155939,trade
2026-08-19,OCEAN,-309.39298796,trade
2026-06-02,NEAR,76.35044856,trade
2026-08-23,NEAR,25.335698,trade
2026-08-23,PUMP,9532.888,trade
2020-09-09,DOT,46.13697516,trade
2020-09-14,DOT,-46.13697516,trade
2020-10-02,DOT,75.82443,trade
2020-11-20,DOT,-75.82443,trade
2020-11-25,DOT,53.53414586,trade
2020-12-29,DOT,-53.39531803,trade
2021-02-15,DOT,11.32075471,trade
2021-02-28,DOT,7.91327055,trade
2021-03-01,DOT,-8.57142857,trade
2021-09-21,DOT,7.4074074,trade
2026-06-02,DOT,-18.72719906,trade
2021-01-11,XRP,-1.70303207,trade
2021-01-15,XRP,1032.70223752,trade
2021-01-31,XRP,-774.52667814,trade
2021-02-07,XRP,591.71597633,trade
2021-02-26,XRP,-1227.39243571,trade
2021-04-05,XRP,-488.06937975,trade
2021-04-06,XRP,-162.68979326,trade
2021-04-26,XRP,263.15789473,trade
2021-05-20,XRP,173.91304347,trade
2021-12-05,XRP,180.37518037,trade
2024-12-05,XRP,-500,trade
2025-01-17,XRP,-117.44611857,trade
2026-02-05,XRP,133.33333334,trade
2026-09-13,XRP,37.20487236,trade
2021-09-07,SOL,1.49700598,trade
2025-01-04,SOL,-1.98174299,trade
2025-01-20,SOL,-1.98174299,trade
2025-12-08,SOL,0.74934433,trade
2026-06-02,SOL,5.16795866,trade
2026-09-03,SOL,0.49207756,trade
2026-09-13,SOL,0.50095181,trade
"""


def fetch_history(ticker: str) -> dict[str, float]:
    start = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp())
    end = int((datetime.now(timezone.utc) + timedelta(days=2)).timestamp())
    query = urlencode({"period1": start, "period2": end, "interval": "1d", "events": "history"})
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}-USD?{query}"
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    for attempt in range(4):
        try:
            context = ssl.create_default_context(cafile=certifi.where())
            with urlopen(request, timeout=15, context=context) as response:
                result = json.load(response)["chart"]["result"][0]
            closes = result["indicators"]["quote"][0]["close"]
            return {
                datetime.fromtimestamp(ts, timezone.utc).date().isoformat(): float(close)
                for ts, close in zip(result["timestamp"], closes) if close is not None
            }
        except Exception:
            if attempt == 3:
                return {}
            time.sleep(2 ** attempt)
    return {}


def closest_price(history: dict[str, float], day: str, fallback: float | None = None) -> float:
    cursor = date.fromisoformat(day)
    for _ in range(8):
        if cursor.isoformat() in history:
            return history[cursor.isoformat()]
        cursor -= timedelta(days=1)
    if fallback is not None:
        return fallback
    raise RuntimeError(f"No daily price available for {day}")


def instrument_id(connection: sqlite3.Connection, ticker: str) -> int:
    row = connection.execute(
        "SELECT id FROM instruments WHERE platform = 'Kraken' AND ticker = ?", (ticker,)
    ).fetchone()
    if row:
        return row["id"]
    return connection.execute(
        """INSERT INTO instruments
           (name,ticker,asset_class,platform,native_currency,sector,notes,price_source,source_symbol,coverage_status)
           VALUES (?,?,'crypto','Kraken','USD',NULL,?,'kraken',?,'covered')""",
        (NAMES[ticker], ticker, "Imported from Kraken screenshots; execution prices estimated from daily USD closes.", f"{ticker}USD"),
    ).lastrowid


def main() -> None:
    DATABASE.parent.mkdir(parents=True, exist_ok=True)
    migrate(DATABASE)
    with connect(DATABASE) as connection:
        ensure_cash_instruments(connection)
        if connection.execute("SELECT 1 FROM transactions WHERE external_id LIKE ? LIMIT 1", (IMPORT_PREFIX + "%",)).fetchone():
            raise SystemExit("Kraken screenshot import is already present; no changes made.")

        parsed = []
        for line in ROWS.strip().splitlines():
            day, ticker, amount, kind = line.split(",")
            parsed.append((day, ticker, float(amount), kind))
        tickers = sorted(set(NAMES) | set(TARGETS))
        histories = {}
        for ticker in tickers:
            print(f"Fetching {ticker} daily closes...")
            histories[ticker] = fetch_history(ticker)

        ids = {ticker: instrument_id(connection, ticker) for ticker in tickers}
        sequence = 0
        for day, ticker, amount, kind in sorted(parsed):
            sequence += 1
            price = closest_price(histories[ticker], day, SCREENSHOT_PRICES.get(ticker))
            if kind == "deposit":
                transaction_type = "transfer"
                net_amount = amount * price
                external = 1
            else:
                transaction_type = "buy" if amount > 0 else "sell"
                net_amount = None
                external = 0
            adjustment_date = ZERO_RECONCILIATION_DATES.get(ticker, today)
            connection.execute(
                """INSERT INTO transactions
                   (instrument_id,type,trade_date,quantity,unit_price,fees,currency,net_amount,
                    external_id,source_type,note,platform,is_external_transfer)
                   VALUES (?,?,?,?,?,0,'USD',?,?,'import',?,'Kraken',?)""",
                (ids[ticker], transaction_type, day, amount if kind == "deposit" else abs(amount),
                 price, net_amount, f"{IMPORT_PREFIX}{sequence}",
                 "Kraken screenshot import; execution price estimated from daily USD close.", external),
            )

        # Reconcile quantities to the current Kraken screenshot. These adjustments
        # make missing rewards/fees/history explicit instead of disguising them as trades.
        from portfolio.positions import positions_as_of
        current = {p["instrument"]["ticker"]: float(p["quantity"]) for p in positions_as_of(connection, include_zero=True)}
        today = date.today().isoformat()
        for ticker, target in TARGETS.items():
            delta = target - current.get(ticker, 0.0)
            if abs(delta) < 1e-10:
                continue
            price = SCREENSHOT_PRICES[ticker]
            sequence += 1
            connection.execute(
                """INSERT INTO transactions
                   (instrument_id,type,trade_date,quantity,unit_price,fees,currency,net_amount,
                    external_id,source_type,note,platform,is_external_transfer)
                   VALUES (?,'transfer',?,?,?,0,'USD',?,?,'import',?,'Kraken',1)""",
                (ids[ticker], adjustment_date, delta, price, delta * price, f"{IMPORT_PREFIX}{sequence}",
                 "Quantity reconciliation to 2026-09-26 Kraken portfolio screenshot; omitted rewards/fees or missing history."),
            )

        usd = connection.execute(
            "SELECT id FROM instruments WHERE platform='Kraken' AND asset_class='cash' AND native_currency='USD'"
        ).fetchone()["id"]
        connection.execute(
            """INSERT INTO transactions
               (instrument_id,type,trade_date,currency,net_amount,external_id,source_type,note,platform,is_external_transfer)
               VALUES (?,'transfer',?,'USD',42.39,?,'import',?,'Kraken',1)""",
            (usd, today, IMPORT_PREFIX + "usd-balance", "Current USD balance from 2026-09-26 Kraken screenshot."),
        )

        for ticker, history in histories.items():
            for day, price in history.items():
                connection.execute(
                    """INSERT OR IGNORE INTO prices
                       (instrument_id,price_date,price,currency,source,fetched_at)
                       VALUES (?,?,?,'USD','Yahoo daily close estimate',CURRENT_TIMESTAMP)""",
                    (ids[ticker], day, price),
                )
        for ticker, price in SCREENSHOT_PRICES.items():
            connection.execute(
                """INSERT OR REPLACE INTO prices
                   (instrument_id,price_date,price,currency,source,fetched_at)
                   VALUES (?,?,?,'USD','Kraken portfolio screenshot',CURRENT_TIMESTAMP)""",
                (ids[ticker], today, price),
            )

        final = {p["instrument"]["ticker"]: float(p["quantity"]) for p in positions_as_of(connection)}
        print("Imported Kraken history. Final non-zero quantities:")
        for ticker in sorted(final):
            if final[ticker]:
                print(f"  {ticker}: {final[ticker]:.10g}")


if __name__ == "__main__":
    main()
