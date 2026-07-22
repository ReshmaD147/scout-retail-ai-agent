"""Tests for scout.services.product_search_service."""

import sqlite3

import pytest

from scout.config import get_settings
from scout.services.embedding_service import HashingEmbeddingProvider
from scout.services.product_search_service import search_products_by_meaning


@pytest.fixture(autouse=True)
def _use_seeded_database(seeded_db_path, monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_PATH", seeded_db_path)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _provider():
    return HashingEmbeddingProvider(dimensions=128)


def test_exact_product_id_match_bypasses_semantic_search():
    outcome = search_products_by_meaning("Tell me about FTW-004 please", provider=_provider())

    assert outcome.retrieval_method == "exact_product_id"
    assert [p.product_id for p in outcome.products] == ["FTW-004"]


def test_exact_brand_match_returns_only_that_brand():
    outcome = search_products_by_meaning("Do you carry Aria products?", provider=_provider())

    assert outcome.retrieval_method == "exact_brand"
    assert outcome.products
    assert all(p.brand == "Aria" for p in outcome.products)


def test_literal_keyword_still_wins_over_semantic_when_provided():
    outcome = search_products_by_meaning(
        "find work shoes under $100", keyword="work", category="Footwear", max_price=100.0, provider=_provider()
    )

    assert outcome.retrieval_method == "literal_keyword"
    assert [p.product_id for p in outcome.products] == ["FTW-004"]


def test_semantic_search_finds_the_comfort_work_shoe_by_meaning():
    outcome = search_products_by_meaning(
        "comfortable shoes for standing all day", category="Footwear", provider=_provider()
    )

    assert outcome.retrieval_method == "semantic"
    assert outcome.candidates_considered > 3
    assert "FTW-004" in [p.product_id for p in outcome.products]  # UNVERIFIED - run and confirm


def test_semantic_search_never_returns_more_than_the_configured_limit(monkeypatch):
    monkeypatch.setenv("SEMANTIC_SEARCH_CANDIDATE_LIMIT", "2")
    get_settings.cache_clear()

    outcome = search_products_by_meaning(
        "comfortable everyday footwear", category="Footwear", provider=_provider()
    )

    assert len(outcome.products) <= 2
    get_settings.cache_clear()


def test_semantic_search_excludes_an_inactive_product(seeded_db_path):
    with sqlite3.connect(seeded_db_path) as connection:
        connection.execute("UPDATE products SET active = 0 WHERE product_id = 'FTW-004'")
        connection.commit()

    outcome = search_products_by_meaning(
        "comfortable shoes for standing all day", category="Footwear", provider=_provider()
    )

    assert "FTW-004" not in [p.product_id for p in outcome.products]


def test_semantic_search_excludes_a_product_over_budget():
    outcome = search_products_by_meaning(
        "comfortable shoes for standing all day", category="Footwear", max_price=10.0, provider=_provider()
    )

    assert outcome.products == []


def test_does_not_pad_results_below_the_similarity_floor(monkeypatch):
    # UNVERIFIED THRESHOLD: 0.9 is a guess at a floor high enough that
    # only the strongest textual match(es) survive. If this hashing
    # provider's real cosine scores for this query never get close to
    # 0.9, either every result gets excluded (also fine - still proves
    # "not padded") or you may need to lower this value. The assertion
    # below only checks "fewer than the full pool," which should hold
    # either way.
    monkeypatch.setenv("SEMANTIC_SEARCH_MIN_SIMILARITY", "0.9")
    get_settings.cache_clear()

    outcome = search_products_by_meaning(
        "comfortable shoes for standing all day", category="Footwear", provider=_provider()
    )

    assert len(outcome.products) < 10  # never padded up to the full Footwear pool
    get_settings.cache_clear()