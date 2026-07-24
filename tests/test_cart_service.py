"""Tests for scout/services/cart_service.py (Step 15).

Every test uses `seeded_db_path` (tests/conftest.py) - a fresh,
temporary, freshly-seeded database - and passes it explicitly as
`db_path` to every cart_service call, so nothing here ever touches the
development database.

Scenario -> test name, matching the numbered scenarios the Step 15
prompt lists explicitly (19/20, product-reference resolution, live in
tests/test_product_reference_service.py instead, since they are a
different module; 21-22 are React tests; 23 is "all existing tests
still pass," confirmed by running the whole suite, not something this
file can assert about itself):
    1.  test_add_valid_product
    2.  test_reject_invalid_product
    3.  test_reject_inactive_product
    4.  test_reject_zero_or_negative_quantity
    5.  test_reject_quantity_above_configured_maximum
    6.  test_reject_quantity_above_available_inventory
    7.  test_add_same_product_twice_merges_quantity
    8.  test_update_quantity
    9.  test_remove_item
    10. test_clear_cart
    11. test_subtotal_is_calculated_correctly
    12. test_revalidate_a_changed_price
    13. test_ignore_an_expired_promotion
    14. test_carts_are_isolated_between_sessions
    15. test_set_valid_pickup_store
    16. test_reject_pickup_disabled_store
    17. test_reject_pickup_when_one_item_is_unavailable
    18. test_select_delivery
"""

import sqlite3
from datetime import date, timedelta

import pytest

from scout.config import get_settings
from scout.services import cart_service
from scout.services.cart_service import CartServiceError

FOOTWEAR_PRODUCT = "FTW-004"  # ComfortPro Shift Support - has an active promotion
BAG_PRODUCT = "BAG-001"
LOW_STOCK_PRODUCT = "ELE-006"  # network-wide sellable total is well under max_cart_item_quantity
STORE_WITH_STOCK = "STR-002"  # 8 available, 1 reserved -> 7 sellable for FTW-004
STORE_OUT_OF_STOCK = "STR-001"  # 0 available for FTW-004


def _deactivate_product(db_path: str, product_id: str) -> None:
    with sqlite3.connect(db_path) as connection:
        connection.execute("UPDATE products SET active = 0 WHERE product_id = ?", (product_id,))


def _set_price(db_path: str, product_id: str, price: float) -> None:
    with sqlite3.connect(db_path) as connection:
        connection.execute("UPDATE products SET price = ? WHERE product_id = ?", (price, product_id))


def _disable_pickup(db_path: str, store_id: str) -> None:
    with sqlite3.connect(db_path) as connection:
        connection.execute("UPDATE stores SET pickup_enabled = 0 WHERE store_id = ?", (store_id,))


def _insert_expired_promotion(db_path: str, product_id: str, promotion_id: str) -> None:
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO promotions (promotion_id, product_id, label, discount_percent, discount_amount,
                                     start_date, end_date, active)
            VALUES (?, ?, 'Expired Test Promo', 50.0, NULL, '2020-01-01', '2020-01-31', 1)
            """,
            (promotion_id, product_id),
        )


def _insert_current_promotion(db_path: str, product_id: str, promotion_id: str, discount_percent: float) -> None:
    today = date.today()
    start_date = (today - timedelta(days=1)).isoformat()
    end_date = (today + timedelta(days=7)).isoformat()
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO promotions (promotion_id, product_id, label, discount_percent, discount_amount,
                                     start_date, end_date, active)
            VALUES (?, ?, 'Current Test Promo', ?, NULL, ?, ?, 1)
            """,
            (promotion_id, product_id, discount_percent, start_date, end_date),
        )


def _network_sellable(db_path: str, product_id: str) -> int:
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            "SELECT quantity_available, quantity_reserved FROM inventory WHERE product_id = ?",
            (product_id,),
        ).fetchall()
    return sum(max(available - reserved, 0) for available, reserved in rows)


# --- 1-6: add_item validation -----------------------------------------------------


def test_add_valid_product(seeded_db_path):
    cart = cart_service.add_item("session-1", FOOTWEAR_PRODUCT, 2, db_path=seeded_db_path)
    assert cart.cart_id is not None
    assert len(cart.items) == 1
    assert cart.items[0].product_id == FOOTWEAR_PRODUCT
    assert cart.items[0].quantity == 2
    assert cart.validation_status == "valid"


def test_reject_invalid_product(seeded_db_path):
    with pytest.raises(CartServiceError) as exc_info:
        cart_service.add_item("session-1", "NOPE-999", 1, db_path=seeded_db_path)
    assert exc_info.value.error_type == "product_not_found"


def test_reject_inactive_product(seeded_db_path):
    _deactivate_product(seeded_db_path, FOOTWEAR_PRODUCT)
    with pytest.raises(CartServiceError) as exc_info:
        cart_service.add_item("session-1", FOOTWEAR_PRODUCT, 1, db_path=seeded_db_path)
    assert exc_info.value.error_type == "product_inactive"


def test_reject_zero_or_negative_quantity(seeded_db_path):
    for bad_quantity in (0, -1):
        with pytest.raises(CartServiceError) as exc_info:
            cart_service.add_item("session-1", FOOTWEAR_PRODUCT, bad_quantity, db_path=seeded_db_path)
        assert exc_info.value.error_type == "invalid_quantity"


def test_reject_quantity_above_configured_maximum(seeded_db_path):
    max_quantity = get_settings().max_cart_item_quantity
    with pytest.raises(CartServiceError) as exc_info:
        cart_service.add_item("session-1", FOOTWEAR_PRODUCT, max_quantity + 1, db_path=seeded_db_path)
    assert exc_info.value.error_type == "quantity_exceeds_maximum"


def test_reject_quantity_above_available_inventory(seeded_db_path):
    network_total = _network_sellable(seeded_db_path, LOW_STOCK_PRODUCT)
    max_quantity = get_settings().max_cart_item_quantity
    assert network_total + 1 <= max_quantity, "test fixture must exceed inventory before the max-quantity limit"
    with pytest.raises(CartServiceError) as exc_info:
        cart_service.add_item("session-1", LOW_STOCK_PRODUCT, network_total + 1, db_path=seeded_db_path)
    assert exc_info.value.error_type == "insufficient_inventory"


# --- 7-11: merge / update / remove / clear / subtotal -----------------------------


def test_add_same_product_twice_merges_quantity(seeded_db_path):
    cart_service.add_item("session-1", FOOTWEAR_PRODUCT, 2, db_path=seeded_db_path)
    cart = cart_service.add_item("session-1", FOOTWEAR_PRODUCT, 1, db_path=seeded_db_path)
    assert len(cart.items) == 1
    assert cart.items[0].quantity == 3


def test_update_quantity(seeded_db_path):
    cart = cart_service.add_item("session-1", FOOTWEAR_PRODUCT, 1, db_path=seeded_db_path)
    item_id = cart.items[0].cart_item_id
    updated = cart_service.update_quantity("session-1", item_id, 5, db_path=seeded_db_path)
    assert updated.items[0].quantity == 5


def test_remove_item(seeded_db_path):
    cart = cart_service.add_item("session-1", FOOTWEAR_PRODUCT, 1, db_path=seeded_db_path)
    item_id = cart.items[0].cart_item_id
    updated = cart_service.remove_item("session-1", item_id, db_path=seeded_db_path)
    assert updated.items == []


def test_clear_cart(seeded_db_path):
    cart_service.add_item("session-1", FOOTWEAR_PRODUCT, 1, db_path=seeded_db_path)
    cart_service.add_item("session-1", BAG_PRODUCT, 1, db_path=seeded_db_path)
    cleared = cart_service.clear_cart("session-1", db_path=seeded_db_path)
    assert cleared.items == []
    assert cleared.subtotal == 0.0


def test_subtotal_is_calculated_correctly(seeded_db_path):
    cart = cart_service.add_item("session-1", FOOTWEAR_PRODUCT, 2, db_path=seeded_db_path)
    cart = cart_service.add_item("session-1", BAG_PRODUCT, 1, db_path=seeded_db_path)
    expected = round(sum(item.line_total for item in cart.items), 2)
    assert cart.subtotal == expected
    assert cart.subtotal == round(cart.items[0].line_total + cart.items[1].line_total, 2)


def test_cart_recalculates_active_promotion_from_backend(seeded_db_path):
    _insert_current_promotion(seeded_db_path, FOOTWEAR_PRODUCT, "PRM-CART-CURRENT", 50.0)

    cart = cart_service.add_item("session-1", FOOTWEAR_PRODUCT, 1, db_path=seeded_db_path)

    assert cart.items[0].promotion_id == "PRM-CART-CURRENT"
    assert cart.items[0].promotion_label == "Current Test Promo"
    assert cart.items[0].unit_price == round(89.99 * 0.5, 2)


# --- 12-13: revalidation -----------------------------------------------------------


def test_revalidate_a_changed_price(seeded_db_path):
    cart = cart_service.add_item("session-1", FOOTWEAR_PRODUCT, 1, db_path=seeded_db_path)
    original_price = cart.items[0].unit_price

    _set_price(seeded_db_path, FOOTWEAR_PRODUCT, original_price + 50)

    revalidated = cart_service.get_cart_view("session-1", db_path=seeded_db_path)
    assert revalidated.items[0].unit_price != original_price
    assert revalidated.items[0].unit_price_snapshot == original_price
    assert any("price" in warning.lower() and "changed" in warning.lower() for warning in revalidated.warnings)


def test_ignore_an_expired_promotion(seeded_db_path):
    _insert_expired_promotion(seeded_db_path, BAG_PRODUCT, "PRM-EXPIRED-TEST")
    cart = cart_service.add_item("session-1", BAG_PRODUCT, 1, db_path=seeded_db_path)
    # The expired promotion offers 50% off - if it were (wrongly) applied,
    # unit_price would be half of the catalog price. It must not be.
    assert cart.items[0].promotion_id != "PRM-EXPIRED-TEST"


# --- 14: isolation -------------------------------------------------------------------


def test_carts_are_isolated_between_sessions(seeded_db_path):
    cart_service.add_item("session-a", FOOTWEAR_PRODUCT, 1, db_path=seeded_db_path)
    cart_b = cart_service.get_cart_view("session-b", db_path=seeded_db_path)
    assert cart_b.cart_id is None
    assert cart_b.items == []

    cart_a = cart_service.get_cart_view("session-a", db_path=seeded_db_path)
    assert len(cart_a.items) == 1

    # session-b must not be able to touch session-a's item.
    item_id = cart_a.items[0].cart_item_id
    with pytest.raises(CartServiceError) as exc_info:
        cart_service.remove_item("session-b", item_id, db_path=seeded_db_path)
    assert exc_info.value.error_type == "cart_item_not_found"


# --- 15-18: fulfillment --------------------------------------------------------------


def test_set_valid_pickup_store(seeded_db_path):
    cart_service.add_item("session-1", FOOTWEAR_PRODUCT, 1, db_path=seeded_db_path)
    cart = cart_service.set_fulfillment("session-1", "pickup", STORE_WITH_STOCK, db_path=seeded_db_path)
    assert cart.fulfillment_type == "pickup"
    assert cart.store_id == STORE_WITH_STOCK
    assert cart.validation_status == "valid"


def test_reject_pickup_disabled_store(seeded_db_path):
    _disable_pickup(seeded_db_path, STORE_WITH_STOCK)
    cart_service.add_item("session-1", FOOTWEAR_PRODUCT, 1, db_path=seeded_db_path)
    with pytest.raises(CartServiceError) as exc_info:
        cart_service.set_fulfillment("session-1", "pickup", STORE_WITH_STOCK, db_path=seeded_db_path)
    assert exc_info.value.error_type == "store_pickup_disabled"


def test_reject_pickup_when_one_item_is_unavailable(seeded_db_path):
    cart_service.add_item("session-1", FOOTWEAR_PRODUCT, 1, db_path=seeded_db_path)
    with pytest.raises(CartServiceError) as exc_info:
        cart_service.set_fulfillment("session-1", "pickup", STORE_OUT_OF_STOCK, db_path=seeded_db_path)
    assert exc_info.value.error_type == "store_cannot_fulfill"

    # Nothing should have changed - the cart keeps its previous (none) fulfillment.
    cart = cart_service.get_cart_view("session-1", db_path=seeded_db_path)
    assert cart.fulfillment_type is None


def test_select_delivery(seeded_db_path):
    cart_service.add_item("session-1", FOOTWEAR_PRODUCT, 1, db_path=seeded_db_path)
    cart = cart_service.set_fulfillment("session-1", "delivery", None, db_path=seeded_db_path)
    assert cart.fulfillment_type == "delivery"
    assert cart.store_id is None
