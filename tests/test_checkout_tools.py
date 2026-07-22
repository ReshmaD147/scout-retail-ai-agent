"""Direct MCP checkout tool tests."""

import pytest

from scout.config import get_settings
from scout.mcp.checkout_tools import confirm_checkout, create_checkout_review
from scout.services import cart_service


@pytest.fixture(autouse=True)
def _use_seeded_database(seeded_db_path, monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_PATH", seeded_db_path)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_checkout_tools_return_structured_review_and_order(seeded_db_path):
    cart_service.add_item("tool-session", "FTW-004", 1, db_path=seeded_db_path)
    cart_service.set_fulfillment("tool-session", "pickup", "STR-002", db_path=seeded_db_path)

    review_result = create_checkout_review("tool-session")
    assert review_result.error is None
    assert review_result.review is not None

    order_result = confirm_checkout(
        review_result.review.checkout_id,
        "tool-session",
        "tool-checkout-key-0001",
        True,
    )
    assert order_result.error is None
    assert order_result.order is not None
    assert order_result.order.status == "confirmed"


def test_checkout_tool_refuses_missing_confirmation(seeded_db_path):
    cart_service.add_item("tool-session", "FTW-004", 1, db_path=seeded_db_path)
    cart_service.set_fulfillment("tool-session", "pickup", "STR-002", db_path=seeded_db_path)
    review = create_checkout_review("tool-session").review
    assert review is not None

    result = confirm_checkout(
        review.checkout_id,
        "tool-session",
        "tool-checkout-key-0002",
        False,
    )
    assert result.order is None
    assert result.error is not None
    assert result.error.error_type == "confirmation_required"
