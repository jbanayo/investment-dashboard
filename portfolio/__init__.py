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
        record_sell,
    )

    @app.get("/")
    def index():
        return redirect(url_for("instruments"))

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
            known_platforms=KNOWN_PLATFORMS,
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
            known_platforms=KNOWN_PLATFORMS,
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

    @app.route("/transactions/new/<transaction_type>", methods=["GET", "POST"])
    def new_transaction(transaction_type: str):
        if transaction_type not in ("buy", "sell", "dividend"):
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
                    else:
                        _, gain = record_sell(connection, request.form)
                message = "Purchase recorded with its generated cash leg."
                if transaction_type == "sell":
                    message = f"Sale recorded with its generated cash leg. Realised gain/loss: {gain:.2f}."
                elif transaction_type == "dividend":
                    message = "Dividend recorded with its generated net-cash leg."
                flash(message)
                return redirect(url_for("transactions"))
            except TransactionError as error:
                flash(str(error), "error")
        return render_template(
            "transaction_form.html", transaction_type=transaction_type,
            instruments=instruments,
        )

    return app
