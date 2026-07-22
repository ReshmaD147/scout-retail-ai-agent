"""Recommendation-reference repository (Step 15).

The only place that runs SQL against session_recommendation_snapshots -
see the long comment above that table in scout/database/schema.sql for
what this narrow, single-purpose cache is (and is not) for.
"""

import json
from datetime import datetime, timezone
from typing import List, Optional, TypedDict

from scout.database.connection import connection_scope
from scout.repositories.models import SessionRecommendationSnapshot


class ProductReference(TypedDict):
    product_id: str
    name: str


class RecommendationReferenceRepository:
    """Read/write access to session_recommendation_snapshots."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        """
        Args:
            db_path: Optional override of the configured database path.
                Tests pass a temporary file path here.
        """
        self._db_path = db_path

    def save(self, session_id: str, workflow_id: str, products: List[ProductReference]) -> None:
        """Overwrite the stored recommendation list for a session.

        Args:
            session_id: The chat session this list belongs to.
            workflow_id: The workflow run that produced this list, for
                traceability.
            products: The verified, ranked (product_id, name) pairs
                shown to the customer - already-grounded data, never
                fetched or guessed by this method itself.

        There is exactly one row per session_id: "INSERT ... ON
        CONFLICT ... DO UPDATE" means the newest chat response always
        replaces the previous snapshot, since only the *most recent*
        recommendation list is ever a valid target for "the first
        product."
        """
        now = datetime.now(timezone.utc).isoformat()
        with connection_scope(self._db_path) as connection:
            connection.execute(
                """
                INSERT INTO session_recommendation_snapshots (session_id, workflow_id, products_json, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT (session_id) DO UPDATE SET
                    workflow_id = excluded.workflow_id,
                    products_json = excluded.products_json,
                    updated_at = excluded.updated_at
                """,
                (session_id, workflow_id, json.dumps(products), now),
            )

    def get(self, session_id: str) -> Optional[SessionRecommendationSnapshot]:
        """Retrieve the last verified recommendation list for a session.

        Returns:
            None if this session has never received a recommendation
            (or its snapshot has not been saved) - a normal case (a
            brand-new session, or one that only ever asked about
            policies), not an error.
        """
        with connection_scope(self._db_path) as connection:
            row = connection.execute(
                "SELECT * FROM session_recommendation_snapshots WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return SessionRecommendationSnapshot.from_row(row) if row is not None else None
