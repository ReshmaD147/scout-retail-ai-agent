"""Product-embedding repository: the only place that runs SQL against
product_embeddings (Step 15.5).

Like every other repository (see scout/repositories/__init__.py), this
does no embedding computation and no staleness decision at all - it
only stores and retrieves rows exactly as given. Whether a stored
embedding is still usable (matching model_name and search_text_hash) is
scout/services/product_search_service.py's job, one layer up.
"""

import json
from datetime import datetime, timezone
from typing import Dict, List, Optional

from scout.database.connection import connection_scope
from scout.repositories.models import ProductEmbedding


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class EmbeddingRepository:
    """Read/write access to the product_embeddings table."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        """
        Args:
            db_path: Optional override of the configured database path.
                Tests pass a temporary file path here.
        """
        self._db_path = db_path

    def get_by_product_id(self, product_id: str) -> Optional[ProductEmbedding]:
        """Retrieve one product's stored embedding, if any.

        Returns:
            None if this product has never been embedded (or its row
            was deleted along with the product via ON DELETE CASCADE) -
            a normal state the caller (product_search_service) handles
            by computing and storing a fresh one, not an error.
        """
        with connection_scope(self._db_path) as connection:
            row = connection.execute(
                "SELECT * FROM product_embeddings WHERE product_id = ?", (product_id,)
            ).fetchone()
        return ProductEmbedding.from_row(row) if row is not None else None

    def get_for_product_ids(self, product_ids: List[str]) -> Dict[str, ProductEmbedding]:
        """Batch-fetch stored embeddings for a set of products.

        Returns:
            A dict keyed by product_id, containing only the IDs that
            actually have a stored row - callers must not assume every
            requested ID is present (see get_by_product_id).
        """
        if not product_ids:
            return {}
        placeholders = ",".join("?" for _ in product_ids)
        with connection_scope(self._db_path) as connection:
            rows = connection.execute(
                f"SELECT * FROM product_embeddings WHERE product_id IN ({placeholders})",
                product_ids,
            ).fetchall()
        return {row["product_id"]: ProductEmbedding.from_row(row) for row in rows}

    def upsert(
        self,
        product_id: str,
        model_name: str,
        embedding: List[float],
        search_text_hash: str,
    ) -> ProductEmbedding:
        """Store (or overwrite) one product's embedding.

        Called whenever scout/services/product_search_service.py finds
        a missing or stale row - "precompute and reuse" (Step 15.5)
        means this is the only place a fresh vector is ever written,
        and every later search reuses exactly this row until it is
        overwritten again.
        """
        now = _now()
        embedding_json = json.dumps(embedding)
        with connection_scope(self._db_path) as connection:
            connection.execute(
                """
                INSERT INTO product_embeddings
                    (product_id, model_name, embedding_json, search_text_hash, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (product_id) DO UPDATE SET
                    model_name = excluded.model_name,
                    embedding_json = excluded.embedding_json,
                    search_text_hash = excluded.search_text_hash,
                    updated_at = excluded.updated_at
                """,
                (product_id, model_name, embedding_json, search_text_hash, now, now),
            )
        return ProductEmbedding(
            product_id=product_id,
            model_name=model_name,
            embedding=embedding,
            search_text_hash=search_text_hash,
            created_at=now,
            updated_at=now,
        )

    def delete_by_product_id(self, product_id: str) -> None:
        """Remove one product's stored embedding (e.g. before a forced re-embed)."""
        with connection_scope(self._db_path) as connection:
            connection.execute("DELETE FROM product_embeddings WHERE product_id = ?", (product_id,))