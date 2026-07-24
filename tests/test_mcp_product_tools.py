"""Tests for the MCP product tools.

Every tool is called directly as a plain Python function - the same
way scout/mcp/product_tools.py documents them as being tested in this
phase. Nothing here starts an MCP server, a client session, or
LangGraph; list_tools() is used once just to prove each function is
actually registered with real MCP metadata.

Uses the shared seeded_db_path fixture from tests/conftest.py, plus a
fixture that repoints get_settings().database_path at it so the tools
(which build repositories with no explicit db_path) hit the seeded
temporary database instead of the development one.
"""

import asyncio
from datetime import date

import pytest

from scout.config import get_settings
from scout.mcp.product_tools import (
    find_similar_products,
    get_product_details,
    get_promotions,
    mcp_server,
    rank_products,
    search_products,
)


@pytest.fixture(autouse=True)
def _use_seeded_database(seeded_db_path, monkeypatch):
    """Point the default database path at the seeded temp DB for every
    test in this module, since the tools build repositories with
    db_path=None (i.e. "use the configured database")."""
    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_PATH", seeded_db_path)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Registration / schema sanity check
# ---------------------------------------------------------------------------


def test_all_five_tools_are_registered_with_mcp_metadata():
    # mcp_server is shared across scout/mcp/*.py (Step 7 added inventory
    # tools onto the same instance - see scout/mcp/server.py), so this
    # checks that the five product tools are present, not that they are
    # the only tools registered.
    tools = asyncio.run(mcp_server.list_tools())
    names = {tool.name for tool in tools}

    assert {
        "search_products",
        "get_product_details",
        "get_promotions",
        "rank_products",
        "find_similar_products",
    }.issubset(names)
    for tool in tools:
        assert tool.description  # every tool has a real description
        assert "properties" in tool.inputSchema  # every tool has a real input schema


# ---------------------------------------------------------------------------
# search_products
# ---------------------------------------------------------------------------


def test_search_products_returns_structured_results():
    result = search_products(category="Footwear", max_price=100)

    assert result.error is None
    assert result.count == len(result.products)
    assert result.count > 0
    assert all(p.price <= 100 for p in result.products)
    assert all(p.category == "Footwear" for p in result.products)


def test_search_products_rejects_invalid_limit():
    result = search_products(limit=0)

    assert result.error is not None
    assert result.error.error_type == "validation_error"
    assert result.products == []


def test_search_products_rejects_negative_max_price():
    result = search_products(max_price=-10)

    assert result.error is not None
    assert result.error.error_type == "validation_error"


# ---------------------------------------------------------------------------
# get_product_details
# ---------------------------------------------------------------------------


def test_get_product_details_returns_full_record():
    result = get_product_details("FTW-004")

    assert result.error is None
    assert result.product is not None
    assert result.product.name == "ComfortPro Shift Support"
    assert result.product.attributes["use_case"] == "work shifts / standing all day"


def test_get_product_details_not_found_is_structured_not_invented():
    result = get_product_details("DOES-NOT-EXIST")

    assert result.product is None
    assert result.error is not None
    assert result.error.error_type == "not_found"


def test_get_product_details_rejects_empty_id():
    result = get_product_details("   ")

    assert result.error is not None
    assert result.error.error_type == "validation_error"


# ---------------------------------------------------------------------------
# get_promotions
# ---------------------------------------------------------------------------


def test_get_promotions_reports_raw_flag_and_reconciled_validity():
    # PRM-004 (ELE-001) is active=1 but starts in the future - should
    # show up (active flag is 1) but is_currently_valid must be False.
    result = get_promotions(product_id="ELE-001", as_of_date="2026-07-21")

    assert result.error is None
    assert len(result.promotions) == 1
    promo = result.promotions[0]
    assert promo.active is True
    assert promo.is_currently_valid is False


def test_get_promotions_marks_current_promotion_valid():
    # PRM-002 (FTW-004) is active=1 and 2026-07-21 falls in its range.
    result = get_promotions(product_id="FTW-004", as_of_date="2026-07-21")

    assert len(result.promotions) == 1
    assert result.promotions[0].is_currently_valid is True


def test_get_promotions_marks_service_industry_discount_valid():
    result = get_promotions(product_id="FTW-008", as_of_date="2026-07-21")

    assert result.error is None
    assert len(result.promotions) == 1
    assert result.promotions[0].promotion_id == "PRM-006"
    assert result.promotions[0].is_currently_valid is True


def test_get_promotions_rejects_bad_date_format():
    result = get_promotions(as_of_date="not-a-date")

    assert result.error is not None
    assert result.error.error_type == "validation_error"


# ---------------------------------------------------------------------------
# rank_products
# ---------------------------------------------------------------------------


def test_rank_products_orders_deterministically():
    result = rank_products(["FTW-007", "FTW-008", "FTW-004"])

    assert result.error is None
    assert result.missing_product_ids == []
    ranks = [entry.rank for entry in result.ranked_products]
    assert ranks == sorted(ranks)


def test_rank_products_reports_missing_ids_without_inventing_them():
    result = rank_products(["FTW-004", "DOES-NOT-EXIST"])

    assert result.error is None
    assert result.missing_product_ids == ["DOES-NOT-EXIST"]
    assert result.count == 1
    assert result.ranked_products[0].product.product_id == "FTW-004"


def test_rank_products_rejects_empty_list():
    result = rank_products([])

    assert result.error is not None
    assert result.error.error_type == "validation_error"


def test_rank_products_rejects_too_many_ids():
    result = rank_products([f"FTW-{i:03d}" for i in range(60)])

    assert result.error is not None
    assert result.error.error_type == "validation_error"


# ---------------------------------------------------------------------------
# find_similar_products
# ---------------------------------------------------------------------------


def test_find_similar_products_matches_category_and_price_band():
    # FTW-008 (ComfortPro EasyStand Clog, $49.99) should find other
    # Footwear within 30% of its price, excluding itself.
    result = find_similar_products("FTW-008", limit=5)

    assert result.error is None
    assert result.count > 0
    assert all(p.category == "Footwear" for p in result.similar_products)
    assert all(p.product_id != "FTW-008" for p in result.similar_products)
    assert all(abs(p.price - 49.99) <= 49.99 * 0.30 for p in result.similar_products)


def test_find_similar_products_not_found_reference():
    result = find_similar_products("DOES-NOT-EXIST")

    assert result.error is not None
    assert result.error.error_type == "not_found"
    assert result.similar_products == []


def test_find_similar_products_can_disable_price_band():
    narrow = find_similar_products("FTW-008", max_price_difference_percent=1)
    wide = find_similar_products("FTW-008", max_price_difference_percent=None)

    assert len(wide.similar_products) >= len(narrow.similar_products)


def test_find_similar_products_rejects_invalid_limit():
    result = find_similar_products("FTW-008", limit=0)

    assert result.error is not None
    assert result.error.error_type == "validation_error"
