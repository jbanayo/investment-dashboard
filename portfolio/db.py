"""SQLite connection and migration support."""

from __future__ import annotations

import sqlite3
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).with_name("migrations")


def connect(database_path: str | Path) -> sqlite3.Connection:
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def migrate(database_path: str | Path) -> None:
    """Apply unapplied SQL migrations in version order."""
    with connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        applied = {
            row["version"]
            for row in connection.execute("SELECT version FROM schema_migrations")
        }
        for migration_path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            version = migration_path.stem.split("_", 1)[0]
            if version in applied:
                continue
            connection.executescript(migration_path.read_text())
            connection.execute(
                "INSERT INTO schema_migrations (version) VALUES (?)", (version,)
            )
