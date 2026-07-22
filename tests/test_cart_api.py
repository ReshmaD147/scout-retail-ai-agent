"""Integration tests for Scout's cart REST API (Step 15).

Uses the same `client`/`seeded_db_path` pattern as tests/test_chat_api.py:
a real FastAPI app, a real (temporary, freshly seeded) SQLite database -
never the development database - and real HTTP requests through
`TestClient`. No cart_service function is stubbed here; that isolated
coverage already lives in tests/test_cart_service.py. These tests exist
to confirm the *wiring*: request validation, status codes, and that a
raised CartServiceError becomes the right structured HTTP error.
"""

import pytest

from scout.config import get_settings

FOOTWEAR_PRODUCT = "FTW-004"
STORE_WITH_STOCK = "STR-002"
ACCEPTANCE_QUERY = "Find comfortable work shoes under $100 that I can pick up today near Maple Grove."


@pytest.fixture(autouse=True)
def _use_seeded_database(seeded_db_path, monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_PATH", seeded_db_path)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_add_item_returns_200_and_the_new_cart(client):
    response = client.post(
        "/cart/items", json={"session_id": "api-1", "product_id": FOOTWEAR_PRODUCT, "quantity": 2}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["items"][0]["product_id"] == FOOTWEAR_PRODUCT
    assert body["items"][0]["quantity"] == 2
    assert body["subtotal"] > 0


def test_add_item_with_invalid_product_returns_404(client):
    response = client.post("/cart/items", json={"session_id": "api-2", "product_id": "NOPE-999", "quantity": 1})
    assert response.status_code == 404
    assert response.json()["code"] == "PRODUCT_NOT_FOUND"


def test_add_item_with_zero_quantity_returns_422(client):
    response = client.post(
        "/cart/items", json={"session_id": "api-3", "product_id": FOOTWEAR_PRODUCT, "quantity": 0}
    )
    assert response.status_code == 422


def test_get_cart_for_unknown_session_returns_empty_cart(client):
    response = client.get("/cart/never-seen-session")
    assert response.status_code == 200
    body = response.json()
    assert body["cart_id"] is None
    assert body["items"] == []


def test_full_rest_lifecycle(client):
    add = client.post(
        "/cart/items", json={"session_id": "api-4", "product_id": FOOTWEAR_PRODUCT, "quantity": 1}
    ).json()
    item_id = add["items"][0]["cart_item_id"]

    patched = client.patch(
        f"/cart/items/{item_id}", json={"session_id": "api-4", "quantity": 3}
    ).json()
    assert patched["items"][0]["quantity"] == 3

    fulfillment = client.put(
        "/cart/api-4/fulfillment", json={"fulfillment_type": "pickup", "store_id": STORE_WITH_STOCK}
    )
    assert fulfillment.status_code == 200
    assert fulfillment.json()["fulfillment_type"] == "pickup"

    validated = client.post("/cart/api-4/validate")
    assert validated.status_code == 200
    assert validated.json()["validation_status"] == "valid"

    removed = client.delete(f"/cart/items/{item_id}", params={"session_id": "api-4"})
    assert removed.status_code == 200
    assert removed.json()["items"] == []

    client.post("/cart/items", json={"session_id": "api-4", "product_id": FOOTWEAR_PRODUCT, "quantity": 1})
    cleared = client.delete("/cart/api-4")
    assert cleared.status_code == 200
    assert cleared.json()["items"] == []


def test_remove_item_from_wrong_session_returns_404(client):
    add = client.post(
        "/cart/items", json={"session_id": "owner-session", "product_id": FOOTWEAR_PRODUCT, "quantity": 1}
    ).json()
    item_id = add["items"][0]["cart_item_id"]

    response = client.delete(f"/cart/items/{item_id}", params={"session_id": "intruder-session"})
    assert response.status_code == 404
    assert response.json()["code"] == "CART_ITEM_NOT_FOUND"


def test_cart_command_add_first_product_after_a_real_chat_response(client):
    """End-to-end: a real /chat call verifies a ranked product list,
    /chat persists it (scout.api.routes.chat.save_recommendation_snapshot),
    and a natural-language cart command resolves "the first product"
    against exactly that list - never a guess."""
    chat_response = client.post(
        "/chat", json={"session_id": "cart-command-session", "message": ACCEPTANCE_QUERY}
    ).json()
    assert chat_response["status"] == "completed"
    assert len(chat_response["products"]) > 0
    top_product_id = chat_response["products"][0]["product_id"]

    command_response = client.post(
        "/cart/cart-command-session/command", json={"message": "Add the first product to my cart."}
    )
    assert command_response.status_code == 200
    body = command_response.json()
    assert body["clarification"] is None
    assert body["cart"]["items"][0]["product_id"] == top_product_id


def test_cart_command_with_no_recommendation_history_returns_clarification(client):
    response = client.post(
        "/cart/session-with-no-history/command", json={"message": "Add the first product to my cart."}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["clarification"] is not None
    assert body["cart"]["items"] == []


def test_cart_command_unknown_instruction_returns_clarification(client):
    response = client.post("/cart/api-5/command", json={"message": "sing me a song"})
    assert response.status_code == 200
    assert response.json()["clarification"] is not None


def test_health_chat_and_stream_still_work_alongside_cart_routes(client):
    assert client.get("/health").status_code == 200
    assert client.post("/chat", json={"session_id": "s-1", "message": ACCEPTANCE_QUERY}).status_code == 200
    with client.stream(
        "POST", "/chat/stream", json={"session_id": "s-2", "message": ACCEPTANCE_QUERY}
    ) as response:
        assert response.status_code == 200
