"""The Inventory and Fulfillment Agent's pipeline steps.

CLAUDE.md section 4 gives one agent four responsibilities: check the
selected store, check nearby stores when required, find substitutes
when required, and return evidence for every claim. Step 10's graph
diagram shows each of those as its own node (so every real step stays
visible - see scout/orchestration/routing.py's module docstring on why
Scout never hides steps inside one giant function), so this module
holds four node functions instead of one:

    inventory_agent_node        - check the selected store (always).
    availability_evaluation_node - summarize what was found, decide if
                                    fallback is needed.
    nearby_store_search_node    - check nearby stores (only if needed).
    substitute_search_node      - find substitutes (only if still needed).

`products_needing_fulfillment()` is the one shared question every one
of these (and the graph's conditional edges, scout/orchestration/graph.py)
needs answered: which candidates still have no confirmed sellable
stock from any channel checked so far. It is answered by scanning
`state.inventory_results` - never by re-deciding availability with new
logic in each node.

Tool-failure handling: every MCP tool call here is wrapped so a
structured `.error` (validation/not_found) or a real `sqlite3.Error`
(a genuine database failure) becomes a `WorkflowError` and the node
moves on to the next candidate - never an unhandled exception that
would crash the whole workflow over one bad candidate.
"""

import sqlite3
from typing import Any, Dict, List

from scout.mcp.inventory_tools import (
    check_network_inventory,
    check_store_inventory,
    find_available_substitutes,
    find_nearby_inventory,
    get_delivery_estimate,
)
from scout.orchestration.limits import check_step_budget
from scout.orchestration.state import EvidenceEntry, RetailGraphState, ToolCallTrace, WorkflowError


def products_needing_fulfillment(state: RetailGraphState) -> List[str]:
    """product_ids among state.product_candidates with no confirmed stock yet.

    "Confirmed stock" means at least one entry in state.inventory_results
    for that product_id with sellable_quantity > 0, from any channel
    (selected_store, nearby_store, or substitute) checked so far this
    workflow.
    """
    fulfilled_ids = {
        entry["product_id"] for entry in state.inventory_results if entry.get("sellable_quantity", 0) > 0
    }
    return [candidate.product_id for candidate in state.product_candidates if candidate.product_id not in fulfilled_ids]


def inventory_agent_node(state: RetailGraphState) -> Dict[str, Any]:
    """Check every candidate's stock at the customer's selected store."""
    limit_update = check_step_budget(state)
    if limit_update is not None:
        return limit_update

    update: Dict[str, Any] = {"step_count": state.step_count + 1}

    if not state.product_candidates:
        update["tool_results"] = [
            ToolCallTrace(tool_name="check_store_inventory", status="success", summary="no candidates to check")
        ]
        return update

    store_id = (state.intent or {}).get("selected_store_id")
    if not store_id:
        update["tool_results"] = [
            ToolCallTrace(
                tool_name="check_store_inventory",
                status="success",
                summary="selected-store pickup check was not requested; continuing to network availability",
            )
        ]
        return update

    inventory_results = list(state.inventory_results)
    evidence: List[EvidenceEntry] = []
    errors: List[WorkflowError] = []
    tool_results: List[ToolCallTrace] = []

    for candidate in state.product_candidates:
        try:
            result = check_store_inventory(candidate.product_id, store_id)
        except sqlite3.Error:
            errors.append(
                WorkflowError(
                    error_type="database_error",
                    message="A database error occurred while checking store inventory.",
                    agent="inventory",
                    step="check_store_inventory",
                )
            )
            tool_results.append(
                ToolCallTrace(
                    tool_name="check_store_inventory",
                    status="error",
                    summary=f"database error checking {candidate.product_id}",
                )
            )
            continue

        if result.error is not None:
            errors.append(
                WorkflowError(
                    error_type=result.error.error_type,
                    message=result.error.message,
                    agent="inventory",
                    step="check_store_inventory",
                )
            )
            tool_results.append(
                ToolCallTrace(tool_name="check_store_inventory", status="error", summary=result.error.message)
            )
            continue

        inventory_results.append(
            {
                "product_id": candidate.product_id,
                "channel": "selected_store",
                "store_id": store_id,
                "store_name": result.store_name,
                "sellable_quantity": result.sellable_quantity,
                "status": result.status,
            }
        )

        if result.sellable_quantity > 0:
            claim = (
                f"{candidate.name} ({candidate.product_id}) has {result.sellable_quantity} unit(s) "
                f"available for pickup today at {result.store_name}"
            )
        else:
            claim = (
                f"{candidate.name} ({candidate.product_id}) is not available for pickup today at "
                f"{result.store_name} (status: {result.status})"
            )
        evidence.append(EvidenceEntry(source="check_store_inventory", claim=claim, data=result.model_dump()))
        tool_results.append(
            ToolCallTrace(
                tool_name="check_store_inventory", status="success", summary=f"{candidate.product_id}: {result.status}"
            )
        )

    update["inventory_results"] = inventory_results
    if evidence:
        update["evidence"] = evidence
    if errors:
        update["errors"] = errors
    update["tool_results"] = tool_results
    return update


def availability_evaluation_node(state: RetailGraphState) -> Dict[str, Any]:
    """Summarize selected-store results and surface how many candidates still need fallback.

    Calls no tool itself - this is the deterministic "what does this
    mean" reasoning step over inventory_agent_node's already-collected
    results, kept as its own graph node so it stays visible rather than
    being folded silently into inventory_agent_node.
    """
    limit_update = check_step_budget(state)
    if limit_update is not None:
        return limit_update

    total = len(state.product_candidates)
    if total == 0:
        summary = "no candidates to evaluate"
    elif not (state.intent or {}).get("selected_store_id"):
        summary = "selected-store pickup check was not needed for this request"
    else:
        still_needed = len(products_needing_fulfillment(state))
        fulfilled = total - still_needed
        summary = f"{fulfilled} of {total} candidate(s) confirmed available for pickup today at the selected store"

    return {
        "step_count": state.step_count + 1,
        "tool_results": [ToolCallTrace(tool_name="availability_evaluation", status="success", summary=summary)],
    }


def nearby_store_search_node(state: RetailGraphState) -> Dict[str, Any]:
    """Check nearby stores for every candidate still lacking confirmed stock."""
    limit_update = check_step_budget(state)
    if limit_update is not None:
        return limit_update

    update: Dict[str, Any] = {"step_count": state.step_count + 1}

    intent = state.intent or {}
    store_id = intent.get("selected_store_id")
    latitude = intent.get("selected_store_latitude")
    longitude = intent.get("selected_store_longitude")
    needing = products_needing_fulfillment(state)

    if not needing or latitude is None or longitude is None:
        update["tool_results"] = [
            ToolCallTrace(tool_name="find_nearby_inventory", status="success", summary="no nearby search needed")
        ]
        return update

    candidates_by_id = {candidate.product_id: candidate for candidate in state.product_candidates}
    inventory_results = list(state.inventory_results)
    evidence: List[EvidenceEntry] = []
    errors: List[WorkflowError] = []
    tool_results: List[ToolCallTrace] = []

    for product_id in needing:
        try:
            result = find_nearby_inventory(
                product_id=product_id, latitude=latitude, longitude=longitude, exclude_store_id=store_id
            )
        except sqlite3.Error:
            errors.append(
                WorkflowError(
                    error_type="database_error",
                    message="A database error occurred while checking nearby stores.",
                    agent="inventory",
                    step="find_nearby_inventory",
                )
            )
            tool_results.append(
                ToolCallTrace(
                    tool_name="find_nearby_inventory", status="error", summary=f"database error for {product_id}"
                )
            )
            continue

        if result.error is not None:
            errors.append(
                WorkflowError(
                    error_type=result.error.error_type,
                    message=result.error.message,
                    agent="inventory",
                    step="find_nearby_inventory",
                )
            )
            tool_results.append(
                ToolCallTrace(tool_name="find_nearby_inventory", status="error", summary=result.error.message)
            )
            continue

        if not result.results:
            tool_results.append(
                ToolCallTrace(
                    tool_name="find_nearby_inventory",
                    status="success",
                    summary=f"no nearby store can fulfill {product_id}",
                )
            )
            continue

        # Nearest fulfillable store is first (FindNearbyInventoryResult is
        # sorted nearest-first - see scout/mcp/inventory_tools.py) - one
        # piece of evidence is enough to ground "you can pick this up
        # nearby," not every store checked.
        best = result.results[0]
        product = candidates_by_id.get(product_id)
        product_name = product.name if product else product_id

        inventory_results.append(
            {
                "product_id": product_id,
                "channel": "nearby_store",
                "store_id": best.store_id,
                "store_name": best.store_name,
                "sellable_quantity": best.sellable_quantity,
                "status": best.status,
                "distance_miles": best.distance_miles,
            }
        )
        evidence.append(
            EvidenceEntry(
                source="find_nearby_inventory",
                claim=(
                    f"{product_name} ({product_id}) has {best.sellable_quantity} unit(s) available for "
                    f"pickup today at {best.store_name}, {best.distance_miles} miles away"
                ),
                data=best.model_dump(),
            )
        )
        tool_results.append(
            ToolCallTrace(
                tool_name="find_nearby_inventory", status="success", summary=f"{product_id}: found at {best.store_name}"
            )
        )

    update["inventory_results"] = inventory_results
    if evidence:
        update["evidence"] = evidence
    if errors:
        update["errors"] = errors
    update["tool_results"] = tool_results or [
        ToolCallTrace(tool_name="find_nearby_inventory", status="success", summary="checked nearby stores")
    ]
    return update


def substitute_search_node(state: RetailGraphState) -> Dict[str, Any]:
    """Find in-budget substitutes, at the selected store, for anything still unfulfilled."""
    limit_update = check_step_budget(state)
    if limit_update is not None:
        return limit_update

    update: Dict[str, Any] = {"step_count": state.step_count + 1}

    intent = state.intent or {}
    store_id = intent.get("selected_store_id")
    max_price = intent.get("max_price")
    needing = products_needing_fulfillment(state)

    if not needing or not store_id:
        update["tool_results"] = [
            ToolCallTrace(
                tool_name="find_available_substitutes", status="success", summary="no substitute search needed"
            )
        ]
        return update

    inventory_results = list(state.inventory_results)
    new_candidates = list(state.product_candidates)
    existing_ids = {candidate.product_id for candidate in new_candidates}
    evidence: List[EvidenceEntry] = []
    errors: List[WorkflowError] = []
    tool_results: List[ToolCallTrace] = []

    for product_id in needing:
        try:
            result = find_available_substitutes(product_id=product_id, store_id=store_id)
        except sqlite3.Error:
            errors.append(
                WorkflowError(
                    error_type="database_error",
                    message="A database error occurred while searching for substitutes.",
                    agent="inventory",
                    step="find_available_substitutes",
                )
            )
            tool_results.append(
                ToolCallTrace(
                    tool_name="find_available_substitutes",
                    status="error",
                    summary=f"database error for {product_id}",
                )
            )
            continue

        if result.error is not None:
            errors.append(
                WorkflowError(
                    error_type=result.error.error_type,
                    message=result.error.message,
                    agent="inventory",
                    step="find_available_substitutes",
                )
            )
            tool_results.append(
                ToolCallTrace(tool_name="find_available_substitutes", status="error", summary=result.error.message)
            )
            continue

        # find_available_substitutes' own price band is relative to the
        # out-of-stock reference product, not the customer's original
        # budget - re-enforcing max_price here is the same defensive,
        # never-trust-a-single-enforcement-point pattern
        # scout/mcp/product_tools.py's search_products already uses.
        usable = [
            substitute
            for substitute in result.substitutes
            if max_price is None or substitute.product.price <= max_price
        ]

        if not usable:
            tool_results.append(
                ToolCallTrace(
                    tool_name="find_available_substitutes",
                    status="success",
                    summary=f"no in-budget substitute found for {product_id}",
                )
            )
            continue

        best = usable[0]
        if best.product.product_id not in existing_ids:
            new_candidates.append(best.product)
            existing_ids.add(best.product.product_id)

        inventory_results.append(
            {
                "product_id": best.product.product_id,
                "channel": "substitute",
                "store_id": store_id,
                "store_name": intent.get("selected_store_name"),
                "sellable_quantity": best.sellable_quantity,
                "substitute_for": product_id,
            }
        )
        evidence.append(
            EvidenceEntry(
                source="find_available_substitutes",
                claim=(
                    f"{best.product.name} ({best.product.product_id}) is offered as a substitute for "
                    f"{product_id}, with {best.sellable_quantity} unit(s) available for pickup today"
                ),
                data=best.model_dump(),
            )
        )
        tool_results.append(
            ToolCallTrace(
                tool_name="find_available_substitutes",
                status="success",
                summary=f"found substitute {best.product.product_id} for {product_id}",
            )
        )

    update["inventory_results"] = inventory_results
    update["product_candidates"] = new_candidates
    if evidence:
        update["evidence"] = evidence
    if errors:
        update["errors"] = errors
    update["tool_results"] = tool_results or [
        ToolCallTrace(tool_name="find_available_substitutes", status="success", summary="checked for substitutes")
    ]
    return update


def network_delivery_search_node(state: RetailGraphState) -> Dict[str, Any]:
    """Check store-network stock and configured delivery for unfulfilled products.

    This runs only after selected-store and nearby-store checks were weak. The
    resulting channel is labelled ``delivery`` rather than ``online`` because
    Scout's current schema models a store-network aggregate, not a separate
    warehouse or ecommerce inventory source.
    """
    limit_update = check_step_budget(state)
    if limit_update is not None:
        return limit_update

    update: Dict[str, Any] = {"step_count": state.step_count + 1}
    needing = products_needing_fulfillment(state)
    if not needing:
        update["tool_results"] = [
            ToolCallTrace(
                tool_name="check_network_inventory",
                status="success",
                summary="no delivery search needed",
            )
        ]
        return update

    candidates_by_id = {candidate.product_id: candidate for candidate in state.product_candidates}
    inventory_results = list(state.inventory_results)
    evidence: List[EvidenceEntry] = []
    errors: List[WorkflowError] = []
    traces: List[ToolCallTrace] = []

    for product_id in needing:
        try:
            network = check_network_inventory(product_id)
        except sqlite3.Error:
            errors.append(
                WorkflowError(
                    error_type="database_error",
                    message="A database error occurred while checking delivery inventory.",
                    agent="inventory",
                    step="check_network_inventory",
                )
            )
            traces.append(
                ToolCallTrace(
                    tool_name="check_network_inventory",
                    status="error",
                    summary=f"database error for {product_id}",
                )
            )
            continue

        if network.error is not None:
            errors.append(
                WorkflowError(
                    error_type=network.error.error_type,
                    message=network.error.message,
                    agent="inventory",
                    step="check_network_inventory",
                )
            )
            traces.append(
                ToolCallTrace(
                    tool_name="check_network_inventory",
                    status="error",
                    summary=network.error.message,
                )
            )
            continue

        traces.append(
            ToolCallTrace(
                tool_name="check_network_inventory",
                status="success",
                summary=(
                    f"{product_id}: {network.sellable_quantity} unit(s) across the store network"
                ),
            )
        )
        if not network.available:
            continue

        try:
            delivery = get_delivery_estimate(product_id)
        except sqlite3.Error:
            errors.append(
                WorkflowError(
                    error_type="database_error",
                    message="A database error occurred while estimating delivery.",
                    agent="inventory",
                    step="get_delivery_estimate",
                )
            )
            traces.append(
                ToolCallTrace(
                    tool_name="get_delivery_estimate",
                    status="error",
                    summary=f"database error for {product_id}",
                )
            )
            continue

        if delivery.error is not None:
            errors.append(
                WorkflowError(
                    error_type=delivery.error.error_type,
                    message=delivery.error.message,
                    agent="inventory",
                    step="get_delivery_estimate",
                )
            )
            traces.append(
                ToolCallTrace(
                    tool_name="get_delivery_estimate",
                    status="error",
                    summary=delivery.error.message,
                )
            )
            continue
        if not delivery.delivery_available or delivery.policy_evidence is None:
            traces.append(
                ToolCallTrace(
                    tool_name="get_delivery_estimate",
                    status="success",
                    summary=f"delivery unavailable for {product_id}",
                )
            )
            continue

        product = candidates_by_id.get(product_id)
        product_name = product.name if product is not None else product_id
        policy = delivery.policy_evidence
        result_entry = {
            "product_id": product_id,
            "channel": "delivery",
            "store_id": None,
            "store_name": None,
            "sellable_quantity": delivery.sellable_quantity,
            "contributing_store_ids": delivery.contributing_store_ids,
            "delivery_min_days": policy.minimum_days,
            "delivery_max_days": policy.maximum_days,
            "availability_source": policy.inventory_source,
        }
        inventory_results.append(result_entry)
        evidence.append(
            EvidenceEntry(
                source="get_delivery_estimate",
                claim=(
                    f"{product_name} ({product_id}) has {delivery.sellable_quantity} unit(s) "
                    f"available across the Scout store network; standard prototype delivery is "
                    f"estimated at {policy.minimum_days}-{policy.maximum_days} days"
                ),
                data=delivery.model_dump(),
            )
        )
        traces.append(
            ToolCallTrace(
                tool_name="get_delivery_estimate",
                status="success",
                summary=(
                    f"{product_id}: configured delivery window "
                    f"{policy.minimum_days}-{policy.maximum_days} days"
                ),
            )
        )

    update["inventory_results"] = inventory_results
    if evidence:
        update["evidence"] = evidence
    if errors:
        update["errors"] = errors
    update["tool_results"] = traces or [
        ToolCallTrace(
            tool_name="check_network_inventory",
            status="success",
            summary="checked network delivery inventory",
        )
    ]
    return update
