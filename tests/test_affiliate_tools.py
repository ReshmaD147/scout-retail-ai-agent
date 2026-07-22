"""Direct MCP tool tests for Step 16.5."""

import asyncio

import pytest

from scout.config import get_settings
from scout.mcp.affiliate_tools import (
    get_external_offer_details,
    mcp_server,
    search_external_offers,
    track_affiliate_click,
)


@pytest.fixture(autouse=True)
def _use_seeded_database(seeded_db_path, monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_PATH", seeded_db_path)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_affiliate_tools_are_registered():
    names = {tool.name for tool in asyncio.run(mcp_server.list_tools())}
    assert {"search_external_offers", "get_external_offer_details", "track_affiliate_click"}.issubset(names)


def test_search_tool_returns_similar_offers_without_direct_urls():
    result = search_external_offers(
        query_text="comfortable work shoes for standing",
        category="Footwear",
        max_price=100,
    )

    assert result.error is None
    assert result.offers
    assert result.offers[0].match_type == "similar"
    assert "merchant_url" not in result.offers[0].model_dump()


def test_details_tool_reverifies_offer():
    result = get_external_offer_details("EXT-OFF-001")
    assert result.error is None
    assert result.offer is not None
    assert result.offer.active is True
    assert result.offer.availability_status == "in_stock"


def test_click_tool_returns_mock_redirect_and_records_click():
    result = track_affiliate_click(
        offer_id="EXT-OFF-001",
        session_id="tool-affiliate-session",
        match_type="similar",
    )
    assert result.error is None
    assert result.click_id
    assert result.redirect_url.startswith("https://example.com/")
