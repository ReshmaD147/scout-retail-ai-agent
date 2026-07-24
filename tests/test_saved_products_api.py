import pytest

from scout.config import get_settings
from scout.repositories.saved_product_repository import SavedProductRepository
from scout.services.saved_product_service import list_saved_products, save_product

PRODUCT_ID = "FTW-004"


@pytest.fixture(autouse=True)
def _use_seeded_database(seeded_db_path, monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_PATH", seeded_db_path)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_save_valid_product_and_list_it(client):
    response = client.post("/saved-products", json={"session_id": "saved-a", "product_id": PRODUCT_ID})
    assert response.status_code == 200
    body = response.json()
    assert body["saved_product_ids"] == [PRODUCT_ID]
    assert body["products"][0]["product"]["name"] == "ComfortPro Shift Support"


def test_remove_saved_product(client):
    client.post("/saved-products", json={"session_id": "saved-remove", "product_id": PRODUCT_ID})
    response = client.delete(f"/saved-products/{PRODUCT_ID}", params={"session_id": "saved-remove"})
    assert response.status_code == 200
    assert response.json()["saved_product_ids"] == []


def test_duplicate_save_is_idempotent(client):
    first = client.post("/saved-products", json={"session_id": "saved-dupe", "product_id": PRODUCT_ID}).json()
    second = client.post("/saved-products", json={"session_id": "saved-dupe", "product_id": PRODUCT_ID}).json()
    assert first["count"] == 1
    assert second["count"] == 1
    assert first["products"][0]["saved_id"] == second["products"][0]["saved_id"]


def test_list_saved_product_ids(client):
    client.post("/saved-products", json={"session_id": "saved-ids", "product_id": PRODUCT_ID})
    response = client.get("/saved-products/ids", params={"session_id": "saved-ids"})
    assert response.status_code == 200
    assert response.json() == [PRODUCT_ID]


def test_saved_products_persist_across_reads(client):
    client.post("/saved-products", json={"session_id": "saved-persist", "product_id": PRODUCT_ID})
    first = client.get("/saved-products", params={"session_id": "saved-persist"}).json()
    second = client.get("/saved-products", params={"session_id": "saved-persist"}).json()
    assert first["saved_product_ids"] == second["saved_product_ids"] == [PRODUCT_ID]


def test_guest_session_isolation(client):
    client.post("/saved-products", json={"session_id": "saved-owner-a", "product_id": PRODUCT_ID})
    response = client.get("/saved-products", params={"session_id": "saved-owner-b"})
    assert response.status_code == 200
    assert response.json()["saved_product_ids"] == []


def test_authenticated_customer_isolation(client):
    client.post("/saved-products", json={"customer_id": "customer-a", "product_id": PRODUCT_ID})
    response = client.get("/saved-products", params={"customer_id": "customer-b"})
    assert response.status_code == 200
    assert response.json()["saved_product_ids"] == []


def test_missing_owner_is_rejected(client):
    response = client.post("/saved-products", json={"product_id": PRODUCT_ID})
    assert response.status_code == 400
    assert response.json()["code"] == "MISSING_OWNER"


def test_unknown_product_is_rejected(client):
    response = client.post("/saved-products", json={"session_id": "saved-unknown", "product_id": "NOPE"})
    assert response.status_code == 404
    assert response.json()["code"] == "PRODUCT_NOT_FOUND"


def test_repository_uniqueness_constraint(seeded_db_path):
    repo = SavedProductRepository(seeded_db_path)
    first = repo.save(PRODUCT_ID, "repo-owner", None)
    second = repo.save(PRODUCT_ID, "repo-owner", None)
    assert first.saved_id == second.saved_id
    assert len(repo.list_for_owner("repo-owner", None)) == 1


def test_service_does_not_mutate_cart_checkout_or_inventory(seeded_db_path):
    before = list_saved_products("side-effect-owner", db_path=seeded_db_path)
    after = save_product("side-effect-owner", PRODUCT_ID, db_path=seeded_db_path)
    assert before.count == 0
    assert after.count == 1
