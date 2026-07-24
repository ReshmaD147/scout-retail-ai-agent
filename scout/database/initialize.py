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


def _table_sql(connection, table_name: str) -> str:
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row["sql"] if row and row["sql"] else ""


def _migrate_orders_status_constraint(connection) -> None:
    sql = _table_sql(connection, "orders")
    if "status IN ('confirmed')" not in sql:
        return
    connection.execute("PRAGMA foreign_keys=OFF")
    connection.execute("ALTER TABLE orders RENAME TO orders_old_status_constraint")
    connection.execute(
        """
        CREATE TABLE orders (
            order_id               TEXT PRIMARY KEY,
            checkout_id            TEXT NOT NULL UNIQUE REFERENCES checkout_sessions (checkout_id),
            session_id             TEXT NOT NULL,
            cart_id                TEXT NOT NULL REFERENCES carts (cart_id),
            payment_id             TEXT NOT NULL UNIQUE REFERENCES payments (payment_id),
            status                 TEXT NOT NULL CHECK (status IN ('confirmed', 'canceled')),
            fulfillment_type       TEXT NOT NULL CHECK (fulfillment_type IN ('pickup', 'delivery')),
            store_id               TEXT REFERENCES stores (store_id),
            shipping_address_json  TEXT,
            subtotal               REAL NOT NULL CHECK (subtotal >= 0),
            discount_total         REAL NOT NULL CHECK (discount_total >= 0),
            merchandise_total      REAL NOT NULL CHECK (merchandise_total >= 0),
            tax_total              REAL NOT NULL CHECK (tax_total >= 0),
            shipping_total         REAL NOT NULL CHECK (shipping_total >= 0),
            total                  REAL NOT NULL CHECK (total >= 0),
            currency               TEXT NOT NULL,
            created_at             TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        INSERT INTO orders (
            order_id, checkout_id, session_id, cart_id, payment_id, status,
            fulfillment_type, store_id, shipping_address_json, subtotal,
            discount_total, merchandise_total, tax_total, shipping_total,
            total, currency, created_at
        )
        SELECT order_id, checkout_id, session_id, cart_id, payment_id, status,
               fulfillment_type, store_id, shipping_address_json, subtotal,
               discount_total, merchandise_total, tax_total, shipping_total,
               total, currency, created_at
        FROM orders_old_status_constraint
        """
    )
    connection.execute("DROP TABLE orders_old_status_constraint")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_orders_session ON orders (session_id, created_at)")
    connection.execute("PRAGMA foreign_keys=ON")


def apply_lightweight_migrations(connection) -> None:
    _migrate_orders_status_constraint(connection)
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
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS saved_products (
            saved_id    TEXT PRIMARY KEY,
            session_id  TEXT,
            customer_id TEXT,
            product_id  TEXT NOT NULL REFERENCES products (product_id),
            created_at  TEXT NOT NULL,
            CHECK (session_id IS NOT NULL OR customer_id IS NOT NULL)
        )
        """
    )
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_saved_products_session_product
            ON saved_products (session_id, product_id)
            WHERE session_id IS NOT NULL AND customer_id IS NULL
        """
    )
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_saved_products_customer_product
            ON saved_products (customer_id, product_id)
            WHERE customer_id IS NOT NULL
        """
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_saved_products_session ON saved_products (session_id, created_at)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_saved_products_customer ON saved_products (customer_id, created_at)")

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS support_cases (
            case_id              TEXT PRIMARY KEY,
            case_reference       TEXT NOT NULL UNIQUE,
            session_id           TEXT NOT NULL,
            workflow_id          TEXT,
            order_id             TEXT,
            category             TEXT NOT NULL,
            sentiment            TEXT NOT NULL CHECK (sentiment IN ('positive', 'neutral', 'negative')),
            risk_level           TEXT NOT NULL CHECK (risk_level IN ('low', 'medium', 'high')),
            status               TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')),
            summary              TEXT NOT NULL,
            created_at           TEXT NOT NULL,
            updated_at           TEXT NOT NULL
        )
        """
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_support_cases_session ON support_cases (session_id, created_at)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_support_cases_order ON support_cases (order_id, created_at)")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS conversation_logs (
            log_id               TEXT PRIMARY KEY,
            workflow_id          TEXT NOT NULL,
            session_id           TEXT NOT NULL,
            user_message         TEXT NOT NULL,
            assistant_response   TEXT,
            status               TEXT NOT NULL,
            message_type         TEXT,
            case_reference       TEXT,
            sentiment            TEXT NOT NULL CHECK (sentiment IN ('positive', 'neutral', 'negative')),
            risk_level           TEXT NOT NULL CHECK (risk_level IN ('low', 'medium', 'high')),
            created_at           TEXT NOT NULL
        )
        """
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_conversation_logs_session ON conversation_logs (session_id, created_at)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_conversation_logs_workflow ON conversation_logs (workflow_id)")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS support_audit_records (
            audit_id             TEXT PRIMARY KEY,
            workflow_id          TEXT NOT NULL,
            session_id           TEXT NOT NULL,
            case_reference       TEXT,
            evidence_json        TEXT NOT NULL,
            verification_json    TEXT NOT NULL,
            created_at           TEXT NOT NULL
        )
        """
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_support_audit_workflow ON support_audit_records (workflow_id)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_support_audit_session ON support_audit_records (session_id, created_at)")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS protected_action_confirmations (
            confirmation_id       TEXT PRIMARY KEY,
            workflow_id           TEXT NOT NULL,
            request_id            TEXT NOT NULL,
            session_id            TEXT NOT NULL,
            customer_id           TEXT NOT NULL,
            action_type           TEXT NOT NULL CHECK (action_type IN (
                'cancel_order',
                'create_return_request',
                'create_exchange_request',
                'change_order_address',
                'create_refund_request',
                'start_protected_payment_handoff'
            )),
            resource_type         TEXT NOT NULL,
            resource_id           TEXT NOT NULL,
            proposal_summary      TEXT NOT NULL,
            customer_effects_json TEXT NOT NULL,
            financial_effects_json TEXT NOT NULL,
            eligibility_status    TEXT NOT NULL,
            eligibility_reason_code TEXT NOT NULL,
            policy_ids_json       TEXT NOT NULL,
            evidence_ids_json     TEXT NOT NULL,
            payload_hash          TEXT NOT NULL,
            idempotency_key       TEXT NOT NULL UNIQUE,
            status                TEXT NOT NULL CHECK (status IN (
                'requested',
                'proposed',
                'awaiting_confirmation',
                'approved',
                'rejected',
                'executing',
                'executed',
                'verified',
                'failed',
                'expired'
            )),
            result_json           TEXT,
            created_at            TEXT NOT NULL,
            expires_at            TEXT NOT NULL,
            consumed_at           TEXT,
            updated_at            TEXT NOT NULL
        )
        """
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_protected_actions_session ON protected_action_confirmations (session_id, created_at)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_protected_actions_workflow ON protected_action_confirmations (workflow_id)")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS protected_action_requests (
            request_id       TEXT PRIMARY KEY,
            confirmation_id  TEXT NOT NULL REFERENCES protected_action_confirmations (confirmation_id),
            action_type      TEXT NOT NULL,
            order_id         TEXT NOT NULL,
            order_item_id    TEXT,
            status           TEXT NOT NULL,
            reason           TEXT,
            payload_json     TEXT NOT NULL,
            created_at       TEXT NOT NULL,
            updated_at       TEXT NOT NULL
        )
        """
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_protected_action_requests_order ON protected_action_requests (order_id, created_at)")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS protected_action_audit_events (
            event_id         TEXT PRIMARY KEY,
            confirmation_id  TEXT,
            workflow_id      TEXT,
            session_id       TEXT NOT NULL,
            customer_id      TEXT,
            event_type       TEXT NOT NULL,
            detail_json      TEXT NOT NULL,
            created_at       TEXT NOT NULL
        )
        """
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_protected_action_audit_confirmation ON protected_action_audit_events (confirmation_id, created_at)")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_memory (
            workflow_id         TEXT PRIMARY KEY,
            session_id          TEXT NOT NULL,
            customer_id         TEXT,
            current_query       TEXT NOT NULL,
            structured_intent_json TEXT,
            current_plan_json   TEXT NOT NULL,
            completed_steps_json TEXT NOT NULL,
            remaining_steps_json TEXT NOT NULL,
            tool_result_refs_json TEXT NOT NULL,
            evidence_ids_json   TEXT NOT NULL,
            selected_products_json TEXT NOT NULL,
            errors_json         TEXT NOT NULL,
            retry_state_json    TEXT NOT NULL,
            verification_status TEXT,
            status              TEXT NOT NULL CHECK (status IN ('active', 'completed', 'expired')),
            created_at          TEXT NOT NULL,
            updated_at          TEXT NOT NULL,
            expires_at          TEXT
        )
        """
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_workflow_memory_session ON workflow_memory (session_id, updated_at)")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS session_memory (
            session_id              TEXT PRIMARY KEY,
            customer_id             TEXT,
            viewed_products_json    TEXT NOT NULL,
            rejected_products_json  TEXT NOT NULL,
            recommended_products_json TEXT NOT NULL,
            current_budget          REAL,
            selected_store_id       TEXT,
            fulfillment_preference  TEXT,
            comparison_set_json     TEXT NOT NULL,
            current_policy_topic    TEXT,
            authorized_order_ref    TEXT,
            memory_disabled         INTEGER NOT NULL DEFAULT 0 CHECK (memory_disabled IN (0, 1)),
            created_at              TEXT NOT NULL,
            updated_at              TEXT NOT NULL,
            expires_at              TEXT NOT NULL
        )
        """
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_session_memory_customer ON session_memory (customer_id, updated_at)")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS durable_preferences (
            preference_id      TEXT PRIMARY KEY,
            customer_id        TEXT NOT NULL,
            type               TEXT NOT NULL,
            value              TEXT NOT NULL,
            confidence         REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
            source             TEXT NOT NULL CHECK (source IN ('explicit', 'customer_confirmed', 'inferred')),
            status             TEXT NOT NULL CHECK (status IN ('active', 'deleted', 'disabled')),
            created_at         TEXT NOT NULL,
            updated_at         TEXT NOT NULL,
            last_confirmed_at  TEXT,
            expires_at         TEXT
        )
        """
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_durable_preferences_customer ON durable_preferences (customer_id, status, updated_at)")
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_durable_preferences_unique_active
            ON durable_preferences (customer_id, type, value)
            WHERE status = 'active'
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_controls (
            customer_id       TEXT PRIMARY KEY,
            memory_enabled    INTEGER NOT NULL CHECK (memory_enabled IN (0, 1)),
            updated_at        TEXT NOT NULL
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
