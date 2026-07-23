"""Step 17 MCP order tool tests."""

import asyncio

import pytest

from scout.config import get_settings
from scout.mcp.order_tools import (
    check_order_eligibility,
    get_fulfillment_details,
    get_order_status,
    get_payment_status,
    lookup_latest_order,
    lookup_order,
    mcp_server,
)
from tests.order_helpers import create_pickup_order


@pytest.fixture(autouse=True)
def _use_seeded_database(seeded_db_path, monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_PATH", seeded_db_path)
    get_settings.cache_clear()
    yield seeded_db_path
    get_settings.cache_clear()


def test_all_order_tools_are_registered_with_mcp_metadata():
    tools = asyncio.run(mcp_server.list_tools())
    names = {tool.name for tool in tools}
    assert {
        "lookup_order",
        "lookup_latest_order",
        "get_order_status",
        "get_payment_status",
        "get_fulfillment_details",
        "check_order_eligibility",
    }.issubset(names)


def test_tools_return_structured_order_facts(_use_seeded_database):
    created = create_pickup_order(_use_seeded_database, "tool-order")

    assert lookup_order(created.order_id, "tool-order").order.order_id == created.order_id
    assert lookup_latest_order("tool-order").order.order_id == created.order_id
    assert get_order_status(created.order_id, "tool-order").order_status == "confirmed"
    assert get_payment_status(created.order_id, "tool-order").payment.status == "succeeded"
    assert get_fulfillment_details(created.order_id, "tool-order").fulfillment.status == "processing"
    assert check_order_eligibility(created.order_id, "tool-order").eligibility.cancellation.eligible is True


def test_lookup_tool_returns_safe_not_found_error(_use_seeded_database):
    result = lookup_order("missing", "tool-order")
    assert result.order is None
    assert result.error.error_type == "order_not_found"
