"""Tests for ranking_service."""

import random

from scout.services.ranking_service import rank_products
from tests.factories import make_product


def test_missing_rating_sorts_after_rated_products():
    rated = make_product(product_id="A", rating=4.5, review_count=100, price=50.0)
    unrated = make_product(product_id="B", rating=None, review_count=0, price=10.0)

    ranked = rank_products([unrated, rated])

    assert [entry.product.product_id for entry in ranked] == ["A", "B"]


def test_higher_rating_ranks_first():
    low = make_product(product_id="A", rating=3.0, review_count=50, price=50.0)
    high = make_product(product_id="B", rating=4.8, review_count=50, price=50.0)

    ranked = rank_products([low, high])

    assert [entry.product.product_id for entry in ranked] == ["B", "A"]


def test_ranking_order_is_stable_regardless_of_input_order():
    products = [
        make_product(product_id="A", rating=4.0, review_count=10, price=20.0),
        make_product(product_id="B", rating=4.0, review_count=10, price=20.0),
        make_product(product_id="C", rating=4.5, review_count=5, price=15.0),
    ]

    first_pass = [entry.product.product_id for entry in rank_products(products)]

    shuffled = products[:]
    random.Random(42).shuffle(shuffled)
    second_pass = [entry.product.product_id for entry in rank_products(shuffled)]

    assert first_pass == second_pass
    # A and B tie on rating/review_count/price - product_id breaks the tie.
    assert first_pass == ["C", "A", "B"]
