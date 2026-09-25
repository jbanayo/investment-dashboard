"""Application factory for the local portfolio dashboard."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from .db import migrate
from .db import connect
from .cash import ensure_cash_instruments

if TYPE_CHECKING:
    from flask import Flask


def create_app(test_config: dict | None = None) -> "Flask":
    from flask import Flask

    app = Flask(__name__, instance_relative_config=True)
    default_database = Path(app.instance_path) / "portfolio.db"
    app.config.from_mapping(
        DATABASE=os.environ.get("PORTFOLIO_DATABASE", str(default_database)),
        BASE_CURRENCY=os.environ.get("PORTFOLIO_BASE_CURRENCY", "PHP").upper(),
        SECRET_KEY=os.environ.get("PORTFOLIO_SECRET_KEY", "local-development-only"),
    )

    if test_config:
        app.config.update(test_config)

    database_path = Path(app.config["DATABASE"])
    database_path.parent.mkdir(parents=True, exist_ok=True)
    migrate(database_path)
    with connect(database_path) as connection:
        ensure_cash_instruments(connection)

    def database_connection():
        return connect(database_path)

    from flask import flash, redirect, render_template, request, url_for
    from .instruments import (
        ASSET_CLASSES,
        KNOWN_PLATFORMS,
        PRICE_SOURCES,
        COVERAGE_STATUSES,
        InstrumentError,
        create_instrument,
        delete_instrument,
        list_instruments,
        update_instrument,
    )
    from .transactions import (
        TransactionError,
        dividend_income,
        list_transactions,
        record_buy,
        record_dividend,
        record_reward,
        record_sell,
    )
    from .ledger import record_fee, record_transfer
    from .prices import record_bulk_prices, record_manual_fx_rate, record_manual_price
    from .positions import portfolio_snapshot, position_transactions, positions_as_of
    from .positions import daily_valuations, transfer_adjusted_returns
    from .chart import chart_geometry
    from .settings import get_setting, set_setting
    from .corrections import delete_transaction, update_transaction
    from .reconciliation import record_reconciliation
    from .dashboard import (
        RANGE_NAMES,
        dividend_income_base,
        fx_summary,
        holdings_groups,
        last_price_refresh,
        recent_notes,
        recent_transactions,
        unrealised_totals,
    )
    from .formatting import FILTERS

    app.jinja_env.filters.update(FILTERS)

    @app.get("/")
    def index():
        return redirect(url_for("dashboard"))

    @app.get("/dashboard")
    def dashboard():
        base_currency = app.config.get("BASE_CURRENCY", "PHP")
        with database_connection() as connection:
            snapshot = portfolio_snapshot(connection, base_currency)
            grouping = get_setting(connection, "dashboard_grouping", "platform")
            chart_mode = get_setting(connection, "chart_mode", "value")
            chart_range = get_setting(connection, "chart_range", "1Y")
            first_trade = connection.execute("SELECT MIN(trade_date) FROM transactions").fetchone()[0]
        from datetime import date, timedelta
        today = date.today()
        start = {"1M": today - timedelta(days=30), "YTD": date(today.year, 1, 1), "1Y": today - timedelta(days=365), "All": date.fromisoformat(first_trade) if first_trade else today}[chart_range]
        with database_connection() as connection:
            chart_points = daily_valuations(connection, start.isoformat(), today.isoformat(), base_currency)
        returns = transfer_adjusted_returns(chart_points)
        chart = chart_geometry(chart_points, "return" if chart_mode == "return" else "value")
        with database_connection() as connection:
            groups = holdings_groups(connection, snapshot, grouping)
            dividends = dividend_income_base(connection, start.isoformat(), today.isoformat(), base_currency)
            fx = fx_summary(connection, snapshot)
            last_refresh = last_price_refresh(connection)
            recent = recent_transactions(connection)
            notes = recent_notes(connection)
        stale_count = sum(1 for item in snapshot["positions"] if item["stale"])
        return render_template(
            "dashboard.html", snapshot=snapshot, grouping=grouping, groups=groups, chart=chart,
            chart_points=chart_points, chart_mode=chart_mode, chart_range=chart_range,
            range_name=RANGE_NAMES[chart_range], chart_start=start.isoformat(), returns=returns,
            unrealised=unrealised_totals(snapshot), dividends=dividends, fx=fx,
            last_refresh=last_refresh, recent=recent, notes=notes, stale_count=stale_count,
        )

    @app.route("/reconciliation", methods=["GET", "POST"])
    def reconciliation():
        base_currency = app.config.get("BASE_CURRENCY", "PHP")
        if request.method == "POST":
            try:
                with database_connection() as connection:
                    record_reconciliation(connection, request.form.get("spreadsheet_total", ""), base_currency=base_currency, reconciliation_date=request.form.get("reconciliation_date") or None, note=request.form.get("note", ""))
                flash("Reconciliation recorded.")
                return redirect(url_for("reconciliation"))
            except TransactionError as error:
                flash(str(error), "error")
        with database_connection() as connection:
            records = connection.execute("SELECT * FROM reconciliation_records ORDER BY reconciliation_date DESC, id DESC").fetchall()
        return render_template("reconciliation.html", records=records, base_currency=base_currency)

    @app.post("/dashboard/grouping")
    def set_dashboard_grouping():
        grouping = request.form.get("grouping")
        if grouping not in ("platform", "asset_class"):
            return "Invalid grouping", 400
        with database_connection() as connection:
            set_setting(connection, "dashboard_grouping", grouping)
        return redirect(url_for("dashboard"))

    @app.post("/dashboard/chart-settings")
    def set_chart_settings():
        mode, chart_range = request.form.get("mode"), request.form.get("range")
        if mode not in ("value", "return") or chart_range not in ("1M", "YTD", "1Y", "All"):
            return "Invalid chart settings", 400
        with database_connection() as connection:
            set_setting(connection, "chart_mode", mode)
            set_setting(connection, "chart_range", chart_range)
        return redirect(url_for("dashboard"))

    @app.get("/positions")
    def positions():
        as_of = request.args.get("as_of") or None
        with database_connection() as connection:
            records = positions_as_of(connection, as_of, include_zero=True)
        return render_template("positions.html", positions=records, as_of=as_of)

    @app.get("/positions/<int:instrument_id>")
    def position_detail(instrument_id: int):
        as_of = request.args.get("as_of") or None
        with database_connection() as connection:
            instrument = connection.execute("SELECT * FROM instruments WHERE id = ?", (instrument_id,)).fetchone()
            records = position_transactions(connection, instrument_id, as_of)
        if instrument is None:
            return "Instrument not found", 404
        return render_template("position_detail.html", instrument=instrument, transactions=records, as_of=as_of)

    @app.get("/instruments")
    def instruments():
        platform = request.args.get("platform") or None
        asset_class = request.args.get("asset_class") or None
        with database_connection() as connection:
            all_platforms = [
                row[0] for row in connection.execute(
                    "SELECT DISTINCT platform FROM instruments ORDER BY platform"
                )
            ]
            records = list_instruments(connection, platform, asset_class)
        return render_template(
            "instruments.html", instruments=records, asset_classes=ASSET_CLASSES,
            known_platforms=KNOWN_PLATFORMS, platforms=all_platforms,
            selected_platform=platform, selected_asset_class=asset_class,
        )

    @app.route("/instruments/new", methods=["GET", "POST"])
    def new_instrument():
        if request.method == "POST":
            try:
                with database_connection() as connection:
                    create_instrument(connection, request.form)
                flash("Instrument added.")
                return redirect(url_for("instruments"))
            except InstrumentError as error:
                flash(str(error), "error")
        return render_template(
            "instrument_form.html", instrument=None, asset_classes=ASSET_CLASSES,
            known_platforms=KNOWN_PLATFORMS, price_sources=PRICE_SOURCES,
            coverage_statuses=COVERAGE_STATUSES,
        )

    @app.route("/instruments/<int:instrument_id>/edit", methods=["GET", "POST"])
    def edit_instrument(instrument_id: int):
        with database_connection() as connection:
            instrument = connection.execute(
                "SELECT * FROM instruments WHERE id = ?", (instrument_id,)
            ).fetchone()
        if instrument is None:
            return "Instrument not found", 404
        if request.method == "POST":
            try:
                with database_connection() as connection:
                    update_instrument(connection, instrument_id, request.form)
                flash("Instrument updated.")
                return redirect(url_for("instruments"))
            except InstrumentError as error:
                flash(str(error), "error")
        return render_template(
            "instrument_form.html", instrument=instrument, asset_classes=ASSET_CLASSES,
            known_platforms=KNOWN_PLATFORMS, price_sources=PRICE_SOURCES,
            coverage_statuses=COVERAGE_STATUSES,
        )

    @app.post("/instruments/<int:instrument_id>/delete")
    def remove_instrument(instrument_id: int):
        try:
            with database_connection() as connection:
                delete_instrument(connection, instrument_id)
            flash("Instrument deleted.")
        except InstrumentError as error:
            flash(str(error), "error")
        return redirect(url_for("instruments"))

    @app.get("/transactions")
    def transactions():
        with database_connection() as connection:
            records = list_transactions(connection)
            dividends = dividend_income(connection)
        return render_template("transactions.html", transactions=records, dividends=dividends)

    @app.route("/transactions/new/fee", methods=["GET", "POST"])
    def new_fee():
        with database_connection() as connection:
            instruments = connection.execute(
                "SELECT * FROM instruments WHERE asset_class != 'cash' ORDER BY platform, name"
            ).fetchall()
        if request.method == "POST":
            try:
                with database_connection() as connection:
                    record_fee(connection, request.form)
                flash("Fee recorded as a cash debit.")
                return redirect(url_for("transactions"))
            except TransactionError as error:
                flash(str(error), "error")
        return render_template("fee_form.html", instruments=instruments, known_platforms=KNOWN_PLATFORMS)

    @app.route("/transactions/new/transfer", methods=["GET", "POST"])
    def new_transfer():
        if request.method == "POST":
            try:
                with database_connection() as connection:
                    transaction_ids = record_transfer(connection, request.form)
                flash(f"Recorded {len(transaction_ids)} transfer ledger entr{'y' if len(transaction_ids) == 1 else 'ies'}.")
                return redirect(url_for("transactions"))
            except TransactionError as error:
                flash(str(error), "error")
        return render_template("transfer_form.html", known_platforms=KNOWN_PLATFORMS)

    @app.route("/transactions/new/<transaction_type>", methods=["GET", "POST"])
    def new_transaction(transaction_type: str):
        if transaction_type not in ("buy", "sell", "dividend", "reward"):
            return "Transaction type not found", 404
        with database_connection() as connection:
            instruments = connection.execute(
                "SELECT * FROM instruments WHERE asset_class != 'cash' ORDER BY platform, name"
            ).fetchall()
        if request.method == "POST":
            try:
                with database_connection() as connection:
                    if transaction_type == "buy":
                        record_buy(connection, request.form)
                    elif transaction_type == "dividend":
                        record_dividend(connection, request.form)
                    elif transaction_type == "reward":
                        record_reward(connection, request.form)
                    else:
                        _, gain = record_sell(connection, request.form)
                message = "Purchase recorded with its generated cash leg."
                if transaction_type == "sell":
                    message = f"Sale recorded with its generated cash leg. Realised gain/loss: {gain:.2f}."
                elif transaction_type == "dividend":
                    message = "Dividend recorded with its generated net-cash leg."
                elif transaction_type == "reward":
                    message = "Reward recorded as income with no cash leg."
                flash(message)
                return redirect(url_for("transactions"))
            except TransactionError as error:
                flash(str(error), "error")
        return render_template(
            "transaction_form.html", transaction_type=transaction_type,
            instruments=instruments, transaction=None,
        )

    @app.route("/transactions/<int:transaction_id>/edit", methods=["GET", "POST"])
    def edit_transaction(transaction_id: int):
        with database_connection() as connection:
            transaction = connection.execute("SELECT * FROM transactions WHERE id = ?", (transaction_id,)).fetchone()
            instruments = connection.execute("SELECT * FROM instruments WHERE asset_class != 'cash' ORDER BY platform, name").fetchall()
        if transaction is None:
            return "Transaction not found", 404
        if transaction["parent_transaction_id"] is not None:
            flash("Generated cash legs must be edited through their parent transaction.", "error")
            return redirect(url_for("transactions"))
        if transaction["type"] not in ("buy", "sell"):
            flash("This transaction type cannot yet be edited from the ledger.", "error")
            return redirect(url_for("transactions"))
        if request.method == "POST":
            try:
                with database_connection() as connection:
                    update_transaction(connection, transaction_id, request.form)
                flash("Transaction updated and all derived figures recomputed.")
                return redirect(url_for("transactions"))
            except TransactionError as error:
                flash(str(error), "error")
        return render_template("transaction_form.html", transaction_type=transaction["type"], instruments=instruments, transaction=transaction)

    @app.post("/transactions/<int:transaction_id>/delete")
    def remove_transaction(transaction_id: int):
        try:
            with database_connection() as connection:
                delete_transaction(connection, transaction_id)
            flash("Transaction and its generated cash leg deleted. Derived figures recomputed.")
        except TransactionError as error:
            flash(str(error), "error")
        return redirect(url_for("transactions"))

    @app.get("/prices")
    def prices():
        with database_connection() as connection:
            instruments = connection.execute(
                "SELECT * FROM instruments WHERE asset_class != 'cash' ORDER BY platform, name"
            ).fetchall()
            latest_prices = connection.execute(
                """
                SELECT p.* FROM prices p JOIN (
                    SELECT instrument_id, MAX(price_date) AS price_date
                    FROM prices GROUP BY instrument_id
                ) latest ON latest.instrument_id = p.instrument_id AND latest.price_date = p.price_date
                WHERE p.source = 'manual'
                """
            ).fetchall()
            fx_rates = connection.execute(
                "SELECT * FROM fx_rates WHERE base_currency = 'USD' AND quote_currency = 'PHP' ORDER BY rate_date DESC"
            ).fetchall()
        price_by_instrument = {price["instrument_id"]: price for price in latest_prices}
        return render_template("prices.html", instruments=instruments, price_by_instrument=price_by_instrument, fx_rates=fx_rates)

    @app.route("/prices/new", methods=["GET", "POST"])
    def new_price():
        with database_connection() as connection:
            instruments = connection.execute(
                "SELECT * FROM instruments WHERE asset_class != 'cash' ORDER BY platform, name"
            ).fetchall()
        if request.method == "POST":
            try:
                with database_connection() as connection:
                    record_manual_price(connection, request.form)
                flash("Manual price saved.")
                return redirect(url_for("prices"))
            except TransactionError as error:
                flash(str(error), "error")
        return render_template("price_form.html", instruments=instruments)

    @app.route("/prices/bulk", methods=["GET", "POST"])
    def bulk_prices():
        with database_connection() as connection:
            instruments = connection.execute(
                "SELECT * FROM instruments WHERE asset_class != 'cash' ORDER BY platform, name"
            ).fetchall()
        if request.method == "POST":
            try:
                with database_connection() as connection:
                    written = record_bulk_prices(connection, request.form.get("price_date", ""), request.form)
                flash(f"Saved {written} manual price{'s' if written != 1 else ''}.")
                return redirect(url_for("prices"))
            except TransactionError as error:
                flash(str(error), "error")
        return render_template("bulk_prices.html", instruments=instruments)

    @app.route("/fx-rates/new", methods=["GET", "POST"])
    def new_fx_rate():
        if request.method == "POST":
            try:
                with database_connection() as connection:
                    record_manual_fx_rate(connection, request.form)
                flash("USD/PHP rate saved.")
                return redirect(url_for("prices"))
            except TransactionError as error:
                flash(str(error), "error")
        return render_template("fx_rate_form.html")

    return app
