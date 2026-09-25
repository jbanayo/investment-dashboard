import sqlite3


THEMES = ("system", "light", "dark")
BASE_CURRENCIES = ("PHP", "USD")


def get_setting(connection: sqlite3.Connection, key: str, default: str) -> str:
    row = connection.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(connection: sqlite3.Connection, key: str, value: str) -> None:
    connection.execute(
        """
        INSERT INTO app_settings (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP
        """,
        (key, value),
    )


def portfolio_preferences(connection: sqlite3.Connection) -> dict[str, str]:
    return {
        "display_name": get_setting(connection, "portfolio_display_name", "Portfolio"),
        "base_currency": get_setting(connection, "portfolio_base_currency", "PHP"),
        "theme": get_setting(connection, "appearance_theme", "system"),
    }


def save_portfolio_preferences(
    connection: sqlite3.Connection, display_name: str, base_currency: str, theme: str
) -> None:
    display_name = display_name.strip()
    if not display_name:
        raise ValueError("Enter a portfolio display name.")
    if len(display_name) > 80:
        raise ValueError("Portfolio display name must be 80 characters or fewer.")
    base_currency = base_currency.upper()
    if base_currency not in BASE_CURRENCIES:
        raise ValueError("Choose a supported base currency.")
    if theme not in THEMES:
        raise ValueError("Choose a supported appearance.")
    set_setting(connection, "portfolio_display_name", display_name)
    set_setting(connection, "portfolio_base_currency", base_currency)
    set_setting(connection, "appearance_theme", theme)


def reset_portfolio_data(connection: sqlite3.Connection) -> None:
    """Clear user-entered portfolio data while retaining preferences and schema."""
    for table in (
        "price_revisions", "fx_rate_revisions", "ratings", "notes",
        "prices", "fx_rates", "reconciliation_records", "documents",
    ):
        connection.execute(f"DELETE FROM {table}")
    # Generated cash legs reference their parent transaction with RESTRICT.
    connection.execute("DELETE FROM transactions WHERE parent_transaction_id IS NOT NULL")
    connection.execute("DELETE FROM transactions")
    connection.execute("DELETE FROM instruments")
