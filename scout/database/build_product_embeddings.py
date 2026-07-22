"""Offline batch precompute for product embeddings (Step 15.5).

Not required for correctness - scout/services/product_search_service.py
already computes and stores (via scout/repositories/embedding_repository.py)
any product's embedding lazily, the first time a semantic search needs
it, exactly like scout/database/seed.py's INSERT OR IGNORE pattern makes
re-running safe. This script exists so an operator can warm the cache
in one batch after seeding or updating the catalog - e.g. in a
deployment step - instead of paying that one-time cost inside a
customer's first request.

Safe to run any number of times: the shared staleness check in
scout.services.product_search_service.ensure_current_embedding (matching
model_name and search_text_hash) means re-running this after no catalog
change recomputes nothing.
"""

import logging
from typing import Optional

from scout.repositories.embedding_repository import EmbeddingRepository
from scout.repositories.product_repository import ProductRepository
from scout.services.embedding_service import get_embedding_provider
from scout.services.product_search_service import ensure_current_embedding

logger = logging.getLogger(__name__)

_LARGE_CATALOG_LIMIT = 1000


def build_product_embeddings(db_path: Optional[str] = None) -> int:
    """Compute and store an embedding for every active product that
    does not already have a current one.

    Args:
        db_path: Optional override of the configured database path,
            used by tests to target a temporary file.

    Returns:
        How many embeddings were actually (re)computed - as opposed to
        already being current and left untouched.
    """
    provider = get_embedding_provider()
    embedding_repo = EmbeddingRepository(db_path)
    products = ProductRepository(db_path).list_active(limit=_LARGE_CATALOG_LIMIT)

    stored = embedding_repo.get_for_product_ids([product.product_id for product in products])
    rebuilt = 0

    for product in products:
        before = stored.get(product.product_id)
        ensure_current_embedding(product, provider, embedding_repo, stored)
        if before is None or before.model_name != provider.model_name or before.search_text_hash is None:
            rebuilt += 1

    logger.info(
        "product_embeddings_built",
        extra={"total_products": len(products), "rebuilt": rebuilt, "model_name": provider.model_name},
    )
    return rebuilt


if __name__ == "__main__":
    count = build_product_embeddings()
    print(f"Rebuilt {count} product embedding(s).")