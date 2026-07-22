"""Deterministic catalog similarity.

"Similar" means: same category as a reference product (the caller
fetches same-category candidates via ProductRepository), optionally
within a maximum percent price difference, excluding the reference
product itself. No vector search or model is involved - see
scout/database/schema.sql for why vector retrieval, if added later,
would only ever propose candidates, never override this as the source
of truth for "similar."

This lives in the service layer specifically so that no MCP tool ever
needs to call another MCP tool to reuse this logic.
scout.mcp.product_tools.find_similar_products and
scout.mcp.inventory_tools.find_available_substitutes both fetch their
own candidates from ProductRepository and then call
filter_similar_candidates() directly - the tool-calling-tool pattern
that briefly existed for find_available_substitutes is exactly what
this module removes.
"""

from typing import List, Optional

from scout.repositories.models import Product


def filter_similar_candidates(
    reference: Product,
    candidates: List[Product],
    max_price_difference_percent: Optional[float] = 30.0,
) -> List[Product]:
    """Filter candidates down to those similar to `reference`.

    Args:
        reference: The product other candidates are compared against.
        candidates: Already-fetched candidate products (e.g. same
            category, from ProductRepository.list_active()).
        max_price_difference_percent: Maximum allowed price difference
            from reference.price, as a percent of that price. None
            disables the price filter entirely.

    Returns:
        candidates, excluding the reference product itself and, when
        max_price_difference_percent is given, any candidate outside
        that percent of the reference's price. Order is preserved -
        ranking is a separate step (scout.services.ranking_service).
    """
    filtered = [candidate for candidate in candidates if candidate.product_id != reference.product_id]

    if max_price_difference_percent is not None:
        allowed_difference = reference.price * (max_price_difference_percent / 100)
        filtered = [
            candidate
            for candidate in filtered
            if abs(candidate.price - reference.price) <= allowed_difference
        ]

    return filtered
