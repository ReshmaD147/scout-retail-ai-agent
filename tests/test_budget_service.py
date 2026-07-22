"""Tests for budget_service.

No database involved - these are pure-Python checks against in-memory
Product models built by tests/factories.py.
"""

import pytest

from scout.services.budget_service import filter_within_budget, is_within_budget
from tests.factories import make_product


def test_price_exactly_at_budget_is_within_budget():
    assert is_within_budget(price=100.0, max_budget=100.0) is True


def test_price_above_budget_is_not_within_budget():
    assert is_within_budget(price=100.01, max_budget=100.0) is False


def test_filter_within_budget_includes_boundary_and_excludes_above():
    at_budget = make_product(product_id="A", price=100.0)
    under_budget = make_product(product_id="B", price=89.99)
    over_budget = make_product(product_id="C", price=109.99)

    result = filter_within_budget([at_budget, under_budget, over_budget], max_budget=100.0)

    assert {p.product_id for p in result} == {"A", "B"}


def test_negative_budget_is_rejected():
    with pytest.raises(ValueError):
        is_within_budget(price=10.0, max_budget=-5.0)
