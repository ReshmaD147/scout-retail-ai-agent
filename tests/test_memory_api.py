from fastapi.testclient import TestClient

from scout.api.app import create_app
from scout.config import get_settings
from scout.services import memory_service


def _client_for_db(db_path: str, monkeypatch) -> TestClient:
    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_PATH", db_path)
    get_settings.cache_clear()
    return TestClient(create_app())


def test_memory_preference_controls(client, seeded_db_path, monkeypatch):
    client = _client_for_db(seeded_db_path, monkeypatch)

    created = client.post(
        "/memory/preferences",
        json={"customer_id": "api-memory", "type": "preferred_brand", "value": "ComfortPro", "confidence": 1.0, "source": "explicit"},
    )
    assert created.status_code == 200
    preference_id = created.json()["preference_id"]

    listed = client.get("/memory/preferences", params={"customer_id": "api-memory"})
    assert listed.status_code == 200
    assert listed.json()[0]["preference_id"] == preference_id

    deleted = client.delete(f"/memory/preferences/{preference_id}", params={"customer_id": "api-memory"})
    assert deleted.status_code == 200
    assert client.get("/memory/preferences", params={"customer_id": "api-memory"}).json() == []


def test_memory_disable_and_clear_session_controls(seeded_db_path, monkeypatch):
    client = _client_for_db(seeded_db_path, monkeypatch)

    viewed = client.post("/memory/session/viewed", json={"session_id": "api-session", "product_id": "FTW-004", "customer_id": "api-customer"})
    assert viewed.status_code == 200
    assert viewed.json()["viewed_products"] == ["FTW-004"]

    disabled = client.post("/memory/controls", json={"customer_id": "api-customer", "memory_enabled": False})
    assert disabled.status_code == 200
    assert disabled.json()["memory_enabled"] is False
    assert memory_service.list_preferences("api-customer", db_path=seeded_db_path) == []

    cleared = client.delete("/memory/session/api-session")
    assert cleared.status_code == 200
