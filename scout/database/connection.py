"""SQLite connection management.

Every connection to the Scout database - from initialization, seeding,
future repositories, or tests - goes through this module, so foreign
key enforcement and row access are configured identically everywhere.
SQLite does not enforce foreign keys unless a connection explicitly
turns that pragma on, so we do it here, once, instead of relying on
every caller to remember.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from scout.config import get_settings


def _ensure_parent_directory(db_path: str) -> None:
    """Create the parent directory for a file-based database, if needed."""
    if db_path == ":memory:":
        return
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)


def get_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """Open a new SQLite connection with foreign-key enforcement enabled.

    Args:
        db_path: Optional override of the configured database path.
            Tests pass a temporary file path here so they never touch
            the development database.

    Returns:
        An open sqlite3.Connection with row_factory set to sqlite3.Row,
        so query results can be read by column name (row["price"]).
    """
    resolved_path = db_path or get_settings().database_path
    _ensure_parent_directory(resolved_path)

    connection = sqlite3.connect(resolved_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    return connection


@contextmanager
def connection_scope(db_path: Optional[str] = None) -> Iterator[sqlite3.Connection]:
    """Open a connection, commit on success, roll back and close on error.

    Usage:
        with connection_scope() as connection:
            connection.execute(...)
    """
    connection = get_connection(db_path)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
