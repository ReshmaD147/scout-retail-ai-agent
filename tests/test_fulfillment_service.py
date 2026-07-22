"""Tests for fulfillment_service.

No database involved - pure-Python checks against in-memory
InventoryRecord models built by tests/factories.py.
"""

from scout.services.fulfillment_service import (
    NetworkAvailability,
    aggregate_network_availability,
    evaluate_delivery_estimate,
    evaluate_pickup_estimate,
    has_weak_fulfillment,
)
from scout.services.inventory_service import AvailabilityStatus
from tests.factories import make_inventory_record


def test_pickup_available_when_sellable_and_ready_minutes_known():
    record = make_inventory_record(quantity_available=5, quantity_reserved=0, pickup_ready_minutes=30)
    estimate = evaluate_pickup_estimate(record)
    assert estimate.available is True
    assert estimate.ready_minutes == 30


def test_pickup_unavailable_when_out_of_stock():
    record = make_inventory_record(quantity_available=0, quantity_reserved=0, restock_date=None)
    estimate = evaluate_pickup_estimate(record)
    assert estimate.available is False
    assert estimate.reason == "out_of_stock"


def test_pickup_unavailable_when_out_of_stock_with_restock_date():
    record = make_inventory_record(quantity_available=0, quantity_reserved=0, restock_date="2026-09-01")
    estimate = evaluate_pickup_estimate(record)
    assert estimate.available is False
    assert "2026-09-01" in estimate.reason


def test_pickup_unavailable_when_not_tracked():
    estimate = evaluate_pickup_estimate(None)
    assert estimate.available is False
    assert estimate.reason == "not_tracked"


def test_pickup_unknown_when_sellable_but_no_ready_time_recorded():
    record = make_inventory_record(quantity_available=5, quantity_reserved=0, pickup_ready_minutes=None)
    estimate = evaluate_pickup_estimate(record)
    assert estimate.available is False
    assert estimate.reason == "pickup_time_unknown"


def test_pickup_unavailable_when_fully_reserved():
    record = make_inventory_record(quantity_available=5, quantity_reserved=5, pickup_ready_minutes=30)
    estimate = evaluate_pickup_estimate(record)
    assert estimate.available is False
    assert estimate.reason == "out_of_stock"


def test_aggregate_network_availability_sums_sellable_across_stores():
    records = [
        make_inventory_record(store_id="B", quantity_available=5, quantity_reserved=0),
        make_inventory_record(store_id="A", quantity_available=3, quantity_reserved=3),  # 0 sellable
        make_inventory_record(store_id="C", quantity_available=10, quantity_reserved=4),
    ]
    result = aggregate_network_availability(records)
    assert result.total_sellable_quantity == 5 + 6
    # Sorted, and the zero-sellable store excluded entirely.
    assert result.contributing_store_ids == ["B", "C"]


def test_aggregate_network_availability_empty_when_no_records():
    result = aggregate_network_availability([])
    assert result.total_sellable_quantity == 0
    assert result.contributing_store_ids == []


def test_evaluate_delivery_estimate_available_within_configured_window():
    network = NetworkAvailability(total_sellable_quantity=5, contributing_store_ids=["A"])
    estimate = evaluate_delivery_estimate(
        network, min_quantity=1, standard_min_days=3, standard_max_days=5
    )
    assert estimate.available is True
    assert (estimate.min_days, estimate.max_days) == (3, 5)


def test_evaluate_delivery_estimate_respects_min_quantity():
    network = NetworkAvailability(total_sellable_quantity=2, contributing_store_ids=["A"])
    estimate = evaluate_delivery_estimate(
        network, min_quantity=5, standard_min_days=3, standard_max_days=5
    )
    assert estimate.available is False


def test_evaluate_delivery_estimate_unavailable_reports_restock_date():
    network = NetworkAvailability(total_sellable_quantity=0, contributing_store_ids=[])
    estimate = evaluate_delivery_estimate(
        network,
        min_quantity=1,
        standard_min_days=3,
        standard_max_days=5,
        earliest_restock_date="2026-09-01",
    )
    assert estimate.available is False
    assert "2026-09-01" in estimate.reason


def test_evaluate_delivery_estimate_unavailable_without_restock_date():
    network = NetworkAvailability(total_sellable_quantity=0, contributing_store_ids=[])
    estimate = evaluate_delivery_estimate(network, min_quantity=1, standard_min_days=3, standard_max_days=5)
    assert estimate.available is False
    assert estimate.reason == "out_of_stock_network_wide"


def test_has_weak_fulfillment_true_without_any_in_stock():
    assert has_weak_fulfillment([AvailabilityStatus.OUT_OF_STOCK, AvailabilityStatus.LOW_STOCK]) is True


def test_has_weak_fulfillment_false_with_at_least_one_in_stock():
    assert has_weak_fulfillment([AvailabilityStatus.OUT_OF_STOCK, AvailabilityStatus.IN_STOCK]) is False


def test_has_weak_fulfillment_true_when_nothing_checked_yet():
    assert has_weak_fulfillment([]) is True
