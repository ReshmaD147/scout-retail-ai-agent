"""End-to-end regression tests for exact product-type/deal filtering."""

import pytest

from scout.config import get_settings


@pytest.fixture(autouse=True)
def _use_seeded_database(seeded_db_path, monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_PATH", seeded_db_path)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_wireless_earbuds_never_returns_power_banks_and_may_return_only_two(client):
    response = client.post("/chat", json={"session_id": "reg-earbuds", "message": "Wireless earbuds"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert len(body["products"]) == 2
    assert all(product["subcategory"] == "Earbuds" for product in body["products"])
    assert "ELE-005" not in {product["product_id"] for product in body["products"]}
    assert not any("No store was resolved" in error["message"] for error in body["errors"])


def test_coffee_maker_deals_returns_only_current_promoted_coffee_makers(client):
    response = client.post("/chat", json={"session_id": "reg-coffee", "message": "Coffee maker deals"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert [product["product_id"] for product in body["products"]] == ["HOM-001"]
    assert all(product["subcategory"] == "Coffee Makers" for product in body["products"])
    assert "Coffee Lovers Discount" in (body["answer"] or "")
    assert "LumaGlow Ambient Table Lamp" not in (body["answer"] or "")


def test_structured_filters_are_applied_by_backend_not_only_react(client):
    response = client.post(
        "/chat",
        json={
            "session_id": "reg-filter",
            "message": "Show me electronics",
            "filters": {
                "category": "Electronics",
                "product_type": "Earbuds",
                "max_price": 100,
                "attributes": ["connectivity:Bluetooth 5.3"],
                "in_stock_only": True,
                "fulfillment": "delivery",
            },
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert [product["product_id"] for product in body["products"]] == ["ELE-001"]
    assert all(product["price"] <= 100 for product in body["products"])
    assert all(option["channel"] == "delivery" for option in body["fulfillment_options"])
