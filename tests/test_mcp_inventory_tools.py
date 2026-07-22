"""Tests for the MCP inventory and fulfillment tools.

Every tool is called directly as a plain Python function - no running
MCP server, no LangGraph. Uses the shared seeded_db_path fixture from
tests/conftest.py, repointed at via DATABASE_PATH so the tools (which
build repositories with no explicit db_path) hit the seeded temporary
database instead of the development one.
"""

import asyncio

import pytest

from scout.config import get_settings
from scout.mcp.inventory_tools import (
    check_network_inventory,
    check_store_inventory,
    find_available_substitutes,
    find_nearby_inventory,
    get_delivery_estimate,
    get_pickup_estimate,
)
from scout.mcp.server import mcp_server


@pytest.fixture(autouse=True)
def _use_seeded_database(seeded_db_path, monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_PATH", seeded_db_path)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


MAPLE_GROVE_LAT = 45.0725
MAPLE_GROVE_LON = -93.4557


def test_all_eleven_tools_are_registered_on_the_shared_server():
    tools = asyncio.run(mcp_server.list_tools())
    names = {tool.name for tool in tools}

    assert {
        "search_products",
        "get_product_details",
        "get_promotions",
        "rank_products",
        "find_similar_products",
        "check_store_inventory",
        "find_nearby_inventory",
        "check_network_inventory",
        "get_pickup_estimate",
        "get_delivery_estimate",
        "find_available_substitutes",
    }.issubset(names)


# ---------------------------------------------------------------------------
# check_store_inventory
# ---------------------------------------------------------------------------


def test_check_store_inventory_out_of_stock_at_maple_grove():
    result = check_store_inventory("FTW-004", "STR-001")

    assert result.error is None
    assert result.status == "out_of_stock"
    assert result.sellable_quantity == 0
    assert result.evidence.record_found is True


def test_check_store_inventory_in_stock_at_plymouth():
    result = check_store_inventory("FTW-004", "STR-002")

    assert result.error is None
    assert result.status == "in_stock"
    assert result.sellable_quantity == 7  # 8 available - 1 reserved


def test_check_store_inventory_not_found_product():
    result = check_store_inventory("DOES-NOT-EXIST", "STR-001")
    assert result.error is not None
    assert result.error.error_type == "not_found"


def test_check_store_inventory_not_found_store():
    result = check_store_inventory("FTW-004", "STR-999")
    assert result.error is not None
    assert result.error.error_type == "not_found"


def test_check_store_inventory_rejects_empty_ids():
    result = check_store_inventory("", "STR-001")
    assert result.error.error_type == "validation_error"


# ---------------------------------------------------------------------------
# find_nearby_inventory
# ---------------------------------------------------------------------------


def test_find_nearby_inventory_finds_plymouth_and_brooklyn_park():
    result = find_nearby_inventory(
        product_id="FTW-004",
        latitude=MAPLE_GROVE_LAT,
        longitude=MAPLE_GROVE_LON,
        radius_miles=50,
        exclude_store_id="STR-001",
    )

    assert result.error is None
    store_ids = {entry.store_id for entry in result.results}
    assert store_ids == {"STR-002", "STR-003"}
    distances = [entry.distance_miles for entry in result.results]
    assert distances == sorted(distances)


def test_find_nearby_inventory_respects_min_quantity():
    result = find_nearby_inventory(
        product_id="FTW-004",
        latitude=MAPLE_GROVE_LAT,
        longitude=MAPLE_GROVE_LON,
        radius_miles=50,
        exclude_store_id="STR-001",
        min_quantity=10,
    )

    assert result.error is None
    assert result.results == []


def test_find_nearby_inventory_rejects_bad_latitude():
    result = find_nearby_inventory(product_id="FTW-004", latitude=200, longitude=MAPLE_GROVE_LON)
    assert result.error.error_type == "validation_error"


def test_find_nearby_inventory_not_found_product():
    result = find_nearby_inventory(product_id="DOES-NOT-EXIST", latitude=MAPLE_GROVE_LAT, longitude=MAPLE_GROVE_LON)
    assert result.error.error_type == "not_found"


# ---------------------------------------------------------------------------
# check_network_inventory
# ---------------------------------------------------------------------------


def test_check_network_inventory_aggregates_across_stores():
    result = check_network_inventory("FTW-004")

    assert result.error is None
    assert result.availability_source == "store_network"
    assert result.sellable_quantity == 10  # 0 + 7 + 3
    assert result.contributing_store_ids == ["STR-002", "STR-003"]
    assert result.available is True


def test_check_network_inventory_zero_everywhere():
    result = check_network_inventory("BAG-005")

    assert result.error is None
    assert result.sellable_quantity == 0
    assert result.contributing_store_ids == []
    assert result.available is False


def test_check_network_inventory_respects_min_quantity():
    result = check_network_inventory("FTW-004", min_quantity=100)
    assert result.available is False


def test_check_network_inventory_rejects_invalid_min_quantity():
    result = check_network_inventory("FTW-004", min_quantity=0)
    assert result.error.error_type == "validation_error"


# ---------------------------------------------------------------------------
# get_pickup_estimate
# ---------------------------------------------------------------------------


def test_get_pickup_estimate_available_with_ready_minutes():
    result = get_pickup_estimate("FTW-004", "STR-002")

    assert result.error is None
    assert result.pickup_available is True
    assert result.pickup_ready_minutes == 45


def test_get_pickup_estimate_unavailable_out_of_stock():
    result = get_pickup_estimate("FTW-004", "STR-001")

    assert result.pickup_available is False
    assert result.reason == "out_of_stock"


def test_get_pickup_estimate_unavailable_with_restock_date():
    result = get_pickup_estimate("FTW-002", "STR-001")

    assert result.pickup_available is False
    assert "2026-08-10" in result.reason


def test_get_pickup_estimate_not_found_store():
    result = get_pickup_estimate("FTW-004", "STR-999")
    assert result.error.error_type == "not_found"


# ---------------------------------------------------------------------------
# get_delivery_estimate
# ---------------------------------------------------------------------------


def test_get_delivery_estimate_available_from_configured_window():
    result = get_delivery_estimate("FTW-004")

    assert result.error is None
    assert result.delivery_available is True
    assert result.policy_evidence is not None
    assert result.policy_evidence.evidence_type == "configured_policy"
    assert result.policy_evidence.is_carrier_estimate is False
    assert (result.policy_evidence.minimum_days, result.policy_evidence.maximum_days) == (3, 5)
    assert result.sellable_quantity == 10


def test_get_delivery_estimate_available_even_when_selected_store_needs_restock():
    # FTW-002 is out at STR-001 (with a restock date) but has stock at
    # STR-003 and STR-004 - network-wide, it's still deliverable.
    result = get_delivery_estimate("FTW-002")

    assert result.delivery_available is True
    assert result.sellable_quantity == 13


def test_get_delivery_estimate_unavailable_reports_restock_date():
    result = get_delivery_estimate("FTW-010")

    assert result.delivery_available is False
    assert result.policy_evidence is None
    assert "2026-09-01" in result.reason


def test_get_delivery_estimate_unavailable_without_restock_date():
    result = get_delivery_estimate("BAG-005")

    assert result.delivery_available is False
    assert result.policy_evidence is None
    assert result.reason == "out_of_stock_network_wide"


def test_get_delivery_estimate_rejects_invalid_min_quantity():
    result = get_delivery_estimate("FTW-004", min_quantity=0)
    assert result.error.error_type == "validation_error"


# ---------------------------------------------------------------------------
# find_available_substitutes
# ---------------------------------------------------------------------------


def test_find_available_substitutes_store_network_channel():
    result = find_available_substitutes("FTW-008")

    assert result.error is None
    assert result.fulfillment_channel_checked == "store_network"
    assert result.count == 1
    assert result.substitutes[0].product.product_id == "FTW-007"
    assert result.substitutes[0].sellable_quantity == 28  # 18 + 10 across stores


def test_find_available_substitutes_selected_store_channel():
    result = find_available_substitutes("FTW-008", store_id="STR-001")

    assert result.error is None
    assert result.fulfillment_channel_checked == "selected_store"
    assert result.count == 1
    assert result.substitutes[0].product.product_id == "FTW-007"
    assert result.substitutes[0].sellable_quantity == 18


def test_find_available_substitutes_nearby_store_channel():
    result = find_available_substitutes(
        "FTW-008", latitude=MAPLE_GROVE_LAT, longitude=MAPLE_GROVE_LON
    )

    assert result.error is None
    assert result.fulfillment_channel_checked == "nearby_store"
    assert result.count == 1
    assert result.substitutes[0].distance_miles is not None


def test_find_available_substitutes_not_found_reference():
    result = find_available_substitutes("DOES-NOT-EXIST")
    assert result.error is not None
    assert result.error.error_type == "not_found"


def test_find_available_substitutes_rejects_lat_without_long():
    result = find_available_substitutes("FTW-008", latitude=MAPLE_GROVE_LAT)
    assert result.error.error_type == "validation_error"


def test_find_available_substitutes_rejects_invalid_limit():
    result = find_available_substitutes("FTW-008", limit=0)
    assert result.error.error_type == "validation_error"


def test_find_available_substitutes_not_found_selected_store():
    result = find_available_substitutes("FTW-008", store_id="STR-999")
    assert result.error.error_type == "not_found"
