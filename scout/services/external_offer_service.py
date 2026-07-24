"""Deterministic matching and click tracking for external merchant fallback."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Literal, Optional, Sequence, Set, Tuple
from urllib.parse import urlparse

from scout.mcp.schemas import ExternalOfferSummary
from scout.repositories.affiliate_repository import AffiliateRepository
from scout.repositories.models import ExternalOfferRecord
from scout.repositories.product_repository import ProductRepository
from scout.services.external_merchant_adapter import ExternalMerchantAdapter, MockExternalMerchantAdapter

AFFILIATE_DISCLOSURE = (
    "Demo external offer. In a production affiliate integration, Scout may earn "
    "a commission from qualifying purchases. External checkout is handled by the retailer."
)

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
_STOP_WORDS = {
    "a", "an", "and", "at", "for", "from", "i", "in", "me", "my", "near",
    "of", "on", "or", "that", "the", "to", "under", "with", "today", "find",
    "looking", "want", "can", "pick", "up",
}
_SYNONYM_GROUPS: Tuple[Set[str], ...] = (
    {"comfortable", "comfort", "cushion", "cushioned", "foam", "support", "supportive"},
    {"standing", "shift", "shifts", "work", "workday", "service"},
    {"shoe", "shoes", "footwear", "sneaker", "sneakers", "clog", "clogs"},
    {"bag", "bags", "backpack", "tote", "duffel", "commute", "travel"},
    {"earbud", "earbuds", "audio", "wireless", "headphone", "headphones"},
    {"coffee", "maker", "brew", "brewer", "kitchen"},
    {"hiking", "trail", "outdoor", "boot", "boots", "waterproof"},
)


class ExternalOfferServiceError(Exception):
    def __init__(self, error_type: str, message: str) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.message = message


@dataclass(frozen=True)
class ReferenceIdentifiers:
    upc: Optional[str] = None
    gtin: Optional[str] = None
    model_number: Optional[str] = None


def _normalize_identifier(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    normalized = re.sub(r"[^A-Z0-9]", "", value.upper())
    return normalized or None


def _tokens(text: str) -> Set[str]:
    raw = {token for token in _TOKEN_PATTERN.findall(text.lower()) if token not in _STOP_WORDS}
    expanded = set(raw)
    for group in _SYNONYM_GROUPS:
        if raw & group:
            expanded.update(group)
    return expanded


def _offer_text(offer: ExternalOfferRecord) -> str:
    attributes = " ".join(
        str(value) for value in offer.attributes.values() if isinstance(value, (str, int, float))
    )
    tags = " ".join(str(tag) for tag in offer.attributes.get("tags", []))
    return " ".join(
        [
            offer.product_name,
            offer.brand,
            offer.category,
            offer.description,
            attributes,
            tags,
        ]
    )


def _exact_identifier_match(
    offer: ExternalOfferRecord, reference: Optional[ReferenceIdentifiers]
) -> Optional[str]:
    if reference is None:
        return None
    pairs = (
        ("UPC", reference.upc, offer.upc),
        ("GTIN", reference.gtin, offer.gtin),
        ("model number", reference.model_number, offer.model_number),
    )
    for label, reference_value, offer_value in pairs:
        normalized_reference = _normalize_identifier(reference_value)
        normalized_offer = _normalize_identifier(offer_value)
        if normalized_reference and normalized_offer and normalized_reference == normalized_offer:
            return label
    return None


def _score_offer(query_tokens: Set[str], offer: ExternalOfferRecord) -> Tuple[float, List[str]]:
    offer_tokens = _tokens(_offer_text(offer))
    overlap = sorted(query_tokens & offer_tokens)
    if not query_tokens:
        return 0.0, overlap
    coverage = len(overlap) / len(query_tokens)
    # Slight deterministic preference for more specific matches; price, rating,
    # and merchant are tie-breakers later. No commission field exists and no
    # commission signal is used anywhere in this score.
    specificity = min(len(overlap), 8) * 0.03
    return round(coverage + specificity, 6), overlap


def search_external_offers(
    *,
    query_text: str,
    category: Optional[str] = None,
    max_price: Optional[float] = None,
    reference_product_id: Optional[str] = None,
    reference_identifiers: Optional[ReferenceIdentifiers] = None,
    limit: int = 3,
    db_path: Optional[str] = None,
    adapter: Optional[ExternalMerchantAdapter] = None,
) -> List[ExternalOfferSummary]:
    """Return up to `limit` deterministic mock merchant matches.

    Category and budget are hard filters. Relevance score, lower price, higher
    rating, then offer_id determine order. Exact is allowed only when UPC, GTIN,
    or model number matches; otherwise the label is always "Similar external
    alternative," even if names happen to look alike.
    """
    if not query_text or not query_text.strip():
        raise ExternalOfferServiceError("validation_error", "query_text must not be empty")
    if max_price is not None and max_price < 0:
        raise ExternalOfferServiceError("validation_error", "max_price must be non-negative")
    if not (1 <= limit <= 20):
        raise ExternalOfferServiceError("validation_error", "limit must be between 1 and 20")

    active_adapter = adapter or MockExternalMerchantAdapter(db_path)
    query_tokens = _tokens(query_text)
    scored: List[Tuple[float, ExternalOfferRecord, str, Optional[str], List[str]]] = []

    for offer in active_adapter.list_available_offers():
        if category is not None and offer.category.casefold() != category.casefold():
            continue
        if max_price is not None and offer.price > max_price:
            continue

        exact_identifier = _exact_identifier_match(offer, reference_identifiers)
        score, overlap = _score_offer(query_tokens, offer)
        if exact_identifier is None and score <= 0:
            continue
        match_type: Literal["exact", "similar"] = "exact" if exact_identifier else "similar"
        if exact_identifier:
            score += 10.0
        scored.append((score, offer, match_type, exact_identifier, overlap))

    scored.sort(
        key=lambda entry: (
            -entry[0],
            entry[1].price,
            -(entry[1].rating or 0.0),
            entry[1].offer_id,
        )
    )

    summaries: List[ExternalOfferSummary] = []
    for score, offer, match_type, exact_identifier, overlap in scored[:limit]:
        if match_type == "exact":
            match_label = f"Exact external match by {exact_identifier}"
            match_reason = f"The external offer has the same verified {exact_identifier}."
        else:
            match_label = "Similar external alternative"
            matched_terms = ", ".join(overlap[:4])
            match_reason = (
                f"Matches requested needs such as {matched_terms}."
                if matched_terms
                else "Matches the requested product category and budget."
            )
        summaries.append(
            ExternalOfferSummary(
                offer_id=offer.offer_id,
                merchant_name=offer.merchant_name,
                external_product_id=offer.external_product_id,
                product_name=offer.product_name,
                brand=offer.brand,
                category=offer.category,
                description=offer.description,
                price=offer.price,
                currency=offer.currency,
                rating=offer.rating,
                review_count=offer.review_count,
                availability_status=offer.availability_status,
                image_url=offer.image_url,
                match_type=match_type,
                match_label=match_label,
                match_reason=match_reason,
                source_product_id=reference_product_id,
                matched_identifier_type=exact_identifier,
                observed_at=offer.updated_at,
                same_product_verified=match_type == "exact" and exact_identifier is not None,
                affiliate_disclosure=AFFILIATE_DISCLOSURE,
                evidence_ids=[f"external-offer-{offer.offer_id}"],
                relevance_score=round(score, 6),
                disclosure=AFFILIATE_DISCLOSURE,
            )
        )
    return summaries


def get_external_offer(offer_id: str, *, db_path: Optional[str] = None) -> ExternalOfferRecord:
    if not offer_id or not offer_id.strip():
        raise ExternalOfferServiceError("validation_error", "offer_id must not be empty")
    offer = MockExternalMerchantAdapter(db_path).get_offer(offer_id)
    if offer is None:
        raise ExternalOfferServiceError("not_found", "External offer was not found")
    return offer


def track_affiliate_click(
    *,
    offer_id: str,
    session_id: str,
    match_type: Literal["exact", "similar"],
    workflow_id: Optional[str] = None,
    source_product_id: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Tuple[str, str]:
    """Persist one click and return (click_id, mock merchant redirect URL)."""
    if not session_id or not session_id.strip():
        raise ExternalOfferServiceError("validation_error", "session_id must not be empty")
    if match_type not in ("exact", "similar"):
        raise ExternalOfferServiceError("validation_error", "match_type must be exact or similar")

    offer = get_external_offer(offer_id, db_path=db_path)
    if not offer.active or offer.availability_status != "in_stock":
        raise ExternalOfferServiceError("offer_unavailable", "External offer is no longer available")

    parsed_url = urlparse(offer.merchant_url)
    if parsed_url.scheme != "https" or not parsed_url.hostname:
        raise ExternalOfferServiceError(
            "invalid_merchant_url",
            "External merchant destination is not configured safely",
        )

    normalized_source_product_id = source_product_id.strip() if source_product_id else None
    if normalized_source_product_id and ProductRepository(db_path).get_by_id(normalized_source_product_id) is None:
        raise ExternalOfferServiceError("not_found", "Source Scout product was not found")

    normalized_workflow_id = workflow_id.strip() if workflow_id else None
    if len(session_id.strip()) > 128:
        raise ExternalOfferServiceError("validation_error", "session_id must be 128 characters or fewer")
    if normalized_workflow_id and len(normalized_workflow_id) > 128:
        raise ExternalOfferServiceError("validation_error", "workflow_id must be 128 characters or fewer")

    click = AffiliateRepository(db_path).record_click(
        offer_id=offer.offer_id,
        session_id=session_id.strip(),
        workflow_id=normalized_workflow_id,
        source_product_id=normalized_source_product_id,
        match_type=match_type,
    )
    return click.click_id, offer.merchant_url
