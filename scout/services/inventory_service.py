"""Deterministic inventory availability evaluation.

Turns one raw inventory row into a clear availability status. Python
does the arithmetic (available minus reserved, compared against a
threshold and today's restock information) - nothing here is a
judgment call an agent or model makes; it's a fixed set of rules
applied to numbers already validated by the database.
"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel

from scout.repositories.models import InventoryRecord

DEFAULT_LOW_STOCK_THRESHOLD = 3


class AvailabilityStatus(str, Enum):
    """The possible outcomes of evaluating one inventory row."""

    NOT_TRACKED = "not_tracked"
    OUT_OF_STOCK = "out_of_stock"
    RESTOCK_SCHEDULED = "restock_scheduled"
    LOW_STOCK = "low_stock"
    IN_STOCK = "in_stock"


class AvailabilityResult(BaseModel):
    """The result of evaluating a product's availability at one store."""

    status: AvailabilityStatus
    sellable_quantity: int
    restock_date: Optional[str] = None


def evaluate_availability(
    record: Optional[InventoryRecord],
    low_stock_threshold: int = DEFAULT_LOW_STOCK_THRESHOLD,
) -> AvailabilityResult:
    """Turn one inventory row into a deterministic availability status.

    Args:
        record: The inventory row for this product at this store, or
            None if the product is not tracked there at all (no row -
            different from a row that says zero, see
            InventoryRepository.get_for_product_and_store).
        low_stock_threshold: A sellable quantity at or below this
            number (but still greater than zero) is reported as
            LOW_STOCK instead of IN_STOCK.

    Returns:
        An AvailabilityResult. sellable_quantity is always
        `max(quantity_available - quantity_reserved, 0)` - reserved
        units are never counted as available to sell, even when
        quantity_available alone is positive. status is:
          - NOT_TRACKED: record is None.
          - RESTOCK_SCHEDULED: nothing sellable, but a restock_date is
            on file.
          - OUT_OF_STOCK: nothing sellable, and no restock_date.
          - LOW_STOCK: sellable, but at or below low_stock_threshold.
          - IN_STOCK: sellable, above low_stock_threshold.
    """
    if record is None:
        return AvailabilityResult(
            status=AvailabilityStatus.NOT_TRACKED, sellable_quantity=0, restock_date=None
        )

    sellable_quantity = max(record.quantity_available - record.quantity_reserved, 0)

    if sellable_quantity <= 0:
        status = (
            AvailabilityStatus.RESTOCK_SCHEDULED
            if record.restock_date
            else AvailabilityStatus.OUT_OF_STOCK
        )
    elif sellable_quantity <= low_stock_threshold:
        status = AvailabilityStatus.LOW_STOCK
    else:
        status = AvailabilityStatus.IN_STOCK

    return AvailabilityResult(
        status=status,
        sellable_quantity=sellable_quantity,
        restock_date=record.restock_date,
    )


def can_fulfill(record: Optional[InventoryRecord], quantity_needed: int = 1) -> bool:
    """Whether at least `quantity_needed` units can be sold right now.

    Args:
        record: The inventory row to check, or None if untracked.
        quantity_needed: How many units are needed. Must be positive.

    Returns:
        True if sellable_quantity >= quantity_needed.

    Raises:
        ValueError: If quantity_needed is not positive.
    """
    if quantity_needed <= 0:
        raise ValueError("quantity_needed must be greater than 0")
    return evaluate_availability(record).sellable_quantity >= quantity_needed
