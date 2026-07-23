"""Understand request: turn the raw customer_query into structured intent.

Structured extraction asks the configured local Ollama chat model for
strict JSON, validates it with Pydantic, retries once on malformed JSON,
and falls back to the original deterministic parser whenever the model
path is unavailable or invalid. The node still emits the legacy fields
the existing graph uses, so downstream agents do not need to change.

Idempotent: if state.intent is already set (e.g. a test constructing a
precise scenario, or a resumed workflow), this node leaves it unchanged
rather than re-deriving it from customer_query - see
scout/orchestration/state.py's "how state prevents duplicate work."
"""

import re
from typing import Any, Dict, List, Optional

from scout.mcp.store_tools import find_store_by_location
from scout.orchestration.limits import check_step_budget
from scout.orchestration.state import EvidenceEntry, RetailGraphState, WorkflowError
from scout.services.intent_service import StructuredIntent, extract_intent_with_ollama

# Deliberately small and literal: real category/attribute extraction is
# the Recommendation Agent's job once Phase 5 (Ollama integration)
# exists. This only has to resolve Scout's own demo catalog categories
# (scout/database/seed.py) well enough to run the acceptance workflow
# without guessing.
_CATEGORY_KEYWORDS = {
    "shoes": "Footwear",
    "shoe": "Footwear",
    "boots": "Footwear",
    "boot": "Footwear",
    "sneakers": "Footwear",
    "sneaker": "Footwear",
    "backpacks": "Bags",
    "backpack": "Bags",
    "bags": "Bags",
    "bag": "Bags",
    "tote": "Bags",
    "duffel": "Bags",
    "earbuds": "Electronics",
    "earbud": "Electronics",
    "speaker": "Electronics",
    "tablet": "Electronics",
    "headphones": "Electronics",
    "power bank": "Electronics",
    "coffee maker": "Home and Kitchen",
    "kettle": "Home and Kitchen",
    "lamp": "Home and Kitchen",
    "fridge": "Home and Kitchen",
}

_SUBCATEGORY_KEYWORDS = [
    ("hiking backpack", "Hiking Backpack"),
    ("wireless earbuds", "Earbuds"),
    ("coffee makers", "Coffee Makers"),
    ("coffee maker", "Coffee Makers"),
    ("work shoes", "Work"),
    ("work shoe", "Work"),
    ("running shoes", "Running"),
    ("running shoe", "Running"),
    ("hiking boots", "Hiking"),
    ("hiking boot", "Hiking"),
    ("earbuds", "Earbuds"),
    ("earbud", "Earbuds"),
    ("power bank", "Chargers & Power"),
    ("speaker", "Speakers"),
    ("tablet", "Tablets"),
    ("kettle", "Kettles"),
    ("lamp", "Lighting"),
    ("mini fridge", "Small Appliances"),
    ("fridge", "Small Appliances"),
    ("backpack", "Backpack"),
    ("duffel", "Duffel"),
    ("tote", "Tote"),
    ("briefcase", "Briefcase"),
]

_DESCRIPTOR_KEYWORDS = [
    "work",
    "running",
    "hiking",
    "casual",
    "training",
    "trail",
    "outdoor",
    "lifestyle",
]
"""Soft descriptors used as a search keyword (matched against a
product's name/description by search_products) - not a full attribute
model. "comfortable" is deliberately not one of these: it has no
literal match in the catalog's descriptions, so treating it as a
keyword filter would silently return zero results instead of relying
on the existing rating-based ranking (scout.services.ranking_service)
to prefer higher-rated, presumably more comfortable products."""

_BUDGET_PATTERN = re.compile(r"(?:under|below|less than)\s*\$?\s*(\d+(?:\.\d{1,2})?)", re.IGNORECASE)
_LOCATION_PATTERN = re.compile(
    r"\bnear\s+([A-Za-z][A-Za-z\s]*?)(?=[.,!?]|\s+that\b|\s+today\b|$)", re.IGNORECASE
)
_PICKUP_PATTERN = re.compile(r"pick[\s-]?up", re.IGNORECASE)
_ORDER_ID_PATTERN = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)
_ORDER_REQUEST_PATTERN = re.compile(
    r"\b(order|tracking|track|payment status|where is my order|cancel|cancellation|return|exchange)\b",
    re.IGNORECASE,
)
_DEALS_PATTERN = re.compile(r"\b(deal|deals|discount|discounted|sale|promotion|promotions)\b", re.IGNORECASE)


def _extract_order_action(query_lower: str) -> str:
    if "cancel" in query_lower:
        return "cancel_eligibility"
    if "return" in query_lower:
        return "return_eligibility"
    if "exchange" in query_lower:
        return "exchange_eligibility"
    if "payment" in query_lower:
        return "payment_status"
    if "track" in query_lower or "where is" in query_lower:
        return "tracking"
    return "status"


def _extract_category(query_lower: str) -> Optional[str]:
    for word, category in _CATEGORY_KEYWORDS.items():
        if word in query_lower:
            return category
    return None


def _extract_keyword(query_lower: str) -> Optional[str]:
    for word in _DESCRIPTOR_KEYWORDS:
        if word in query_lower:
            return word
    return None


def _extract_subcategory(query_lower: str) -> Optional[str]:
    for phrase, subcategory in _SUBCATEGORY_KEYWORDS:
        if phrase in query_lower:
            return subcategory
    return None


def _extract_max_price(query: str) -> Optional[float]:
    match = _BUDGET_PATTERN.search(query)
    return float(match.group(1)) if match else None


def _extract_location_text(query: str) -> Optional[str]:
    match = _LOCATION_PATTERN.search(query)
    return match.group(1).strip() if match else None


def _extract_pickup_requested(query: str) -> bool:
    return bool(_PICKUP_PATTERN.search(query))


def _deterministic_structured_intent(query: str) -> StructuredIntent:
    query_lower = query.lower()
    order_match = _ORDER_ID_PATTERN.search(query)
    if _ORDER_REQUEST_PATTERN.search(query_lower):
        order_action = _extract_order_action(query_lower)
        request_type = "order_eligibility" if order_action.endswith("_eligibility") else "order_status"
        return StructuredIntent(
            request_type=request_type,
            order_id=order_match.group(0).lower() if order_match else None,
            needs_clarification=False,
            confidence=0.7,
        )

    category = _extract_category(query_lower)
    product_type = _extract_subcategory(query_lower)
    budget_max = _extract_max_price(query)
    location = _extract_location_text(query)
    pickup_requested = _extract_pickup_requested(query)
    deals = bool(_DEALS_PATTERN.search(query_lower))
    has_product_signal = category is not None or product_type is not None or budget_max is not None or deals
    if not has_product_signal and not location:
        return StructuredIntent(
            request_type="clarification",
            needs_clarification=True,
            clarification_question=(
                "Could you tell me what product you're looking for, your budget, "
                "and which store or area you'd like to check?"
            ),
            confidence=0.4,
        )

    return StructuredIntent(
        request_type="deals" if deals else "product_search",
        product_type=product_type,
        category=category,
        use_case=_extract_keyword(query_lower),
        budget_max=budget_max,
        location=location,
        fulfillment_preference="pickup" if pickup_requested else None,
        urgency="today" if "today" in query_lower else None,
        needs_clarification=False,
        confidence=0.65,
    )


def _legacy_intent_from_structured(structured: StructuredIntent, query: str) -> Dict[str, Any]:
    query_lower = query.lower()
    if structured.request_type in {"order_status", "order_eligibility"}:
        order_action = _extract_order_action(query_lower)
        if structured.request_type == "order_eligibility" and order_action == "status":
            order_action = "cancel_eligibility" if "cancel" in query_lower else "return_eligibility"
        return {
            "request_type": "order",
            "order_id": structured.order_id,
            "order_action": order_action,
            "structured_intent": structured.model_dump(mode="json"),
        }

    fulfillment = structured.fulfillment_preference
    pickup_requested = fulfillment == "pickup" or _extract_pickup_requested(query)
    return {
        "request_type": "recommendation",
        "category": structured.category or _extract_category(query_lower),
        "subcategory": structured.product_type or _extract_subcategory(query_lower),
        "keyword": structured.use_case or _extract_keyword(query_lower),
        "max_price": structured.budget_max or _extract_max_price(query),
        "attribute_filters": list(structured.attributes),
        "deals_only": structured.request_type == "deals" or bool(_DEALS_PATTERN.search(query_lower)),
        "in_stock_only": True,
        "fulfillment": fulfillment,
        "pickup_requested": pickup_requested,
        "location_text": structured.location or _extract_location_text(query),
        "selected_store_id": None,
        "selected_store_name": None,
        "selected_store_latitude": None,
        "selected_store_longitude": None,
        "location_resolved": False,
        "structured_intent": structured.model_dump(mode="json"),
        "needs_clarification": structured.needs_clarification,
        "clarification_question": structured.clarification_question,
    }


def understand_request_node(state: RetailGraphState) -> Dict[str, Any]:
    """Extract structured intent from state.customer_query.

    Never invents a category, budget, or store: anything not found in
    the query is left as None/False, and a location that does not
    resolve to a real Scout store is reported via
    intent["location_resolved"] = False plus a structured
    WorkflowError, rather than a guessed store_id.
    """
    limit_update = check_step_budget(state)
    if limit_update is not None:
        return limit_update

    if state.intent is not None:
        return {"step_count": state.step_count + 1}

    query = state.customer_query
    deterministic = _deterministic_structured_intent(query)
    extraction = extract_intent_with_ollama(query, fallback_intent=deterministic)
    intent = _legacy_intent_from_structured(extraction.intent, query)
    intent["extraction_source"] = extraction.extraction_source

    if intent["request_type"] == "order":
        return {
            "step_count": state.step_count + 1,
            "intent": intent,
            "structured_intent": extraction.intent,
            "intent_extraction_source": extraction.extraction_source,
        }

    # API filters are already validated by ChatRequest. They are hard
    # customer constraints and therefore override any looser value
    # extracted from the natural-language message.
    requested_filters = state.requested_filters or {}
    if requested_filters.get("category") is not None:
        intent["category"] = requested_filters["category"]
    if requested_filters.get("product_type") is not None:
        intent["subcategory"] = requested_filters["product_type"]
    if requested_filters.get("max_price") is not None:
        intent["max_price"] = requested_filters["max_price"]
    if requested_filters.get("attributes"):
        intent["attribute_filters"] = list(requested_filters["attributes"])
    if "in_stock_only" in requested_filters:
        intent["in_stock_only"] = bool(requested_filters["in_stock_only"])
    if requested_filters.get("fulfillment") is not None:
        intent["fulfillment"] = requested_filters["fulfillment"]
        intent["pickup_requested"] = requested_filters["fulfillment"] == "pickup"

    evidence: List[EvidenceEntry] = []
    errors: List[WorkflowError] = []

    if intent["location_text"]:
        result = find_store_by_location(intent["location_text"])
        if result.error is None:
            intent["selected_store_id"] = result.store_id
            intent["selected_store_name"] = result.store_name
            intent["selected_store_latitude"] = result.latitude
            intent["selected_store_longitude"] = result.longitude
            intent["location_resolved"] = True
            evidence.append(
                EvidenceEntry(
                    source="find_store_by_location",
                    claim=f"{intent['location_text']} resolved to {result.store_name} ({result.store_id})",
                    data=result.model_dump(),
                )
            )
        else:
            errors.append(
                WorkflowError(
                    error_type=result.error.error_type,
                    message=result.error.message,
                    agent="understand_request",
                    step="resolve_location",
                )
            )

    update: Dict[str, Any] = {
        "step_count": state.step_count + 1,
        "intent": intent,
        "structured_intent": extraction.intent,
        "intent_extraction_source": extraction.extraction_source,
    }
    if evidence:
        update["evidence"] = evidence
    if errors:
        update["errors"] = errors
    return update
