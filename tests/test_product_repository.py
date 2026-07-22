"""Tests for ProductRepository.

Uses the shared seeded_db_path fixture from tests/conftest.py - a
freshly initialized and seeded temporary database, never the
development database.
"""

from scout.repositories.product_repository import ProductRepository


def test_list_active_returns_only_active_products(seeded_db_path):
    repo = ProductRepository(seeded_db_path)
    products = repo.list_active()
    assert len(products) == 30
    assert all(p.active for p in products)


def test_list_active_filters_by_category(seeded_db_path):
    repo = ProductRepository(seeded_db_path)
    products = repo.list_active(category="Footwear")
    assert len(products) == 10
    assert all(p.category == "Footwear" for p in products)


def test_get_by_id_returns_product(seeded_db_path):
    repo = ProductRepository(seeded_db_path)
    product = repo.get_by_id("FTW-004")
    assert product is not None
    assert product.name == "ComfortPro Shift Support"
    assert product.attributes["use_case"] == "work shifts / standing all day"


def test_get_by_id_returns_none_for_missing_product(seeded_db_path):
    repo = ProductRepository(seeded_db_path)
    assert repo.get_by_id("DOES-NOT-EXIST") is None


def test_search_by_keyword_matches_description(seeded_db_path):
    repo = ProductRepository(seeded_db_path)
    results = repo.search(keyword="work shoe")
    assert results
    assert any(p.product_id == "FTW-004" for p in results)


def test_search_by_max_price_enforces_budget(seeded_db_path):
    repo = ProductRepository(seeded_db_path)
    results = repo.search(category="Footwear", max_price=100)
    assert results
    assert all(p.price <= 100 for p in results)


def test_search_combines_filters_with_and(seeded_db_path):
    repo = ProductRepository(seeded_db_path)
    results = repo.search(category="Footwear", brand="ComfortPro", max_price=100)
    ids = {p.product_id for p in results}
    assert ids == {"FTW-004", "FTW-008"}


def test_search_keyword_is_treated_as_literal_text_not_sql(seeded_db_path):
    repo = ProductRepository(seeded_db_path)
    # A keyword that looks like a SQL injection payload must be treated
    # as a literal substring to search for. If keyword were concatenated
    # into the query instead of bound as a parameter, this could alter
    # the query and return every row (or raise a syntax error).
    results = repo.search(keyword="' OR '1'='1")
    assert results == []


def test_search_with_no_filters_returns_active_products(seeded_db_path):
    repo = ProductRepository(seeded_db_path)
    results = repo.search()
    assert len(results) == 30
