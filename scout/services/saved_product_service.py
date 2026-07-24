"""Deterministic Saved Products business logic."""

from typing import List, Optional

from pydantic import BaseModel, Field

from scout.mcp.schemas import ProductSummary
from scout.repositories.product_repository import ProductRepository
from scout.repositories.saved_product_repository import SavedProductRepository


class SavedProductServiceError(Exception):
    def __init__(self, error_type: str, message: str) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.message = message


class SavedProductView(BaseModel):
    saved_id: str
    product: ProductSummary
    created_at: str
    availability_label: str
    can_add_to_cart: bool


class SavedProductsView(BaseModel):
    session_id: Optional[str] = None
    customer_id: Optional[str] = None
    saved_product_ids: List[str] = Field(default_factory=list)
    products: List[SavedProductView] = Field(default_factory=list)
    count: int = 0


def list_saved_products(
    session_id: Optional[str],
    customer_id: Optional[str] = None,
    db_path: Optional[str] = None,
) -> SavedProductsView:
    _validate_owner(session_id, customer_id)
    saved_repo = SavedProductRepository(db_path)
    product_repo = ProductRepository(db_path)
    saved_rows = saved_repo.list_for_owner(session_id, customer_id)

    products: List[SavedProductView] = []
    for saved in saved_rows:
        product = product_repo.get_by_id(saved.product_id)
        if product is None:
            continue
        products.append(
            SavedProductView(
                saved_id=saved.saved_id,
                product=_to_summary(product),
                created_at=saved.created_at,
                availability_label="Available" if product.active else "Unavailable",
                can_add_to_cart=product.active,
            )
        )

    return SavedProductsView(
        session_id=None if customer_id else session_id,
        customer_id=customer_id,
        saved_product_ids=[item.product.product_id for item in products],
        products=products,
        count=len(products),
    )


def list_saved_product_ids(
    session_id: Optional[str],
    customer_id: Optional[str] = None,
    db_path: Optional[str] = None,
) -> List[str]:
    return list_saved_products(session_id, customer_id, db_path).saved_product_ids


def save_product(
    session_id: Optional[str],
    product_id: str,
    customer_id: Optional[str] = None,
    db_path: Optional[str] = None,
) -> SavedProductsView:
    _validate_owner(session_id, customer_id)
    product = ProductRepository(db_path).get_by_id(product_id)
    if product is None:
        raise SavedProductServiceError("product_not_found", "Scout could not find that product.")
    SavedProductRepository(db_path).save(product_id, session_id, customer_id)
    return list_saved_products(session_id, customer_id, db_path)


def remove_product(
    session_id: Optional[str],
    product_id: str,
    customer_id: Optional[str] = None,
    db_path: Optional[str] = None,
) -> SavedProductsView:
    _validate_owner(session_id, customer_id)
    SavedProductRepository(db_path).remove(product_id, session_id, customer_id)
    return list_saved_products(session_id, customer_id, db_path)


def _validate_owner(session_id: Optional[str], customer_id: Optional[str]) -> None:
    if not (customer_id and customer_id.strip()) and not (session_id and session_id.strip()):
        raise SavedProductServiceError("missing_owner", "A session or customer is required to use saved products.")


def _to_summary(product) -> ProductSummary:
    return ProductSummary(
        product_id=product.product_id,
        name=product.name,
        brand=product.brand,
        category=product.category,
        subcategory=product.subcategory,
        price=product.price,
        rating=product.rating,
        review_count=product.review_count,
        active=product.active,
        attributes=product.attributes,
    )
