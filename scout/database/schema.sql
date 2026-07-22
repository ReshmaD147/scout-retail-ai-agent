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
    status             TEXT NOT NULL CHECK (status IN ('succeeded', 'failed')),
    amount             REAL NOT NULL CHECK (amount >= 0),
    currency           TEXT NOT NULL,
    created_at         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    order_id               TEXT PRIMARY KEY,
    checkout_id            TEXT NOT NULL UNIQUE REFERENCES checkout_sessions (checkout_id),
    session_id             TEXT NOT NULL,
    cart_id                TEXT NOT NULL REFERENCES carts (cart_id),
    payment_id             TEXT NOT NULL UNIQUE REFERENCES payments (payment_id),
    status                 TEXT NOT NULL CHECK (status IN ('confirmed')),
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
