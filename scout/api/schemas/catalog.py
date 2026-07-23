"""Public response models for catalog-backed recommendation filters."""

from typing import Dict, List

from pydantic import BaseModel, Field


class CatalogAttributeOptionResponse(BaseModel):
    token: str
    label: str
    key: str
    value: str
    categories: List[str] = Field(default_factory=list)
    product_types: List[str] = Field(default_factory=list)


class CatalogFilterOptionsResponse(BaseModel):
    max_price: float
    categories: List[str]
    product_types: Dict[str, List[str]]
    attributes: List[CatalogAttributeOptionResponse]
