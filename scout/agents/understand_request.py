"""Understand request: turn the raw customer_query into structured intent.

Deterministic, regex/keyword-based extraction - there is no LLM or
Ollama integration in this codebase yet (Phase 5's job, explicitly
skipped so far), so this is a transparent, testable placeholder for
real NLU. It extracts exactly what CLAUDE.md's primary example
workflow needs: a product category and search keyword, a maximum
price, whether pickup is requested, and a location resolved to one of
Scout's real stores via the find_store_by_location MCP tool
(scout/mcp/store_tools.py) - never a guessed store_id.

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


def _extract_max_price(query: str) -> Optional[float]:
    match = _BUDGET_PATTERN.search(query)
    return float(match.group(1)) if match else None


def _extract_location_text(query: str) -> Optional[str]:
    match = _LOCATION_PATTERN.search(query)
    return match.group(1).strip() if match else None


def _extract_pickup_requested(query: str) -> bool:
    return bool(_PICKUP_PATTERN.search(query))


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
    query_lower = query.lower()

    intent: Dict[str, Any] = {
        "category": _extract_category(query_lower),
        "keyword": _extract_keyword(query_lower),
        "max_price": _extract_max_price(query),
        "pickup_requested": _extract_pickup_requested(query),
        "location_text": _extract_location_text(query),
        "selected_store_id": None,
        "selected_store_name": None,
        "selected_store_latitude": None,
        "selected_store_longitude": None,
        "location_resolved": False,
    }

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
    }
    if evidence:
        update["evidence"] = evidence
    if errors:
        update["errors"] = errors
    return update
