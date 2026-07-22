"""Store repository: the only place that runs SQL against stores.

Also owns the nearby-store distance calculation. With only five demo
stores there is no reason to push distance math into SQL - it is
computed in plain Python (Haversine formula) after a normal
parameterized SELECT.
"""

import math
from typing import List, Optional

from scout.config import get_settings
from scout.database.connection import connection_scope
from scout.repositories.models import Store, StoreDistance

_EARTH_RADIUS_MILES = 3958.8


def _haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two lat/lon points, in miles."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return _EARTH_RADIUS_MILES * c


class StoreRepository:
    """Read access to the stores table."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        """
        Args:
            db_path: Optional override of the configured database path.
                Tests pass a temporary file path here.
        """
        self._db_path = db_path

    def list_stores(self, active_only: bool = True) -> List[Store]:
        """List demo stores.

        Args:
            active_only: If True (default), only active stores are
                returned.

        Returns:
            Stores ordered by city. Empty list if none match.
        """
        query = "SELECT * FROM stores"
        params: List[object] = []
        if active_only:
            query += " WHERE active = 1"
        query += " ORDER BY city"

        with connection_scope(self._db_path) as connection:
            rows = connection.execute(query, params).fetchall()

        return [Store.from_row(row) for row in rows]

    def get_by_id(self, store_id: str) -> Optional[Store]:
        """Retrieve one store by its primary key.

        Args:
            store_id: The store's store_id, e.g. "STR-001".

        Returns:
            A Store if found, otherwise None. Not finding a store is
            not an error - callers decide what that means.
        """
        with connection_scope(self._db_path) as connection:
            row = connection.execute(
                "SELECT * FROM stores WHERE store_id = ?",
                (store_id,),
            ).fetchone()

        return Store.from_row(row) if row is not None else None

    def find_nearby(
        self,
        latitude: float,
        longitude: float,
        radius_miles: Optional[float] = None,
        exclude_store_id: Optional[str] = None,
        active_only: bool = True,
    ) -> List[StoreDistance]:
        """Find nearby-store candidates within a radius, nearest first.

        Args:
            latitude: Latitude of the reference point (e.g. the
                customer's selected store, or a ZIP code centroid).
            longitude: Longitude of the reference point.
            radius_miles: Maximum distance to include. When omitted,
                falls back to the centrally configured
                NEARBY_STORE_RADIUS_MILES setting.
            exclude_store_id: A store to leave out of the results -
                typically the store the customer already checked.
            active_only: If True (default), only active stores are
                considered candidates.

        Returns:
            StoreDistance entries (store + distance_miles), sorted by
            distance ascending. Empty list if no store falls within
            the radius.
        """
        resolved_radius = (
            radius_miles if radius_miles is not None else get_settings().nearby_store_radius_miles
        )

        candidates = [
            store
            for store in self.list_stores(active_only=active_only)
            if store.store_id != exclude_store_id
        ]

        results: List[StoreDistance] = []
        for store in candidates:
            distance = _haversine_miles(latitude, longitude, store.latitude, store.longitude)
            if distance <= resolved_radius:
                results.append(StoreDistance(store=store, distance_miles=round(distance, 2)))

        return sorted(results, key=lambda entry: entry.distance_miles)
