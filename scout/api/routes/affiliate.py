"""Thin API routes for mock external-offer search and click tracking."""

from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Query
from fastapi.responses import RedirectResponse

from scout.api.exceptions import ScoutAppError
from scout.api.schemas.affiliate import ExternalOfferSearchRequest, ExternalOfferSearchResponse
from scout.mcp.affiliate_tools import search_external_offers
from scout.services.external_offer_service import ExternalOfferServiceError, track_affiliate_click

router = APIRouter(prefix="/affiliate", tags=["affiliate"])


@router.post("/offers/search", response_model=ExternalOfferSearchResponse)
def search_offers(request: ExternalOfferSearchRequest) -> ExternalOfferSearchResponse:
    result = search_external_offers(
        query_text=request.query_text,
        category=request.category,
        max_price=request.max_price,
        limit=request.limit,
    )
    if result.error is not None:
        raise ScoutAppError(
            result.error.message,
            status_code=400 if result.error.error_type == "validation_error" else 404,
            code=result.error.error_type.upper(),
        )
    return ExternalOfferSearchResponse(offers=result.offers, count=result.count)


@router.get("/click/{offer_id}")
def click_offer(
    offer_id: str,
    session_id: str = Query(min_length=1, max_length=128),
    match_type: Literal["exact", "similar"] = Query(),
    workflow_id: Optional[str] = Query(default=None, max_length=128),
    source_product_id: Optional[str] = Query(default=None, max_length=128),
) -> RedirectResponse:
    """Record a click, then redirect to the mock merchant URL.

    This endpoint never adds a product to Scout's cart and never creates an
    external payment/order. `merchant_url` is intentionally kept server-side so
    every outbound click passes through this audit point.
    """
    try:
        _click_id, redirect_url = track_affiliate_click(
            offer_id=offer_id,
            session_id=session_id,
            workflow_id=workflow_id,
            source_product_id=source_product_id,
            match_type=match_type,
        )
    except ExternalOfferServiceError as exc:
        status = 404 if exc.error_type == "not_found" else 409 if exc.error_type == "offer_unavailable" else 400
        raise ScoutAppError(exc.message, status_code=status, code=exc.error_type.upper()) from exc
    return RedirectResponse(url=redirect_url, status_code=307)
