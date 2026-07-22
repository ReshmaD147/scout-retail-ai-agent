"""HTTP contract tests for Step 16.5 external offer search and redirect."""

import pytest

from scout.config import get_settings
from scout.repositories.affiliate_repository import AffiliateRepository


@pytest.fixture(autouse=True)
def _use_seeded_database(seeded_db_path, monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_PATH", seeded_db_path)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_external_search_api_returns_mock_similar_offers(client):
    response = client.post(
        "/affiliate/offers/search",
        json={
            "query_text": "comfortable work shoes for standing",
            "category": "Footwear",
            "max_price": 100,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["offers"]
    assert all(offer["match_type"] == "similar" for offer in body["offers"])
    assert all("merchant_url" not in offer for offer in body["offers"])


def test_click_endpoint_records_then_redirects(client, seeded_db_path):
    response = client.get(
        "/affiliate/click/EXT-OFF-001",
        params={
            "session_id": "api-affiliate-session",
            "workflow_id": "workflow-1",
            "match_type": "similar",
        },
        follow_redirects=False,
    )

    assert response.status_code == 307
    assert response.headers["location"].startswith("https://example.com/")
    clicks = AffiliateRepository(seeded_db_path).list_clicks_for_session("api-affiliate-session")
    assert len(clicks) == 1


def test_external_offer_cannot_be_added_to_scout_cart(client):
    response = client.post(
        "/cart/items",
        json={"session_id": "external-cart", "product_id": "EXT-OFF-001", "quantity": 1},
    )
    assert response.status_code in {400, 404}
