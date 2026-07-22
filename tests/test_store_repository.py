"""Tests for StoreRepository."""

from scout.repositories.store_repository import StoreRepository


def test_list_stores_returns_five_active_stores(seeded_db_path):
    repo = StoreRepository(seeded_db_path)
    stores = repo.list_stores()
    assert len(stores) == 5
    assert all(s.active for s in stores)


def test_get_by_id_returns_store(seeded_db_path):
    repo = StoreRepository(seeded_db_path)
    store = repo.get_by_id("STR-001")
    assert store is not None
    assert store.city == "Maple Grove"


def test_get_by_id_returns_none_for_missing_store(seeded_db_path):
    repo = StoreRepository(seeded_db_path)
    assert repo.get_by_id("STR-999") is None


def test_find_nearby_excludes_reference_store_and_sorts_by_distance(seeded_db_path):
    repo = StoreRepository(seeded_db_path)
    maple_grove = repo.get_by_id("STR-001")

    nearby = repo.find_nearby(
        latitude=maple_grove.latitude,
        longitude=maple_grove.longitude,
        radius_miles=50,
        exclude_store_id="STR-001",
    )

    assert nearby
    assert all(entry.store.store_id != "STR-001" for entry in nearby)
    distances = [entry.distance_miles for entry in nearby]
    assert distances == sorted(distances)


def test_find_nearby_respects_radius(seeded_db_path):
    repo = StoreRepository(seeded_db_path)
    maple_grove = repo.get_by_id("STR-001")

    nearby = repo.find_nearby(
        latitude=maple_grove.latitude,
        longitude=maple_grove.longitude,
        radius_miles=0.01,
        exclude_store_id="STR-001",
    )

    assert nearby == []


def test_find_nearby_falls_back_to_configured_default_radius(seeded_db_path, monkeypatch):
    from scout.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("NEARBY_STORE_RADIUS_MILES", "1000")

    repo = StoreRepository(seeded_db_path)
    maple_grove = repo.get_by_id("STR-001")

    nearby = repo.find_nearby(
        latitude=maple_grove.latitude,
        longitude=maple_grove.longitude,
        exclude_store_id="STR-001",
    )

    assert len(nearby) == 4
    get_settings.cache_clear()
