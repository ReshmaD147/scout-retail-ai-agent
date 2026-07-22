"""Tests for the find_store_by_location MCP tool."""

import pytest

from scout.config import get_settings
from scout.mcp.store_tools import find_store_by_location


@pytest.fixture(autouse=True)
def _use_seeded_database(seeded_db_path, monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_PATH", seeded_db_path)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_resolves_an_exact_city_match():
    result = find_store_by_location("Maple Grove")

    assert result.error is None
    assert result.store_id == "STR-001"
    assert result.store_name == "Scout Demo Store - Maple Grove"
    assert result.latitude is not None and result.longitude is not None


def test_resolves_case_insensitively():
    result = find_store_by_location("maple grove")
    assert result.error is None
    assert result.store_id == "STR-001"


def test_resolves_a_partial_city_match():
    # "Grove" is not an exact city name (the city is "Maple Grove"),
    # so this exercises the substring-fallback path, not the exact match.
    result = find_store_by_location("Grove")
    assert result.error is None
    assert result.store_id == "STR-001"


def test_rejects_empty_location_text():
    result = find_store_by_location("")
    assert result.error is not None
    assert result.error.error_type == "validation_error"


def test_not_found_for_an_unknown_location():
    result = find_store_by_location("Nowhere, Antarctica")
    assert result.error is not None
    assert result.error.error_type == "not_found"
    assert result.store_id is None
