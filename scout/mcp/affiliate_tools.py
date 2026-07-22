"""Approved MCP tools for Step 16.5 external merchant fallback."""

from __future__ import annotations

from typing import Literal, Optional

from scout.mcp.schemas import (
    ExternalOfferDetail,
    GetExternalOfferResult,
    SearchExternalOffersResult,
    ToolError,
    TrackAffiliateClickResult,
)
from scout.mcp.server import mcp_server
from scout.services.external_offer_service import (
    ExternalOfferServiceError,
    get_external_offer,
    search_external_offers as search_service,
    track_affiliate_click as track_service,
)


@mcp_server.tool()
def search_external_offers(
    query_text: str,
    category: Optional[str] = None,
    max_price: Optional[float] = None,
    limit: int = 3,
) -> SearchExternalOffersResult:
    """Search the synthetic external-offer feed after internal options fail.

    Category and budget are deterministic hard filters. Ranking uses request
    relevance, price, rating, and a stable offer-id tie-breaker; no commission
    value exists or participates. "Exact" is returned only when an explicitly
    verified identifier data is intentionally not accepted by this current tool,
    because Scout's synthetic internal catalog has no authoritative UPC/GTIN/model
    fields yet. Therefore this Step 16.5 tool returns similar alternatives only.
    """
    try:
        offers = search_service(
            query_text=query_text,
            category=category,
            max_price=max_price,
            limit=limit,
        )
    except ExternalOfferServiceError as exc:
        return SearchExternalOffersResult(
            offers=[], count=0, error=ToolError(error_type=exc.error_type, message=exc.message)
        )
    return SearchExternalOffersResult(offers=offers, count=len(offers), error=None)


@mcp_server.tool()
def get_external_offer_details(offer_id: str) -> GetExternalOfferResult:
    """Re-read one external offer for final grounding verification.

    The direct merchant URL is intentionally not returned. Browser navigation
    must go through the affiliate click endpoint/tool so the click is recorded.
    """
    try:
        offer = get_external_offer(offer_id)
    except ExternalOfferServiceError as exc:
        return GetExternalOfferResult(
            offer=None, error=ToolError(error_type=exc.error_type, message=exc.message)
        )
    return GetExternalOfferResult(
        offer=ExternalOfferDetail(
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
            upc=offer.upc,
            gtin=offer.gtin,
            model_number=offer.model_number,
            active=offer.active,
        ),
        error=None,
    )


@mcp_server.tool()
def track_affiliate_click(
    offer_id: str,
    session_id: str,
    match_type: Literal["exact", "similar"],
    workflow_id: Optional[str] = None,
    source_product_id: Optional[str] = None,
) -> TrackAffiliateClickResult:
    """Record one external-offer click and return its mock redirect URL.

    This is click analytics only: it never creates a Scout cart item, payment,
    or order and does not claim a purchase occurred.
    """
    try:
        click_id, redirect_url = track_service(
            offer_id=offer_id,
            session_id=session_id,
            workflow_id=workflow_id,
            source_product_id=source_product_id,
            match_type=match_type,
        )
    except ExternalOfferServiceError as exc:
        return TrackAffiliateClickResult(
            click_id=None,
            redirect_url=None,
            error=ToolError(error_type=exc.error_type, message=exc.message),
        )
    return TrackAffiliateClickResult(click_id=click_id, redirect_url=redirect_url, error=None)
