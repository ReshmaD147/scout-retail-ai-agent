"""Deterministic nearby-store radius policy.

StoreRepository.find_nearby() already does the mechanical work of
fetching stores and computing raw distances (Haversine, in Python,
since there are only five demo stores). This module owns a different
concern: deciding what radius is actually *allowed*. A caller - today
a test, later an Inventory Agent - might ask for "stores within 5,000
miles"; Python enforces a hard ceiling on that request regardless of
what was asked for, the same way every time. This is a bounded-
autonomy guardrail: an agent can request a search, but it cannot
expand the search radius beyond what configuration allows.
"""

from typing import List, Optional

from scout.config import get_settings
from scout.repositories.models import StoreDistance


def resolve_search_radius(requested_radius_miles: Optional[float] = None) -> float:
    """Resolve the radius to actually search, enforcing the configured ceiling.

    Args:
        requested_radius_miles: The radius a caller wants to search.
            None falls back to the configured default
            (NEARBY_STORE_RADIUS_MILES).

    Returns:
        The radius to use: the requested value, or the configured
        default if none was given, capped so it never exceeds
        MAX_SEARCH_RADIUS_MILES - no matter how large a value was
        requested.

    Raises:
        ValueError: If the resolved radius is zero or negative. That is
            an invalid input to correct explicitly, not something to
            silently clamp upward.
    """
    settings = get_settings()
    radius = requested_radius_miles if requested_radius_miles is not None else settings.nearby_store_radius_miles

    if radius <= 0:
        raise ValueError("radius_miles must be greater than 0")

    return min(radius, settings.max_search_radius_miles)


def filter_within_radius(
    candidates: List[StoreDistance], radius_miles: float
) -> List[StoreDistance]:
    """Defensively re-check a list of StoreDistance against a radius.

    Args:
        candidates: Already-computed store distances (e.g. from
            StoreRepository.find_nearby()).
        radius_miles: The maximum distance to keep.

    Returns:
        Only the candidates with distance_miles <= radius_miles.
        Repositories should already filter by radius before returning,
        but a service never assumes an upstream layer enforced a
        business rule correctly - re-validating it here means the
        limit holds regardless of what called this function.
    """
    return [candidate for candidate in candidates if candidate.distance_miles <= radius_miles]
