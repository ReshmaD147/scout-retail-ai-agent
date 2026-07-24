from scout.mcp.schemas import ProductSummary
from scout.services.product_relevance_service import check_product_relevance, filter_relevant_products


def _product(product_id: str, category: str, subcategory: str) -> ProductSummary:
    return ProductSummary(
        product_id=product_id,
        name=f"{subcategory} product",
        brand="Scout",
        category=category,
        subcategory=subcategory,
        price=49.99,
        rating=4.5,
        review_count=100,
        active=True,
        attributes={"tags": ["work shoe"], "cushioning": "High", "slip_resistance": "High"},
    )


def test_unrelated_product_category_is_rejected_before_explanation():
    kettle = _product("KIT-001", "Home and Kitchen", "Kettles")

    result = check_product_relevance(
        kettle,
        {"category": "Footwear", "subcategory": "Work", "max_price": 100.0},
        "Work shoes under $100",
    )

    assert result.passed is False
    assert "does not match requested" in result.reasons[0]


def test_relevant_product_passes_with_reasons_and_attributes():
    shoe = _product("FTW-004", "Footwear", "Work")

    result = check_product_relevance(
        shoe,
        {"category": "Footwear", "subcategory": "Work", "max_price": 100.0},
        "comfortable slip resistant work shoes under $100",
    )

    assert result.passed is True
    assert "comfortable" in result.matched_attributes
    assert "slip" in result.matched_attributes


def test_filter_does_not_force_three_products_when_only_one_is_relevant():
    shoe = _product("FTW-004", "Footwear", "Work")
    kettle = _product("KIT-001", "Home and Kitchen", "Kettles")

    products, results = filter_relevant_products(
        [shoe, kettle],
        {"category": "Footwear", "subcategory": "Work", "max_price": 100.0},
        "Work shoes under $100",
    )

    assert [product.product_id for product in products] == ["FTW-004"]
    assert [result.passed for result in results] == [True, False]
