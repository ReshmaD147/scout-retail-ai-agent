"""Build catalog-backed filter choices for the React UI.

The service reads typed Product models through ProductRepository and
only exposes categories, subcategories, prices, and scalar attributes
that actually exist in the active catalog.  It performs no SQL itself
and invents no merchandising labels.
"""

from collections import defaultdict
from math import ceil
from typing import Dict, List, Set, Tuple

from pydantic import BaseModel, Field

from scout.repositories.product_repository import ProductRepository


class CatalogAttributeOption(BaseModel):
    token: str
    label: str
    key: str
    value: str
    categories: List[str] = Field(default_factory=list)
    product_types: List[str] = Field(default_factory=list)


class CatalogFilterOptions(BaseModel):
    max_price: float
    categories: List[str]
    product_types: Dict[str, List[str]]
    attributes: List[CatalogAttributeOption]


def _humanize_key(key: str) -> str:
    return key.replace("_", " ").strip()


def _humanize_value(value: object) -> str:
    return str(value).replace("_", " ").strip()


def _label_for(key: str, value: object) -> str:
    human_key = _humanize_key(key)
    human_value = _humanize_value(value)
    if key in {"cushioning", "width", "slip_resistance"}:
        return f"{human_value.title()} {human_key}"
    if key == "water_resistance":
        return human_value.replace("-", " ").title()
    if key == "use_case":
        return f"Use case: {human_value}"
    return f"{human_value} {human_key}".strip()


def build_catalog_filter_options() -> CatalogFilterOptions:
    products = ProductRepository().list_active(limit=1000)
    categories = sorted({product.category for product in products})
    product_types: Dict[str, List[str]] = {
        category: sorted({product.subcategory for product in products if product.category == category})
        for category in categories
    }

    attribute_scope: Dict[Tuple[str, str], Dict[str, Set[str]]] = defaultdict(
        lambda: {"categories": set(), "product_types": set()}
    )
    for product in products:
        for key, value in product.attributes.items():
            # Large list-valued fields such as size_options are valid
            # catalog data but make poor global checkbox filters. They
            # remain searchable in natural language and are simply not
            # advertised as compact UI facets here.
            if isinstance(value, (list, dict)) or value is None:
                continue
            value_text = str(value).strip()
            if not value_text or value_text.casefold() in {"n/a", "none"}:
                continue
            scope = attribute_scope[(key, value_text)]
            scope["categories"].add(product.category)
            scope["product_types"].add(product.subcategory)

    attributes = [
        CatalogAttributeOption(
            token=f"{key}:{value}",
            label=_label_for(key, value),
            key=key,
            value=value,
            categories=sorted(scope["categories"]),
            product_types=sorted(scope["product_types"]),
        )
        for (key, value), scope in attribute_scope.items()
    ]
    attributes.sort(key=lambda option: (option.label.casefold(), option.token.casefold()))

    return CatalogFilterOptions(
        max_price=float(ceil(max((product.price for product in products), default=500.0))),
        categories=categories,
        product_types=product_types,
        attributes=attributes,
    )
