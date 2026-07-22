"""Tests for scout/mcp/cart_tools.py (Step 15).

These confirm the MCP tool layer's own responsibilities: blank-input
validation and translating a scout.services.cart_service.CartServiceError
into a structured ToolError - not cart business logic itself, which
tests/test_cart_service.py already covers directly against the
service. Each tool is called as a plain Python function (the same
pattern scout/mcp/product_tools.py's tests use) - no running MCP
server needed.
"""

from scout.mcp.cart_tools import (
    add_to_cart,
    clear_cart,
    get_cart,
    remove_from_cart,
    set_fulfillment_method,
    update_cart_quantity,
    validate_cart,
)

PRODUCT_ID = "FTW-004"


def test_add_to_cart_success(seeded_db_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", seeded_db_path)
    import scout.config as config

    config.get_settings.cache_clear()
    result = add_to_cart(session_id="tool-session-1", product_id=PRODUCT_ID, quantity=2)
    config.get_settings.cache_clear()

    assert result.error is None
    assert result.cart is not None
    assert result.cart.items[0].quantity == 2


def test_add_to_cart_blank_session_id_is_a_validation_error():
    result = add_to_cart(session_id="   ", product_id=PRODUCT_ID, quantity=1)
    assert result.cart is None
    assert result.error is not None
    assert result.error.error_type == "validation_error"


def test_add_to_cart_missing_product_returns_structured_error(seeded_db_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", seeded_db_path)
    import scout.config as config

    config.get_settings.cache_clear()
    result = add_to_cart(session_id="tool-session-2", product_id="NOPE-999", quantity=1)
    config.get_settings.cache_clear()

    assert result.cart is None
    assert result.error.error_type == "product_not_found"


def test_get_cart_returns_empty_cart_for_new_session(seeded_db_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", seeded_db_path)
    import scout.config as config

    config.get_settings.cache_clear()
    result = get_cart(session_id="tool-session-brand-new")
    config.get_settings.cache_clear()

    assert result.error is None
    assert result.cart.cart_id is None
    assert result.cart.items == []


def test_full_tool_lifecycle(seeded_db_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", seeded_db_path)
    import scout.config as config

    config.get_settings.cache_clear()

    add_result = add_to_cart(session_id="tool-session-3", product_id=PRODUCT_ID, quantity=1)
    item_id = add_result.cart.items[0].cart_item_id

    updated = update_cart_quantity(session_id="tool-session-3", cart_item_id=item_id, quantity=3)
    assert updated.cart.items[0].quantity == 3

    validated = validate_cart(session_id="tool-session-3")
    assert validated.cart.validation_status == "valid"

    fulfillment = set_fulfillment_method(session_id="tool-session-3", fulfillment_type="delivery")
    assert fulfillment.cart.fulfillment_type == "delivery"

    removed = remove_from_cart(session_id="tool-session-3", cart_item_id=item_id)
    assert removed.cart.items == []

    add_to_cart(session_id="tool-session-3", product_id=PRODUCT_ID, quantity=1)
    cleared = clear_cart(session_id="tool-session-3")
    assert cleared.cart.items == []

    config.get_settings.cache_clear()
