"""Tests for Scout database initialization and seeding.

Every test here runs against a temporary SQLite file created by
pytest's built-in tmp_path fixture. None of these tests read or write
the development database configured by DATABASE_PATH / .env.
"""

from scout.database.connection import connection_scope
from scout.database.initialize import initialize_database
from scout.database.seed import EXTERNAL_OFFERS, INVENTORY, PRODUCTS, PROMOTIONS, STORES, seed_database

EXPECTED_TABLES = {
    "products",
    "stores",
    "inventory",
    "promotions",
    "carts",
    "cart_items",
    "checkout_sessions",
    "payments",
    "orders",
    "order_items",
    "inventory_reservations",
    "external_offers",
    "affiliate_clicks",
}
EXPECTED_CATEGORIES = {"Footwear", "Bags", "Electronics", "Home and Kitchen"}

# The seeded_db_path fixture used below lives in tests/conftest.py, shared
# with the repository test modules.


def test_initialize_creates_all_tables(tmp_path):
    db_path = str(tmp_path / "init_only.db")
    initialize_database(db_path)

    with connection_scope(db_path) as connection:
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    table_names = {row["name"] for row in rows}

    assert EXPECTED_TABLES.issubset(table_names)


def test_foreign_keys_enabled(tmp_path):
    db_path = str(tmp_path / "fk_check.db")
    initialize_database(db_path)

    with connection_scope(db_path) as connection:
        result = connection.execute("PRAGMA foreign_keys").fetchone()

    assert result[0] == 1


def test_seed_creates_five_stores(seeded_db_path):
    assert len(STORES) == 5
    with connection_scope(seeded_db_path) as connection:
        count = connection.execute("SELECT COUNT(*) AS c FROM stores").fetchone()["c"]
    assert count == 5


def test_seed_creates_thirty_products(seeded_db_path):
    assert len(PRODUCTS) == 30
    with connection_scope(seeded_db_path) as connection:
        count = connection.execute("SELECT COUNT(*) AS c FROM products").fetchone()["c"]
    assert count == 30


def test_seed_creates_all_four_categories(seeded_db_path):
    with connection_scope(seeded_db_path) as connection:
        rows = connection.execute("SELECT DISTINCT category FROM products").fetchall()
    categories = {row["category"] for row in rows}
    assert categories == EXPECTED_CATEGORIES


def test_inventory_rows_reference_valid_products(seeded_db_path):
    assert len(INVENTORY) > 0
    with connection_scope(seeded_db_path) as connection:
        orphaned = connection.execute(
            """
            SELECT COUNT(*) AS c
            FROM inventory
            LEFT JOIN products USING (product_id)
            WHERE products.product_id IS NULL
            """
        ).fetchone()["c"]
    assert orphaned == 0


def test_inventory_rows_reference_valid_stores(seeded_db_path):
    with connection_scope(seeded_db_path) as connection:
        orphaned = connection.execute(
            """
            SELECT COUNT(*) AS c
            FROM inventory
            LEFT JOIN stores USING (store_id)
            WHERE stores.store_id IS NULL
            """
        ).fetchone()["c"]
    assert orphaned == 0


def test_active_and_inactive_promotions_exist(seeded_db_path):
    assert len(PROMOTIONS) > 0
    with connection_scope(seeded_db_path) as connection:
        active_count = connection.execute(
            "SELECT COUNT(*) AS c FROM promotions WHERE active = 1"
        ).fetchone()["c"]
        inactive_count = connection.execute(
            "SELECT COUNT(*) AS c FROM promotions WHERE active = 0"
        ).fetchone()["c"]
    assert active_count > 0
    assert inactive_count > 0


def test_product_unavailable_in_maple_grove_but_available_elsewhere(seeded_db_path):
    with connection_scope(seeded_db_path) as connection:
        maple_grove_out = connection.execute(
            """
            SELECT i.product_id
            FROM inventory i
            JOIN stores s ON s.store_id = i.store_id
            WHERE s.city = 'Maple Grove' AND i.quantity_available = 0
            """
        ).fetchall()
        maple_grove_out_products = {row["product_id"] for row in maple_grove_out}

        available_elsewhere = connection.execute(
            """
            SELECT i.product_id
            FROM inventory i
            JOIN stores s ON s.store_id = i.store_id
            WHERE s.city != 'Maple Grove' AND i.quantity_available > 0
            """
        ).fetchall()
        available_elsewhere_products = {row["product_id"] for row in available_elsewhere}

    overlap = maple_grove_out_products & available_elsewhere_products
    assert overlap, "Expected at least one product out at Maple Grove but available elsewhere"


def test_product_with_zero_local_availability(seeded_db_path):
    with connection_scope(seeded_db_path) as connection:
        rows = connection.execute(
            """
            SELECT product_id, SUM(quantity_available) AS total_available
            FROM inventory
            GROUP BY product_id
            HAVING total_available = 0
            """
        ).fetchall()
    assert len(rows) >= 1


def test_seed_creates_mock_external_offers_without_real_retailer_urls(seeded_db_path):
    assert len(EXTERNAL_OFFERS) > 0
    with connection_scope(seeded_db_path) as connection:
        rows = connection.execute(
            "SELECT merchant_name, merchant_url FROM external_offers"
        ).fetchall()
    assert len(rows) == len(EXTERNAL_OFFERS)
    rendered = " ".join(f"{row['merchant_name']} {row['merchant_url']}" for row in rows).lower()
    assert "amazon" not in rendered
    assert "walmart" not in rendered
    assert all(row["merchant_url"].startswith("https://example.com/") for row in rows)


def test_seeding_twice_does_not_duplicate(seeded_db_path):
    seed_database(seeded_db_path)  # run seeding again on top of itself

    with connection_scope(seeded_db_path) as connection:
        products = connection.execute("SELECT COUNT(*) AS c FROM products").fetchone()["c"]
        stores = connection.execute("SELECT COUNT(*) AS c FROM stores").fetchone()["c"]
        inventory = connection.execute("SELECT COUNT(*) AS c FROM inventory").fetchone()["c"]
        promotions = connection.execute("SELECT COUNT(*) AS c FROM promotions").fetchone()["c"]
        external_offers = connection.execute("SELECT COUNT(*) AS c FROM external_offers").fetchone()["c"]

    assert products == len(PRODUCTS)
    assert stores == len(STORES)
    assert inventory == len(INVENTORY)
    assert promotions == len(PROMOTIONS)
    assert external_offers == len(EXTERNAL_OFFERS)
