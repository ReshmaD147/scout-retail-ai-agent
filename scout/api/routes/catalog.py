"""Read-only catalog metadata used to render real filter controls."""

from fastapi import APIRouter

from scout.api.schemas.catalog import CatalogFilterOptionsResponse
from scout.services.catalog_filter_service import build_catalog_filter_options

router = APIRouter(tags=["catalog"])


@router.get("/catalog/filter-options", response_model=CatalogFilterOptionsResponse)
def catalog_filter_options() -> CatalogFilterOptionsResponse:
    return CatalogFilterOptionsResponse.model_validate(build_catalog_filter_options().model_dump())
