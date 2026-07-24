"""Read-only persistence boundary for Step 17 order status.

Only this repository executes SQL for order lookup, payment status, immutable
order items, inventory reservations, and mutable fulfillment/tracking facts.
The Order Agent and service layer never query SQLite directly.
"""

from __future__ import annotations

from typing import List, Optional

from scout.database.connection import connection_scope
from scout.repositories.models import (
    InventoryReservationRecord,
    OrderFulfillmentRecord,
    OrderItemRecord,
    OrderRecord,
    PaymentRecord,
)


class OrderRepository:
    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db_path = db_path

    def get_by_id_for_session(self, order_id: str, session_id: str) -> Optional[OrderRecord]:
        with connection_scope(self._db_path) as connection:
            row = connection.execute(
                "SELECT * FROM orders WHERE order_id = ? AND session_id = ?",
                (order_id, session_id),
            ).fetchone()
        return OrderRecord.from_row(row) if row is not None else None

    def update_status_for_session(self, order_id: str, session_id: str, status: str) -> bool:
        with connection_scope(self._db_path) as connection:
            updated = connection.execute(
                "UPDATE orders SET status = ? WHERE order_id = ? AND session_id = ?",
                (status, order_id, session_id),
            )
        return updated.rowcount == 1

    def get_latest_for_session(self, session_id: str) -> Optional[OrderRecord]:
        with connection_scope(self._db_path) as connection:
            row = connection.execute(
                """
                SELECT * FROM orders
                WHERE session_id = ?
                ORDER BY created_at DESC, order_id DESC
                LIMIT 1
                """,
                (session_id,),
            ).fetchone()
        return OrderRecord.from_row(row) if row is not None else None

    def get_payment(self, order_id: str) -> Optional[PaymentRecord]:
        with connection_scope(self._db_path) as connection:
            row = connection.execute(
                """
                SELECT p.* FROM payments p
                JOIN orders o ON o.payment_id = p.payment_id
                WHERE o.order_id = ?
                """,
                (order_id,),
            ).fetchone()
        return PaymentRecord.from_row(row) if row is not None else None

    def list_items(self, order_id: str) -> List[OrderItemRecord]:
        with connection_scope(self._db_path) as connection:
            rows = connection.execute(
                "SELECT * FROM order_items WHERE order_id = ? ORDER BY created_at, order_item_id",
                (order_id,),
            ).fetchall()
        return [OrderItemRecord.from_row(row) for row in rows]

    def list_reservations(self, order_id: str) -> List[InventoryReservationRecord]:
        with connection_scope(self._db_path) as connection:
            rows = connection.execute(
                """
                SELECT * FROM inventory_reservations
                WHERE order_id = ?
                ORDER BY order_item_id, store_id
                """,
                (order_id,),
            ).fetchall()
        return [InventoryReservationRecord.from_row(row) for row in rows]

    def get_fulfillment(self, order_id: str) -> Optional[OrderFulfillmentRecord]:
        with connection_scope(self._db_path) as connection:
            row = connection.execute(
                "SELECT * FROM order_fulfillments WHERE order_id = ?",
                (order_id,),
            ).fetchone()
        return OrderFulfillmentRecord.from_row(row) if row is not None else None
