"""Deterministic promotion / discount calculation.

scout/database/schema.sql deliberately stores only the raw facts of a
promotion (a manual active flag, a date range, and a discount) and
defers deciding "is this promotion usable right now, and what does it
make the price" to the service layer. This module is that service:
Python compares today's date against the range, checks the manual
flag, and does the discount arithmetic. A language model never invents
or estimates a discounted price.
"""

from datetime import date
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from scout.repositories.models import Product, Promotion


class PriceResult(BaseModel):
    """The outcome of reconciling a product's promotions for one date."""

    original_price: float
    final_price: float
    applied_promotion_id: Optional[str] = None


def is_promotion_valid(promotion: Promotion, as_of: date) -> bool:
    """A promotion is usable only if BOTH are true:

    1. Its manual `active` flag is set to 1.
    2. `as_of` falls within [start_date, end_date], inclusive.

    Either condition failing means the promotion does not apply -
    an active flag cannot resurrect an expired date range, and a
    currently-valid date range cannot override a manual disable.

    Public (not prefixed with _) because the get_promotions MCP tool
    (scout/mcp/product_tools.py) also needs this exact reconciliation
    to report whether a promotion is currently usable, and it must stay
    identical to what calculate_price() uses - duplicating this check
    in two places would risk them drifting apart.
    """
    if not promotion.active:
        return False
    start = date.fromisoformat(promotion.start_date)
    end = date.fromisoformat(promotion.end_date)
    return start <= as_of <= end


def _apply_discount(price: float, promotion: Promotion) -> float:
    """Compute a discounted price, never letting it go below zero."""
    if promotion.discount_percent is not None:
        discounted = price * (1 - promotion.discount_percent / 100)
    elif promotion.discount_amount is not None:
        discounted = price - promotion.discount_amount
    else:
        discounted = price
    return round(max(discounted, 0.0), 2)


def calculate_price(
    product: Product,
    promotions: List[Promotion],
    as_of: Optional[date] = None,
) -> PriceResult:
    """Compute the effective price for a product given its promotions.

    Args:
        product: The product whose price may be discounted.
        promotions: Promotion rows to consider. Callers may pass every
            promotion they have for this product - active, inactive,
            past, or future - this function does the reconciliation,
            so repositories and callers don't need to pre-filter.
        as_of: The date to evaluate validity against. Defaults to
            today. Tests should always pass an explicit date so
            results are reproducible regardless of when they run.

    Returns:
        A PriceResult with the original price, the best (lowest) valid
        final price, and which promotion produced it. If no promotion
        is currently valid, final_price equals original_price and
        applied_promotion_id is None - a product with no valid
        promotion is not an error, it simply is not discounted.
    """
    resolved_date = as_of if as_of is not None else date.today()

    valid_promotions = [
        promotion
        for promotion in promotions
        if promotion.product_id == product.product_id
        and is_promotion_valid(promotion, resolved_date)
    ]

    if not valid_promotions:
        return PriceResult(
            original_price=product.price,
            final_price=product.price,
            applied_promotion_id=None,
        )

    priced_options = [
        (_apply_discount(product.price, promotion), promotion) for promotion in valid_promotions
    ]
    # Best deal for the customer = lowest final price. Ties are broken
    # by promotion_id so the result is deterministic regardless of the
    # order promotions were passed in.
    best_price, best_promotion = min(
        priced_options, key=lambda option: (option[0], option[1].promotion_id)
    )

    return PriceResult(
        original_price=product.price,
        final_price=best_price,
        applied_promotion_id=best_promotion.promotion_id,
    )


def build_verified_promotion_summary(
    product: Product,
    promotions: List[Promotion],
    promotion_id: str,
    as_of: Optional[date] = None,
) -> Optional[Dict[str, Any]]:
    """Return verified display data for one active product promotion.

    The product card can display this shape directly, but every value is
    calculated here from product + promotion repository facts.
    """
    promotion = next((item for item in promotions if item.promotion_id == promotion_id), None)
    if promotion is None or promotion.product_id != product.product_id:
        return None
    resolved_date = as_of if as_of is not None else date.today()
    if not is_promotion_valid(promotion, resolved_date):
        return None
    price_result = calculate_price(product, promotions, resolved_date)
    if price_result.applied_promotion_id != promotion.promotion_id:
        return None
    original_price = round(product.price, 2)
    promotional_price = round(price_result.final_price, 2)
    savings = round(original_price - promotional_price, 2)
    if savings <= 0:
        return None
    if promotion.discount_percent is not None:
        discount_type = "percent"
        discount_value = float(promotion.discount_percent)
        terms_summary = None
    elif promotion.discount_amount is not None:
        discount_type = "amount"
        discount_value = float(promotion.discount_amount)
        terms_summary = None
    else:
        return None
    return {
        "promotion_id": promotion.promotion_id,
        "label": promotion.label,
        "discount_type": discount_type,
        "discount_value": discount_value,
        "original_price": original_price,
        "promotional_price": promotional_price,
        "savings": savings,
        "valid_until": promotion.end_date,
        "terms_summary": terms_summary,
        "verified": True,
    }
