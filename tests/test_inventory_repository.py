"""Tests for InventoryRepository."""

from scout.repositories.inventory_repository import InventoryRepository


def test_get_for_product_and_store_returns_record(seeded_db_path):
    repo = InventoryRepository(seeded_db_path)
    record = repo.get_for_product_and_store("FTW-004", "STR-002")
    assert record is not None
    assert record.quantity_available == 8


def test_get_for_product_and_store_returns_record_when_out_of_stock(seeded_db_path):
    # FTW-004 has an explicit row at Maple Grove with quantity 0 - a
    # real, tracked row, not a missing one - so this must return a
    # record (with quantity_available == 0), not None.
    repo = InventoryRepository(seeded_db_path)
    record = repo.get_for_product_and_store("FTW-004", "STR-001")
    assert record is not None
    assert record.quantity_available == 0


def test_get_for_product_and_store_returns_none_when_no_row_exists(seeded_db_path):
    # FTW-005 is only tracked at STR-001 in the seed data, so STR-005
    # has no row at all for this product.
    repo = InventoryRepository(seeded_db_path)
    assert repo.get_for_product_and_store("FTW-005", "STR-005") is None


def test_list_for_product_returns_all_tracked_stores(seeded_db_path):
    repo = InventoryRepository(seeded_db_path)
    records = repo.list_for_product("BAG-005")
    assert len(records) == 5
    assert all(r.quantity_available == 0 for r in records)


def test_list_for_product_returns_empty_list_for_untracked_product(seeded_db_path):
    repo = InventoryRepository(seeded_db_path)
    assert repo.list_for_product("DOES-NOT-EXIST") == []
