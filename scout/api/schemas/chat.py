"""Request/response schemas for POST /chat (Step 12).

Two deliberately small, independent public contracts:

`ChatRequest` is everything a client is allowed to send - five fields,
nothing else. `extra="forbid"` (see the class docstring) is what turns
"the client must never control internal graph fields such as plan,
next_agent, evidence, retry_count, step_count, or workflow_status"
from a convention into something FastAPI enforces before the route
function ever runs: none of those names exist on this model, and
`extra="forbid"` rejects any that show up in the request body anyway.

`ChatResponse` is everything a client is allowed to see - built *from*
`RetailGraphState` by scout/api/routes/chat.py, never a serialization
of that state itself. `products` reuses `ProductSummary`
(scout/mcp/schemas.py) since that is already exactly the customer-safe
product shape every other tool in this codebase returns.
"""

from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from scout.mcp.schemas import ExternalOfferSummary, ProductSummary
from scout.services.order_service import OrderStatusView

_MAX_MESSAGE_LENGTH = 2000
"""A reasonable ceiling for one chat message - generous for a real
customer request, small enough to keep the graph's own inputs (and any
future LLM prompt built from them) bounded rather than unbounded."""


class RecommendationFilters(BaseModel):
    """Customer-controlled recommendation filters supported end to end.

    These are hard constraints, not ranking hints.  React sends them to
    `/chat` or `/chat/stream`; `understand_request_node` merges them into
    the structured intent; the deterministic search/inventory services
    enforce them.  No internal graph field is exposed through this
    model.

    `attributes` uses canonical ``key:value`` tokens returned by
    ``GET /catalog/filter-options``.  Keeping the token machine-readable
    prevents the frontend from inventing product attributes or relying
    on fuzzy display-label matching.
    """

    model_config = ConfigDict(extra="forbid")

    max_price: Optional[float] = Field(default=None, ge=0)
    category: Optional[str] = None
    product_type: Optional[str] = None
    attributes: List[str] = Field(default_factory=list, max_length=12)
    in_stock_only: bool = True
    fulfillment: Optional[Literal["pickup", "delivery"]] = None

    @field_validator("category", "product_type")
    @classmethod
    def _optional_filter_text_must_not_be_blank(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be whitespace-only")
        return stripped

    @field_validator("attributes")
    @classmethod
    def _attribute_tokens_must_be_nonblank(cls, values: List[str]) -> List[str]:
        cleaned: List[str] = []
        for value in values:
            stripped = value.strip()
            if not stripped:
                raise ValueError("attribute filters must not be blank")
            if stripped not in cleaned:
                cleaned.append(stripped)
        return cleaned


class ChatRequest(BaseModel):
    """The only shape a client may send to POST /chat.

    `extra="forbid"` is what makes "the client cannot control internal
    graph fields" a hard guarantee rather than a convention: posting
    `{"plan": [...]}` or `{"workflow_status": "completed"}` alongside
    an otherwise-valid request fails validation (422) instead of being
    silently ignored, or worse, accepted - there simply is no field on
    this model that could ever reach one of RetailGraphState's
    internal execution fields.
    """

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1, description="Identifies the customer's conversation.")
    message: str = Field(
        min_length=1, max_length=_MAX_MESSAGE_LENGTH, description="The customer's request, as typed."
    )
    user_id: Optional[str] = Field(default=None, description="The authenticated customer, if known.")
    store_id: Optional[str] = Field(default=None, description="A store the customer already has in mind.")
    location: Optional[str] = Field(default=None, description="A free-text location hint (e.g. a city).")
    filters: Optional[RecommendationFilters] = Field(
        default=None,
        description="Optional deterministic product and fulfillment filters.",
    )

    @field_validator("session_id", "message")
    @classmethod
    def _required_field_must_not_be_blank(cls, value: str) -> str:
        """Field(min_length=1) alone would accept " " (one space) - a
        whitespace-only value must be rejected too, and Step 12
        explicitly requires it for both session_id and message."""
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be empty or whitespace-only")
        return stripped

    @field_validator("user_id", "store_id", "location")
    @classmethod
    def _optional_field_must_not_be_blank(cls, value: Optional[str]) -> Optional[str]:
        """None (the field being omitted) is fine - a present-but-blank
        value is not."""
        if value is None:
            return value
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be whitespace-only")
        return stripped


class ChatError(BaseModel):
    """One safe, structured problem the workflow encountered.

    `code` is a stable, machine-readable category (mirrors
    WorkflowError.error_type, scout/orchestration/state.py, or one of
    Step 12's own route-level codes like "WORKFLOW_TIMEOUT");
    `message` is the same customer-safe text CLAUDE.md section 12
    already requires of every WorkflowError - never a stack trace,
    SQL, a file path, or a hidden prompt.
    """

    code: str
    message: str


class FulfillmentOption(BaseModel):
    """One grounded way to get a specific product, for the customer to compare.

    Built directly from an `inventory_results` entry
    (scout/orchestration/state.py) - the same data
    scout/agents/response_verification.py already re-verified before
    trusting it - never a live re-query from the route itself.
    """

    product_id: str
    channel: str
    """One of "selected_store", "nearby_store", or "substitute" - see
    scout/agents/inventory_agent.py."""
    store_id: Optional[str] = None
    store_name: Optional[str] = None
    sellable_quantity: int
    distance_miles: Optional[float] = None
    substitute_for: Optional[str] = None
    """Set only when channel == "substitute" - the original product_id
    this option stands in for."""
    delivery_min_days: Optional[int] = None
    delivery_max_days: Optional[int] = None


class RequestedLocation(BaseModel):
    """A customer-safe map point resolved from the request.

    Today Scout resolves a city/store phrase to one of its real store
    records.  The frontend uses this only to place the requested-area
    marker; it is not claimed to be the customer's precise GPS position.
    """

    label: str
    latitude: float
    longitude: float


class ChatResponse(BaseModel):
    """The only shape POST /chat ever returns for a request that was
    itself valid (HTTP 200 in every case below - see
    scout/api/routes/chat.py for why "failed" is a normal business
    outcome, not a server error).
    """

    workflow_id: str
    session_id: str
    status: Literal["completed", "clarification_required", "no_results", "confirmation_required", "failed"]
    answer: Optional[str] = None
    """The grounded natural-language answer, or the clarifying
    question when status == "clarification_required". None only when
    there is genuinely nothing safe to say yet (should not normally
    happen once workflow_status is terminal/paused)."""
    products: List[ProductSummary] = Field(default_factory=list)
    fulfillment_options: List[FulfillmentOption] = Field(default_factory=list)
    requested_location: Optional[RequestedLocation] = None
    external_offers: List[ExternalOfferSummary] = Field(default_factory=list)
    """Mock merchant alternatives returned only when no internal option is fulfillable."""
    order: Optional[OrderStatusView] = None
    """Verified read-only order status returned by the Step 17 Order Agent."""
    activity_events: List[str] = Field(default_factory=list)
    """A fixed vocabulary of customer-safe phrases describing what
    Scout did (e.g. "Searching the product catalog") - never a tool's
    raw output, a model's reasoning, or a prompt. See
    scout/api/routes/chat.py's _build_activity_events."""
    errors: List[ChatError] = Field(default_factory=list)
