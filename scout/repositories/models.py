"""Domain models returned by the repository layer.

Repositories never hand back a raw sqlite3.Row or a dict - every method
converts rows into one of these typed Pydantic models before returning.
That gives every caller (services, agents, API routes, tests) a single,
documented shape to depend on instead of column names scattered through
the codebase.

Each model has a from_row() classmethod that does that conversion in
one place, right next to the model it builds.
"""

import json
import sqlite3
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class Product(BaseModel):
    """One row from the products table.

    rating is typed Optional even though the current database column is
    NOT NULL (every seeded product has one). The service layer (Step 4)
    needs to rank and filter products that may not have a rating yet -
    for example a newly added product with no reviews - without
    guessing a value, so the domain model allows None here rather than
    forcing every future caller to fabricate a fake rating just to
    satisfy the type.
    """

    product_id: str
    name: str
    brand: str
    category: str
    subcategory: str
    description: str
    price: float
    rating: Optional[float]
    review_count: int
    attributes: Dict[str, Any]
    image_url: Optional[str]
    active: bool
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Product":
        return cls(
            product_id=row["product_id"],
            name=row["name"],
            brand=row["brand"],
            category=row["category"],
            subcategory=row["subcategory"],
            description=row["description"],
            price=row["price"],
            rating=row["rating"],
            review_count=row["review_count"],
            attributes=json.loads(row["attributes_json"]),
            image_url=row["image_url"],
            active=bool(row["active"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


class Store(BaseModel):
    """One row from the stores table."""

    store_id: str
    store_name: str
    city: str
    state: str
    postal_code: str
    latitude: float
    longitude: float
    pickup_enabled: bool
    active: bool

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Store":
        return cls(
            store_id=row["store_id"],
            store_name=row["store_name"],
            city=row["city"],
            state=row["state"],
            postal_code=row["postal_code"],
            latitude=row["latitude"],
            longitude=row["longitude"],
            pickup_enabled=bool(row["pickup_enabled"]),
            active=bool(row["active"]),
        )


class StoreDistance(BaseModel):
    """A store paired with its computed distance from a reference point.

    Returned by StoreRepository.find_nearby() - distance_miles is
    computed in Python, not stored in the database.
    """

    store: Store
    distance_miles: float


class InventoryRecord(BaseModel):
    """One row from the inventory table: one product at one store."""

    product_id: str
    store_id: str
    quantity_available: int
    quantity_reserved: int
    pickup_ready_minutes: Optional[int]
    restock_date: Optional[str]
    updated_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "InventoryRecord":
        return cls(
            product_id=row["product_id"],
            store_id=row["store_id"],
            quantity_available=row["quantity_available"],
            quantity_reserved=row["quantity_reserved"],
            pickup_ready_minutes=row["pickup_ready_minutes"],
            restock_date=row["restock_date"],
            updated_at=row["updated_at"],
        )


class Promotion(BaseModel):
    """One row from the promotions table.

    active reflects only the stored on/off flag. Whether the promotion
    is also within its start_date/end_date range is NOT decided here -
    see scout/database/schema.sql and PromotionRepository.list_active().
    """

    promotion_id: str
    product_id: str
    label: str
    discount_percent: Optional[float]
    discount_amount: Optional[float]
    start_date: str
    end_date: str
    active: bool

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Promotion":
        return cls(
            promotion_id=row["promotion_id"],
            product_id=row["product_id"],
            label=row["label"],
            discount_percent=row["discount_percent"],
            discount_amount=row["discount_amount"],
            start_date=row["start_date"],
            end_date=row["end_date"],
            active=bool(row["active"]),
        )


class Cart(BaseModel):
    """One row from the carts table (Step 15).

    fulfillment_type/store_id are None until the customer chooses one -
    see scout/services/cart_service.py for the validation that runs
    before either is ever set.
    """

    cart_id: str
    session_id: str
    customer_id: Optional[str]
    fulfillment_type: Optional[str]
    store_id: Optional[str]
    status: str
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Cart":
        return cls(
            cart_id=row["cart_id"],
            session_id=row["session_id"],
            customer_id=row["customer_id"],
            fulfillment_type=row["fulfillment_type"],
            store_id=row["store_id"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


class CartItem(BaseModel):
    """One row from the cart_items table (Step 15).

    unit_price_snapshot/promotion_id are the price/promotion recorded
    at add-time, kept for audit only - see the long comment in
    scout/database/schema.sql for why every cart read recomputes the
    CURRENT price instead of trusting this column.
    """

    cart_item_id: str
    cart_id: str
    product_id: str
    quantity: int
    unit_price_snapshot: float
    promotion_id: Optional[str]
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "CartItem":
        return cls(
            cart_item_id=row["cart_item_id"],
            cart_id=row["cart_id"],
            product_id=row["product_id"],
            quantity=row["quantity"],
            unit_price_snapshot=row["unit_price_snapshot"],
            promotion_id=row["promotion_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


class SessionRecommendationSnapshot(BaseModel):
    """One row from session_recommendation_snapshots (Step 15).

    `products` is the ranked (product_id, name) list /chat or
    /chat/stream last verified for this session - see
    scout/database/schema.sql for why this table exists and what it
    deliberately does not hold.
    """

    session_id: str
    workflow_id: str
    products: List[Dict[str, str]]
    """Each entry is {"product_id": ..., "name": ...}, in rank order."""
    updated_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "SessionRecommendationSnapshot":
        return cls(
            session_id=row["session_id"],
            workflow_id=row["workflow_id"],
            products=json.loads(row["products_json"]),
            updated_at=row["updated_at"],
        )

class ProductEmbedding(BaseModel):
    """One row from product_embeddings (Step 15.5).

    See the long comment above that table in scout/database/schema.sql
    for what model_name/search_text_hash guard against - this model
    only carries the data, it makes no staleness decision itself.
    """

    product_id: str
    model_name: str
    embedding: List[float]
    search_text_hash: str
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "ProductEmbedding":
        return cls(
            product_id=row["product_id"],
            model_name=row["model_name"],
            embedding=json.loads(row["embedding_json"]),
            search_text_hash=row["search_text_hash"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

class CheckoutSessionRecord(BaseModel):
    """One persisted Step 16 checkout-review session."""

    checkout_id: str
    session_id: str
    cart_id: str
    status: str
    fulfillment_type: str
    store_id: Optional[str]
    shipping_address: Optional[Dict[str, Any]]
    subtotal: float
    discount_total: float
    merchandise_total: float
    tax_total: float
    shipping_total: float
    total: float
    currency: str
    review_hash: str
    review_json: str
    confirm_idempotency_key: Optional[str]
    created_at: str
    updated_at: str
    completed_at: Optional[str]

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "CheckoutSessionRecord":
        return cls(
            checkout_id=row["checkout_id"],
            session_id=row["session_id"],
            cart_id=row["cart_id"],
            status=row["status"],
            fulfillment_type=row["fulfillment_type"],
            store_id=row["store_id"],
            shipping_address=(
                json.loads(row["shipping_address_json"])
                if row["shipping_address_json"] is not None
                else None
            ),
            subtotal=row["subtotal"],
            discount_total=row["discount_total"],
            merchandise_total=row["merchandise_total"],
            tax_total=row["tax_total"],
            shipping_total=row["shipping_total"],
            total=row["total"],
            currency=row["currency"],
            review_hash=row["review_hash"],
            review_json=row["review_json"],
            confirm_idempotency_key=row["confirm_idempotency_key"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            completed_at=row["completed_at"],
        )


class PaymentRecord(BaseModel):
    """One persisted payment result. Step 16 stores mock-provider facts only."""

    payment_id: str
    checkout_id: str
    provider: str
    provider_reference: str
    status: str
    amount: float
    currency: str
    created_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "PaymentRecord":
        return cls(**dict(row))


class OrderRecord(BaseModel):
    """One confirmed order created atomically from a checkout session."""

    order_id: str
    checkout_id: str
    session_id: str
    cart_id: str
    payment_id: str
    status: str
    fulfillment_type: str
    store_id: Optional[str]
    shipping_address: Optional[Dict[str, Any]]
    subtotal: float
    discount_total: float
    merchandise_total: float
    tax_total: float
    shipping_total: float
    total: float
    currency: str
    created_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "OrderRecord":
        values = dict(row)
        shipping_json = values.pop("shipping_address_json")
        values["shipping_address"] = json.loads(shipping_json) if shipping_json is not None else None
        return cls(**values)


class OrderItemRecord(BaseModel):
    """One immutable line snapshot attached to a confirmed order."""

    order_item_id: str
    order_id: str
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
    created_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "OrderItemRecord":
        return cls(**dict(row))


class InventoryReservationRecord(BaseModel):
    """One store-level reservation created for an order item."""

    reservation_id: str
    order_id: str
    order_item_id: str
    product_id: str
    store_id: str
    quantity: int
    status: str
    created_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "InventoryReservationRecord":
        return cls(**dict(row))


class OrderFulfillmentRecord(BaseModel):
    """Mutable fulfillment facts attached to an immutable Step 16 order."""

    order_id: str
    fulfillment_status: str
    carrier_name: Optional[str]
    tracking_number: Optional[str]
    tracking_url: Optional[str]
    estimated_ready_at: Optional[str]
    estimated_delivery_at: Optional[str]
    shipped_at: Optional[str]
    delivered_at: Optional[str]
    picked_up_at: Optional[str]
    updated_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "OrderFulfillmentRecord":
        return cls(**dict(row))


class ExternalOfferRecord(BaseModel):
    """One synthetic merchant offer from Step 16.5's mock feed."""

    offer_id: str
    merchant_name: str
    external_product_id: str
    product_name: str
    brand: str
    category: str
    description: str
    price: float
    currency: str
    rating: Optional[float]
    review_count: int
    availability_status: str
    attributes: Dict[str, Any]
    image_url: Optional[str]
    merchant_url: str
    upc: Optional[str]
    gtin: Optional[str]
    model_number: Optional[str]
    active: bool
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "ExternalOfferRecord":
        values = dict(row)
        values["attributes"] = json.loads(values.pop("attributes_json"))
        values["active"] = bool(values["active"])
        return cls(**values)


class AffiliateClickRecord(BaseModel):
    """One external-offer click; not an order or purchase record."""

    click_id: str
    offer_id: str
    session_id: str
    workflow_id: Optional[str]
    source_product_id: Optional[str]
    match_type: str
    clicked_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "AffiliateClickRecord":
        return cls(**dict(row))
