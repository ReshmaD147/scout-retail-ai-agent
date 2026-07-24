"""Deterministic relevance checks before Scout explains products."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from scout.mcp.schemas import ProductSummary


class RelevanceResult(BaseModel):
    product_id: str
    passed: bool
    reasons: List[str] = Field(default_factory=list)
    matched_attributes: List[str] = Field(default_factory=list)


_ATTRIBUTE_ALIASES = {
    "comfortable": ["cushioning", "comfort", "memory foam", "arch support"],
    "comfort": ["cushioning", "comfort", "memory foam", "arch support"],
    "supportive": ["support", "arch support", "cushioning"],
    "support": ["support", "arch support", "cushioning"],
    "slip": ["slip", "slip resistance", "slip resistant"],
    "wide": ["wide", "wide width", "wide fit"],
    "travel": ["travel", "luggage", "carry-on", "backpack"],
}


def _clean(value: Any) -> str:
    return str(value).replace("_", " ").replace("-", " ").strip().lower()


def _product_terms(product: ProductSummary) -> List[str]:
    terms = [
        product.name,
        product.brand,
        product.category,
        product.subcategory,
    ]
    for key, value in (product.attributes or {}).items():
        terms.append(str(key))
        if isinstance(value, list):
            terms.extend(str(item) for item in value)
        else:
            terms.append(str(value))
    return [_clean(term) for term in terms if str(term).strip()]


def _required_attributes(intent: Dict[str, Any], query: str) -> List[str]:
    requested = list(intent.get("attribute_filters") or []) + list(intent.get("attributes") or [])
    query_lower = query.lower()
    for word in _ATTRIBUTE_ALIASES:
        if word in query_lower and word not in requested:
            requested.append(word)
    return [str(item).strip() for item in requested if str(item).strip()]


def _attribute_matches(attribute: str, terms: List[str]) -> bool:
    attribute_lower = _clean(attribute)
    aliases = _ATTRIBUTE_ALIASES.get(attribute_lower, [attribute_lower])
    return any(alias in term or term in alias for alias in aliases for term in terms)


def check_product_relevance(
    product: ProductSummary,
    intent: Dict[str, Any],
    query: str,
) -> RelevanceResult:
    reasons: List[str] = []
    matched_attributes: List[str] = []

    category = intent.get("category")
    if category and product.category.lower() != str(category).lower():
        return RelevanceResult(
            product_id=product.product_id,
            passed=False,
            reasons=[f"category {product.category!r} does not match requested {category!r}"],
        )
    if category:
        reasons.append(f"category matched {product.category}")

    subcategory = intent.get("subcategory") or intent.get("product_type")
    if subcategory and str(subcategory).lower() not in product.subcategory.lower():
        return RelevanceResult(
            product_id=product.product_id,
            passed=False,
            reasons=[f"product type {product.subcategory!r} does not match requested {subcategory!r}"],
        )
    if subcategory:
        reasons.append(f"product type matched {product.subcategory}")

    max_price = intent.get("max_price") or intent.get("budget_max")
    if max_price is not None and product.price > float(max_price):
        return RelevanceResult(
            product_id=product.product_id,
            passed=False,
            reasons=[f"price {product.price:.2f} exceeds budget {float(max_price):.2f}"],
        )
    if max_price is not None:
        reasons.append(f"price is within ${float(max_price):.2f} budget")

    terms = _product_terms(product)
    for attribute in _required_attributes(intent, query):
        if _attribute_matches(attribute, terms):
            matched_attributes.append(attribute)
        else:
            return RelevanceResult(
                product_id=product.product_id,
                passed=False,
                reasons=[f"required attribute {attribute!r} was not verified"],
                matched_attributes=matched_attributes,
            )

    if matched_attributes:
        reasons.append(f"matched attributes: {', '.join(matched_attributes)}")
    if not reasons:
        reasons.append("matched retrieved product evidence")
    return RelevanceResult(
        product_id=product.product_id,
        passed=True,
        reasons=reasons,
        matched_attributes=matched_attributes,
    )


def filter_relevant_products(
    products: List[ProductSummary],
    intent: Dict[str, Any],
    query: str,
) -> Tuple[List[ProductSummary], List[RelevanceResult]]:
    results = [check_product_relevance(product, intent, query) for product in products]
    passed_ids = {result.product_id for result in results if result.passed}
    return [product for product in products if product.product_id in passed_ids], results
