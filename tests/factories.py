"""Factory helpers for building in-memory domain models in tests.

Service-layer tests construct Product/Store/InventoryRecord/Promotion
models directly in memory - no database involved at all - so these
factories exist only to keep individual test functions from repeating
every required field. Each factory fills in sane defaults and accepts
keyword overrides for whatever the test actually cares about.
"""

from typing import Any, Dict

from scout.repositories.models import InventoryRecord, Product, Promotion, Store


def make_product(**overrides: Any) -> Product:
    defaults: Dict[str, Any] = {
        "product_id": "TEST-001",
        "name": "Test Product",
        "brand": "TestBrand",
        "category": "Footwear",
        "subcategory": "Test",
        "description": "A product used only in tests.",
        "price": 50.0,
        "rating": 4.0,
        "review_count": 10,
        "attributes": {},
        "image_url": None,
        "active": True,
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }
    defaults.update(overrides)
    return Product(**defaults)


def make_store(**overrides: Any) -> Store:
    defaults: Dict[str, Any] = {
        "store_id": "STR-TEST",
        "store_name": "Test Store",
        "city": "Testville",
        "state": "MN",
        "postal_code": "00000",
        "latitude": 45.0,
        "longitude": -93.0,
        "pickup_enabled": True,
        "active": True,
    }
    defaults.update(overrides)
    return Store(**defaults)


def make_inventory_record(**overrides: Any) -> InventoryRecord:
    defaults: Dict[str, Any] = {
        "product_id": "TEST-001",
        "store_id": "STR-TEST",
        "quantity_available": 10,
        "quantity_reserved": 0,
        "pickup_ready_minutes": 30,
        "restock_date": None,
        "updated_at": "2026-01-01T00:00:00+00:00",
    }
    defaults.update(overrides)
    return InventoryRecord(**defaults)


def make_promotion(**overrides: Any) -> Promotion:
    defaults: Dict[str, Any] = {
        "promotion_id": "PRM-TEST",
        "product_id": "TEST-001",
        "label": "Test Promotion",
        "discount_percent": 10.0,
        "discount_amount": None,
        "start_date": "2026-01-01",
        "end_date": "2026-12-31",
        "active": True,
    }
    defaults.update(overrides)
    return Promotion(**defaults)
