"""GET /stores (Step 15).

Kept intentionally trivial: there is no business logic to a store
listing (no pricing, no ranking, no per-request interpretation), so
this route reads directly from StoreRepository rather than through an
empty pass-through service layer - the same "repositories are the SQL
boundary, everything else just reads typed models back" rule
scout/repositories/__init__.py already documents, applied to the
simplest possible case.
"""

from typing import List

from fastapi import APIRouter

from scout.api.schemas.stores import StoreSummary
from scout.repositories.store_repository import StoreRepository

router = APIRouter(tags=["stores"])


@router.get("/stores", response_model=List[StoreSummary])
def list_stores() -> List[StoreSummary]:
    """List Scout's active demo stores, for the pickup-store selector."""
    stores = StoreRepository().list_stores(active_only=True)
    return [
        StoreSummary(
            store_id=store.store_id,
            store_name=store.store_name,
            city=store.city,
            state=store.state,
            postal_code=store.postal_code,
            latitude=store.latitude,
            longitude=store.longitude,
            pickup_enabled=store.pickup_enabled,
            active=store.active,
        )
        for store in stores
    ]
