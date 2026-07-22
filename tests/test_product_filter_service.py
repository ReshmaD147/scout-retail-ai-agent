"""Tests for product_filter_service."""

from scout.services.product_filter_service import filter_products
from tests.factories import make_product


def test_filter_by_category():
    shoe = make_product(product_id="A", category="Footwear")
    bag = make_product(product_id="B", category="Bags")

    result = filter_products([shoe, bag], category="Footwear")

    assert [p.product_id for p in result] == ["A"]


def test_filter_excludes_inactive_by_default():
    active = make_product(product_id="A", active=True)
    inactive = make_product(product_id="B", active=False)

    result = filter_products([active, inactive])

    assert [p.product_id for p in result] == ["A"]


def test_filter_by_min_rating_excludes_missing_rating():
    high = make_product(product_id="A", rating=4.5)
    low = make_product(product_id="B", rating=2.0)
    unrated = make_product(product_id="C", rating=None)

    result = filter_products([high, low, unrated], min_rating=4.0)

    assert [p.product_id for p in result] == ["A"]
