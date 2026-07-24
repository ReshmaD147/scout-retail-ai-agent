-- Scout retail database schema.
--
-- Every statement uses "IF NOT EXISTS" so this script can be executed
-- any number of times without error or data loss. SQLite does not
-- enforce foreign keys by default - every connection that touches
-- this schema must run "PRAGMA foreign_keys = ON" (handled centrally
-- in scout/database/connection.py), not here in the schema itself.

CREATE TABLE IF NOT EXISTS products (
    product_id      TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    brand           TEXT NOT NULL,
    category        TEXT NOT NULL CHECK (category IN ('Footwear', 'Bags', 'Electronics', 'Home and Kitchen')),
    subcategory     TEXT NOT NULL,
    description     TEXT NOT NULL,
    price           REAL NOT NULL CHECK (price >= 0),
    rating          REAL NOT NULL CHECK (rating >= 0 AND rating <= 5),
    review_count    INTEGER NOT NULL DEFAULT 0 CHECK (review_count >= 0),
    attributes_json TEXT NOT NULL DEFAULT '{}',
    image_url       TEXT,
    active          INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_products_category ON products (category);

CREATE TABLE IF NOT EXISTS stores (
    store_id       TEXT PRIMARY KEY,
    store_name     TEXT NOT NULL,
    city           TEXT NOT NULL,
    state          TEXT NOT NULL,
    postal_code    TEXT NOT NULL,
    latitude       REAL NOT NULL,
    longitude      REAL NOT NULL,
    pickup_enabled INTEGER NOT NULL DEFAULT 1 CHECK (pickup_enabled IN (0, 1)),
    active         INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
);

-- Inventory is a separate table from products because a product is one
-- catalog fact (its name, price, description) while its availability is
-- a different fact per store, that changes constantly. Mixing the two
-- would mean either duplicating every product's catalog data once per
-- store, or being unable to represent a product carried at zero, one,
-- or many stores.
CREATE TABLE IF NOT EXISTS inventory (
    product_id           TEXT NOT NULL REFERENCES products (product_id) ON DELETE CASCADE,
    store_id             TEXT NOT NULL REFERENCES stores (store_id) ON DELETE CASCADE,
    quantity_available    INTEGER NOT NULL DEFAULT 0 CHECK (quantity_available >= 0),
    quantity_reserved     INTEGER NOT NULL DEFAULT 0 CHECK (quantity_reserved >= 0),
    pickup_ready_minutes  INTEGER,
    restock_date          TEXT,
    updated_at            TEXT NOT NULL,
    PRIMARY KEY (product_id, store_id)
);

CREATE INDEX IF NOT EXISTS idx_inventory_store ON inventory (store_id);
CREATE INDEX IF NOT EXISTS idx_inventory_product ON inventory (product_id);

-- Promotions store the raw facts of a discount (label, percent or
-- amount, date range, and a manual on/off flag). Whether a promotion is
-- currently valid - active flag AND today's date within range - and
-- what the final price becomes is deliberately NOT computed here. That
-- calculation belongs in the service layer (a later phase), so pricing
-- logic lives in one deterministic place instead of being duplicated
-- across seed data and application code.
CREATE TABLE IF NOT EXISTS promotions (
    promotion_id     TEXT PRIMARY KEY,
    product_id       TEXT NOT NULL REFERENCES products (product_id) ON DELETE CASCADE,
    label            TEXT NOT NULL,
    discount_percent REAL CHECK (discount_percent IS NULL OR (discount_percent >= 0 AND discount_percent <= 100)),
    discount_amount  REAL CHECK (discount_amount IS NULL OR discount_amount >= 0),
    start_date       TEXT NOT NULL,
    end_date         TEXT NOT NULL,
    active           INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
);

CREATE INDEX IF NOT EXISTS idx_promotions_product ON promotions (product_id);

-- Step 15: cart and fulfillment selection.
--
-- A cart is deliberately its own table, not a field on some larger
-- "session" record: a session can have exactly one *active* cart at a
-- time (enforced below by a partial unique index), but its identity
-- (cart_id) is stable even as items, fulfillment choice, and status
-- change - the same reason `inventory` is its own table instead of a
-- column on `products` (see the comment above). fulfillment_type/
-- store_id are nullable because a brand-new cart has not chosen either
-- yet; both are set together, deterministically, by
-- scout/services/cart_service.py, never guessed by a model.
CREATE TABLE IF NOT EXISTS carts (
    cart_id          TEXT PRIMARY KEY,
    session_id       TEXT NOT NULL,
    customer_id      TEXT,
    fulfillment_type TEXT CHECK (fulfillment_type IS NULL OR fulfillment_type IN ('pickup', 'delivery')),
    store_id         TEXT REFERENCES stores (store_id),
    status           TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'abandoned', 'converted')),
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_carts_session ON carts (session_id);

-- A session may have many carts over time (abandoned/converted ones
-- pile up), but never more than one *active* one - this partial
-- unique index is the single source of truth for "carts are isolated
-- by session," enforced by SQLite itself rather than only by
-- application code that a future bug could bypass.
CREATE UNIQUE INDEX IF NOT EXISTS idx_carts_one_active_per_session
    ON carts (session_id) WHERE status = 'active';

-- unit_price_snapshot records the price at the moment a product was
-- added - kept purely as an audit/"price changed since you added this"
-- signal for the customer. It is NEVER treated as the source of truth
-- for what the customer owes: every cart read re-fetches the product's
-- CURRENT price and CURRENT promotions (scout/services/promotion_service.py)
-- and recomputes the line total from those, exactly per this phase's
-- instruction to "always revalidate the current database price before
-- checkout." promotion_id is similarly a snapshot of which promotion
-- applied at add-time, not a claim that it still applies.
CREATE TABLE IF NOT EXISTS cart_items (
    cart_item_id         TEXT PRIMARY KEY,
    cart_id              TEXT NOT NULL REFERENCES carts (cart_id) ON DELETE CASCADE,
    product_id           TEXT NOT NULL REFERENCES products (product_id),
    quantity              INTEGER NOT NULL CHECK (quantity > 0),
    unit_price_snapshot   REAL NOT NULL CHECK (unit_price_snapshot >= 0),
    promotion_id          TEXT REFERENCES promotions (promotion_id),
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL,
    UNIQUE (cart_id, product_id)
);

CREATE INDEX IF NOT EXISTS idx_cart_items_cart ON cart_items (cart_id);

-- Saved products are deterministic customer preference records. They
-- store only ownership + product_id, never a copied product snapshot;
-- current product details are always re-read from products.
CREATE TABLE IF NOT EXISTS saved_products (
    saved_id    TEXT PRIMARY KEY,
    session_id  TEXT,
    customer_id TEXT,
    product_id  TEXT NOT NULL REFERENCES products (product_id),
    created_at  TEXT NOT NULL,
    CHECK (session_id IS NOT NULL OR customer_id IS NOT NULL)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_saved_products_session_product
    ON saved_products (session_id, product_id)
    WHERE session_id IS NOT NULL AND customer_id IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_saved_products_customer_product
    ON saved_products (customer_id, product_id)
    WHERE customer_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_saved_products_session ON saved_products (session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_saved_products_customer ON saved_products (customer_id, created_at);

-- Step 15 also needs to resolve phrases like "the first product" in a
-- cart command to a real product_id. That reference must be grounded
-- in a *verified* recommendation result, not guessed - so /chat and
-- /chat/stream (scout/api/routes/chat.py) record the ranked product
-- list they already verified for a session here, overwritten on every
-- new chat response for that session. This is intentionally narrow:
-- it holds nothing but "the last product list shown," not preferences,
-- history, or anything else CLAUDE.md reserves for the (future,
-- unbuilt) Phase 18 session-memory system.
CREATE TABLE IF NOT EXISTS session_recommendation_snapshots (
    session_id    TEXT PRIMARY KEY,
    workflow_id   TEXT NOT NULL,
    products_json TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

-- Step 15.5: semantic product search.
--
-- One row per product, holding the vector produced by whichever
-- embedding provider is currently configured (scout/services/
-- embedding_service.py). embedding_json is a JSON-encoded list of
-- floats rather than a SQLite BLOB so it stays human-inspectable and
-- portable across the pure-Python "hashing" provider and a real
-- Ollama-backed model - this table never assumes a fixed vector
-- length. model_name records which provider/model produced the
-- stored vector (e.g. "hashing-v1:256" or "ollama:nomic-embed-text");
-- scout/services/product_search_service.py treats a stored row whose
-- model_name does not match the currently configured provider as
-- stale and recomputes it, so switching providers can never silently
-- compare vectors from two different vector spaces.
-- search_text_hash is a sha256 of the exact text that produced the
-- embedding (scout/services/product_search_text_service.py); a
-- catalog edit that changes a product's name/description/attributes
-- changes this hash, which is also treated as stale - the embedding is
-- "precomputed and reused" (Step 15.5) only for as long as the text it
-- was built from has not changed, never reused blindly forever.
CREATE TABLE IF NOT EXISTS product_embeddings (
    product_id       TEXT PRIMARY KEY REFERENCES products (product_id) ON DELETE CASCADE,
    model_name       TEXT NOT NULL,
    embedding_json   TEXT NOT NULL,
    search_text_hash TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);
-- Step 16: checkout, mock payment, order creation, and inventory reservations.
--
-- Checkout is intentionally separate from carts. A cart remains mutable while
-- shopping; a checkout session is an immutable review snapshot that must be
-- explicitly confirmed. The service revalidates the live cart at confirmation
-- and rejects the operation when the snapshot changed.
CREATE TABLE IF NOT EXISTS checkout_sessions (
    checkout_id              TEXT PRIMARY KEY,
    session_id               TEXT NOT NULL,
    cart_id                  TEXT NOT NULL REFERENCES carts (cart_id),
    status                   TEXT NOT NULL DEFAULT 'review'
                                 CHECK (status IN ('review', 'processing', 'completed', 'failed')),
    fulfillment_type         TEXT NOT NULL CHECK (fulfillment_type IN ('pickup', 'delivery')),
    store_id                 TEXT REFERENCES stores (store_id),
    shipping_address_json    TEXT,
    subtotal                 REAL NOT NULL CHECK (subtotal >= 0),
    discount_total           REAL NOT NULL CHECK (discount_total >= 0),
    merchandise_total        REAL NOT NULL CHECK (merchandise_total >= 0),
    tax_total                REAL NOT NULL CHECK (tax_total >= 0),
    shipping_total           REAL NOT NULL CHECK (shipping_total >= 0),
    total                    REAL NOT NULL CHECK (total >= 0),
    currency                 TEXT NOT NULL,
    review_hash              TEXT NOT NULL,
    review_json              TEXT NOT NULL,
    confirm_idempotency_key  TEXT,
    payment_provider         TEXT,
    payment_intent_id        TEXT,
    payment_status           TEXT CHECK (payment_status IS NULL OR payment_status IN (
                                 'checkout_created', 'payment_requires_action',
                                 'payment_processing', 'payment_succeeded',
                                 'payment_failed', 'payment_canceled',
                                 'order_created', 'order_creation_failed'
                               )),
    created_at               TEXT NOT NULL,
    updated_at               TEXT NOT NULL,
    completed_at             TEXT,
    UNIQUE (session_id, confirm_idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_checkout_sessions_session
    ON checkout_sessions (session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_checkout_sessions_cart
    ON checkout_sessions (cart_id);

-- The prototype uses a deterministic mock payment adapter. No card number,
-- security code, or other sensitive payment credential is stored here.
CREATE TABLE IF NOT EXISTS payments (
    payment_id         TEXT PRIMARY KEY,
    checkout_id        TEXT NOT NULL UNIQUE REFERENCES checkout_sessions (checkout_id),
    provider           TEXT NOT NULL,
    provider_reference TEXT NOT NULL UNIQUE,
    status             TEXT NOT NULL CHECK (status IN ('succeeded', 'failed', 'processing', 'canceled')),
    amount             REAL NOT NULL CHECK (amount >= 0),
    currency           TEXT NOT NULL,
    created_at         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS stripe_webhook_events (
    event_id           TEXT PRIMARY KEY,
    event_type         TEXT NOT NULL,
    checkout_id        TEXT,
    payment_intent_id  TEXT,
    processed_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
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
);

CREATE INDEX IF NOT EXISTS idx_orders_session ON orders (session_id, created_at);

CREATE TABLE IF NOT EXISTS order_items (
    order_item_id       TEXT PRIMARY KEY,
    order_id            TEXT NOT NULL REFERENCES orders (order_id) ON DELETE CASCADE,
    product_id          TEXT NOT NULL REFERENCES products (product_id),
    product_name        TEXT NOT NULL,
    brand               TEXT NOT NULL,
    quantity            INTEGER NOT NULL CHECK (quantity > 0),
    catalog_unit_price  REAL NOT NULL CHECK (catalog_unit_price >= 0),
    charged_unit_price  REAL NOT NULL CHECK (charged_unit_price >= 0),
    line_subtotal       REAL NOT NULL CHECK (line_subtotal >= 0),
    discount_total      REAL NOT NULL CHECK (discount_total >= 0),
    line_total          REAL NOT NULL CHECK (line_total >= 0),
    promotion_id        TEXT REFERENCES promotions (promotion_id),
    promotion_label     TEXT,
    created_at          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_order_items_order ON order_items (order_id);

-- Reservations preserve the exact store allocation used at checkout. For a
-- pickup order, every line is reserved at the selected store. A delivery line
-- may be split across multiple active stores. quantity_available remains the
-- physical on-hand count; quantity_reserved increases, so existing sellable
-- inventory logic (available - reserved) immediately sees the order.
CREATE TABLE IF NOT EXISTS inventory_reservations (
    reservation_id  TEXT PRIMARY KEY,
    order_id        TEXT NOT NULL REFERENCES orders (order_id) ON DELETE CASCADE,
    order_item_id   TEXT NOT NULL REFERENCES order_items (order_item_id) ON DELETE CASCADE,
    product_id      TEXT NOT NULL REFERENCES products (product_id),
    store_id        TEXT NOT NULL REFERENCES stores (store_id),
    quantity        INTEGER NOT NULL CHECK (quantity > 0),
    status          TEXT NOT NULL DEFAULT 'reserved' CHECK (status IN ('reserved')),
    created_at      TEXT NOT NULL,
    UNIQUE (order_item_id, store_id)
);

CREATE INDEX IF NOT EXISTS idx_inventory_reservations_order
    ON inventory_reservations (order_id);
CREATE INDEX IF NOT EXISTS idx_inventory_reservations_inventory
    ON inventory_reservations (product_id, store_id);

-- Step 16.5: mock external merchant offers and affiliate click tracking.
--
-- External offers are deliberately separate from Scout products. They are
-- never added to Scout carts, never used by Scout checkout, and never treated
-- as Scout inventory. They represent a mock merchant feed that is consulted
-- only after every internal fulfillment path has failed.
CREATE TABLE IF NOT EXISTS external_offers (
    offer_id             TEXT PRIMARY KEY,
    merchant_name        TEXT NOT NULL,
    external_product_id  TEXT NOT NULL,
    product_name         TEXT NOT NULL,
    brand                TEXT NOT NULL,
    category             TEXT NOT NULL CHECK (category IN ('Footwear', 'Bags', 'Electronics', 'Home and Kitchen')),
    description          TEXT NOT NULL,
    price                REAL NOT NULL CHECK (price >= 0),
    currency             TEXT NOT NULL DEFAULT 'USD',
    rating               REAL CHECK (rating IS NULL OR (rating >= 0 AND rating <= 5)),
    review_count         INTEGER NOT NULL DEFAULT 0 CHECK (review_count >= 0),
    availability_status  TEXT NOT NULL CHECK (availability_status IN ('in_stock', 'out_of_stock')),
    attributes_json      TEXT NOT NULL DEFAULT '{}',
    image_url            TEXT,
    merchant_url         TEXT NOT NULL,
    upc                  TEXT,
    gtin                 TEXT,
    model_number         TEXT,
    active               INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL,
    UNIQUE (merchant_name, external_product_id)
);

CREATE INDEX IF NOT EXISTS idx_external_offers_category
    ON external_offers (category, active, availability_status);

-- A click record is analytics/audit data only. It never creates an order,
-- changes inventory, or proves a purchase happened. match_type is persisted so
-- the demo can audit whether the customer clicked a clearly labelled exact or
-- similar external result.
CREATE TABLE IF NOT EXISTS affiliate_clicks (
    click_id           TEXT PRIMARY KEY,
    offer_id           TEXT NOT NULL REFERENCES external_offers (offer_id),
    session_id         TEXT NOT NULL,
    workflow_id        TEXT,
    source_product_id  TEXT REFERENCES products (product_id),
    match_type         TEXT NOT NULL CHECK (match_type IN ('exact', 'similar')),
    clicked_at         TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_affiliate_clicks_offer
    ON affiliate_clicks (offer_id, clicked_at);
CREATE INDEX IF NOT EXISTS idx_affiliate_clicks_session
    ON affiliate_clicks (session_id, clicked_at);

-- Step 17: read-only order status and fulfillment tracking.
--
-- `orders` and `order_items` remain the immutable purchase record created by
-- Step 16. This table holds the fulfillment lifecycle facts that can change
-- after checkout (processing, ready for pickup, shipped, delivered, picked up)
-- without rewriting the original order totals or item snapshots. Step 17 only
-- reads these records; no cancellation, return, exchange, or refund write is
-- implemented.
CREATE TABLE IF NOT EXISTS order_fulfillments (
    order_id               TEXT PRIMARY KEY REFERENCES orders (order_id) ON DELETE CASCADE,
    fulfillment_status     TEXT NOT NULL DEFAULT 'processing'
                               CHECK (fulfillment_status IN (
                                   'processing', 'ready_for_pickup', 'shipped',
                                   'delivered', 'picked_up'
                               )),
    carrier_name           TEXT,
    tracking_number        TEXT,
    tracking_url           TEXT,
    estimated_ready_at     TEXT,
    estimated_delivery_at  TEXT,
    shipped_at             TEXT,
    delivered_at           TEXT,
    picked_up_at           TEXT,
    updated_at             TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_order_fulfillments_tracking
    ON order_fulfillments (tracking_number);

-- Step 6 support escalation, conversation logging, and verification audit.
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
);
CREATE INDEX IF NOT EXISTS idx_support_cases_session ON support_cases (session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_support_cases_order ON support_cases (order_id, created_at);

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
);
CREATE INDEX IF NOT EXISTS idx_conversation_logs_session ON conversation_logs (session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_conversation_logs_workflow ON conversation_logs (workflow_id);

CREATE TABLE IF NOT EXISTS support_audit_records (
    audit_id             TEXT PRIMARY KEY,
    workflow_id          TEXT NOT NULL,
    session_id           TEXT NOT NULL,
    case_reference       TEXT,
    evidence_json        TEXT NOT NULL,
    verification_json    TEXT NOT NULL,
    created_at           TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_support_audit_workflow ON support_audit_records (workflow_id);
CREATE INDEX IF NOT EXISTS idx_support_audit_session ON support_audit_records (session_id, created_at);

-- Step 17 protected-action confirmation ledger.
--
-- These tables store proposals and deterministic execution results for
-- sensitive actions that must never be executed by autonomous agents. A row in
-- protected_action_confirmations is only a proposal until its status reaches a
-- terminal execution state; request rows record reviewable non-payment support
-- requests and are not proof that a refund/return/exchange was approved.
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
);
CREATE INDEX IF NOT EXISTS idx_protected_actions_session
    ON protected_action_confirmations (session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_protected_actions_workflow
    ON protected_action_confirmations (workflow_id);

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
);
CREATE INDEX IF NOT EXISTS idx_protected_action_requests_order
    ON protected_action_requests (order_id, created_at);

CREATE TABLE IF NOT EXISTS protected_action_audit_events (
    event_id         TEXT PRIMARY KEY,
    confirmation_id  TEXT,
    workflow_id      TEXT,
    session_id       TEXT NOT NULL,
    customer_id      TEXT,
    event_type       TEXT NOT NULL,
    detail_json      TEXT NOT NULL,
    created_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_protected_action_audit_confirmation
    ON protected_action_audit_events (confirmation_id, created_at);

-- Step 18 memory boundaries.
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
);
CREATE INDEX IF NOT EXISTS idx_workflow_memory_session ON workflow_memory (session_id, updated_at);

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
);
CREATE INDEX IF NOT EXISTS idx_session_memory_customer ON session_memory (customer_id, updated_at);

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
);
CREATE INDEX IF NOT EXISTS idx_durable_preferences_customer ON durable_preferences (customer_id, status, updated_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_durable_preferences_unique_active
    ON durable_preferences (customer_id, type, value)
    WHERE status = 'active';

CREATE TABLE IF NOT EXISTS memory_controls (
    customer_id       TEXT PRIMARY KEY,
    memory_enabled    INTEGER NOT NULL CHECK (memory_enabled IN (0, 1)),
    updated_at        TEXT NOT NULL
);
