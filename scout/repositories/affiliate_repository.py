"""SQLite boundary for Step 16.5 external offers and affiliate clicks."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Optional

from scout.database.connection import connection_scope
from scout.repositories.models import AffiliateClickRecord, ExternalOfferRecord


class AffiliateRepository:
    """Read mock merchant offers and persist click audit records.

    No ranking or matching logic lives here. The repository only executes
    parameterized SQL and maps rows into typed models; deterministic matching
    belongs to scout.services.external_offer_service.
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path

    def list_active_offers(self) -> List[ExternalOfferRecord]:
        with connection_scope(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM external_offers
                WHERE active = 1 AND availability_status = 'in_stock'
                ORDER BY offer_id
                """
            ).fetchall()
        return [ExternalOfferRecord.from_row(row) for row in rows]

    def get_offer(self, offer_id: str) -> Optional[ExternalOfferRecord]:
        with connection_scope(self.db_path) as connection:
            row = connection.execute(
                "SELECT * FROM external_offers WHERE offer_id = ?",
                (offer_id,),
            ).fetchone()
        return ExternalOfferRecord.from_row(row) if row is not None else None

    def record_click(
        self,
        *,
        offer_id: str,
        session_id: str,
        match_type: str,
        workflow_id: Optional[str] = None,
        source_product_id: Optional[str] = None,
    ) -> AffiliateClickRecord:
        click_id = str(uuid.uuid4())
        clicked_at = datetime.now(timezone.utc).isoformat()
        with connection_scope(self.db_path) as connection:
            connection.execute(
                """
                INSERT INTO affiliate_clicks (
                    click_id, offer_id, session_id, workflow_id,
                    source_product_id, match_type, clicked_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    click_id,
                    offer_id,
                    session_id,
                    workflow_id,
                    source_product_id,
                    match_type,
                    clicked_at,
                ),
            )
        return AffiliateClickRecord(
            click_id=click_id,
            offer_id=offer_id,
            session_id=session_id,
            workflow_id=workflow_id,
            source_product_id=source_product_id,
            match_type=match_type,
            clicked_at=clicked_at,
        )

    def list_clicks_for_session(self, session_id: str) -> List[AffiliateClickRecord]:
        with connection_scope(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT * FROM affiliate_clicks
                WHERE session_id = ?
                ORDER BY clicked_at, click_id
                """,
                (session_id,),
            ).fetchall()
        return [AffiliateClickRecord.from_row(row) for row in rows]
