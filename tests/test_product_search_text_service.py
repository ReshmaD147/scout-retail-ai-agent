"""Tests for scout.services.product_search_text_service."""

from tests.factories import make_product

from scout.services.product_search_text_service import build_search_text, hash_search_text


def test_build_search_text_includes_core_catalog_fields():
    product = make_product(
        name="ComfortPro Shift Support",
        brand="ComfortPro",
        category="Footwear",
        subcategory="Work",
        description="Slip-resistant work shoe with arch support designed for long shifts.",
        attributes={"cushioning": "high", "use_case": "work shifts / standing all day"},
    )

    text = build_search_text(product)

    for expected in [
        "comfortpro shift support",
        "footwear",
        "work",
        "arch support",
        "standing all day",
    ]:
        assert expected in text


def test_build_search_text_flattens_list_and_nested_attributes():
    product = make_product(attributes={"size_options": ["7", "8", "9"], "specs": {"material": "canvas"}})

    text = build_search_text(product)

    assert "7" in text
    assert "canvas" in text


def test_build_search_text_is_deterministic_regardless_of_attribute_order():
    product_a = make_product(attributes={"color": "blue", "material": "nylon"})
    product_b = make_product(attributes={"material": "nylon", "color": "blue"})

    assert build_search_text(product_a) == build_search_text(product_b)


def test_hash_search_text_is_stable_and_change_sensitive():
    text = "a stable piece of text"
    assert hash_search_text(text) == hash_search_text(text)
    assert hash_search_text(text) != hash_search_text(text + " changed")