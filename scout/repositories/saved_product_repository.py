"""Saved product repository: the only SQL boundary for saved_products."""

import sqlite3
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from scout.database.connection import connection_scope
from scout.repositories.models import SavedProduct


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SavedProductRepository:
    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db_path = db_path

    def list_for_owner(self, session_id: Optional[str], customer_id: Optional[str]) -> List[SavedProduct]:
        where, params = _owner_clause(session_id, customer_id)
        with connection_scope(self._db_path) as connection:
            rows = connection.execute(
                f"SELECT * FROM saved_products WHERE {where} ORDER BY created_at DESC",
                params,
            ).fetchall()
        return [SavedProduct.from_row(row) for row in rows]

    def get_for_owner(self, product_id: str, session_id: Optional[str], customer_id: Optional[str]) -> Optional[SavedProduct]:
        where, params = _owner_clause(session_id, customer_id)
        with connection_scope(self._db_path) as connection:
            row = connection.execute(
                f"SELECT * FROM saved_products WHERE product_id = ? AND {where}",
                (product_id, *params),
            ).fetchone()
        return SavedProduct.from_row(row) if row is not None else None

    def save(self, product_id: str, session_id: Optional[str], customer_id: Optional[str]) -> SavedProduct:
        existing = self.get_for_owner(product_id, session_id, customer_id)
        if existing is not None:
            return existing

        saved_id = str(uuid.uuid4())
        now = _now()
        with connection_scope(self._db_path) as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO saved_products (saved_id, session_id, customer_id, product_id, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (saved_id, None if customer_id else session_id, customer_id, product_id, now),
                )
            except sqlite3.IntegrityError:
                existing_after_race = self.get_for_owner(product_id, session_id, customer_id)
                if existing_after_race is not None:
                    return existing_after_race
                raise

        return SavedProduct(
            saved_id=saved_id,
            session_id=None if customer_id else session_id,
            customer_id=customer_id,
            product_id=product_id,
            created_at=now,
        )

    def remove(self, product_id: str, session_id: Optional[str], customer_id: Optional[str]) -> bool:
        where, params = _owner_clause(session_id, customer_id)
        with connection_scope(self._db_path) as connection:
            cursor = connection.execute(
                f"DELETE FROM saved_products WHERE product_id = ? AND {where}",
                (product_id, *params),
            )
        return cursor.rowcount > 0


def _owner_clause(session_id: Optional[str], customer_id: Optional[str]) -> tuple[str, tuple[str, ...]]:
    if customer_id:
        return "customer_id = ?", (customer_id,)
    if session_id:
        return "session_id = ? AND customer_id IS NULL", (session_id,)
    raise ValueError("session_id or customer_id is required")
