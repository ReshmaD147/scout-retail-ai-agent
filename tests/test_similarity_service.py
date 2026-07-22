"""Tests for similarity_service.

Pure Python, no database - the same in-memory factories used across
the other service tests. This is the shared function
find_similar_products (scout/mcp/product_tools.py) and
find_available_substitutes (scout/mcp/inventory_tools.py) both call
directly, so neither has to invoke the other as an MCP tool.
"""

from scout.services.similarity_service import filter_similar_candidates
from tests.factories import make_product


def test_filter_similar_candidates_excludes_the_reference_itself():
    reference = make_product(product_id="REF-001", price=50.0)
    candidates = [reference, make_product(product_id="OTHER-001", price=51.0)]

    result = filter_similar_candidates(reference, candidates)

    assert [p.product_id for p in result] == ["OTHER-001"]


def test_filter_similar_candidates_applies_price_band():
    reference = make_product(product_id="REF-001", price=100.0)
    within_band = make_product(product_id="IN-001", price=125.0)  # +25%, within 30%
    outside_band = make_product(product_id="OUT-001", price=200.0)  # +100%, outside 30%

    result = filter_similar_candidates(
        reference, [within_band, outside_band], max_price_difference_percent=30.0
    )

    assert [p.product_id for p in result] == ["IN-001"]


def test_filter_similar_candidates_price_band_is_symmetric():
    reference = make_product(product_id="REF-001", price=100.0)
    cheaper = make_product(product_id="CHEAP-001", price=80.0)  # -20%, within 30%

    result = filter_similar_candidates(reference, [cheaper], max_price_difference_percent=30.0)

    assert [p.product_id for p in result] == ["CHEAP-001"]


def test_filter_similar_candidates_can_disable_price_band():
    reference = make_product(product_id="REF-001", price=100.0)
    far_off = make_product(product_id="FAR-001", price=900.0)

    result = filter_similar_candidates(reference, [far_off], max_price_difference_percent=None)

    assert [p.product_id for p in result] == ["FAR-001"]


def test_filter_similar_candidates_empty_candidates_returns_empty():
    reference = make_product(product_id="REF-001", price=100.0)

    result = filter_similar_candidates(reference, [])

    assert result == []
