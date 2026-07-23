"""Regression coverage for the real, catalog-backed React filter contract."""

import pytest

from scout.config import get_settings


@pytest.fixture(autouse=True)
def _use_seeded_database(seeded_db_path, monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_PATH", seeded_db_path)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_catalog_filter_options_are_derived_from_active_catalog(client):
    response = client.get("/catalog/filter-options")
    assert response.status_code == 200
    body = response.json()
    assert body["max_price"] >= 219
    assert "Electronics" in body["categories"]
    assert "Earbuds" in body["product_types"]["Electronics"]
    assert all(":" in option["token"] for option in body["attributes"])


def test_stores_include_real_coordinates_for_the_map(client):
    response = client.get("/stores")
    assert response.status_code == 200
    stores = response.json()
    assert stores
    assert all(isinstance(store["latitude"], (int, float)) for store in stores)
    assert all(isinstance(store["longitude"], (int, float)) for store in stores)
