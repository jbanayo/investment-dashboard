"""Application factory for the local portfolio dashboard."""

from __future__ import annotations

import os
import json
from pathlib import Path
from typing import TYPE_CHECKING

from .db import migrate
from .db import connect
from .cash import ensure_cash_instruments

APP_VERSION = "1.1.0"

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
        TWELVE_DATA_API_KEY=os.environ.get("TWELVE_DATA_API_KEY", ""),
    )

    if test_config:
        app.config.update(test_config)

    database_path = Path(app.config["DATABASE"])
    database_path.parent.mkdir(parents=True, exist_ok=True)
    migrate(database_path)
    with connect(database_path) as connection:
        ensure_cash_instruments(connection)

    if not app.config["TWELVE_DATA_API_KEY"]:
        key_file = Path(app.instance_path) / "twelve_data_api_key"
        if key_file.exists():
            app.config["TWELVE_DATA_API_KEY"] = key_file.read_text().strip()

    def database_connection():
        return connect(database_path)

    from flask import after_this_request, flash, redirect, render_template, request, send_file, url_for
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
    from .settings import (
        BASE_CURRENCIES, THEMES, get_setting, portfolio_preferences,
        reset_portfolio_data, save_portfolio_preferences, set_setting,
    )
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
    from .fetch import (
        refresh_twelve_data_crypto_prices, refresh_twelve_data_ibkr_prices,
        twelve_data_usage,
    )
    from .pse_edge import refresh_pse_edge_prices
    from .research import (
        CONFIDENCE_LEVELS, STANCES, STATUSES, TRIGGER_TYPES, ResearchError,
        create_manual_research, list_research, research_counts,
        monitored_research,
        transition_research_item, update_research_item,
    )
    from .research_import import (
        MAX_IMPORT_BYTES, ResearchImportError, confirm_research_import,
        discard_research_import_preview, research_import_preview,
        stage_research_import,
    )

    app.jinja_env.filters.update(FILTERS)

    @app.context_processor
    def inject_app_preferences():
        with database_connection() as connection:
            preferences = portfolio_preferences(connection)
            tour_seen = get_setting(connection, "tour_seen", "0") == "1"
            draft_count = connection.execute(
                "SELECT COUNT(*) FROM research_items WHERE status = 'draft'"
            ).fetchone()[0]
        return {
            "app_preferences": preferences, "tour_autostart": not tour_seen,
            "research_draft_count": draft_count, "app_version": APP_VERSION,
        }

    @app.post("/tour/seen")
    def mark_tour_seen():
        # The first-run tour starts once on its own; the nav's Tour button replays it.
        with database_connection() as connection:
            set_setting(connection, "tour_seen", "1")
        return "", 204

    @app.get("/")
    def index():
        return redirect(url_for("dashboard"))

    @app.get("/dashboard")
    def dashboard():
        with database_connection() as connection:
            base_currency = get_setting(
                connection, "portfolio_base_currency", app.config.get("BASE_CURRENCY", "PHP")
            )
            platforms = [row["platform"] for row in connection.execute(
                """SELECT DISTINCT platform FROM transactions
                   WHERE parent_transaction_id IS NULL ORDER BY platform"""
            )]
            selected_platform = get_setting(connection, "dashboard_platform", "__all__")
            if selected_platform == "__all__" or selected_platform not in platforms:
                selected_platform = None
            snapshot = portfolio_snapshot(connection, base_currency, platform=selected_platform)
            grouping = get_setting(connection, "dashboard_grouping", "platform")
            chart_mode = get_setting(connection, "chart_mode", "value")
            chart_range = get_setting(connection, "chart_range", "1Y")
            first_trade = connection.execute(
                "SELECT MIN(trade_date) FROM transactions"
                + (" WHERE platform = ?" if selected_platform else ""),
                (selected_platform,) if selected_platform else (),
            ).fetchone()[0]
        from datetime import date, timedelta
        today = date.today()
        start = {"1M": today - timedelta(days=30), "YTD": date(today.year, 1, 1), "1Y": today - timedelta(days=365), "All": date.fromisoformat(first_trade) if first_trade else today}[chart_range]
        with database_connection() as connection:
            chart_points = daily_valuations(
                connection, start.isoformat(), today.isoformat(), base_currency, selected_platform
            )
        returns = transfer_adjusted_returns(chart_points)
        chart = chart_geometry(chart_points, "return" if chart_mode == "return" else "value")
        with database_connection() as connection:
            groups = holdings_groups(connection, snapshot, grouping)
            dividends = dividend_income_base(
                connection, start.isoformat(), today.isoformat(), base_currency, selected_platform
            )
            fx = fx_summary(connection, snapshot)
            last_refresh = last_price_refresh(connection, selected_platform)
            recent = recent_transactions(connection, platform=selected_platform)
            notes = recent_notes(connection, platform=selected_platform)
            monitoring = monitored_research(connection, selected_platform)
        stale_count = sum(1 for item in snapshot["positions"] if item["stale"])
        return render_template(
            "dashboard.html", snapshot=snapshot, grouping=grouping, groups=groups, chart=chart,
            chart_points=chart_points, chart_mode=chart_mode, chart_range=chart_range,
            range_name=RANGE_NAMES[chart_range], chart_start=start.isoformat(), returns=returns,
            unrealised=unrealised_totals(snapshot), dividends=dividends, fx=fx,
            last_refresh=last_refresh, recent=recent, notes=notes, stale_count=stale_count,
            platforms=platforms, selected_platform=selected_platform,
            monitoring=monitoring,
        )

    @app.route("/settings", methods=["GET", "POST"])
    def settings_page():
        if request.method == "POST":
            try:
                with database_connection() as connection:
                    save_portfolio_preferences(
                        connection,
                        request.form.get("display_name", ""),
                        request.form.get("base_currency", ""),
                        request.form.get("theme", ""),
                    )
                flash("Settings saved.")
                return redirect(url_for("settings_page"))
            except ValueError as error:
                flash(str(error), "error")
        with database_connection() as connection:
            preferences = portfolio_preferences(connection)
        return render_template(
            "settings.html", preferences=preferences,
            base_currencies=BASE_CURRENCIES, themes=THEMES,
            database_path=str(database_path.resolve()),
        )

    @app.get("/settings/database/export")
    def export_database():
        import sqlite3
        import tempfile
        export_file = tempfile.NamedTemporaryFile(
            prefix="portfolio-backup-", suffix=".db", delete=False
        )
        export_path = Path(export_file.name)
        export_file.close()
        with sqlite3.connect(database_path) as source, sqlite3.connect(export_path) as target:
            source.backup(target)

        @after_this_request
        def remove_export(response):
            try:
                export_path.unlink(missing_ok=True)
            finally:
                return response

        return send_file(
            export_path, as_attachment=True,
            download_name="portfolio-backup.db",
            mimetype="application/vnd.sqlite3",
        )

    @app.post("/settings/database/reset")
    def reset_database():
        if request.form.get("confirmation") != "RESET":
            flash("Type RESET exactly to confirm data removal.", "error")
            return redirect(url_for("settings_page"))
        with database_connection() as connection:
            reset_portfolio_data(connection)
            ensure_cash_instruments(connection)
        flash("Portfolio data reset. Settings were retained.")
        return redirect(url_for("settings_page"))

    @app.route("/reconciliation", methods=["GET", "POST"])
    def reconciliation():
        with database_connection() as connection:
            base_currency = get_setting(
                connection, "portfolio_base_currency", app.config.get("BASE_CURRENCY", "PHP")
            )
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

    @app.post("/dashboard/platform")
    def set_dashboard_platform():
        platform = request.form.get("platform", "__all__")
        with database_connection() as connection:
            valid_platforms = {
                row["platform"] for row in connection.execute(
                    "SELECT DISTINCT platform FROM transactions WHERE parent_transaction_id IS NULL"
                )
            }
            if platform != "__all__" and platform not in valid_platforms:
                return "Invalid platform", 400
            set_setting(connection, "dashboard_platform", platform)
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
            twelve_used, twelve_remaining = twelve_data_usage(connection)
        price_by_instrument = {price["instrument_id"]: price for price in latest_prices}
        return render_template(
            "prices.html", instruments=instruments, price_by_instrument=price_by_instrument,
            fx_rates=fx_rates, twelve_used=twelve_used, twelve_remaining=twelve_remaining,
            twelve_configured=bool(app.config["TWELVE_DATA_API_KEY"]),
        )

    @app.post("/prices/refresh/crypto")
    def refresh_crypto_prices():
        try:
            with database_connection() as connection:
                result = refresh_twelve_data_crypto_prices(
                    connection, app.config["TWELVE_DATA_API_KEY"]
                )
            message = (
                f"Twelve Data refreshed {result.instruments_updated} crypto instruments and saved "
                f"{result.prices_written:,} daily prices using {result.requests_used} requests. "
                f"{result.requests_remaining} requests remain today."
            )
            if result.instruments_pending:
                message += f" {result.instruments_pending} instruments still need a later refresh."
            if result.failures:
                message += " Failed: " + "; ".join(f.message for f in result.failures)
                flash(message, "error")
            else:
                flash(message)
        except (RuntimeError, ValueError) as error:
            flash(str(error), "error")
        destination = "dashboard" if request.form.get("return_to") == "dashboard" else "prices"
        return redirect(url_for(destination))

    @app.post("/prices/refresh/ibkr")
    def refresh_ibkr_prices():
        try:
            with database_connection() as connection:
                result = refresh_twelve_data_ibkr_prices(
                    connection, app.config["TWELVE_DATA_API_KEY"]
                )
            message = (
                f"Twelve Data refreshed {result.instruments_updated} IBKR instruments and saved "
                f"{result.prices_written:,} daily prices using {result.requests_used} requests. "
                f"{result.requests_remaining} requests remain today."
            )
            if result.instruments_pending:
                message += f" {result.instruments_pending} instruments still need a later refresh."
            if result.failures:
                message += " Failed: " + "; ".join(f.message for f in result.failures)
                flash(message, "error")
            else:
                flash(message)
        except (RuntimeError, ValueError) as error:
            flash(str(error), "error")
        destination = "dashboard" if request.form.get("return_to") == "dashboard" else "prices"
        return redirect(url_for(destination))

    @app.post("/prices/refresh/pse")
    def refresh_pse_prices():
        with database_connection() as connection:
            result = refresh_pse_edge_prices(connection)
        message = (
            f"PSE Edge refreshed {result.instruments_updated} BDO instruments and saved "
            f"{result.prices_written:,} daily prices using {result.requests_used} requests."
        )
        if result.failures:
            message += " Failed: " + "; ".join(failure.message for failure in result.failures)
            flash(message, "error")
        else:
            flash(message)
        destination = "dashboard" if request.form.get("return_to") == "dashboard" else "prices"
        return redirect(url_for(destination))

    @app.post("/prices/refresh/all")
    def refresh_all_prices():
        summaries: list[str] = []
        failures: list[str] = []
        with database_connection() as connection:
            try:
                crypto = refresh_twelve_data_crypto_prices(
                    connection, app.config["TWELVE_DATA_API_KEY"]
                )
                summaries.append(
                    f"Crypto: {crypto.instruments_updated} instruments, "
                    f"{crypto.prices_written:,} prices, {crypto.requests_used} requests"
                )
                if crypto.instruments_pending:
                    summaries.append(f"Crypto pending: {crypto.instruments_pending}")
                failures.extend(f"Crypto: {item.message}" for item in crypto.failures)
            except (RuntimeError, ValueError) as error:
                failures.append(f"Crypto: {error}")

            try:
                ibkr = refresh_twelve_data_ibkr_prices(
                    connection, app.config["TWELVE_DATA_API_KEY"]
                )
                summaries.append(
                    f"IBKR: {ibkr.instruments_updated} instruments, "
                    f"{ibkr.prices_written:,} prices, {ibkr.requests_used} requests"
                )
                if ibkr.instruments_pending:
                    summaries.append(f"IBKR pending: {ibkr.instruments_pending}")
                failures.extend(f"IBKR: {item.message}" for item in ibkr.failures)
            except (RuntimeError, ValueError) as error:
                failures.append(f"IBKR: {error}")

            try:
                pse = refresh_pse_edge_prices(connection)
                summaries.append(
                    f"PSE: {pse.instruments_updated} instruments, "
                    f"{pse.prices_written:,} prices, {pse.requests_used} requests"
                )
                failures.extend(f"PSE: {item.message}" for item in pse.failures)
            except (RuntimeError, ValueError) as error:
                failures.append(f"PSE: {error}")

        message = "Refresh complete. " + "; ".join(summaries) + "."
        if failures:
            message += " Issues: " + "; ".join(failures)
            flash(message, "error")
        else:
            flash(message)
        destination = "dashboard" if request.form.get("return_to") == "dashboard" else "prices"
        return redirect(url_for(destination))

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

    @app.get("/research")
    def research():
        status = request.args.get("status", "draft")
        if status not in STATUSES:
            status = "draft"
        selected_platform = request.args.get("platform", "").strip() or None
        with database_connection() as connection:
            counts = research_counts(connection)
            platforms = [row["platform"] for row in connection.execute(
                "SELECT DISTINCT platform FROM instruments WHERE asset_class != 'cash' ORDER BY platform"
            )]
            if selected_platform not in platforms:
                selected_platform = None
            items = list_research(connection, status, selected_platform)
            if status == "monitoring":
                monitoring_states = {
                    item["id"]: item for item in monitored_research(connection, selected_platform)
                }
                for item in items:
                    state = monitoring_states.get(item["id"])
                    if state:
                        item.update({
                            "monitoring_status": state["monitoring_status"],
                            "monitoring_label": state["monitoring_label"],
                            "current_price": state["current_price"],
                            "current_price_date": state["current_price_date"],
                            "current_price_currency": state["current_price_currency"],
                            "distance_to_trigger": state["distance_to_trigger"],
                        })
        return render_template(
            "research.html", items=items, counts=counts, status=status,
            statuses=STATUSES, platforms=platforms, selected_platform=selected_platform,
        )

    @app.route("/research/import", methods=["GET", "POST"])
    def import_research():
        with database_connection() as connection:
            instruments = connection.execute(
                "SELECT * FROM instruments WHERE asset_class != 'cash' ORDER BY platform, name"
            ).fetchall()
        if request.method == "POST":
            try:
                instrument_id = int(request.form.get("instrument_id", ""))
                upload = request.files.get("research_file")
                if not upload or not upload.filename:
                    raise ResearchImportError("Choose a Markdown research file.")
                content = upload.stream.read(MAX_IMPORT_BYTES + 1)
                with database_connection() as connection:
                    token = stage_research_import(
                        connection, instrument_id, upload.filename,
                        request.form.get("agent_name", ""), content,
                    )
                return redirect(url_for("preview_research_import", token=token))
            except (ResearchImportError, TypeError, ValueError) as error:
                flash(str(error), "error")
        return render_template("research_import.html", instruments=instruments)

    @app.get("/research/import/preview/<token>")
    def preview_research_import(token: str):
        with database_connection() as connection:
            preview = research_import_preview(connection, token)
        if not preview:
            flash("This import preview expired or was already used.", "error")
            return redirect(url_for("import_research"))
        return render_template("research_import_preview.html", preview=preview)

    @app.post("/research/import/preview/<token>/cancel")
    def cancel_research_import(token: str):
        with database_connection() as connection:
            discard_research_import_preview(connection, token)
        flash("Research import cancelled.")
        return redirect(url_for("import_research"))

    @app.post("/research/import/preview/<token>/confirm")
    def confirm_research_import_route(token: str):
        try:
            with database_connection() as connection:
                confirm_research_import(connection, token)
            flash("AI-assisted research imported for review.")
            return redirect(url_for("research", status="draft"))
        except ResearchImportError as error:
            flash(str(error), "error")
            return redirect(url_for("import_research"))

    @app.route("/research/new", methods=["GET", "POST"])
    def new_research():
        if request.method == "POST":
            try:
                with database_connection() as connection:
                    item_id = create_manual_research(connection, request.form)
                    status = connection.execute(
                        "SELECT status FROM research_items WHERE id = ?", (item_id,)
                    ).fetchone()["status"]
                flash("Research saved.")
                return redirect(url_for("research", status=status))
            except ResearchError as error:
                flash(str(error), "error")
        with database_connection() as connection:
            instruments = connection.execute(
                "SELECT * FROM instruments WHERE asset_class != 'cash' ORDER BY platform, name"
            ).fetchall()
        return render_template(
            "research_form.html", instruments=instruments, stances=STANCES,
            trigger_types=TRIGGER_TYPES, confidence_levels=CONFIDENCE_LEVELS,
            form_values=request.form, editing=False, item=None,
        )

    @app.route("/research/<int:item_id>/edit", methods=["GET", "POST"])
    def edit_research(item_id: int):
        with database_connection() as connection:
            item = connection.execute(
                """SELECT r.*, i.name AS instrument_name, i.ticker, i.platform
                   FROM research_items r JOIN instruments i ON i.id = r.instrument_id
                   WHERE r.id = ?""",
                (item_id,),
            ).fetchone()
        if not item:
            return "Research item not found", 404
        if request.method == "POST":
            try:
                with database_connection() as connection:
                    update_research_item(connection, item_id, request.form)
                flash("Research updated. The original imported Markdown was preserved.")
                return redirect(url_for("research", status=item["status"]))
            except ResearchError as error:
                flash(str(error), "error")
                form_values = request.form
        else:
            form_values = {
                "instrument_id": str(item["instrument_id"]),
                "research_date": item["research_date"], "stance": item["stance"],
                "time_horizon": item["time_horizon"] or "",
                "trigger_type": item["trigger_type"],
                "trigger_price": item["trigger_price"] or "",
                "trigger_currency": item["trigger_currency"] or "",
                "expires_on": item["expires_on"] or "",
                "event_trigger": item["event_trigger"] or "", "summary": item["summary"],
                "supporting_points": "\n".join(json.loads(item["supporting_points_json"])),
                "risks": "\n".join(json.loads(item["risks_json"])),
                "confidence": item["confidence"] or "",
                "confidence_reason": item["confidence_reason"] or "",
            }
        return render_template(
            "research_form.html", instruments=(), stances=STANCES,
            trigger_types=TRIGGER_TYPES, confidence_levels=CONFIDENCE_LEVELS,
            form_values=form_values, editing=True, item=item,
        )

    @app.post("/research/<int:item_id>/status")
    def research_status(item_id: int):
        try:
            new_status = request.form.get("status", "")
            with database_connection() as connection:
                transition_research_item(connection, item_id, new_status)
            flash({
                "monitoring": "Research added to monitoring.",
                "saved": "Research saved to the library.",
                "archived": "Research archived.",
                "draft": "Research restored to drafts.",
            }[new_status])
        except (ResearchError, KeyError) as error:
            flash(str(error) or "Could not update research.", "error")
        return redirect(url_for("research", status=request.form.get("return_status", "draft")))

    return app
