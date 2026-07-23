"""Deterministic product filtering.

Applies hard-constraint filters (category, subcategory, brand, minimum
rating, active status) to an in-memory list of Product models, in
plain Python - no SQL, no model calls. This is intentionally decoupled
from however the candidate list was produced, so it works the same way
whether the products came from ProductRepository.search() today or
from a vector-search candidate set in a later phase.

Budget/price filtering is deliberately NOT handled here - see
budget_service.py. Keeping "is this product even eligible" separate
from "is this product affordable" keeps each service doing exactly one
job, which is easier to test and reason about than one filter function
that does everything.
"""

from typing import List, Optional

from scout.repositories.models import Product


def filter_products(
    products: List[Product],
    category: Optional[str] = None,
    subcategory: Optional[str] = None,
    brand: Optional[str] = None,
    min_rating: Optional[float] = None,
    attributes: Optional[List[str]] = None,
    active_only: bool = True,
) -> List[Product]:
    """Apply deterministic hard-constraint filters, combined with AND.

    Args:
        products: Candidate products already fetched from somewhere
            (a repository search, for example).
        category: Exact category a product must have.
        subcategory: Exact subcategory a product must have.
        brand: Exact brand a product must have.
        min_rating: Minimum rating (inclusive) a product must have. A
            product with no rating (None) never satisfies a min_rating
            filter - a missing rating is not treated as "unknown, so
            let it through."
        active_only: If True (default), inactive products are removed.

    Returns:
        The subset of `products` that satisfies every supplied filter,
        preserving the input order. Empty list if nothing matches -
        this is a normal result, not an error.
    """

    def matches(product: Product) -> bool:
        if active_only and not product.active:
            return False
        if category is not None and product.category.casefold() != category.casefold():
            return False
        if subcategory is not None and product.subcategory.casefold() != subcategory.casefold():
            return False
        if brand is not None and product.brand.casefold() != brand.casefold():
            return False
        if min_rating is not None:
            if product.rating is None or product.rating < min_rating:
                return False
        if attributes and not all(_matches_attribute_token(product, token) for token in attributes):
            return False
        return True

    return [product for product in products if matches(product)]


def _normalise(value: object) -> str:
    return " ".join(str(value).strip().casefold().replace("_", " ").split())


def _matches_attribute_token(product: Product, token: str) -> bool:
    """Match one backend-issued attribute token against authoritative data.

    Tokens returned by ``GET /catalog/filter-options`` have the form
    ``key:value`` and are matched exactly (case-insensitively) against
    the product's attributes.  A plain token is accepted for API
    clients that do not use the discovery endpoint, but it still only
    matches text present in the real attribute key/value pair.
    """
    raw = token.strip()
    if ":" in raw:
        key_text, value_text = raw.split(":", 1)
        wanted_key = _normalise(key_text)
        wanted_value = _normalise(value_text)
        for key, value in product.attributes.items():
            if _normalise(key) != wanted_key:
                continue
            if isinstance(value, list):
                return any(_normalise(item) == wanted_value for item in value)
            return _normalise(value) == wanted_value
        return False

    needle = _normalise(raw)
    haystack = " ".join(
        f"{_normalise(key)} {_normalise(item)}"
        for key, value in product.attributes.items()
        for item in (value if isinstance(value, list) else [value])
    )
    return needle in haystack
