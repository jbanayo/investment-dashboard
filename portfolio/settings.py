import sqlite3


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
