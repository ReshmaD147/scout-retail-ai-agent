"""Deterministic product ranking.

Produces a fully reproducible order over a list of products using only
fields already validated by the database - rating, review_count,
price, and product_id as a final tiebreaker. Nothing here is inferred
or guessed by a model; the same input always produces the same output,
in the same order, regardless of what order it was given in.
"""

from typing import List, Tuple

from pydantic import BaseModel

from scout.repositories.models import Product


class RankedProduct(BaseModel):
    """One product plus its position and the components that produced it."""

    product: Product
    rank: int
    rating_component: float
    review_component: int
    price_component: float


def _sort_key(product: Product) -> Tuple[bool, float, int, float, str]:
    """Build the deterministic sort key for one product.

    Ordering, most significant first:
      1. Missing rating (None) sorts after every rated product - a
         missing rating is never guessed at or treated as average.
      2. Rating, descending.
      3. review_count, descending - more reviews backing a given
         rating is preferred as a tiebreaker.
      4. price, ascending - all else equal, cheaper first.
      5. product_id, ascending - the final, unconditional tiebreaker,
         guaranteeing a stable order even when every other component
         ties, no matter what order the input list was in.
    """
    rating_is_missing = product.rating is None
    return (
        rating_is_missing,
        -(product.rating or 0.0),
        -product.review_count,
        product.price,
        product.product_id,
    )


def rank_products(products: List[Product]) -> List[RankedProduct]:
    """Deterministically rank products, highest-ranked first.

    Args:
        products: The products to rank. The input order does not
            affect the result.

    Returns:
        RankedProduct entries in ranked order, rank starting at 1. Each
        entry exposes the individual components (rating_component,
        review_component, price_component) that went into its
        position, so a caller can explain a ranking without re-deriving
        it.
    """
    ordered = sorted(products, key=_sort_key)

    return [
        RankedProduct(
            product=product,
            rank=index + 1,
            rating_component=product.rating if product.rating is not None else 0.0,
            review_component=product.review_count,
            price_component=product.price,
        )
        for index, product in enumerate(ordered)
    ]
