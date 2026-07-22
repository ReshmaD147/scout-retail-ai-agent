"""Structured input/output schemas for every MCP product tool.

Every tool returns one of the *Result models defined here - never a
raw dict, a raw repository model, or free text. FastMCP derives each
tool's real MCP `outputSchema` from these models' fields automatically,
so the schema documented for a tool is always exactly what the code
returns, not a description that can drift out of sync.

ToolError is embedded in every result instead of being raised as an
exception, so "something did not work" is always structured data a
caller can branch on, the same shape every time.
"""

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel

from scout.services.cart_service import CartView
from scout.services.checkout_service import CheckoutReview, OrderConfirmation


class ToolError(BaseModel):
    """A structured, safe-to-show description of why a tool call failed."""

    error_type: str
    """One of: "validation_error", "not_found"."""

    message: str


class ProductSummary(BaseModel):
    """The fields every product-related tool needs to show a customer."""

    product_id: str
    name: str
    brand: str
    category: str
    subcategory: str
    price: float
    rating: Optional[float]
    review_count: int
    active: bool


class ProductDetail(ProductSummary):
    """Everything ProductSummary has, plus the full catalog record."""

    description: str
    attributes: Dict[str, Any]
    image_url: Optional[str]
    created_at: str
    updated_at: str


class PromotionSummary(BaseModel):
    """One promotion, with both its raw flag and its reconciled validity."""

    promotion_id: str
    product_id: str
    label: str
    discount_percent: Optional[float]
    discount_amount: Optional[float]
    start_date: str
    end_date: str
    active: bool
    is_currently_valid: bool
    """Computed by scout.services.promotion_service.is_promotion_valid -
    active AND within [start_date, end_date] as of the evaluation date.
    active alone (the raw stored flag) is not enough to say a promotion
    is usable right now; see scout/database/schema.sql."""


class RankedProductSummary(BaseModel):
    """One ranked product plus the components that produced its position."""

    rank: int
    product: ProductSummary
    rating_component: float
    review_component: int
    price_component: float


class SearchProductsResult(BaseModel):
    products: List[ProductSummary]
    count: int
    error: Optional[ToolError] = None


class GetProductDetailsResult(BaseModel):
    product: Optional[ProductDetail] = None
    error: Optional[ToolError] = None


class GetPromotionsResult(BaseModel):
    promotions: List[PromotionSummary]
    count: int
    error: Optional[ToolError] = None


class RankProductsResult(BaseModel):
    ranked_products: List[RankedProductSummary]
    count: int
    missing_product_ids: List[str]
    """product_ids the caller asked to rank that do not exist. Never
    silently dropped without a trace - a caller needs to know a
    requested ID did not resolve to a real product."""
    error: Optional[ToolError] = None


class FindSimilarProductsResult(BaseModel):
    reference_product_id: str
    similar_products: List[ProductSummary]
    count: int
    error: Optional[ToolError] = None


# ---------------------------------------------------------------------------
# Inventory and fulfillment tools (scout/mcp/inventory_tools.py)
# ---------------------------------------------------------------------------


class InventoryEvidence(BaseModel):
    """The raw inventory facts behind an availability or fulfillment claim.

    Every inventory/fulfillment tool attaches one of these to its
    result so a claim like "in stock" or "ships in 3-5 days" is always
    traceable back to a specific store's row - or, when record_found is
    False, an explicit statement that no row exists rather than a
    silently invented one.
    """

    store_id: str
    record_found: bool
    quantity_available: Optional[int] = None
    quantity_reserved: Optional[int] = None
    restock_date: Optional[str] = None


class CheckStoreInventoryResult(BaseModel):
    product_id: str
    store_id: str
    store_name: Optional[str] = None
    status: Optional[str] = None
    """One of the AvailabilityStatus values (e.g. "in_stock", "out_of_stock")."""
    sellable_quantity: int = 0
    restock_date: Optional[str] = None
    evidence: Optional[InventoryEvidence] = None
    error: Optional[ToolError] = None


class NearbyStoreAvailability(BaseModel):
    store_id: str
    store_name: str
    distance_miles: float
    status: str
    sellable_quantity: int
    restock_date: Optional[str] = None
    evidence: InventoryEvidence


class FindNearbyInventoryResult(BaseModel):
    product_id: str
    radius_miles: float
    results: List[NearbyStoreAvailability]
    """Only stores that can actually fulfill at least min_quantity units,
    sorted nearest first. Stores checked but unable to fulfill are not
    included - this tool answers "where can I get this," not a full
    inventory dump."""
    count: int
    error: Optional[ToolError] = None


class CheckNetworkInventoryResult(BaseModel):
    """Result of check_network_inventory - store-network availability.

    availability_source is always "store_network": this is a sum of
    real per-store inventory rows, not a genuine online/warehouse
    inventory record (Scout's schema has no separate warehouse table -
    see the module docstring in scout/mcp/inventory_tools.py). The
    field exists so a caller can tell, programmatically, that this
    number is a network aggregate rather than a distinct online stock
    figure - a grounded statement built from this result should say
    "available across the Scout store network," not "available
    online."
    """

    product_id: str
    availability_source: str = "store_network"
    available: bool
    min_quantity: int
    sellable_quantity: int
    contributing_store_ids: List[str]
    error: Optional[ToolError] = None


class GetPickupEstimateResult(BaseModel):
    product_id: str
    store_id: str
    pickup_available: bool
    pickup_ready_minutes: Optional[int] = None
    reason: Optional[str] = None
    evidence: Optional[InventoryEvidence] = None
    error: Optional[ToolError] = None


class DeliveryPolicyEvidence(BaseModel):
    """Labels a delivery window as a configured policy, not a verified fact.

    A real InventoryEvidence traces back to a specific store's
    inventory row. This does not - minimum_days/maximum_days come from
    centralized configuration (STANDARD_DELIVERY_MIN_DAYS/MAX_DAYS),
    applied uniformly whenever network stock exists. Keeping
    evidence_type == "configured_policy" distinct from real inventory
    evidence means a caller can never mistake "we assume 3-5 days" for
    "a carrier confirmed 3-5 days." Customer-facing language built from
    this should say "Standard delivery is estimated at 3-5 days for
    this prototype," never "Your order will arrive in 3-5 days."
    """

    evidence_type: str = "configured_policy"
    policy_name: str = "standard_delivery_window"
    minimum_days: int
    maximum_days: int
    inventory_source: str = "store_network"
    is_carrier_estimate: bool = False


class GetDeliveryEstimateResult(BaseModel):
    product_id: str
    min_quantity: int
    delivery_available: bool
    policy_evidence: Optional[DeliveryPolicyEvidence] = None
    """Populated only when delivery_available is True - see
    DeliveryPolicyEvidence for why this is kept separate from the real
    inventory evidence (sellable_quantity/contributing_store_ids)."""
    reason: Optional[str] = None
    sellable_quantity: int = 0
    contributing_store_ids: List[str] = []
    error: Optional[ToolError] = None


class SubstituteOption(BaseModel):
    product: ProductSummary
    fulfillment_channel: str
    """One of: "selected_store", "nearby_store", "store_network"."""
    sellable_quantity: int
    distance_miles: Optional[float] = None
    evidence: InventoryEvidence


class FindAvailableSubstitutesResult(BaseModel):
    reference_product_id: str
    fulfillment_channel_checked: str
    substitutes: List[SubstituteOption]
    count: int
    error: Optional[ToolError] = None


# ---------------------------------------------------------------------------
# Store lookup tool (scout/mcp/store_tools.py) - added Step 10, to let an
# agent resolve a free-text location (e.g. "Maple Grove") to a real store
# without querying StoreRepository directly (see product_tools.py's
# module docstring for why agents get tools, not database access).
# ---------------------------------------------------------------------------


class FindStoreByLocationResult(BaseModel):
    location_text: str
    store_id: Optional[str] = None
    store_name: Optional[str] = None
    city: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    error: Optional[ToolError] = None


# ---------------------------------------------------------------------------
# Cart tools (scout/mcp/cart_tools.py) - added Step 15.
#
# Every cart tool returns this exact same shape: the caller either gets
# the cart's current, fully revalidated state (`cart`) or a structured
# `error` - never both, never neither. One shared result type is used
# by all seven tools rather than seven near-identical classes, since
# `CartView` (scout.services.cart_service) already carries everything a
# cart operation could report.
# ---------------------------------------------------------------------------


class CartToolResult(BaseModel):
    cart: Optional[CartView] = None
    error: Optional[ToolError] = None


# ---------------------------------------------------------------------------
# Semantic search tool (scout/mcp/semantic_search_tools.py) - added Step 15.5.
# ---------------------------------------------------------------------------


class SemanticSearchProductsResult(BaseModel):
    products: List[ProductSummary]
    count: int
    retrieval_method: str
    """One of "exact_product_id", "exact_brand", "exact_name",
    "exact_color", "literal_keyword", or "semantic" - see
    scout.services.product_search_service for what each means. Exposed
    so a caller (or a future customer-facing trace) can tell a grounded
    exact match apart from a broader meaning-based retrieval, never
    silently blended together."""
    candidates_considered: int
    """How many candidates the winning retrieval strategy evaluated
    before filtering/ranking - Step 15.5's "initial retrieval considers
    more than three candidates" is verifiable directly from this field,
    not just inferred from `count`."""
    error: Optional[ToolError] = None

# ---------------------------------------------------------------------------
# Checkout tools (scout/mcp/checkout_tools.py) - added Step 16.
# ---------------------------------------------------------------------------


class CheckoutToolResult(BaseModel):
    review: Optional[CheckoutReview] = None
    order: Optional[OrderConfirmation] = None
    error: Optional[ToolError] = None


# ---------------------------------------------------------------------------
# External merchant / affiliate tools (Step 16.5).
# ---------------------------------------------------------------------------


class ExternalOfferSummary(BaseModel):
    """Customer-safe external offer. Direct merchant URL is intentionally omitted.

    The browser must use Scout's click-tracking endpoint, which records the
    click and then redirects. External offers never enter the Scout cart.
    """

    offer_id: str
    merchant_name: str
    external_product_id: str
    product_name: str
    brand: str
    category: str
    description: str
    price: float
    currency: str
    rating: Optional[float] = None
    review_count: int = 0
    availability_status: str
    image_url: Optional[str] = None
    match_type: Literal["exact", "similar"]
    match_label: str
    match_reason: str
    source_product_id: Optional[str] = None
    matched_identifier_type: Optional[str] = None
    relevance_score: float
    disclosure: str


class SearchExternalOffersResult(BaseModel):
    offers: List[ExternalOfferSummary]
    count: int
    error: Optional[ToolError] = None


class ExternalOfferDetail(BaseModel):
    offer_id: str
    merchant_name: str
    external_product_id: str
    product_name: str
    brand: str
    category: str
    description: str
    price: float
    currency: str
    rating: Optional[float] = None
    review_count: int = 0
    availability_status: str
    image_url: Optional[str] = None
    upc: Optional[str] = None
    gtin: Optional[str] = None
    model_number: Optional[str] = None
    active: bool


class GetExternalOfferResult(BaseModel):
    offer: Optional[ExternalOfferDetail] = None
    error: Optional[ToolError] = None


class TrackAffiliateClickResult(BaseModel):
    click_id: Optional[str] = None
    redirect_url: Optional[str] = None
    error: Optional[ToolError] = None
