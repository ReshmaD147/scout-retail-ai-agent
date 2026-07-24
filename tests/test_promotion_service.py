"""Tests for promotion_service."""

from datetime import date

from scout.services.promotion_service import build_verified_promotion_summary, calculate_price
from tests.factories import make_product, make_promotion


def test_expired_promotion_does_not_apply():
    product = make_product(product_id="P1", price=100.0)
    expired = make_promotion(
        product_id="P1", start_date="2026-01-01", end_date="2026-02-01", discount_percent=20.0
    )

    result = calculate_price(product, [expired], as_of=date(2026, 7, 21))

    assert result.final_price == 100.0
    assert result.applied_promotion_id is None


def test_future_promotion_does_not_apply():
    product = make_product(product_id="P1", price=100.0)
    future = make_promotion(
        product_id="P1", start_date="2026-09-01", end_date="2026-09-30", discount_percent=20.0
    )

    result = calculate_price(product, [future], as_of=date(2026, 7, 21))

    assert result.final_price == 100.0
    assert result.applied_promotion_id is None


def test_manually_disabled_promotion_does_not_apply_even_during_valid_dates():
    product = make_product(product_id="P1", price=100.0)
    disabled = make_promotion(
        product_id="P1",
        start_date="2026-07-01",
        end_date="2026-07-31",
        active=False,
        discount_percent=20.0,
    )

    result = calculate_price(product, [disabled], as_of=date(2026, 7, 21))

    assert result.final_price == 100.0


def test_active_current_promotion_applies_percent_discount():
    product = make_product(product_id="P1", price=100.0)
    promo = make_promotion(
        product_id="P1", start_date="2026-07-01", end_date="2026-07-31", discount_percent=15.0
    )

    result = calculate_price(product, [promo], as_of=date(2026, 7, 21))

    assert result.final_price == 85.0
    assert result.applied_promotion_id == promo.promotion_id


def test_amount_discount_never_goes_below_zero():
    product = make_product(product_id="P1", price=5.0)
    promo = make_promotion(
        product_id="P1",
        discount_amount=50.0,
        discount_percent=None,
        start_date="2026-07-01",
        end_date="2026-07-31",
    )

    result = calculate_price(product, [promo], as_of=date(2026, 7, 21))

    assert result.final_price == 0.0


def test_best_of_multiple_valid_promotions_is_chosen():
    product = make_product(product_id="P1", price=100.0)
    small = make_promotion(
        promotion_id="PRM-A",
        product_id="P1",
        discount_percent=10.0,
        start_date="2026-07-01",
        end_date="2026-07-31",
    )
    big = make_promotion(
        promotion_id="PRM-B",
        product_id="P1",
        discount_percent=25.0,
        start_date="2026-07-01",
        end_date="2026-07-31",
    )

    result = calculate_price(product, [small, big], as_of=date(2026, 7, 21))

    assert result.final_price == 75.0
    assert result.applied_promotion_id == "PRM-B"


def test_verified_promotion_summary_contains_server_calculated_percent_discount():
    product = make_product(product_id="P1", price=89.99)
    promo = make_promotion(
        promotion_id="PRM-PERCENT",
        product_id="P1",
        label="Workwear Comfort Event",
        start_date="2026-07-01",
        end_date="2026-07-31",
        discount_percent=10.0,
    )

    summary = build_verified_promotion_summary(product, [promo], "PRM-PERCENT", as_of=date(2026, 7, 21))

    assert summary == {
        "promotion_id": "PRM-PERCENT",
        "label": "Workwear Comfort Event",
        "discount_type": "percent",
        "discount_value": 10.0,
        "original_price": 89.99,
        "promotional_price": 80.99,
        "savings": 9.0,
        "valid_until": "2026-07-31",
        "terms_summary": None,
        "verified": True,
    }


def test_verified_promotion_summary_contains_server_calculated_fixed_discount():
    product = make_product(product_id="P1", price=59.99)
    promo = make_promotion(
        promotion_id="PRM-AMOUNT",
        product_id="P1",
        label="Travel Bag Markdown",
        start_date="2026-07-01",
        end_date="2026-07-31",
        discount_percent=None,
        discount_amount=10.0,
    )

    summary = build_verified_promotion_summary(product, [promo], "PRM-AMOUNT", as_of=date(2026, 7, 21))

    assert summary is not None
    assert summary["discount_type"] == "amount"
    assert summary["discount_value"] == 10.0
    assert summary["original_price"] == 59.99
    assert summary["promotional_price"] == 49.99
    assert summary["savings"] == 10.0


def test_verified_promotion_summary_rejects_expired_future_and_wrong_product_promotions():
    product = make_product(product_id="P1", price=100.0)
    expired = make_promotion(
        promotion_id="PRM-EXPIRED",
        product_id="P1",
        start_date="2026-01-01",
        end_date="2026-02-01",
        discount_percent=20.0,
    )
    future = make_promotion(
        promotion_id="PRM-FUTURE",
        product_id="P1",
        start_date="2026-09-01",
        end_date="2026-09-30",
        discount_percent=20.0,
    )
    wrong_product = make_promotion(
        promotion_id="PRM-WRONG",
        product_id="P2",
        start_date="2026-07-01",
        end_date="2026-07-31",
        discount_percent=20.0,
    )

    assert build_verified_promotion_summary(product, [expired], "PRM-EXPIRED", as_of=date(2026, 7, 21)) is None
    assert build_verified_promotion_summary(product, [future], "PRM-FUTURE", as_of=date(2026, 7, 21)) is None
    assert build_verified_promotion_summary(product, [wrong_product], "PRM-WRONG", as_of=date(2026, 7, 21)) is None


def test_verified_promotion_summary_rejects_non_discounting_conditions():
    product = make_product(product_id="P1", price=100.0)
    no_discount = make_promotion(
        promotion_id="PRM-ZERO",
        product_id="P1",
        start_date="2026-07-01",
        end_date="2026-07-31",
        discount_percent=0.0,
    )

    assert build_verified_promotion_summary(product, [no_discount], "PRM-ZERO", as_of=date(2026, 7, 21)) is None
