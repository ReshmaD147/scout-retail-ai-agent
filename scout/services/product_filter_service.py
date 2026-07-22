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
        if category is not None and product.category != category:
            return False
        if subcategory is not None and product.subcategory != subcategory:
            return False
        if brand is not None and product.brand != brand:
            return False
        if min_rating is not None:
            if product.rating is None or product.rating < min_rating:
                return False
        return True

    return [product for product in products if matches(product)]
