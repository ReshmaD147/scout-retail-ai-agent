"""Tests for scout.mcp.semantic_search_tools."""

import pytest

from scout.config import get_settings
from scout.mcp.semantic_search_tools import semantic_search_products


@pytest.fixture(autouse=True)
def _use_seeded_database(seeded_db_path, monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_PATH", seeded_db_path)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_rejects_an_empty_query_text():
    result = semantic_search_products(query_text="   ")

    assert result.error is not None
    assert result.error.error_type == "validation_error"
    assert result.products == []


def test_rejects_a_limit_outside_the_valid_range():
    result = semantic_search_products(query_text="running shoes", limit=0)

    assert result.error is not None
    assert result.error.error_type == "validation_error"


def test_rejects_a_negative_max_price():
    result = semantic_search_products(query_text="running shoes", max_price=-10.0)

    assert result.error is not None
    assert result.error.error_type == "validation_error"


def test_exact_product_id_query_returns_that_product():
    result = semantic_search_products(query_text="Tell me about FTW-004")

    assert result.error is None
    assert result.retrieval_method == "exact_product_id"
    assert [p.product_id for p in result.products] == ["FTW-004"]


def test_literal_keyword_path_is_unchanged():
    result = semantic_search_products(
        query_text="find work shoes under $100", keyword="work", category="Footwear", max_price=100.0
    )

    assert result.error is None
    assert result.retrieval_method == "literal_keyword"
    assert [p.product_id for p in result.products] == ["FTW-004", "FTW-008"]


def test_limit_truncates_the_returned_products():
    result = semantic_search_products(query_text="comfortable everyday footwear", category="Footwear", limit=1)

    assert result.error is None
    assert len(result.products) <= 1
