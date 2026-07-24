from __future__ import annotations

import re
from datetime import date
from pathlib import Path

POLICY_DIR = Path(__file__).resolve().parents[1] / "data" / "policies"
EXPECTED_POLICIES = {
    "returns.md",
    "refunds.md",
    "exchanges.md",
    "shipping_delivery.md",
    "store_pickup.md",
    "order_cancellation.md",
    "warranties.md",
    "damaged_items.md",
    "missing_packages.md",
    "promotions_price_matching.md",
    "gift_cards.md",
    "account_support.md",
}
REQUIRED_METADATA = {
    "policy_id",
    "title",
    "version",
    "effective_date",
    "review_date",
    "status",
    "category",
    "categories",
    "owner",
    "related_policies",
}
ALLOWED_CATEGORIES = {
    "returns",
    "refunds",
    "exchanges",
    "shipping_delivery",
    "store_pickup",
    "order_cancellation",
    "warranties",
    "damaged_items",
    "missing_packages",
    "promotions_price_matching",
    "gift_cards",
    "account_support",
}
VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")


def _parse_value(raw: str) -> str | list[str]:
    value = raw.strip()
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        return [item.strip() for item in inner.split(",") if item.strip()]
    return value


def _load_policy(path: Path) -> tuple[dict[str, str | list[str]], str]:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{path.name} must start with YAML-style metadata"
    _, metadata_text, body = text.split("---", 2)
    metadata: dict[str, str | list[str]] = {}
    for line in metadata_text.strip().splitlines():
        key, value = line.split(":", 1)
        metadata[key.strip()] = _parse_value(value)
    return metadata, body.strip()


def _policy_records() -> dict[str, tuple[dict[str, str | list[str]], str]]:
    return {path.name: _load_policy(path) for path in POLICY_DIR.glob("*.md")}


def test_policy_library_contains_the_required_documents():
    assert POLICY_DIR.exists()
    assert {path.name for path in POLICY_DIR.glob("*.md")} == EXPECTED_POLICIES


def test_policy_metadata_versions_effective_dates_and_categories_are_valid():
    records = _policy_records()
    policy_ids = set()
    for filename, (metadata, body) in records.items():
        missing = REQUIRED_METADATA - set(metadata)
        assert not missing, f"{filename} missing metadata: {sorted(missing)}"
        policy_id = metadata["policy_id"]
        assert isinstance(policy_id, str)
        assert policy_id not in policy_ids
        policy_ids.add(policy_id)
        assert VERSION_PATTERN.match(str(metadata["version"])), filename
        effective_date = date.fromisoformat(str(metadata["effective_date"]))
        review_date = date.fromisoformat(str(metadata["review_date"]))
        assert effective_date <= review_date, filename
        assert metadata["status"] == "active"
        assert metadata["category"] in ALLOWED_CATEGORIES
        categories = metadata["categories"]
        assert isinstance(categories, list) and categories
        assert str(metadata["category"]) in categories
        assert body.startswith("# ")


def test_each_policy_documents_exceptions_and_cross_policy_notes():
    for filename, (_, body) in _policy_records().items():
        assert "## Exceptions" in body, f"{filename} must document exceptions"
        assert "## Cross-Policy Notes" in body, f"{filename} must document cross-policy consistency notes"


def test_related_policy_links_are_existing_markdown_files_and_reciprocal_where_required():
    records = _policy_records()
    existing = set(records)
    for filename, (metadata, body) in records.items():
        related = metadata["related_policies"]
        assert isinstance(related, list) and related, f"{filename} should cite related policies"
        for policy_name in related:
            linked_filename = f"{policy_name}.md"
            assert linked_filename in existing, f"{filename} links to missing {linked_filename}"
            assert f"`{linked_filename}`" in body, f"{filename} should cite `{linked_filename}` in body"

    reciprocal_pairs = {
        ("returns.md", "refunds.md"),
        ("returns.md", "exchanges.md"),
        ("shipping_delivery.md", "missing_packages.md"),
        ("damaged_items.md", "warranties.md"),
        ("gift_cards.md", "refunds.md"),
        ("promotions_price_matching.md", "gift_cards.md"),
    }
    for left, right in reciprocal_pairs:
        left_related = records[left][0]["related_policies"]
        right_related = records[right][0]["related_policies"]
        assert isinstance(left_related, list) and right.removesuffix(".md") in left_related
        assert isinstance(right_related, list) and left.removesuffix(".md") in right_related
