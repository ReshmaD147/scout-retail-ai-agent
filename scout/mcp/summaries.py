"""Shared conversion from repository Product models to the MCP-facing
ProductSummary schema.

Both scout/mcp/product_tools.py and scout/mcp/inventory_tools.py need
to turn a Product into the exact same customer-facing summary shape.
Keeping that mapping here means it is defined once, not maintained as
two independently-drifting copies in each tool module.
"""

from scout.mcp.schemas import ProductSummary
from scout.repositories.models import Product


def product_to_summary(product: Product) -> ProductSummary:
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
