"""Promotion repository: the only place that runs SQL against promotions."""

from typing import List, Optional

from scout.database.connection import connection_scope
from scout.repositories.models import Promotion


class PromotionRepository:
    """Read access to the promotions table."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        """
        Args:
            db_path: Optional override of the configured database path.
                Tests pass a temporary file path here.
        """
        self._db_path = db_path

    def list_active(self, product_id: Optional[str] = None) -> List[Promotion]:
        """List promotions whose stored `active` flag is set to 1.

        This checks only the `active` column - the manual on/off switch
        set by merchandising. It deliberately does NOT check
        start_date/end_date against today's date. As documented in
        scout/database/schema.sql, reconciling the active flag with the
        date range into one "is this promotion usable right now" answer
        is deterministic pricing/business logic that belongs in the
        service layer (a later phase), not in a repository. A repository
        method should do exactly what its name says - list rows where
        active = 1 - and nothing more.

        Args:
            product_id: If given, restrict results to this product.
                None returns active-flagged promotions for every
                product.

        Returns:
            Promotions ordered by promotion_id. Empty list if none
            match.
        """
        query = "SELECT * FROM promotions WHERE active = 1"
        params: List[object] = []

        if product_id is not None:
            query += " AND product_id = ?"
            params.append(product_id)

        query += " ORDER BY promotion_id"

        with connection_scope(self._db_path) as connection:
            rows = connection.execute(query, params).fetchall()

        return [Promotion.from_row(row) for row in rows]
