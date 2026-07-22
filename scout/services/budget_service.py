"""Deterministic budget enforcement.

A customer's stated budget ("under $100") is a hard constraint: Python
compares prices and enforces it directly, every time, the same way.
Nothing here ever asks a language model whether a price fits a budget.
"""

from typing import List

from scout.repositories.models import Product


def is_within_budget(price: float, max_budget: float) -> bool:
    """Whether a price satisfies a maximum budget, boundary included.

    Args:
        price: The price to check.
        max_budget: The maximum the customer is willing to pay.

    Returns:
        True if price <= max_budget. A price exactly equal to the
        budget counts as within budget - "under $100" is treated as
        "$100 or less," matching the primary example workflow.

    Raises:
        ValueError: If max_budget is negative. A negative budget is an
            invalid input, not something to silently reinterpret.
    """
    if max_budget < 0:
        raise ValueError("max_budget must not be negative")
    return price <= max_budget


def filter_within_budget(products: List[Product], max_budget: float) -> List[Product]:
    """Keep only products priced at or under max_budget.

    Args:
        products: Candidate products to check.
        max_budget: The maximum price to allow, inclusive.

    Returns:
        The subset of `products` whose price satisfies
        is_within_budget(), preserving input order.
    """
    return [product for product in products if is_within_budget(product.price, max_budget)]
