"""Deterministic product search-text construction (Step 15.5).

Every embedding - whether for the "hashing" or the "ollama" provider
(scout/services/embedding_service.py) - is computed over the exact same
plain-text document this module builds for a product, never over raw
JSON or a partial field. That single, shared construction is what makes
"precompute and reuse" (schema.sql's product_embeddings.search_text_hash)
meaningful: two calls that build the same text for the same product
always hash identically, so an unrelated code change never triggers a
needless re-embed, and an actual catalog edit always does.

What goes into the text
--------------------------
Name, brand, category, subcategory, and description come directly from
the products table. Every attribute value (scout/database/seed.py's
free-form `attributes` dict - use_case, cushioning, material, color,
capacity, and so on) is appended too, since Step 15.5 explicitly
requires "features, use cases, materials, and tags" to be searchable
by meaning, and this catalog does not have separate columns for those -
they already live inside `attributes_json`.
"""

import hashlib
from typing import Any

from scout.repositories.models import Product


def build_search_text(product: Product) -> str:
    """Build the canonical text an embedding is computed from.

    Args:
        product: The product to describe.

    Returns:
        A single normalized string combining every field Step 15.5
        requires (name, category, subcategory, description, brand, and
        every attribute value) - deterministic and stable for the same
        product data, so the same product always produces the exact
        same text (and therefore the same embedding and the same
        search_text_hash) until its underlying data actually changes.
    """
    parts = [
        product.name,
        product.brand,
        product.category,
        product.subcategory,
        product.description,
    ]
    for key in sorted(product.attributes.keys()):
        parts.append(_attribute_text(product.attributes[key]))

    return " ".join(part for part in parts if part).strip().lower()


def _attribute_text(value: Any) -> str:
    """Flatten one attribute value (string, number, list, or nested
    dict - seed.py uses all of these, e.g. `size_options` is a list)
    into plain words, never raw JSON syntax like brackets or quotes."""
    if isinstance(value, (list, tuple)):
        return " ".join(_attribute_text(item) for item in value)
    if isinstance(value, dict):
        return " ".join(_attribute_text(item) for item in value.values())
    return str(value)


def hash_search_text(search_text: str) -> str:
    """A stable content hash for change detection.

    Args:
        search_text: The exact text produced by build_search_text() for
            one product (or a query - reused for consistency).

    Returns:
        A sha256 hex digest. Used by scout/repositories/models.py's
        ProductEmbedding.search_text_hash and compared against a fresh
        build_search_text() call every time
        scout/services/product_search_service.py considers reusing a
        stored embedding - see that module for the staleness check
        itself, which this function does not perform.
    """
    return hashlib.sha256(search_text.encode("utf-8")).hexdigest()
