"""Scout's approved MCP store-lookup tool.

Added in Step 10: understand_request (scout/agents/understand_request.py)
needs to resolve a customer's free-text location (e.g. "Maple Grove")
to one of Scout's real stores. Nothing in scout/mcp/product_tools.py or
scout/mcp/inventory_tools.py does this - they all take an already-known
store_id or a latitude/longitude. Rather than have an agent import
StoreRepository directly (breaking the same rule product_tools.py's
module docstring explains: agents get tools, not database access), this
is one small, narrowly-scoped tool for exactly that lookup.
"""

from typing import Optional

from scout.mcp.schemas import FindStoreByLocationResult, ToolError
from scout.mcp.server import mcp_server
from scout.repositories.models import Store
from scout.repositories.store_repository import StoreRepository


def _matches(store: Store, normalized_location: str) -> bool:
    return normalized_location in store.city.lower() or normalized_location in store.store_name.lower()


@mcp_server.tool()
def find_store_by_location(location_text: str) -> FindStoreByLocationResult:
    """Resolve a free-text location to one of Scout's real stores.

    Input schema:
        location_text: Required, non-empty (e.g. "Maple Grove").

    Output schema: FindStoreByLocationResult(location_text, store_id,
    store_name, city, latitude, longitude, error).

    Validation: empty location_text -> "validation_error".

    Error responses: no active store's city or store_name matches ->
    "not_found". This never guesses or returns the "closest sounding"
    store when nothing actually matches - a location that does not
    resolve is reported as not found, not silently defaulted to some
    store.

    Matching: case-insensitive exact match on `city` first (e.g.
    "Maple Grove" == "Maple Grove"); if nothing matches exactly, falls
    back to a substring match against `city` or `store_name`. With
    Scout's five fictional demo stores this is unambiguous; a real
    deployment with many stores would need a more careful ranking, but
    that data does not exist in this schema yet.

    Repository called: StoreRepository.list_stores(active_only=True).
    """
    if not location_text or not location_text.strip():
        return FindStoreByLocationResult(
            location_text=location_text,
            error=ToolError(error_type="validation_error", message="location_text must not be empty"),
        )

    normalized = location_text.strip().lower()
    stores = StoreRepository().list_stores(active_only=True)

    match: Optional[Store] = next((store for store in stores if store.city.lower() == normalized), None)
    if match is None:
        match = next((store for store in stores if _matches(store, normalized)), None)

    if match is None:
        return FindStoreByLocationResult(
            location_text=location_text,
            error=ToolError(
                error_type="not_found", message=f"No store found matching location {location_text!r}"
            ),
        )

    return FindStoreByLocationResult(
        location_text=location_text,
        store_id=match.store_id,
        store_name=match.store_name,
        city=match.city,
        latitude=match.latitude,
        longitude=match.longitude,
        error=None,
    )
