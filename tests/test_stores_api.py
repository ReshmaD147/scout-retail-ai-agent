"""Tests for GET /stores (Step 15)."""

import pytest

from scout.config import get_settings


@pytest.fixture(autouse=True)
def _use_seeded_database(seeded_db_path, monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_PATH", seeded_db_path)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_list_stores_returns_seeded_stores(client):
    response = client.get("/stores")
    assert response.status_code == 200
    stores = response.json()
    assert len(stores) == 5
    assert {"store_id", "store_name", "city", "pickup_enabled", "active"} <= stores[0].keys()
    assert any(store["city"] == "Maple Grove" for store in stores)
