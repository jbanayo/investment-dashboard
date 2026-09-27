# Investment Dashboard

A private, local-first portfolio tracker for investments held across brokers and
exchanges. It keeps transactions, positions, prices, FX rates, dividends, and
notes in a local SQLite database and builds a unified portfolio dashboard from
that ledger.

The app currently supports BDO Securities Philippine equities, Kraken crypto,
and IBKR US equities and ETFs. The instrument and transaction screens can also
be used for other platforms.

## What the app does

- Records buys, sells, dividends, rewards, fees, deposits, withdrawals, and
  transfers in an auditable ledger.
- Derives positions, average cost, cash balances, realised gains, unrealised
  gains, allocation, and portfolio totals from the ledger.
- Switches the dashboard between all platforms or one platform such as Kraken
  or BDO Securities.
- Displays portfolio value and transfer-adjusted return over 1 month, year to
  date, 1 year, or the complete history.
- Groups holdings by platform or asset class.
- Fetches Kraken crypto daily closes from Twelve Data.
- Fetches Philippine-equity daily closes for instruments in the BDO ledger from
  the chart endpoint used by PSE Edge.
- Imports IBKR Activity Statement trades, commissions, dividends, tax,
  transfers, cash, accruals, and statement prices, with Yahoo daily closes for
  the imported US securities.
- Stores manual prices and USD/PHP rates when an automated source is unavailable.
- Tracks dividend income, analyst ratings, research notes, and reconciliation
  records.
- Stores manual and externally AI-assisted research drafts, then shows only
  user-approved monitored theses on the dashboard.
- Exports a complete SQLite backup from Settings.
- Keeps display name, base currency, appearance, database information, backup,
  and reset controls in Settings.

Historical chart gaps are explicitly estimated. The app uses average cost until
the first recorded market price and carries the last known price forward after a
series ends. Every affected chart day is marked **assumed**. The latest dashboard
value still uses the newest recorded market, statement, or manual price, so the
end of the chart matches the displayed portfolio total.

Return calculations use recorded deposits and withdrawals. When an imported
trade has no matching cash-ledger entry, the app infers that trade's funding or
proceeds so buying an asset is not misreported as investment profit. These rows
are marked **inferred** in the chart data table.

## Download

Clone the repository and enter the project directory:

```sh
git clone https://github.com/jbanayo/investment-dashboard.git
cd investment-dashboard
```

Alternatively, download the repository as a ZIP from GitHub, extract it, and
open a terminal in the extracted `investment-dashboard` folder.

## Setup

Python 3.11 or newer is recommended. Create a virtual environment and install
the dependencies:

```sh
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
```

On Windows PowerShell, activate the environment with:

```powershell
.venv\Scripts\Activate.ps1
```

Start the development server:

```sh
python3 app.py
```

Open [http://127.0.0.1:5000](http://127.0.0.1:5000). Database migrations run
automatically when the application starts.

## Configure price data

### Twelve Data for crypto and IBKR

Create a Twelve Data API key and either set it for the current shell:

```sh
export TWELVE_DATA_API_KEY="your-key"
python3 app.py
```

or place only the key in:

```text
instance/twelve_data_api_key
```

The `instance/` directory is ignored by Git. The app enforces local Twelve Data
limits of 8 requests per UTC minute and 800 requests per UTC day. Failed and
timed-out calls also count toward those limits.

Use **Refresh prices** on the Dashboard or Prices page. Crypto and IBKR share
the same Twelve Data request limits. IBKR refresh requests only US equities and
ETFs in the IBKR ledger; open positions update through the current date and
closed positions stop at their sale date.

### PSE Edge for Philippine equities

The same **Refresh prices** action requests only Philippine equities that appear
in the BDO Securities ledger. Open positions refresh through the current date;
closed positions stop at their final transaction because later prices cannot
affect the portfolio.

PSE company and security identifiers are cached locally, and requests are paced
at one per second. A manual price or statement ending price takes precedence
when it shares a date with a fetched close.

PSE Edge does not publish this chart endpoint as a supported API. If its format
changes, the refresh reports the affected ticker and retains prices already
stored locally.

For a delisted or unchanged asset, edit the instrument and enable **Carry the
last known price forward in charts**. The chart identifies the result as an
assumed value rather than presenting it as a newly fetched quote.

## Import AI-assisted research

Version 1.1 keeps research local and user-led. You can ask Codex or another AI
agent to research an instrument, then paste its structured JSON result through
**Research → Import AI research**. The app stores the result and its source
links locally as a draft for review.

The app does not make AI API calls, so this workflow has no API configuration or
usage cost. Every imported result starts as a draft and cannot reach dashboard
monitoring until you approve it.

## Local data and backups

The default database is:

```text
instance/portfolio.db
```

Transactions and fetched prices remain on the local computer and are excluded
from Git. To use another database, set `PORTFOLIO_DATABASE`:

```sh
PORTFOLIO_DATABASE=/path/to/portfolio.db python3 app.py
```

Use **Settings → Export database** to download a point-in-time SQLite backup.
Store that backup somewhere separate from the project directory. **Reset local
data** clears the portfolio ledger and market data while retaining the schema
and application preferences.

For a clean test database:

```sh
PORTFOLIO_DATABASE=/private/tmp/portfolio-test.db python3 app.py
```

## Tests

Run the complete test suite from the project root:

```sh
python3 -m unittest discover -s tests -v
```

## Project documents

- [Product requirements](docs/investment-tracker-prd.md)
- [Version 1.1.0 AI research PRD](docs/v1.1.0-ai-research-prd.md)
- [Version 1.1.0 research prototype](docs/v1.1.0-research-prototype.html)
- [Version 1.1.0 dashboard with research prototype](docs/v1.1.0-dashboard-research-prototype.html)
- [Dashboard prototype](docs/dashboard-prototype.html)
- [Style guide](docs/style-guide.md)
- [Reconciliation design](docs/reconciliation.md)
- Epic plans: [1](docs/phase-1-epic.md), [2](docs/phase-2-epic.md),
  [3](docs/phase-3-epic.md), [4](docs/phase-4-epic.md),
  [5](docs/phase-5-epic.md), and [6](docs/phase-6-epic.md)

## Developer

[jbanayo](https://github.com/jbanayo)
