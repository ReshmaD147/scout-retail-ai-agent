"""Scout's approved MCP inventory and fulfillment tools.

Goal: find the best valid fulfillment option for a product, using the
fewest checks necessary - never every tool on every request. These six
tools are deliberately kept separate and narrow, each doing exactly one
check:

    1. check_store_inventory    - the selected store (call first, always).
    2. find_nearby_inventory    - nearby stores (call only if #1 is weak).
    3. check_network_inventory  - store-network-wide (call only if #1 and #2 are weak).
    4. get_pickup_estimate      - pickup timing at one specific store.
    5. get_delivery_estimate    - a network-wide delivery window.
    6. find_available_substitutes - catalog-similar products, but only
       the ones that can actually be fulfilled.

No tool here calls another tool automatically to build the whole
"selected store -> nearby -> store network -> substitutes" sequence -
that conditional decision (call nearby only when needed, stop as soon
as a valid option is found) is the future Supervisor's job (LangGraph,
not yet built). Baking that sequencing into one giant tool would strip
away exactly the bounded-autonomy property CLAUDE.md calls for: an
agent choosing the next step from evidence, not a hardcoded pipeline.

For the same reason, no tool here calls another MCP tool internally
either - find_available_substitutes needs the same catalog-similarity
logic find_similar_products (scout/mcp/product_tools.py) uses, but
both get it by calling scout.services.similarity_service directly with
their own repository-fetched candidates, not by one tool invoking the
other. A tool calling a tool would hide a real step from anything
tracing "which tool ran" (see CLAUDE.md's observability rules).

Modeling notes (read before relying on these tools)
-----------------------------------------------------
Scout's schema (scout/database/schema.sql) has no separate online
warehouse table and no shipping-zone data. Two deliberate
simplifications follow from that, both documented again on the
specific tools below:

- Store-network availability is modeled as "does the store network
  have any sellable stock anywhere," summed from the exact same
  per-store inventory rows check_store_inventory reads
  (scout.services.fulfillment_service.aggregate_network_availability).
  This is NOT a genuine online/warehouse inventory record - there is
  no separate, independently-tracked "online stock" number in this
  schema. check_network_inventory's result always carries
  availability_source == "store_network" so a caller can tell the
  difference; a grounded statement built from it should say "available
  across the Scout store network," never "available online."
- A delivery estimate is a fixed, centrally configured window
  (STANDARD_DELIVERY_MIN_DAYS / STANDARD_DELIVERY_MAX_DAYS) offered
  whenever network-wide stock exists, not a number computed from
  distance or a shipping carrier - that data does not exist yet.
  get_delivery_estimate's result carries this window inside a
  DeliveryPolicyEvidence object (evidence_type == "configured_policy"),
  kept structurally separate from real inventory evidence, so a
  grounded statement should say "Standard delivery is estimated at
  3-5 days for this prototype," never "Your order will arrive in
  3-5 days."
"""

from typing import List, Optional

from scout.config import get_settings
from scout.mcp.errors import ToolValidationError
from scout.mcp.schemas import (
    CheckNetworkInventoryResult,
    CheckStoreInventoryResult,
    DeliveryPolicyEvidence,
    FindAvailableSubstitutesResult,
    FindNearbyInventoryResult,
    GetDeliveryEstimateResult,
    GetPickupEstimateResult,
    InventoryEvidence,
    NearbyStoreAvailability,
    SubstituteOption,
    ToolError,
)
from scout.mcp.server import mcp_server
from scout.mcp.summaries import product_to_summary
from scout.repositories.inventory_repository import InventoryRepository
from scout.repositories.models import InventoryRecord
from scout.repositories.product_repository import ProductRepository
from scout.repositories.store_repository import StoreRepository
from scout.services import fulfillment_service, nearby_store_service, ranking_service, similarity_service
from scout.services.inventory_service import evaluate_availability

_MAX_SUBSTITUTE_LIMIT = 50


def _evidence(store_id: str, record: Optional[InventoryRecord]) -> InventoryEvidence:
    if record is None:
        return InventoryEvidence(store_id=store_id, record_found=False)
    return InventoryEvidence(
        store_id=store_id,
        record_found=True,
        quantity_available=record.quantity_available,
        quantity_reserved=record.quantity_reserved,
        restock_date=record.restock_date,
    )


@mcp_server.tool()
def check_store_inventory(product_id: str, store_id: str) -> CheckStoreInventoryResult:
    """Check one product's availability at one specific store.

    This is the first, cheapest check in Scout's fulfillment process -
    call this before find_nearby_inventory or check_network_inventory,
    which should only run if this one comes back weak (see
    scout.services.fulfillment_service.has_weak_fulfillment).

    Input schema:
        product_id: Required, non-empty.
        store_id: Required, non-empty.

    Output schema: CheckStoreInventoryResult(product_id, store_id,
    store_name, status, sellable_quantity, restock_date, evidence,
    error).

    Validation: empty product_id or store_id -> "validation_error".

    Error responses: unknown product_id or unknown store_id ->
    "not_found". A product simply not tracked at a real store is NOT
    an error - it returns status "not_tracked" with sellable_quantity
    0, since both IDs were valid.

    Repository/service called: InventoryRepository.get_for_product_and_store()
    fetches the row (or None); inventory_service.evaluate_availability()
    turns it into a status.
    """
    if not product_id or not product_id.strip():
        return CheckStoreInventoryResult(
            product_id=product_id,
            store_id=store_id,
            error=ToolError(error_type="validation_error", message="product_id must not be empty"),
        )
    if not store_id or not store_id.strip():
        return CheckStoreInventoryResult(
            product_id=product_id,
            store_id=store_id,
            error=ToolError(error_type="validation_error", message="store_id must not be empty"),
        )

    if ProductRepository().get_by_id(product_id) is None:
        return CheckStoreInventoryResult(
            product_id=product_id,
            store_id=store_id,
            error=ToolError(
                error_type="not_found", message=f"No product found with product_id={product_id!r}"
            ),
        )

    store = StoreRepository().get_by_id(store_id)
    if store is None:
        return CheckStoreInventoryResult(
            product_id=product_id,
            store_id=store_id,
            error=ToolError(error_type="not_found", message=f"No store found with store_id={store_id!r}"),
        )

    record = InventoryRepository().get_for_product_and_store(product_id, store_id)
    availability = evaluate_availability(record)

    return CheckStoreInventoryResult(
        product_id=product_id,
        store_id=store_id,
        store_name=store.store_name,
        status=availability.status.value,
        sellable_quantity=availability.sellable_quantity,
        restock_date=availability.restock_date,
        evidence=_evidence(store_id, record),
        error=None,
    )


@mcp_server.tool()
def find_nearby_inventory(
    product_id: str,
    latitude: float,
    longitude: float,
    radius_miles: Optional[float] = None,
    exclude_store_id: Optional[str] = None,
    min_quantity: int = 1,
) -> FindNearbyInventoryResult:
    """Find nearby stores that can actually fulfill a product.

    Call this only after check_store_inventory shows the selected
    store cannot fulfill the request - it is intentionally a separate,
    explicit step, not something check_store_inventory triggers itself.

    Input schema:
        product_id: Required, non-empty.
        latitude: -90 to 90.
        longitude: -180 to 180.
        radius_miles: Optional; defaults to and is capped by the
            centrally configured radius settings (see
            scout.services.nearby_store_service).
        exclude_store_id: Optional store to skip (e.g. the store
            already checked with check_store_inventory).
        min_quantity: Minimum sellable units required to count as a
            usable result (default 1).

    Output schema: FindNearbyInventoryResult(product_id, radius_miles,
    results, count, error). `results` includes only stores meeting
    min_quantity, nearest first.

    Validation: empty product_id; latitude/longitude out of range;
    min_quantity < 1; or an invalid radius (see resolve_search_radius)
    all return "validation_error".

    Error responses: unknown product_id -> "not_found".

    Repository/service called: StoreRepository.find_nearby() (distance
    + radius filtering); InventoryRepository.get_for_product_and_store()
    per candidate store; inventory_service.evaluate_availability() to
    decide fulfillability; nearby_store_service.resolve_search_radius()
    to enforce the configured radius ceiling regardless of what was
    requested.
    """
    try:
        if not product_id or not product_id.strip():
            raise ToolValidationError("product_id must not be empty")
        if not (-90 <= latitude <= 90):
            raise ToolValidationError("latitude must be between -90 and 90")
        if not (-180 <= longitude <= 180):
            raise ToolValidationError("longitude must be between -180 and 180")
        if min_quantity < 1:
            raise ToolValidationError("min_quantity must be at least 1")
        resolved_radius = nearby_store_service.resolve_search_radius(radius_miles)
    except (ToolValidationError, ValueError) as exc:
        return FindNearbyInventoryResult(
            product_id=product_id,
            radius_miles=radius_miles or 0.0,
            results=[],
            count=0,
            error=ToolError(error_type="validation_error", message=str(exc)),
        )

    if ProductRepository().get_by_id(product_id) is None:
        return FindNearbyInventoryResult(
            product_id=product_id,
            radius_miles=resolved_radius,
            results=[],
            count=0,
            error=ToolError(
                error_type="not_found", message=f"No product found with product_id={product_id!r}"
            ),
        )

    nearby_stores = StoreRepository().find_nearby(
        latitude=latitude,
        longitude=longitude,
        radius_miles=resolved_radius,
        exclude_store_id=exclude_store_id,
    )

    inventory_repository = InventoryRepository()
    results: List[NearbyStoreAvailability] = []
    for entry in nearby_stores:
        record = inventory_repository.get_for_product_and_store(product_id, entry.store.store_id)
        availability = evaluate_availability(record)
        if availability.sellable_quantity >= min_quantity:
            results.append(
                NearbyStoreAvailability(
                    store_id=entry.store.store_id,
                    store_name=entry.store.store_name,
                    distance_miles=entry.distance_miles,
                    status=availability.status.value,
                    sellable_quantity=availability.sellable_quantity,
                    restock_date=availability.restock_date,
                    evidence=_evidence(entry.store.store_id, record),
                )
            )

    return FindNearbyInventoryResult(
        product_id=product_id, radius_miles=resolved_radius, results=results, count=len(results), error=None
    )


@mcp_server.tool()
def check_network_inventory(product_id: str, min_quantity: int = 1) -> CheckNetworkInventoryResult:
    """Check store-network-wide availability for a product.

    Scout's current schema has no separate online-warehouse table (see
    module docstring) - this is modeled as whether the store network
    has any sellable stock anywhere, grounded in the same inventory
    rows check_store_inventory reads. It is genuinely a network
    aggregate, not real online/warehouse inventory - the result's
    availability_source field always says "store_network" so that
    stays explicit. Call this only after both the selected store and
    nearby stores have been checked and neither could fulfill the
    request.

    Input schema:
        product_id: Required, non-empty.
        min_quantity: Minimum sellable units required (default 1).

    Output schema: CheckNetworkInventoryResult(product_id,
    availability_source, available, min_quantity, sellable_quantity,
    contributing_store_ids, error).

    Validation: empty product_id or min_quantity < 1 -> "validation_error".

    Error responses: unknown product_id -> "not_found".

    Repository/service called: InventoryRepository.list_for_product()
    fetches every store's row; fulfillment_service.
    aggregate_network_availability() sums the sellable quantities.
    """
    if not product_id or not product_id.strip():
        return CheckNetworkInventoryResult(
            product_id=product_id,
            available=False,
            min_quantity=min_quantity,
            sellable_quantity=0,
            contributing_store_ids=[],
            error=ToolError(error_type="validation_error", message="product_id must not be empty"),
        )
    if min_quantity < 1:
        return CheckNetworkInventoryResult(
            product_id=product_id,
            available=False,
            min_quantity=min_quantity,
            sellable_quantity=0,
            contributing_store_ids=[],
            error=ToolError(error_type="validation_error", message="min_quantity must be at least 1"),
        )

    if ProductRepository().get_by_id(product_id) is None:
        return CheckNetworkInventoryResult(
            product_id=product_id,
            available=False,
            min_quantity=min_quantity,
            sellable_quantity=0,
            contributing_store_ids=[],
            error=ToolError(
                error_type="not_found", message=f"No product found with product_id={product_id!r}"
            ),
        )

    records = InventoryRepository().list_for_product(product_id)
    network = fulfillment_service.aggregate_network_availability(records)

    return CheckNetworkInventoryResult(
        product_id=product_id,
        available=network.total_sellable_quantity >= min_quantity,
        min_quantity=min_quantity,
        sellable_quantity=network.total_sellable_quantity,
        contributing_store_ids=network.contributing_store_ids,
        error=None,
    )


@mcp_server.tool()
def get_pickup_estimate(product_id: str, store_id: str) -> GetPickupEstimateResult:
    """Estimate pickup readiness time for a product at a specific store.

    Input schema:
        product_id: Required, non-empty.
        store_id: Required, non-empty.

    Output schema: GetPickupEstimateResult(product_id, store_id,
    pickup_available, pickup_ready_minutes, reason, evidence, error).

    Validation: empty product_id or store_id -> "validation_error".

    Error responses: unknown product_id or store_id -> "not_found".

    Repository/service called: InventoryRepository.get_for_product_and_store();
    fulfillment_service.evaluate_pickup_estimate() decides availability
    and timing directly from that row's quantities and
    pickup_ready_minutes field - never a guessed time.
    """
    if not product_id or not product_id.strip():
        return GetPickupEstimateResult(
            product_id=product_id,
            store_id=store_id,
            pickup_available=False,
            error=ToolError(error_type="validation_error", message="product_id must not be empty"),
        )
    if not store_id or not store_id.strip():
        return GetPickupEstimateResult(
            product_id=product_id,
            store_id=store_id,
            pickup_available=False,
            error=ToolError(error_type="validation_error", message="store_id must not be empty"),
        )

    if ProductRepository().get_by_id(product_id) is None:
        return GetPickupEstimateResult(
            product_id=product_id,
            store_id=store_id,
            pickup_available=False,
            error=ToolError(
                error_type="not_found", message=f"No product found with product_id={product_id!r}"
            ),
        )

    store = StoreRepository().get_by_id(store_id)
    if store is None:
        return GetPickupEstimateResult(
            product_id=product_id,
            store_id=store_id,
            pickup_available=False,
            error=ToolError(error_type="not_found", message=f"No store found with store_id={store_id!r}"),
        )

    record = InventoryRepository().get_for_product_and_store(product_id, store_id)
    estimate = fulfillment_service.evaluate_pickup_estimate(record)

    return GetPickupEstimateResult(
        product_id=product_id,
        store_id=store_id,
        pickup_available=estimate.available,
        pickup_ready_minutes=estimate.ready_minutes,
        reason=estimate.reason,
        evidence=_evidence(store_id, record),
        error=None,
    )


@mcp_server.tool()
def get_delivery_estimate(product_id: str, min_quantity: int = 1) -> GetDeliveryEstimateResult:
    """Estimate a network-wide delivery window for a product.

    Grounded in the same network-wide availability
    check_network_inventory uses, plus a fixed configured delivery
    window (STANDARD_DELIVERY_MIN_DAYS / STANDARD_DELIVERY_MAX_DAYS)
    applied deterministically - not a number generated per request.
    There is no location parameter: this simplified model has no
    shipping-zone data yet, so every deliverable order gets the same
    configured window (see module docstring).

    The window is returned inside policy_evidence
    (evidence_type == "configured_policy"), not as plain top-level
    fields, specifically so it is never confused with a real,
    per-shipment inventory record.

    Input schema:
        product_id: Required, non-empty.
        min_quantity: Minimum sellable units required (default 1).

    Output schema: GetDeliveryEstimateResult(product_id, min_quantity,
    delivery_available, policy_evidence, reason, sellable_quantity,
    contributing_store_ids, error). policy_evidence is None when
    delivery_available is False - there is no window to offer.

    Validation: empty product_id or min_quantity < 1 -> "validation_error".

    Error responses: unknown product_id -> "not_found".

    Repository/service called: InventoryRepository.list_for_product();
    fulfillment_service.aggregate_network_availability() and
    fulfillment_service.evaluate_delivery_estimate(), using
    STANDARD_DELIVERY_MIN_DAYS/MAX_DAYS from centralized configuration.
    """
    if not product_id or not product_id.strip():
        return GetDeliveryEstimateResult(
            product_id=product_id,
            min_quantity=min_quantity,
            delivery_available=False,
            error=ToolError(error_type="validation_error", message="product_id must not be empty"),
        )
    if min_quantity < 1:
        return GetDeliveryEstimateResult(
            product_id=product_id,
            min_quantity=min_quantity,
            delivery_available=False,
            error=ToolError(error_type="validation_error", message="min_quantity must be at least 1"),
        )

    if ProductRepository().get_by_id(product_id) is None:
        return GetDeliveryEstimateResult(
            product_id=product_id,
            min_quantity=min_quantity,
            delivery_available=False,
            error=ToolError(
                error_type="not_found", message=f"No product found with product_id={product_id!r}"
            ),
        )

    records = InventoryRepository().list_for_product(product_id)
    network = fulfillment_service.aggregate_network_availability(records)

    restock_dates = sorted(record.restock_date for record in records if record.restock_date)
    earliest_restock = restock_dates[0] if restock_dates else None

    settings = get_settings()
    estimate = fulfillment_service.evaluate_delivery_estimate(
        network_availability=network,
        min_quantity=min_quantity,
        standard_min_days=settings.standard_delivery_min_days,
        standard_max_days=settings.standard_delivery_max_days,
        earliest_restock_date=earliest_restock,
    )

    policy_evidence = None
    if estimate.available:
        policy_evidence = DeliveryPolicyEvidence(
            minimum_days=estimate.min_days,
            maximum_days=estimate.max_days,
        )

    return GetDeliveryEstimateResult(
        product_id=product_id,
        min_quantity=min_quantity,
        delivery_available=estimate.available,
        policy_evidence=policy_evidence,
        reason=estimate.reason,
        sellable_quantity=network.total_sellable_quantity,
        contributing_store_ids=network.contributing_store_ids,
        error=None,
    )


@mcp_server.tool()
def find_available_substitutes(
    product_id: str,
    store_id: Optional[str] = None,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    min_quantity: int = 1,
    limit: int = 5,
) -> FindAvailableSubstitutesResult:
    """Find catalog-similar products that can actually be fulfilled.

    Uses the same shared similarity_service.filter_similar_candidates()
    find_similar_products (scout.mcp.product_tools) calls, so this
    tool never re-implements what "similar" means - but it calls that
    service directly with its own repository-fetched candidates,
    rather than calling the find_similar_products tool itself. Tools
    do not call other tools in Scout (see module docstring) so that
    every real step stays visible to anything tracing tool calls.

    Exactly one fulfillment channel is checked per call, chosen from
    what was given: store_id checks that store, latitude/longitude
    (both required together) checks nearby stores, and giving neither
    falls back to store-network-wide availability. This mirrors the
    overall process: only the channel actually needed gets checked.

    Input schema:
        product_id: Required, non-empty (the reference product).
        store_id: Optional - selects the "selected_store" channel.
        latitude, longitude: Optional, must both be given together -
            selects the "nearby_store" channel. Same ranges as
            find_nearby_inventory.
        min_quantity: Minimum sellable units required (default 1).
        limit: Maximum substitutes to return (1-50, default 5).

    Output schema: FindAvailableSubstitutesResult(reference_product_id,
    fulfillment_channel_checked, substitutes, count, error).
    fulfillment_channel_checked is one of "selected_store",
    "nearby_store", "store_network", or "none" (validation failures).

    Validation: empty product_id; min_quantity < 1; limit outside
    1-50; or only one of latitude/longitude given -> "validation_error".

    Error responses: unknown reference product_id -> "not_found";
    unknown store_id (when using the selected_store channel) ->
    "not_found".

    Repository/service called: ProductRepository.get_by_id() and
    .list_active() (catalog candidates); similarity_service.
    filter_similar_candidates() and ranking_service.rank_products() to
    turn those into ranked similar products; StoreRepository.
    find_nearby() for the nearby_store channel; InventoryRepository
    (per candidate) and fulfillment_service.
    aggregate_network_availability() for the store_network channel;
    inventory_service.evaluate_availability() for the selected_store
    and nearby_store channels.
    """
    try:
        if not product_id or not product_id.strip():
            raise ToolValidationError("product_id must not be empty")
        if min_quantity < 1:
            raise ToolValidationError("min_quantity must be at least 1")
        if not (1 <= limit <= _MAX_SUBSTITUTE_LIMIT):
            raise ToolValidationError(f"limit must be between 1 and {_MAX_SUBSTITUTE_LIMIT}")
        if (latitude is None) != (longitude is None):
            raise ToolValidationError("latitude and longitude must both be provided together")
        if latitude is not None and not (-90 <= latitude <= 90):
            raise ToolValidationError("latitude must be between -90 and 90")
        if longitude is not None and not (-180 <= longitude <= 180):
            raise ToolValidationError("longitude must be between -180 and 180")
    except ToolValidationError as exc:
        return FindAvailableSubstitutesResult(
            reference_product_id=product_id,
            fulfillment_channel_checked="none",
            substitutes=[],
            count=0,
            error=ToolError(error_type="validation_error", message=str(exc)),
        )

    if store_id is not None:
        channel = "selected_store"
    elif latitude is not None:
        channel = "nearby_store"
    else:
        channel = "store_network"

    if channel == "selected_store":
        store = StoreRepository().get_by_id(store_id)
        if store is None:
            return FindAvailableSubstitutesResult(
                reference_product_id=product_id,
                fulfillment_channel_checked=channel,
                substitutes=[],
                count=0,
                error=ToolError(
                    error_type="not_found", message=f"No store found with store_id={store_id!r}"
                ),
            )

    product_repository = ProductRepository()
    reference = product_repository.get_by_id(product_id)
    if reference is None:
        return FindAvailableSubstitutesResult(
            reference_product_id=product_id,
            fulfillment_channel_checked=channel,
            substitutes=[],
            count=0,
            error=ToolError(
                error_type="not_found", message=f"No product found with product_id={product_id!r}"
            ),
        )

    catalog_candidates = product_repository.list_active(category=reference.category)
    similar_candidates = similarity_service.filter_similar_candidates(reference, catalog_candidates)
    ranked = ranking_service.rank_products(similar_candidates)[: limit * 4]
    similar_products = [product_to_summary(entry.product) for entry in ranked]

    inventory_repository = InventoryRepository()

    nearby_stores = []
    if channel == "nearby_store":
        resolved_radius = nearby_store_service.resolve_search_radius(None)
        nearby_stores = StoreRepository().find_nearby(latitude=latitude, longitude=longitude, radius_miles=resolved_radius)

    substitutes: List[SubstituteOption] = []
    for candidate in similar_products:
        if len(substitutes) >= limit:
            break

        if channel == "selected_store":
            record = inventory_repository.get_for_product_and_store(candidate.product_id, store_id)
            availability = evaluate_availability(record)
            if availability.sellable_quantity >= min_quantity:
                substitutes.append(
                    SubstituteOption(
                        product=candidate,
                        fulfillment_channel=channel,
                        sellable_quantity=availability.sellable_quantity,
                        distance_miles=None,
                        evidence=_evidence(store_id, record),
                    )
                )

        elif channel == "nearby_store":
            for entry in nearby_stores:
                record = inventory_repository.get_for_product_and_store(
                    candidate.product_id, entry.store.store_id
                )
                availability = evaluate_availability(record)
                if availability.sellable_quantity >= min_quantity:
                    substitutes.append(
                        SubstituteOption(
                            product=candidate,
                            fulfillment_channel=channel,
                            sellable_quantity=availability.sellable_quantity,
                            distance_miles=entry.distance_miles,
                            evidence=_evidence(entry.store.store_id, record),
                        )
                    )
                    break  # nearest fulfillable store for this candidate is enough evidence

        else:  # store_network
            records = inventory_repository.list_for_product(candidate.product_id)
            network = fulfillment_service.aggregate_network_availability(records)
            if network.total_sellable_quantity >= min_quantity:
                best_store_id = network.contributing_store_ids[0]
                matching_record = next(
                    (record for record in records if record.store_id == best_store_id), None
                )
                substitutes.append(
                    SubstituteOption(
                        product=candidate,
                        fulfillment_channel=channel,
                        sellable_quantity=network.total_sellable_quantity,
                        distance_miles=None,
                        evidence=_evidence(best_store_id, matching_record),
                    )
                )

    return FindAvailableSubstitutesResult(
        reference_product_id=product_id,
        fulfillment_channel_checked=channel,
        substitutes=substitutes,
        count=len(substitutes),
        error=None,
    )
