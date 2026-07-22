"""Tests for inventory_service."""

from scout.services.inventory_service import (
    AvailabilityStatus,
    can_fulfill,
    evaluate_availability,
)
from tests.factories import make_inventory_record


def test_zero_inventory_is_out_of_stock():
    record = make_inventory_record(quantity_available=0, quantity_reserved=0, restock_date=None)
    result = evaluate_availability(record)
    assert result.status == AvailabilityStatus.OUT_OF_STOCK
    assert result.sellable_quantity == 0


def test_zero_inventory_with_restock_date_is_restock_scheduled():
    record = make_inventory_record(quantity_available=0, quantity_reserved=0, restock_date="2026-09-01")
    result = evaluate_availability(record)
    assert result.status == AvailabilityStatus.RESTOCK_SCHEDULED
    assert result.restock_date == "2026-09-01"


def test_fully_reserved_inventory_is_treated_as_out_of_stock():
    # quantity_available says 5, but all 5 units are reserved - nothing
    # is actually sellable, even though quantity_available > 0.
    record = make_inventory_record(quantity_available=5, quantity_reserved=5)
    result = evaluate_availability(record)
    assert result.sellable_quantity == 0
    assert result.status == AvailabilityStatus.OUT_OF_STOCK


def test_partially_reserved_inventory_reduces_sellable_quantity():
    record = make_inventory_record(quantity_available=10, quantity_reserved=7)
    result = evaluate_availability(record)
    assert result.sellable_quantity == 3
    assert result.status == AvailabilityStatus.LOW_STOCK


def test_missing_record_is_not_tracked():
    result = evaluate_availability(None)
    assert result.status == AvailabilityStatus.NOT_TRACKED
    assert result.sellable_quantity == 0


def test_can_fulfill_respects_sellable_quantity():
    record = make_inventory_record(quantity_available=2, quantity_reserved=0)
    assert can_fulfill(record, quantity_needed=2) is True
    assert can_fulfill(record, quantity_needed=3) is False


def test_can_fulfill_false_for_untracked_product():
    assert can_fulfill(None, quantity_needed=1) is False
