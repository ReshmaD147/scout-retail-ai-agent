"""Checkout repository migration and persistence tests."""

import sqlite3

from scout.repositories.checkout_repository import CheckoutRepository, CheckoutSessionWrite


def test_create_session_migrates_old_checkout_schema(tmp_path):
    db_path = str(tmp_path / "old_checkout.db")
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE checkout_sessions (
                checkout_id              TEXT PRIMARY KEY,
                session_id               TEXT NOT NULL,
                cart_id                  TEXT NOT NULL,
                status                   TEXT NOT NULL DEFAULT 'review',
                fulfillment_type         TEXT NOT NULL,
                store_id                 TEXT,
                shipping_address_json    TEXT,
                subtotal                 REAL NOT NULL,
                discount_total           REAL NOT NULL,
                merchandise_total        REAL NOT NULL,
                tax_total                REAL NOT NULL,
                shipping_total           REAL NOT NULL,
                total                    REAL NOT NULL,
                currency                 TEXT NOT NULL,
                review_hash              TEXT NOT NULL,
                review_json              TEXT NOT NULL,
                confirm_idempotency_key  TEXT,
                created_at               TEXT NOT NULL,
                updated_at               TEXT NOT NULL,
                completed_at             TEXT
            )
            """
        )

    created = CheckoutRepository(db_path).create_session(
        CheckoutSessionWrite(
            checkout_id="CHK-OLD",
            session_id="SESSION-OLD",
            cart_id="CART-OLD",
            fulfillment_type="pickup",
            store_id="STR-001",
            shipping_address_json=None,
            subtotal=10.0,
            discount_total=0.0,
            merchandise_total=10.0,
            tax_total=0.8,
            shipping_total=0.0,
            total=10.8,
            currency="USD",
            review_hash="hash",
            review_json='{"checkout_id":"CHK-OLD","status":"review"}',
        )
    )

    assert created.payment_provider is None
    assert created.payment_intent_id is None
    assert created.payment_status == "checkout_created"
    with sqlite3.connect(db_path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(checkout_sessions)")}
        webhook_table = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'stripe_webhook_events'"
        ).fetchone()
    assert {"payment_provider", "payment_intent_id", "payment_status"} <= columns
    assert webhook_table is not None
