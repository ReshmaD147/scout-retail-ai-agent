"""Deterministic fulfillment decisions.

Pickup availability, network-wide ("online") availability aggregation,
delivery-window estimation, and the weak-fulfillment rule that decides
when substitutes are worth looking for. Every function here is pure
Python operating on already-fetched domain models (InventoryRecord) -
no SQL, no network calls, no LLM. Fetching those models from the
database is the MCP tool layer's job (scout/mcp/inventory_tools.py);
deciding what they mean is this module's job.
"""

from typing import List, Optional

from pydantic import BaseModel

from scout.repositories.models import InventoryRecord
from scout.services.inventory_service import AvailabilityStatus, evaluate_availability


class PickupEstimate(BaseModel):
    """The outcome of deciding whether pickup is possible right now."""

    available: bool
    ready_minutes: Optional[int] = None
    reason: Optional[str] = None


def evaluate_pickup_estimate(record: Optional[InventoryRecord]) -> PickupEstimate:
    """Decide whether pickup is possible today, and how long it takes.

    Grounded entirely in the inventory row itself: pickup requires a
    sellable quantity greater than zero AND a recorded
    pickup_ready_minutes value. A product that is sellable but has no
    recorded prep time is reported as unknown, never guessed at.

    Args:
        record: The inventory row for this product at this store, or
            None if untracked.

    Returns:
        A PickupEstimate. `reason` is populated whenever available is
        False: "not_tracked", "out_of_stock",
        "out_of_stock, restock_scheduled=<date>", or
        "pickup_time_unknown".
    """
    availability = evaluate_availability(record)

    if availability.status == AvailabilityStatus.NOT_TRACKED:
        return PickupEstimate(available=False, reason="not_tracked")

    if availability.sellable_quantity <= 0:
        if availability.status == AvailabilityStatus.RESTOCK_SCHEDULED:
            return PickupEstimate(
                available=False,
                reason=f"out_of_stock, restock_scheduled={availability.restock_date}",
            )
        return PickupEstimate(available=False, reason="out_of_stock")

    if record is None or record.pickup_ready_minutes is None:
        return PickupEstimate(available=False, reason="pickup_time_unknown")

    return PickupEstimate(available=True, ready_minutes=record.pickup_ready_minutes, reason=None)


class NetworkAvailability(BaseModel):
    """Aggregate sellable quantity for a product across every tracked store."""

    total_sellable_quantity: int
    contributing_store_ids: List[str]


def aggregate_network_availability(records: List[InventoryRecord]) -> NetworkAvailability:
    """Sum sellable quantity across every store's inventory row for a product.

    This is Scout's stand-in for "online" / network-wide availability:
    the current schema has no separate online-warehouse table (see
    scout/database/schema.sql), so "can this ship to you" is modeled
    deterministically as "does the store network have any sellable
    stock," grounded in the exact same inventory rows
    check_store_inventory reads - never a separate, invented number.

    Args:
        records: Every inventory row for one product (e.g. from
            InventoryRepository.list_for_product()).

    Returns:
        A NetworkAvailability with the summed sellable quantity and
        the sorted list of store_ids that actually contributed a
        positive sellable amount (stores at zero are omitted from the
        evidence list, since they support no part of the claim).
    """
    contributing: List[str] = []
    total = 0
    for record in records:
        result = evaluate_availability(record)
        if result.sellable_quantity > 0:
            total += result.sellable_quantity
            contributing.append(record.store_id)
    return NetworkAvailability(
        total_sellable_quantity=total, contributing_store_ids=sorted(contributing)
    )


class DeliveryEstimate(BaseModel):
    """The outcome of deciding whether a delivery window can be offered."""

    available: bool
    min_days: Optional[int] = None
    max_days: Optional[int] = None
    reason: Optional[str] = None


def evaluate_delivery_estimate(
    network_availability: NetworkAvailability,
    min_quantity: int,
    standard_min_days: int,
    standard_max_days: int,
    earliest_restock_date: Optional[str] = None,
) -> DeliveryEstimate:
    """Decide whether a delivery window can be offered, and what it is.

    If the network has at least min_quantity sellable units anywhere,
    delivery is available within the configured standard window
    (STANDARD_DELIVERY_MIN_DAYS / STANDARD_DELIVERY_MAX_DAYS) - a
    deterministic fulfillment policy applied uniformly to every
    request, not a number invented per call. If nothing is sellable,
    no window is offered; a known restock date (if any) is surfaced in
    the reason instead of a fabricated delivery date.

    Args:
        network_availability: The result of aggregate_network_availability().
        min_quantity: The minimum units the customer needs.
        standard_min_days: Configured minimum delivery days when available.
        standard_max_days: Configured maximum delivery days when available.
        earliest_restock_date: The earliest known restock_date across
            the product's inventory rows, if any.

    Returns:
        A DeliveryEstimate.
    """
    if network_availability.total_sellable_quantity >= min_quantity:
        return DeliveryEstimate(
            available=True, min_days=standard_min_days, max_days=standard_max_days
        )

    if earliest_restock_date is not None:
        return DeliveryEstimate(
            available=False,
            reason=f"out_of_stock_network_wide, restock_scheduled={earliest_restock_date}",
        )

    return DeliveryEstimate(available=False, reason="out_of_stock_network_wide")


def has_weak_fulfillment(statuses: List[AvailabilityStatus]) -> bool:
    """Whether fulfillment is weak enough that substitutes are worth finding.

    Args:
        statuses: The AvailabilityStatus values already checked for a
            product (e.g. the selected store, plus any nearby stores
            already checked).

    Returns:
        True unless at least one given status is IN_STOCK. LOW_STOCK,
        RESTOCK_SCHEDULED, OUT_OF_STOCK, and NOT_TRACKED are all
        treated as weak - even a low-stock hit is risky enough that
        showing a backup option is worthwhile. An empty list (nothing
        checked yet) is also weak - there is no evidence of strong
        fulfillment to point to.
    """
    return not any(status == AvailabilityStatus.IN_STOCK for status in statuses)
