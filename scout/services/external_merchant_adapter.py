"""Mock merchant-feed adapter used by Step 16.5.

The adapter deliberately reads Scout's synthetic `external_offers` table. A
future real integration can implement the same small interface using an
approved retailer feed without changing matching, graph, API, or React code.
"""

from __future__ import annotations

from typing import List, Optional, Protocol

from scout.repositories.affiliate_repository import AffiliateRepository
from scout.repositories.models import ExternalOfferRecord


class ExternalMerchantAdapter(Protocol):
    def list_available_offers(self) -> List[ExternalOfferRecord]: ...

    def get_offer(self, offer_id: str) -> Optional[ExternalOfferRecord]: ...


class MockExternalMerchantAdapter:
    """Database-backed synthetic merchant feed; no network calls."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.repository = AffiliateRepository(db_path)

    def list_available_offers(self) -> List[ExternalOfferRecord]:
        return self.repository.list_active_offers()

    def get_offer(self, offer_id: str) -> Optional[ExternalOfferRecord]:
        return self.repository.get_offer(offer_id)
