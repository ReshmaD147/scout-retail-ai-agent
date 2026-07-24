"""Grounded product explanations from approved structured evidence."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Literal, Optional

import httpx
from pydantic import BaseModel, Field, ValidationError

from scout.config import get_settings

ExplanationSource = Literal["ollama", "retry", "deterministic_fallback"]


class ProductExplanationEvidence(BaseModel):
    product_id: str
    product_name: str
    category: str
    product_type: str
    regular_price: float
    promotional_price: Optional[float] = None
    budget_compliant: Optional[bool] = None
    matched_attributes: List[str] = Field(default_factory=list)
    matched_use_case: Optional[str] = None
    inventory: Optional[Dict[str, Any]] = None
    fulfillment: Optional[Dict[str, Any]] = None
    promotion: Optional[Dict[str, Any]] = None
    rating: Optional[float] = None
    review_count: Optional[int] = None
    evidence_ids: List[str] = Field(default_factory=list)


class ProductExplanation(BaseModel):
    product_id: str
    explanation: str = Field(min_length=1, max_length=500)
    source: ExplanationSource = "deterministic_fallback"


_ATTRIBUTE_LABELS = {
    "high": "high cushioning",
    "wide": "wide fit",
    "comfort": "comfort support",
    "comfortable": "comfort support",
    "support": "arch support",
    "slip resistant": "slip-resistant sole",
    "slip resistance": "slip-resistant sole",
    "high slip resistance": "slip-resistant sole",
    "work shifts / standing all day": "designed for long work shifts",
    "standing all day": "designed for long work shifts",
    "work": "designed for long work shifts",
}


def normalize_attribute_labels(attributes: List[str]) -> List[str]:
    labels: List[str] = []
    for attribute in attributes:
        normalized = re.sub(r"\s+", " ", attribute.replace("_", " ").replace("-", " ").strip().lower())
        label = _ATTRIBUTE_LABELS.get(normalized, normalized)
        if label and label not in labels:
            labels.append(label)
    return labels


def build_prompt(evidence: ProductExplanationEvidence, user_query: str) -> str:
    prompt_evidence = evidence.model_copy(update={"matched_attributes": normalize_attribute_labels(evidence.matched_attributes)})
    return (
        "Return strict JSON only with keys product_id and explanation.\n"
        "Explain how this product matches the customer's actual request using only the evidence JSON.\n"
        "Use two or three short sentences. Mention useful verified attributes, budget compliance, "
        "fulfillment, and active promotion only when present in evidence.\n"
        "Do not say best, perfect, highest quality, or calculate prices/savings. Do not introduce new facts.\n\n"
        f"Customer request: {user_query}\n"
        f"Evidence: {prompt_evidence.model_dump_json()}"
    )


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
    return str(response.json().get("response", ""))


def _parse_explanation(raw: str, expected_product_id: str) -> ProductExplanation:
    parsed = json.loads(raw)
    explanation = ProductExplanation.model_validate(parsed)
    if explanation.product_id != expected_product_id:
        raise ValueError("explanation product_id did not match evidence")
    return explanation


def deterministic_fallback(evidence: ProductExplanationEvidence) -> ProductExplanation:
    matched_attributes = normalize_attribute_labels(evidence.matched_attributes)
    parts = [f"{evidence.product_name} matches your request"]
    if matched_attributes:
        parts.append(f"because its {', '.join(matched_attributes[:3])} fit the request")
    elif evidence.product_type:
        parts.append(f"as a {evidence.product_type.lower()} option")
    sentence = " ".join(parts) + "."
    details: List[str] = []
    if evidence.budget_compliant is True:
        price = evidence.promotional_price if evidence.promotional_price is not None else evidence.regular_price
        details.append(f"Its verified price is ${price:.2f} and within your budget")
    if evidence.inventory:
        quantity = evidence.inventory.get("quantity")
        scope = evidence.inventory.get("scope")
        if quantity is not None and scope:
            details.append(f"inventory is verified at {quantity} available across {scope}")
    if evidence.promotion and evidence.promotion.get("verified"):
        details.append(f"the {evidence.promotion.get('label')} promotion is verified active")
    if details:
        joined = "; ".join(details)
        sentence = f"{sentence} {joined[:1].upper()}{joined[1:]}."
    return ProductExplanation(product_id=evidence.product_id, explanation=sentence, source="deterministic_fallback")


def verify_explanation(explanation: str, evidence: ProductExplanationEvidence) -> bool:
    text = explanation.lower()
    allowed_names = {evidence.product_name.lower(), evidence.category.lower(), evidence.product_type.lower()}
    allowed_attributes = {item.lower() for item in normalize_attribute_labels(evidence.matched_attributes)}
    mentions_promotion = re.search(r"\bpromotion\b", text) is not None
    if evidence.promotion is None and mentions_promotion:
        return False
    if evidence.promotion is not None:
        label = str(evidence.promotion.get("label", "")).lower()
        if label and label not in text and mentions_promotion:
            return False
    for amount in re.findall(r"\$(\d+(?:\.\d{1,2})?)", explanation):
        value = float(amount)
        allowed_prices = {round(evidence.regular_price, 2)}
        if evidence.promotional_price is not None:
            allowed_prices.add(round(evidence.promotional_price, 2))
        promotion = evidence.promotion or {}
        savings = promotion.get("savings")
        if isinstance(savings, (int, float)):
            allowed_prices.add(round(float(savings), 2))
        if round(value, 2) not in allowed_prices:
            return False
    if "best" in text or "perfect" in text or "highest quality" in text:
        return False
    supported_terms = allowed_names | allowed_attributes | {"budget", "price", "verified", "available", "inventory", "delivery", "pickup", "promotion", "active", "rating", "reviews", "request", "matches", "features", "option", "within", "store", "network"}
    content_words = {word for word in re.findall(r"[a-z][a-z-]{3,}", text)}
    unsupported_feature_words = {"waterproof", "leather", "steel", "toe", "insulated", "premium"} - supported_terms
    return not bool(content_words & unsupported_feature_words)


def generate_explanation(
    evidence: ProductExplanationEvidence,
    user_query: str,
    *,
    client: Optional[httpx.Client] = None,
) -> ProductExplanation:
    active_client = client or httpx.Client(timeout=2.0)
    close_client = client is None
    try:
        for source in ("ollama", "retry"):
            try:
                result = _parse_explanation(_post_ollama(build_prompt(evidence, user_query), active_client), evidence.product_id)
                if verify_explanation(result.explanation, evidence):
                    return result.model_copy(update={"source": source})
            except (json.JSONDecodeError, ValidationError, ValueError, httpx.HTTPError):
                continue
        return deterministic_fallback(evidence)
    finally:
        if close_client:
            active_client.close()
