"""Structured intent extraction backed by Scout's local Ollama runtime.

The service returns a typed Pydantic intent and never decides domain facts:
inventory, promotions, prices, eligibility, and store resolution remain in
their existing tools/services.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Literal, Optional

import httpx
from pydantic import BaseModel, Field, ValidationError, field_validator

from scout.config import get_settings

RequestType = Literal[
    "product_search",
    "deals",
    "compare",
    "find_similar",
    "fulfillment",
    "order_status",
    "order_eligibility",
    "policy",
    "clarification",
    "out_of_scope",
]
FulfillmentPreference = Literal["pickup", "delivery", "either"]
Urgency = Literal["today", "this_week", "flexible"]

_PRODUCT_ID_PATTERN = re.compile(r"\b[A-Z]{2,5}-\d{3,5}\b", re.IGNORECASE)
_UUID_ORDER_ID_PATTERN = (
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
)
_HUMAN_ORDER_ID_PATTERN = r"ORD-\d{3,10}"
_ORDER_ID_PATTERN = re.compile(rf"\b(?:{_UUID_ORDER_ID_PATTERN}|{_HUMAN_ORDER_ID_PATTERN})\b", re.IGNORECASE)


class StructuredIntent(BaseModel):
    request_type: RequestType
    product_type: Optional[str] = None
    category: Optional[str] = None
    use_case: Optional[str] = None
    attributes: List[str] = Field(default_factory=list)
    requested_products: List[Dict[str, Any]] = Field(default_factory=list)
    budget_min: Optional[float] = Field(default=None, ge=0)
    budget_max: Optional[float] = Field(default=None, ge=0)
    location: Optional[str] = None
    fulfillment_preference: Optional[FulfillmentPreference] = None
    urgency: Optional[Urgency] = None
    reference_product_id: Optional[str] = None
    comparison_product_ids: List[str] = Field(default_factory=list)
    order_id: Optional[str] = None
    needs_clarification: bool = False
    clarification_question: Optional[str] = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("product_type", "category", "use_case", "location", "clarification_question")
    @classmethod
    def _blank_to_none(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("reference_product_id", "order_id")
    @classmethod
    def _normalize_identifier(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        stripped = value.strip()
        return stripped.upper() if _PRODUCT_ID_PATTERN.fullmatch(stripped) else normalize_order_id(stripped)

    @field_validator("comparison_product_ids")
    @classmethod
    def _normalize_product_ids(cls, values: List[str]) -> List[str]:
        normalized: List[str] = []
        for value in values:
            stripped = value.strip()
            if stripped:
                normalized.append(stripped.upper())
        return normalized


class IntentExtractionResult(BaseModel):
    intent: StructuredIntent
    extraction_source: Literal["llm", "retry", "deterministic_fallback"]


def normalize_order_id(value: str) -> str:
    stripped = value.strip()
    if re.fullmatch(_UUID_ORDER_ID_PATTERN, stripped, re.IGNORECASE):
        return stripped.lower()
    if re.fullmatch(_HUMAN_ORDER_ID_PATTERN, stripped, re.IGNORECASE):
        return stripped.upper()
    return stripped


def _schema_example() -> Dict[str, Any]:
    return {
        "request_type": "product_search",
        "product_type": None,
        "category": None,
        "use_case": None,
        "attributes": [],
        "requested_products": [],
        "budget_min": None,
        "budget_max": None,
        "location": None,
        "fulfillment_preference": None,
        "urgency": None,
        "reference_product_id": None,
        "comparison_product_ids": [],
        "order_id": None,
        "needs_clarification": False,
        "clarification_question": None,
        "confidence": 0.0,
    }


def build_intent_prompt(query: str) -> str:
    return (
        "Return strict JSON only. Do not include markdown, comments, or prose.\n"
        "Extract the customer's retail intent into exactly this JSON shape:\n"
        f"{json.dumps(_schema_example(), sort_keys=True)}\n\n"
        "Allowed request_type values: product_search, deals, compare, find_similar, "
        "fulfillment, order_status, order_eligibility, clarification, out_of_scope.\n"
        "Allowed fulfillment_preference values: pickup, delivery, either, null.\n"
        "Allowed urgency values: today, this_week, flexible, null.\n"
        "Rules: preserve the user's meaning; ask at most one targeted clarification question; "
        "do not invent product IDs, order IDs, stores, prices, or locations; do not decide "
        "inventory, promotion, price, or eligibility facts.\n\n"
        f"User query: {query}"
    )


def _parse_json_object(text: str) -> Dict[str, Any]:
    return json.loads(text)


def _post_ollama(prompt: str, client: httpx.Client) -> str:
    settings = get_settings()
    response = client.post(
        f"{settings.ollama_base_url.rstrip('/')}/api/generate",
        json={
            "model": settings.ollama_chat_model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {"temperature": settings.ollama_chat_temperature},
        },
    )
    response.raise_for_status()
    payload = response.json()
    return str(payload.get("response", ""))


def _validated_llm_intent(query: str, client: httpx.Client) -> StructuredIntent:
    raw = _post_ollama(build_intent_prompt(query), client)
    return StructuredIntent.model_validate(_parse_json_object(raw))


def _mentioned_product_id(value: Optional[str], query: str) -> Optional[str]:
    if not value:
        return None
    normalized = value.strip().upper()
    return normalized if normalized.lower() in query.lower() else None


def _mentioned_order_id(value: Optional[str], query: str) -> Optional[str]:
    if not value:
        return None
    normalized = normalize_order_id(value)
    return normalized if normalized.lower() in query.lower() else None


def _mentioned_text(value: Optional[str], query: str) -> Optional[str]:
    if not value:
        return None
    stripped = value.strip()
    return stripped if stripped.lower() in query.lower() else None


def _mentioned_budget(value: Optional[float], query: str) -> Optional[float]:
    if value is None:
        return None
    text = f"{value:g}"
    return value if text in query else None


def sanitize_llm_intent(intent: StructuredIntent, query: str) -> StructuredIntent:
    comparison_ids = [
        product_id
        for product_id in (_mentioned_product_id(product_id, query) for product_id in intent.comparison_product_ids)
        if product_id is not None
    ]
    return intent.model_copy(
        update={
            "budget_min": _mentioned_budget(intent.budget_min, query),
            "budget_max": _mentioned_budget(intent.budget_max, query),
            "location": _mentioned_text(intent.location, query),
            "reference_product_id": _mentioned_product_id(intent.reference_product_id, query),
            "comparison_product_ids": comparison_ids,
            "order_id": _mentioned_order_id(intent.order_id, query),
        }
    )


def extract_intent_with_ollama(
    query: str,
    *,
    client: Optional[httpx.Client] = None,
    fallback_intent: Optional[StructuredIntent] = None,
) -> IntentExtractionResult:
    active_client = client or httpx.Client(timeout=2.0)
    close_client = client is None
    try:
        try:
            intent = _validated_llm_intent(query, active_client)
            return IntentExtractionResult(intent=sanitize_llm_intent(intent, query), extraction_source="llm")
        except (json.JSONDecodeError, ValidationError):
            intent = _validated_llm_intent(query, active_client)
            return IntentExtractionResult(intent=sanitize_llm_intent(intent, query), extraction_source="retry")
    except Exception:
        fallback = fallback_intent or StructuredIntent(
            request_type="clarification",
            needs_clarification=True,
            clarification_question="What product are you looking for?",
            confidence=0.0,
        )
        return IntentExtractionResult(intent=fallback, extraction_source="deterministic_fallback")
    finally:
        if close_client:
            active_client.close()
