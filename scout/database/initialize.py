"""Database initialization: creates all Scout tables from schema.sql.

Safe to run any number of times - every statement in schema.sql uses
CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS, so re-running
this module never fails and never duplicates structure.
"""

import logging
from pathlib import Path
from typing import Optional

from scout.database.connection import connection_scope

logger = logging.getLogger(__name__)

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def _column_names(connection, table_name: str) -> set[str]:
    return {row["name"] for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()}


def apply_lightweight_migrations(connection) -> None:
    checkout_columns = _column_names(connection, "checkout_sessions")
    if "payment_provider" not in checkout_columns:
        connection.execute("ALTER TABLE checkout_sessions ADD COLUMN payment_provider TEXT")
    if "payment_intent_id" not in checkout_columns:
        connection.execute("ALTER TABLE checkout_sessions ADD COLUMN payment_intent_id TEXT")
    if "payment_status" not in checkout_columns:
        connection.execute("ALTER TABLE checkout_sessions ADD COLUMN payment_status TEXT")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS stripe_webhook_events (
            event_id           TEXT PRIMARY KEY,
            event_type         TEXT NOT NULL,
            checkout_id        TEXT,
            payment_intent_id  TEXT,
            processed_at       TEXT NOT NULL
        )
        """
    )


def initialize_database(db_path: Optional[str] = None) -> None:
    """Create all Scout tables and indexes if they do not already exist.

    Args:
        db_path: Optional override of the configured database path,
            used by tests to target a temporary file.
    """
    schema_sql = _SCHEMA_PATH.read_text(encoding="utf-8")

    with connection_scope(db_path) as connection:
        connection.executescript(schema_sql)
        apply_lightweight_migrations(connection)

    logger.info("database_initialized", extra={"db_path": db_path or "default"})


if __name__ == "__main__":
    initialize_database()
    print(
        "Scout database initialized: catalog, inventory, carts, semantic search, "
        "checkout, payments, orders, reservations, fulfillment tracking, external offers, and affiliate clicks."
    )
