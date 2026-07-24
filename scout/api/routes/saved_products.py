"""Saved Products REST API.

This is a deterministic customer feature: routes call the saved product
service directly and never enter the autonomous agent graph.
"""

from typing import Optional

from fastapi import APIRouter, Query

from scout.api.exceptions import ScoutAppError
from scout.api.schemas.saved_products import SaveProductRequest
from scout.services.saved_product_service import (
    SavedProductServiceError,
    SavedProductsView,
    list_saved_product_ids,
    list_saved_products,
    remove_product,
    save_product,
)

router = APIRouter(prefix="/saved-products", tags=["saved-products"])

_ERROR_STATUS_CODES = {
    "missing_owner": 400,
    "product_not_found": 404,
}


def _as_app_error(exc: SavedProductServiceError) -> ScoutAppError:
    return ScoutAppError(
        exc.message,
        status_code=_ERROR_STATUS_CODES.get(exc.error_type, 400),
        code=exc.error_type.upper(),
    )


@router.get("", response_model=SavedProductsView)
def get_saved_products(
    session_id: Optional[str] = Query(default=None),
    customer_id: Optional[str] = Query(default=None),
) -> SavedProductsView:
    try:
        return list_saved_products(session_id, customer_id)
    except SavedProductServiceError as exc:
        raise _as_app_error(exc) from exc


@router.get("/ids", response_model=list[str])
def get_saved_product_ids(
    session_id: Optional[str] = Query(default=None),
    customer_id: Optional[str] = Query(default=None),
) -> list[str]:
    try:
        return list_saved_product_ids(session_id, customer_id)
    except SavedProductServiceError as exc:
        raise _as_app_error(exc) from exc


@router.post("", response_model=SavedProductsView)
def save_saved_product(request: SaveProductRequest) -> SavedProductsView:
    try:
        return save_product(request.session_id, request.product_id, request.customer_id)
    except SavedProductServiceError as exc:
        raise _as_app_error(exc) from exc


@router.delete("/{product_id}", response_model=SavedProductsView)
def delete_saved_product(
    product_id: str,
    session_id: Optional[str] = Query(default=None),
    customer_id: Optional[str] = Query(default=None),
) -> SavedProductsView:
    try:
        return remove_product(session_id, product_id, customer_id)
    except SavedProductServiceError as exc:
        raise _as_app_error(exc) from exc
