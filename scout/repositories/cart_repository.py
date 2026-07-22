"""Cart repository: the only place that runs SQL against carts/cart_items.

See scout/repositories/__init__.py for why repositories are the sole
SQL boundary. This repository intentionally does no validation and no
pricing/inventory logic at all - it inserts, updates, and reads exactly
what it is told. Every decision about whether a mutation is *allowed*
(product active, quantity in range, enough stock, a valid pickup store)
belongs to scout/services/cart_service.py, one layer up.
"""

import uuid
from datetime import datetime, timezone
from typing import List, Optional

from scout.database.connection import connection_scope
from scout.repositories.models import Cart, CartItem


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CartRepository:
    """Read/write access to the carts and cart_items tables."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        """
        Args:
            db_path: Optional override of the configured database path.
                Tests pass a temporary file path here.
        """
        self._db_path = db_path

    # -- carts ------------------------------------------------------------

    def get_active_cart_by_session(self, session_id: str) -> Optional[Cart]:
        """Return the session's one active cart, if it has one.

        Returns:
            A Cart with status == "active", or None if this session has
            never started a cart (or its cart was cleared/converted).
            Not finding one is not an error - callers (the service
            layer) decide whether to create a new cart in response.
        """
        with connection_scope(self._db_path) as connection:
            row = connection.execute(
                "SELECT * FROM carts WHERE session_id = ? AND status = 'active'",
                (session_id,),
            ).fetchone()
        return Cart.from_row(row) if row is not None else None

    def get_cart_by_id(self, cart_id: str) -> Optional[Cart]:
        """Retrieve one cart by its primary key, regardless of status."""
        with connection_scope(self._db_path) as connection:
            row = connection.execute(
                "SELECT * FROM carts WHERE cart_id = ?", (cart_id,)
            ).fetchone()
        return Cart.from_row(row) if row is not None else None

    def create_cart(self, session_id: str) -> Cart:
        """Create a new active cart for a session.

        Callers must first confirm (via get_active_cart_by_session) that
        the session has no active cart - the partial unique index on
        carts(session_id) WHERE status='active' (scout/database/schema.sql)
        makes a second concurrent attempt fail loudly (sqlite3.IntegrityError)
        rather than silently creating two "active" carts for one session.
        """
        cart_id = str(uuid.uuid4())
        now = _now()
        with connection_scope(self._db_path) as connection:
            connection.execute(
                """
                INSERT INTO carts (cart_id, session_id, customer_id, fulfillment_type, store_id, status, created_at, updated_at)
                VALUES (?, ?, NULL, NULL, NULL, 'active', ?, ?)
                """,
                (cart_id, session_id, now, now),
            )
        return Cart(
            cart_id=cart_id,
            session_id=session_id,
            customer_id=None,
            fulfillment_type=None,
            store_id=None,
            status="active",
            created_at=now,
            updated_at=now,
        )

    def set_fulfillment(self, cart_id: str, fulfillment_type: str, store_id: Optional[str]) -> None:
        """Record the customer's pickup/delivery choice on the cart.

        Args:
            fulfillment_type: "pickup" or "delivery" - already validated
                by the caller.
            store_id: Required by the caller when fulfillment_type is
                "pickup"; None for "delivery".
        """
        with connection_scope(self._db_path) as connection:
            connection.execute(
                "UPDATE carts SET fulfillment_type = ?, store_id = ?, updated_at = ? WHERE cart_id = ?",
                (fulfillment_type, store_id, _now(), cart_id),
            )

    def touch_cart(self, cart_id: str) -> None:
        """Bump a cart's updated_at without changing anything else.

        Called whenever an item under this cart changes, so
        carts.updated_at always reflects the most recent activity on
        the cart as a whole - not just direct edits to the carts row
        itself.
        """
        with connection_scope(self._db_path) as connection:
            connection.execute(
                "UPDATE carts SET updated_at = ? WHERE cart_id = ?", (_now(), cart_id)
            )

    # -- cart_items ---------------------------------------------------------

    def list_items(self, cart_id: str) -> List[CartItem]:
        """List every line item in one cart, ordered by when it was added."""
        with connection_scope(self._db_path) as connection:
            rows = connection.execute(
                "SELECT * FROM cart_items WHERE cart_id = ? ORDER BY created_at",
                (cart_id,),
            ).fetchall()
        return [CartItem.from_row(row) for row in rows]

    def get_item(self, cart_item_id: str) -> Optional[CartItem]:
        """Retrieve one cart item by its primary key."""
        with connection_scope(self._db_path) as connection:
            row = connection.execute(
                "SELECT * FROM cart_items WHERE cart_item_id = ?", (cart_item_id,)
            ).fetchone()
        return CartItem.from_row(row) if row is not None else None

    def get_item_by_product(self, cart_id: str, product_id: str) -> Optional[CartItem]:
        """Find the existing line item for a product in a cart, if any.

        Used by the service layer to decide whether an add-to-cart call
        should merge into an existing line (increase its quantity)
        rather than create a duplicate one - enforced at the database
        level too by the UNIQUE (cart_id, product_id) constraint.
        """
        with connection_scope(self._db_path) as connection:
            row = connection.execute(
                "SELECT * FROM cart_items WHERE cart_id = ? AND product_id = ?",
                (cart_id, product_id),
            ).fetchone()
        return CartItem.from_row(row) if row is not None else None

    def insert_item(
        self,
        cart_id: str,
        product_id: str,
        quantity: int,
        unit_price_snapshot: float,
        promotion_id: Optional[str],
    ) -> CartItem:
        """Insert a new cart line. Callers must have already confirmed
        no line for this (cart_id, product_id) exists yet."""
        cart_item_id = str(uuid.uuid4())
        now = _now()
        with connection_scope(self._db_path) as connection:
            connection.execute(
                """
                INSERT INTO cart_items
                    (cart_item_id, cart_id, product_id, quantity, unit_price_snapshot, promotion_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (cart_item_id, cart_id, product_id, quantity, unit_price_snapshot, promotion_id, now, now),
            )
        return CartItem(
            cart_item_id=cart_item_id,
            cart_id=cart_id,
            product_id=product_id,
            quantity=quantity,
            unit_price_snapshot=unit_price_snapshot,
            promotion_id=promotion_id,
            created_at=now,
            updated_at=now,
        )

    def update_item_quantity(self, cart_item_id: str, quantity: int) -> None:
        """Overwrite a line item's quantity (used both by an explicit
        quantity update and by merging a duplicate add-to-cart call)."""
        with connection_scope(self._db_path) as connection:
            connection.execute(
                "UPDATE cart_items SET quantity = ?, updated_at = ? WHERE cart_item_id = ?",
                (quantity, _now(), cart_item_id),
            )

    def delete_item(self, cart_item_id: str) -> None:
        """Remove one line item from its cart."""
        with connection_scope(self._db_path) as connection:
            connection.execute("DELETE FROM cart_items WHERE cart_item_id = ?", (cart_item_id,))

    def delete_all_items(self, cart_id: str) -> None:
        """Remove every line item from a cart (clear-cart)."""
        with connection_scope(self._db_path) as connection:
            connection.execute("DELETE FROM cart_items WHERE cart_id = ?", (cart_id,))
