"""Persistence boundary for Step 16 checkout and order creation.

Only this module executes SQL for checkout_sessions, payments, orders,
order_items, inventory_reservations, and the atomic inventory/cart writes
that complete an order. The service layer prepares a fully validated commit
plan; this repository persists it in one SQLite transaction and performs the
last concurrency-safe inventory guards.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

from scout.database.connection import connection_scope
from scout.database.initialize import apply_lightweight_migrations
from scout.repositories.models import (
    CheckoutSessionRecord,
    InventoryReservationRecord,
    OrderItemRecord,
    OrderRecord,
    PaymentRecord,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CheckoutRepositoryConflict(Exception):
    """A safe concurrency/persistence conflict detected inside the transaction."""

    def __init__(self, error_type: str, message: str) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.message = message


@dataclass(frozen=True)
class CheckoutSessionWrite:
    checkout_id: str
    session_id: str
    cart_id: str
    fulfillment_type: str
    store_id: Optional[str]
    shipping_address_json: Optional[str]
    subtotal: float
    discount_total: float
    merchandise_total: float
    tax_total: float
    shipping_total: float
    total: float
    currency: str
    review_hash: str
    review_json: str


@dataclass(frozen=True)
class PaymentWrite:
    payment_id: str
    provider: str
    provider_reference: str
    status: str
    amount: float
    currency: str


@dataclass(frozen=True)
class OrderItemWrite:
    order_item_id: str
    product_id: str
    product_name: str
    brand: str
    quantity: int
    catalog_unit_price: float
    charged_unit_price: float
    line_subtotal: float
    discount_total: float
    line_total: float
    promotion_id: Optional[str]
    promotion_label: Optional[str]


@dataclass(frozen=True)
class ReservationWrite:
    reservation_id: str
    order_item_id: str
    product_id: str
    store_id: str
    quantity: int


@dataclass(frozen=True)
class CheckoutCommitPlan:
    checkout_id: str
    session_id: str
    cart_id: str
    idempotency_key: str
    order_id: str
    payment: PaymentWrite
    fulfillment_type: str
    store_id: Optional[str]
    shipping_address_json: Optional[str]
    subtotal: float
    discount_total: float
    merchandise_total: float
    tax_total: float
    shipping_total: float
    total: float
    currency: str
    estimated_ready_at: Optional[str]
    estimated_delivery_at: Optional[str]
    items: List[OrderItemWrite]
    reservations: List[ReservationWrite]


@dataclass(frozen=True)
class IdempotencyLookup:
    checkout_id: str
    status: str
    order_id: Optional[str]


@dataclass(frozen=True)
class PaymentIntentSession:
    checkout_id: str
    session_id: str
    payment_intent_id: str
    payment_status: str
    total: float
    currency: str


class CheckoutRepository:
    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db_path = db_path

    def _ensure_schema(self) -> None:
        with connection_scope(self._db_path) as connection:
            apply_lightweight_migrations(connection)

    def create_session(self, write: CheckoutSessionWrite) -> CheckoutSessionRecord:
        self._ensure_schema()
        now = _now()
        with connection_scope(self._db_path) as connection:
            connection.execute(
                """
                INSERT INTO checkout_sessions (
                    checkout_id, session_id, cart_id, status, fulfillment_type,
                    store_id, shipping_address_json, subtotal, discount_total,
                    merchandise_total, tax_total, shipping_total, total, currency,
                    review_hash, review_json, confirm_idempotency_key,
                    payment_provider, payment_intent_id, payment_status,
                    created_at, updated_at, completed_at
                ) VALUES (?, ?, ?, 'review', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, 'checkout_created', ?, ?, NULL)
                """,
                (
                    write.checkout_id,
                    write.session_id,
                    write.cart_id,
                    write.fulfillment_type,
                    write.store_id,
                    write.shipping_address_json,
                    write.subtotal,
                    write.discount_total,
                    write.merchandise_total,
                    write.tax_total,
                    write.shipping_total,
                    write.total,
                    write.currency,
                    write.review_hash,
                    write.review_json,
                    now,
                    now,
                ),
            )
        created = self.get_session(write.checkout_id)
        if created is None:  # defensive: the INSERT above either succeeded or raised
            raise RuntimeError("checkout session was not persisted")
        return created

    def get_session(self, checkout_id: str) -> Optional[CheckoutSessionRecord]:
        with connection_scope(self._db_path) as connection:
            row = connection.execute(
                "SELECT * FROM checkout_sessions WHERE checkout_id = ?", (checkout_id,)
            ).fetchone()
        return CheckoutSessionRecord.from_row(row) if row is not None else None

    def get_by_payment_intent(self, payment_intent_id: str) -> Optional[PaymentIntentSession]:
        with connection_scope(self._db_path) as connection:
            row = connection.execute(
                """
                SELECT checkout_id, session_id, payment_intent_id, payment_status, total, currency
                FROM checkout_sessions
                WHERE payment_intent_id = ?
                """,
                (payment_intent_id,),
            ).fetchone()
        if row is None:
            return None
        return PaymentIntentSession(**dict(row))

    def attach_payment_intent(
        self,
        *,
        checkout_id: str,
        session_id: str,
        provider: str,
        payment_intent_id: str,
        payment_status: str,
        idempotency_key: str,
    ) -> None:
        now = _now()
        with connection_scope(self._db_path) as connection:
            updated = connection.execute(
                """
                UPDATE checkout_sessions
                SET status = 'processing',
                    payment_provider = ?,
                    payment_intent_id = ?,
                    payment_status = ?,
                    confirm_idempotency_key = ?,
                    updated_at = ?
                WHERE checkout_id = ?
                  AND session_id = ?
                  AND status IN ('review', 'processing')
                  AND (payment_intent_id IS NULL OR payment_intent_id = ?)
                """,
                (
                    provider,
                    payment_intent_id,
                    payment_status,
                    idempotency_key,
                    now,
                    checkout_id,
                    session_id,
                    payment_intent_id,
                ),
            )
            if updated.rowcount != 1:
                raise CheckoutRepositoryConflict(
                    "checkout_not_confirmable",
                    "This checkout is not available for payment.",
                )

    def update_payment_status(self, checkout_id: str, payment_status: str) -> None:
        with connection_scope(self._db_path) as connection:
            connection.execute(
                """
                UPDATE checkout_sessions
                SET payment_status = ?, updated_at = ?
                WHERE checkout_id = ?
                """,
                (payment_status, _now(), checkout_id),
            )

    def has_processed_webhook_event(self, event_id: str) -> bool:
        with connection_scope(self._db_path) as connection:
            row = connection.execute(
                "SELECT 1 FROM stripe_webhook_events WHERE event_id = ?",
                (event_id,),
            ).fetchone()
        return row is not None

    def record_webhook_event(
        self,
        *,
        event_id: str,
        event_type: str,
        checkout_id: Optional[str],
        payment_intent_id: Optional[str],
    ) -> None:
        with connection_scope(self._db_path) as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO stripe_webhook_events (
                    event_id, event_type, checkout_id, payment_intent_id, processed_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (event_id, event_type, checkout_id, payment_intent_id, _now()),
            )

    def find_idempotency(self, session_id: str, idempotency_key: str) -> Optional[IdempotencyLookup]:
        with connection_scope(self._db_path) as connection:
            row = connection.execute(
                """
                SELECT cs.checkout_id, cs.status, o.order_id
                FROM checkout_sessions cs
                LEFT JOIN orders o ON o.checkout_id = cs.checkout_id
                WHERE cs.session_id = ? AND cs.confirm_idempotency_key = ?
                """,
                (session_id, idempotency_key),
            ).fetchone()
        if row is None:
            return None
        return IdempotencyLookup(
            checkout_id=row["checkout_id"], status=row["status"], order_id=row["order_id"]
        )

    def get_order(self, order_id: str) -> Optional[OrderRecord]:
        with connection_scope(self._db_path) as connection:
            row = connection.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
        return OrderRecord.from_row(row) if row is not None else None

    def get_order_by_checkout(self, checkout_id: str) -> Optional[OrderRecord]:
        with connection_scope(self._db_path) as connection:
            row = connection.execute(
                "SELECT * FROM orders WHERE checkout_id = ?", (checkout_id,)
            ).fetchone()
        return OrderRecord.from_row(row) if row is not None else None

    def get_payment_for_order(self, order_id: str) -> Optional[PaymentRecord]:
        with connection_scope(self._db_path) as connection:
            row = connection.execute(
                """
                SELECT p.*
                FROM payments p
                JOIN orders o ON o.payment_id = p.payment_id
                WHERE o.order_id = ?
                """,
                (order_id,),
            ).fetchone()
        return PaymentRecord.from_row(row) if row is not None else None

    def list_order_items(self, order_id: str) -> List[OrderItemRecord]:
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

    def commit_checkout(self, plan: CheckoutCommitPlan) -> None:
        """Persist one confirmed order and reserve inventory atomically.

        The conditional inventory UPDATE is the final race-condition guard:
        even if another request reserved stock after the service built its
        plan, no row can be over-reserved. Any failed line raises and rolls
        back the payment/order/cart writes together.
        """
        now = _now()
        try:
            with connection_scope(self._db_path) as connection:
                connection.execute("BEGIN IMMEDIATE")

                session_row = connection.execute(
                    "SELECT * FROM checkout_sessions WHERE checkout_id = ? AND session_id = ?",
                    (plan.checkout_id, plan.session_id),
                ).fetchone()
                if session_row is None:
                    raise CheckoutRepositoryConflict(
                        "checkout_not_found", "No checkout session was found for this customer session."
                    )
                if session_row["status"] not in {"review", "processing"}:
                    raise CheckoutRepositoryConflict(
                        "checkout_not_confirmable", "This checkout is no longer available for confirmation."
                    )

                connection.execute(
                    """
                    UPDATE checkout_sessions
                    SET status = 'processing', confirm_idempotency_key = ?, updated_at = ?
                    WHERE checkout_id = ? AND status IN ('review', 'processing')
                    """,
                    (plan.idempotency_key, now, plan.checkout_id),
                )

                connection.execute(
                    """
                    INSERT INTO payments (
                        payment_id, checkout_id, provider, provider_reference,
                        status, amount, currency, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        plan.payment.payment_id,
                        plan.checkout_id,
                        plan.payment.provider,
                        plan.payment.provider_reference,
                        plan.payment.status,
                        plan.payment.amount,
                        plan.payment.currency,
                        now,
                    ),
                )

                connection.execute(
                    """
                    INSERT INTO orders (
                        order_id, checkout_id, session_id, cart_id, payment_id,
                        status, fulfillment_type, store_id, shipping_address_json,
                        subtotal, discount_total, merchandise_total, tax_total,
                        shipping_total, total, currency, created_at
                    ) VALUES (?, ?, ?, ?, ?, 'confirmed', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        plan.order_id,
                        plan.checkout_id,
                        plan.session_id,
                        plan.cart_id,
                        plan.payment.payment_id,
                        plan.fulfillment_type,
                        plan.store_id,
                        plan.shipping_address_json,
                        plan.subtotal,
                        plan.discount_total,
                        plan.merchandise_total,
                        plan.tax_total,
                        plan.shipping_total,
                        plan.total,
                        plan.currency,
                        now,
                    ),
                )

                connection.execute(
                    """
                    INSERT INTO order_fulfillments (
                        order_id, fulfillment_status, carrier_name, tracking_number,
                        tracking_url, estimated_ready_at, estimated_delivery_at,
                        shipped_at, delivered_at, picked_up_at, updated_at
                    ) VALUES (?, 'processing', NULL, NULL, NULL, ?, ?, NULL, NULL, NULL, ?)
                    """,
                    (
                        plan.order_id,
                        plan.estimated_ready_at,
                        plan.estimated_delivery_at,
                        now,
                    ),
                )

                for item in plan.items:
                    connection.execute(
                        """
                        INSERT INTO order_items (
                            order_item_id, order_id, product_id, product_name,
                            brand, quantity, catalog_unit_price, charged_unit_price,
                            line_subtotal, discount_total, line_total,
                            promotion_id, promotion_label, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            item.order_item_id,
                            plan.order_id,
                            item.product_id,
                            item.product_name,
                            item.brand,
                            item.quantity,
                            item.catalog_unit_price,
                            item.charged_unit_price,
                            item.line_subtotal,
                            item.discount_total,
                            item.line_total,
                            item.promotion_id,
                            item.promotion_label,
                            now,
                        ),
                    )

                for reservation in plan.reservations:
                    updated = connection.execute(
                        """
                        UPDATE inventory
                        SET quantity_reserved = quantity_reserved + ?, updated_at = ?
                        WHERE product_id = ? AND store_id = ?
                          AND (quantity_available - quantity_reserved) >= ?
                        """,
                        (
                            reservation.quantity,
                            now,
                            reservation.product_id,
                            reservation.store_id,
                            reservation.quantity,
                        ),
                    )
                    if updated.rowcount != 1:
                        raise CheckoutRepositoryConflict(
                            "inventory_changed",
                            "Inventory changed before the order could be reserved. Please review the cart again.",
                        )
                    connection.execute(
                        """
                        INSERT INTO inventory_reservations (
                            reservation_id, order_id, order_item_id, product_id,
                            store_id, quantity, status, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, 'reserved', ?)
                        """,
                        (
                            reservation.reservation_id,
                            plan.order_id,
                            reservation.order_item_id,
                            reservation.product_id,
                            reservation.store_id,
                            reservation.quantity,
                            now,
                        ),
                    )

                converted = connection.execute(
                    """
                    UPDATE carts
                    SET status = 'converted', updated_at = ?
                    WHERE cart_id = ? AND session_id = ? AND status = 'active'
                    """,
                    (now, plan.cart_id, plan.session_id),
                )
                if converted.rowcount != 1:
                    raise CheckoutRepositoryConflict(
                        "cart_changed", "The cart changed before checkout completed. Please review it again."
                    )

                connection.execute(
                    """
                    UPDATE checkout_sessions
                    SET status = 'completed', payment_status = 'order_created', updated_at = ?, completed_at = ?
                    WHERE checkout_id = ?
                    """,
                    (now, now, plan.checkout_id),
                )
        except sqlite3.IntegrityError as exc:
            # Most commonly the per-session idempotency key was already used
            # by another checkout request. Never expose raw SQLite text.
            if "checkout_sessions.session_id" in str(exc) and "confirm_idempotency_key" in str(exc):
                raise CheckoutRepositoryConflict(
                    "idempotency_conflict",
                    "That confirmation key has already been used for another checkout.",
                ) from exc
            raise CheckoutRepositoryConflict(
                "checkout_persistence_conflict",
                "Checkout could not be saved safely. No order was completed.",
            ) from exc
