"""The Response Verification Agent (Step 11).

CLAUDE.md section 4 gives this agent one job: never let an unsupported
claim reach the customer. This module checks every bullet that section
lists, in order, before building `final_response`:

    1. Product ID exists                  -> _verify_against_catalog
    2. Product name matches SQLite        -> _verify_against_catalog
    3. Price matches SQLite               -> _verify_against_catalog
    4. Product satisfies the budget       -> _verify_against_catalog
    5. Inventory claim matches tool evidence -> _verify_inventory_and_store_claim
    6. Store claim matches inventory evidence -> _verify_inventory_and_store_claim
    7. Promotion exists and is active     -> _verify_promotion_claims
    8. Final explanation has no unsupported claim -> _final_response_unsupported_claim

Checks 1-4 re-read the catalog fresh via get_product_details - never
trust a candidate's own (possibly stale) fields; this is CLAUDE.md
section 8's "always revalidate candidate records against the
authoritative data source before returning them," applied one more
time at the very last step before the customer sees anything.

Checks 5-6 are different in kind: they do not re-query the database.
They confirm the claim already sitting in `state.inventory_results`
is actually backed by a real, already-collected `EvidenceEntry` from
an inventory tool call - not a number that arrived in that dict some
other way. This catches "detect contradictions" / "reject unsupported
statements" (CLAUDE.md section 4) as an internal-consistency check,
which is the correct place for it: scout/agents/inventory_agent.py
already re-checks the database itself every time it runs, so this
verifier's job is to confirm the claim and the evidence still agree,
not to re-run the same tool call a third time.

Check 7 is real but currently inert: no node in this graph ever
attaches promotion evidence to a candidate (get_promotions is not
called anywhere in the Step 10 pipeline), so in every run through this
graph today there is nothing to verify and this check trivially
passes. It is still implemented and unit-tested directly, so a future
phase that does attach promotion claims inherits a working verifier
rather than a gap discovered later.

Check 8 is a generic safety net over the composed `final_response`
text itself, independent of how it was built - protects against a
future phase where an LLM (not this module's plain string formatting)
generates the customer-facing prose.

When a specific candidate fails any of 1-7, that candidate is dropped
and the specific issue is recorded as a WorkflowError (CLAUDE.md:
"record the specific validation issue... never silently approve
unsupported content") - other, still-valid candidates are still shown.
Only when *every* candidate fails, or check 8 fails on the composed
response, does this become a workflow-level decision: request a fresh
correction pass through the pipeline (safe, since it is a read-only
re-search, no protected action) if `correction_count` has not reached
`max_correction_attempts` (scout/config.py), otherwise return the
fixed SAFE_FAILURE_MESSAGE. Never returns an unverified answer.
"""

import re
from typing import Any, Dict, List, Optional, Tuple

from scout.config import get_settings
from scout.mcp.affiliate_tools import get_external_offer_details
from scout.mcp.product_tools import get_product_details, get_promotions
from scout.mcp.schemas import ExternalOfferSummary, ProductDetail, ProductSummary
from scout.orchestration.limits import SAFE_FAILURE_MESSAGE, check_step_budget
from scout.orchestration.state import EvidenceEntry, RetailGraphState, ToolCallTrace, WorkflowError
from scout.services import budget_service

_NO_RESULTS_MESSAGE = (
    "I couldn't find a product matching your request that's available for pickup today "
    "within your budget and location. You may want to try a different budget, category, or store."
)

_CHANNEL_TO_EVIDENCE_SOURCE = {
    "selected_store": "check_store_inventory",
    "nearby_store": "find_nearby_inventory",
    "delivery": "get_delivery_estimate",
    "substitute": "find_available_substitutes",
}
"""Which tool must have produced the evidence backing each channel -
see scout/agents/inventory_agent.py. A candidate can accumulate
evidence from more than one channel over the workflow (e.g. checked at
the selected store, then again nearby), so matching on source alone
would be ambiguous; the claim being verified names its own channel, so
the matching evidence must come from *that* channel's tool, not merely
mention the same product_id somewhere in a different channel's claim."""

_MONEY_PATTERN = re.compile(r"\$(\d+\.\d{2})")


def _fulfillment_detail(product_id: str, inventory_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    for entry in inventory_results:
        if entry.get("product_id") == product_id and entry.get("sellable_quantity", 0) > 0:
            return entry
    return {}


def _verify_against_catalog(
    candidate: ProductSummary, max_price: Optional[float]
) -> Tuple[Optional[ProductDetail], List[WorkflowError]]:
    """Checks 1-4: product ID exists, name matches, price matches, budget satisfied.

    Always calls get_product_details fresh - the candidate's own name
    and price are never trusted as-is, no matter how they were
    populated earlier in the workflow.
    """
    issues: List[WorkflowError] = []
    result = get_product_details(candidate.product_id)

    if result.error is not None:
        issues.append(
            WorkflowError(
                error_type="not_found",
                message=(
                    f"{candidate.product_id}: product ID could not be reverified against the "
                    f"catalog ({result.error.message})."
                ),
                agent="verification",
                step="verify_product_id",
            )
        )
        return None, issues

    catalog_product = result.product

    if catalog_product.name != candidate.name:
        issues.append(
            WorkflowError(
                error_type="grounding_failure",
                message=(
                    f"{candidate.product_id}: claimed name {candidate.name!r} does not match the "
                    f"catalog name {catalog_product.name!r}."
                ),
                agent="verification",
                step="verify_product_name",
            )
        )

    if abs(catalog_product.price - candidate.price) > 0.005:
        issues.append(
            WorkflowError(
                error_type="grounding_failure",
                message=(
                    f"{candidate.product_id}: claimed price ${candidate.price:.2f} does not match "
                    f"the catalog price ${catalog_product.price:.2f}."
                ),
                agent="verification",
                step="verify_product_price",
            )
        )

    if max_price is not None and not budget_service.is_within_budget(catalog_product.price, max_price):
        issues.append(
            WorkflowError(
                error_type="grounding_failure",
                message=(
                    f"{candidate.product_id}: catalog price ${catalog_product.price:.2f} exceeds "
                    f"the customer's budget of ${max_price:.2f}."
                ),
                agent="verification",
                step="verify_budget",
            )
        )

    return catalog_product, issues


def _extract_sellable_quantity(data: Dict[str, Any]) -> Optional[int]:
    return data.get("sellable_quantity")


def _extract_store_id(data: Dict[str, Any]) -> Optional[str]:
    return data.get("store_id") or (data.get("evidence") or {}).get("store_id")


def _extract_store_name(data: Dict[str, Any]) -> Optional[str]:
    return data.get("store_name")


def _verify_inventory_and_store_claim(
    product_id: str,
    claim: Dict[str, Any],
    evidence: List[EvidenceEntry],
    intent: Dict[str, Any],
) -> List[WorkflowError]:
    """Checks 5-6: the inventory claim and the store it names are both
    actually backed by a real tool-evidence entry, not fabricated.

    The substitute channel's evidence (find_available_substitutes) has
    no store_name field of its own - substitutes are always checked at
    the customer's selected store (scout/agents/inventory_agent.py), so
    the expected store there is `intent["selected_store_id"]` /
    `intent["selected_store_name"]` instead of a field on the evidence.
    """
    issues: List[WorkflowError] = []
    marker = f"({product_id})"
    expected_source = _CHANNEL_TO_EVIDENCE_SOURCE.get(claim.get("channel"))
    matching = next(
        (entry for entry in evidence if entry.source == expected_source and marker in entry.claim),
        None,
    )

    if matching is None:
        issues.append(
            WorkflowError(
                error_type="grounding_failure",
                message=f"{product_id}: the claimed availability has no supporting tool evidence.",
                agent="verification",
                step="verify_inventory_claim",
            )
        )
        return issues

    data = matching.data
    evidence_quantity = _extract_sellable_quantity(data)
    if evidence_quantity != claim.get("sellable_quantity"):
        issues.append(
            WorkflowError(
                error_type="grounding_failure",
                message=(
                    f"{product_id}: claimed quantity ({claim.get('sellable_quantity')}) does not "
                    f"match the recorded tool evidence ({evidence_quantity})."
                ),
                agent="verification",
                step="verify_inventory_claim",
            )
        )

    if claim.get("channel") == "substitute":
        expected_store_id = intent.get("selected_store_id")
        expected_store_name = intent.get("selected_store_name")
    else:
        expected_store_id = _extract_store_id(data)
        expected_store_name = _extract_store_name(data)

    if expected_store_id is not None and claim.get("store_id") != expected_store_id:
        issues.append(
            WorkflowError(
                error_type="grounding_failure",
                message=(
                    f"{product_id}: claimed store_id ({claim.get('store_id')!r}) does not match "
                    f"the inventory evidence ({expected_store_id!r})."
                ),
                agent="verification",
                step="verify_store_claim",
            )
        )
    if expected_store_name is not None and claim.get("store_name") != expected_store_name:
        issues.append(
            WorkflowError(
                error_type="grounding_failure",
                message=(
                    f"{product_id}: claimed store name ({claim.get('store_name')!r}) does not "
                    f"match the inventory evidence ({expected_store_name!r})."
                ),
                agent="verification",
                step="verify_store_claim",
            )
        )

    return issues


def _verify_promotion_claims(product_id: str, evidence: List[EvidenceEntry]) -> List[WorkflowError]:
    """Check 7: any promotion claimed for this product must still exist and be active.

    Inert today (see module docstring) - real and unit-tested for the
    day a node starts attaching promotion evidence to a candidate.
    """
    issues: List[WorkflowError] = []
    promo_claims = [
        entry
        for entry in evidence
        if entry.source == "get_promotions" and entry.data.get("product_id") == product_id
    ]

    for claim_entry in promo_claims:
        promotion_id = claim_entry.data.get("promotion_id")
        fresh = get_promotions(product_id=product_id)
        if fresh.error is not None:
            issues.append(
                WorkflowError(
                    error_type="grounding_failure",
                    message=f"{product_id}: promotion {promotion_id!r} could not be reverified ({fresh.error.message}).",
                    agent="verification",
                    step="verify_promotion",
                )
            )
            continue

        match = next((promo for promo in fresh.promotions if promo.promotion_id == promotion_id), None)
        if match is None or not match.is_currently_valid:
            issues.append(
                WorkflowError(
                    error_type="grounding_failure",
                    message=f"{product_id}: claimed promotion {promotion_id!r} is not currently active.",
                    agent="verification",
                    step="verify_promotion",
                )
            )

    return issues


def _build_final_response(verified: List[Tuple[ProductSummary, Dict[str, Any]]]) -> str:
    lines = []
    for candidate, detail in verified:
        store_name = detail.get("store_name", "a nearby Scout store")
        quantity = detail.get("sellable_quantity")
        channel = detail.get("channel")
        if channel == "substitute":
            reference = detail.get("substitute_for")
            lines.append(
                f"{candidate.name} (${candidate.price:.2f}) is offered as a substitute for {reference}, "
                f"with {quantity} unit(s) available for pickup today at {store_name}."
            )
        elif channel == "delivery":
            minimum_days = detail.get("delivery_min_days")
            maximum_days = detail.get("delivery_max_days")
            lines.append(
                f"{candidate.name} (${candidate.price:.2f}) has {quantity} unit(s) available across "
                f"the Scout store network. Standard prototype delivery is estimated at "
                f"{minimum_days}-{maximum_days} days."
            )
        else:
            lines.append(
                f"{candidate.name} (${candidate.price:.2f}) has {quantity} unit(s) available for pickup "
                f"today at {store_name}."
            )
    return " ".join(lines)


def _final_response_unsupported_claim(
    final_response: str, verified_candidates: List[ProductSummary]
) -> Optional[WorkflowError]:
    """Check 8: every dollar figure and product name in the composed text is verified.

    A generic safety net over the composed text itself - independent
    of how it was built - so a future phase that generates this prose
    with a model instead of plain string formatting inherits the same
    guarantee.
    """
    verified_prices = {f"{candidate.price:.2f}" for candidate in verified_candidates}
    for amount in _MONEY_PATTERN.findall(final_response):
        if amount not in verified_prices:
            return WorkflowError(
                error_type="grounding_failure",
                message=f"final_response mentions ${amount}, which is not a verified candidate's price.",
                agent="verification",
                step="verify_final_response",
            )

    for candidate in verified_candidates:
        if candidate.name not in final_response:
            return WorkflowError(
                error_type="grounding_failure",
                message=f"final_response does not mention verified candidate {candidate.name!r}.",
                agent="verification",
                step="verify_final_response",
            )

    return None



def _verify_external_offer(
    offer: ExternalOfferSummary, evidence: List[EvidenceEntry]
) -> List[WorkflowError]:
    """Re-read a mock merchant offer and verify every displayed core field."""
    issues: List[WorkflowError] = []
    marker = f"({offer.offer_id})"
    matching_evidence = next(
        (
            entry
            for entry in evidence
            if entry.source == "search_external_offers" and marker in entry.claim
        ),
        None,
    )
    if matching_evidence is None:
        return [
            WorkflowError(
                error_type="grounding_failure",
                message=f"{offer.offer_id}: external offer has no search-tool evidence.",
                agent="verification",
                step="verify_external_offer",
            )
        ]

    details = get_external_offer_details(offer.offer_id)
    if details.error is not None or details.offer is None:
        return [
            WorkflowError(
                error_type="not_found",
                message=f"{offer.offer_id}: external offer could not be reverified.",
                agent="verification",
                step="verify_external_offer",
            )
        ]

    current = details.offer
    comparisons = (
        ("merchant", offer.merchant_name, current.merchant_name),
        ("product name", offer.product_name, current.product_name),
        ("brand", offer.brand, current.brand),
        ("category", offer.category, current.category),
        ("currency", offer.currency, current.currency),
        ("availability", offer.availability_status, current.availability_status),
    )
    for label, claimed, actual in comparisons:
        if claimed != actual:
            issues.append(
                WorkflowError(
                    error_type="grounding_failure",
                    message=f"{offer.offer_id}: claimed {label} does not match the merchant feed.",
                    agent="verification",
                    step="verify_external_offer",
                )
            )
    if abs(offer.price - current.price) > 0.005:
        issues.append(
            WorkflowError(
                error_type="grounding_failure",
                message=f"{offer.offer_id}: external price changed before verification.",
                agent="verification",
                step="verify_external_offer",
            )
        )
    if not current.active or current.availability_status != "in_stock":
        issues.append(
            WorkflowError(
                error_type="grounding_failure",
                message=f"{offer.offer_id}: external offer is no longer available.",
                agent="verification",
                step="verify_external_offer",
            )
        )

    evidence_data = matching_evidence.data
    if evidence_data.get("match_type") != offer.match_type:
        issues.append(
            WorkflowError(
                error_type="grounding_failure",
                message=f"{offer.offer_id}: match label does not match search evidence.",
                agent="verification",
                step="verify_external_match_label",
            )
        )
    if offer.match_type == "exact":
        identifier_type = offer.matched_identifier_type
        identifier_exists = {
            "UPC": current.upc,
            "GTIN": current.gtin,
            "model number": current.model_number,
        }.get(identifier_type or "")
        if not identifier_type or not identifier_exists:
            issues.append(
                WorkflowError(
                    error_type="grounding_failure",
                    message=(
                        f"{offer.offer_id}: exact external match lacks a verified UPC, GTIN, "
                        "or model-number basis."
                    ),
                    agent="verification",
                    step="verify_external_match_label",
                )
            )
    return issues


def _build_external_response(offers: List[ExternalOfferSummary]) -> str:
    if all(offer.match_type == "exact" for offer in offers):
        description = "verified exact external match"
    elif any(offer.match_type == "exact" for offer in offers):
        description = "verified external match and similar alternatives"
    else:
        description = "similar external alternatives"
    names = ", ".join(offer.product_name for offer in offers)
    return (
        "Scout could not find a fulfillable internal option after checking the selected store, "
        "nearby stores, store-network delivery, and internal substitutes. "
        f"Here are {description}: {names}. External offers use demo data, open at the retailer, "
        "and cannot be added to the Scout cart."
    )


def _request_correction_or_fail(state: RetailGraphState, issues: List[WorkflowError]) -> Dict[str, Any]:
    """Every candidate (or the composed response) failed verification.

    Sends the workflow back through the pipeline for one more attempt
    - safe, since it is only a read-only re-search with no protected
    action - as long as `correction_count` has not reached
    `max_correction_attempts`. Clears `inventory_results` so a stale
    entry from the failed pass can never be mistaken for fresh
    evidence on the next one. Once the limit is reached, returns the
    fixed safe-failure message instead of looping again.
    """
    settings = get_settings()
    update: Dict[str, Any] = {}
    if issues:
        update["errors"] = issues

    if state.correction_count < settings.max_correction_attempts:
        update["workflow_status"] = "in_progress"
        update["correction_count"] = state.correction_count + 1
        update["inventory_results"] = []
        update["external_offers"] = []
        update["tool_results"] = [
            ToolCallTrace(
                tool_name="response_verification",
                status="error",
                summary=(
                    f"verification failed for every candidate; requesting correction attempt "
                    f"{state.correction_count + 1} of {settings.max_correction_attempts}"
                ),
            )
        ]
        return update

    update["workflow_status"] = "failed"
    update["final_response"] = SAFE_FAILURE_MESSAGE
    update["product_candidates"] = []
    update["tool_results"] = [
        ToolCallTrace(
            tool_name="response_verification",
            status="error",
            summary="verification failed for every candidate and the correction limit was reached",
        )
    ]
    return update


def response_verification_node(state: RetailGraphState) -> Dict[str, Any]:
    """Verify every surviving candidate against the catalog and evidence, then answer."""
    limit_update = check_step_budget(state)
    if limit_update is not None:
        return limit_update

    update: Dict[str, Any] = {"step_count": state.step_count + 1, "workflow_status": "completed"}

    if not state.product_candidates and state.external_offers:
        verified_external: List[ExternalOfferSummary] = []
        external_issues: List[WorkflowError] = []
        for offer in state.external_offers:
            offer_issues = _verify_external_offer(offer, state.evidence)
            if offer_issues:
                external_issues.extend(offer_issues)
            else:
                verified_external.append(offer)

        if verified_external:
            update["external_offers"] = verified_external
            update["final_response"] = _build_external_response(verified_external)
            if external_issues:
                update["errors"] = external_issues
            update["tool_results"] = [
                ToolCallTrace(
                    tool_name="get_external_offer_details",
                    status="success",
                    summary=f"verified {len(verified_external)} external offer(s)",
                ),
                ToolCallTrace(
                    tool_name="response_verification",
                    status="success",
                    summary="verified external fallback response",
                ),
            ]
            return update

        update["external_offers"] = []
        if external_issues:
            update["errors"] = external_issues

    if not state.product_candidates:
        update["final_response"] = _NO_RESULTS_MESSAGE
        update["tool_results"] = [
            ToolCallTrace(
                tool_name="response_verification", status="success", summary="no fulfillable candidates to verify"
            )
        ]
        return update

    intent = state.intent or {}
    max_price = intent.get("max_price")

    verified: List[Tuple[ProductSummary, Dict[str, Any]]] = []
    issues: List[WorkflowError] = []
    tool_traces: List[ToolCallTrace] = []

    for candidate in state.product_candidates:
        claim = _fulfillment_detail(candidate.product_id, state.inventory_results)
        if not claim:
            issues.append(
                WorkflowError(
                    error_type="grounding_failure",
                    message=(
                        f"{candidate.product_id} had no grounding evidence at verification time and "
                        "was dropped rather than shown to the customer."
                    ),
                    agent="verification",
                    step="verify_inventory_claim",
                )
            )
            continue

        catalog_product, catalog_issues = _verify_against_catalog(candidate, max_price)
        if catalog_issues:
            issues.extend(catalog_issues)
            continue

        inventory_issues = _verify_inventory_and_store_claim(candidate.product_id, claim, state.evidence, intent)
        if inventory_issues:
            issues.extend(inventory_issues)
            continue

        promotion_issues = _verify_promotion_claims(candidate.product_id, state.evidence)
        if promotion_issues:
            issues.extend(promotion_issues)
            continue

        tool_traces.append(
            ToolCallTrace(
                tool_name="get_product_details",
                status="success",
                summary=f"{candidate.product_id} verified against the catalog and inventory evidence",
            )
        )
        verified.append((candidate, claim))
        del catalog_product  # only used for its issues above; the claim carries the display data

    if not verified:
        update.update(_request_correction_or_fail(state, issues))
        return update

    final_response = _build_final_response(verified)
    unsupported = _final_response_unsupported_claim(final_response, [candidate for candidate, _ in verified])
    if unsupported is not None:
        issues.append(unsupported)
        update.update(_request_correction_or_fail(state, issues))
        return update

    update["final_response"] = final_response
    update["product_candidates"] = [candidate for candidate, _ in verified]
    update["external_offers"] = []
    if issues:
        update["errors"] = issues
    update["tool_results"] = tool_traces + [
        ToolCallTrace(
            tool_name="response_verification",
            status="success",
            summary=f"verified {len(verified)} of {len(state.product_candidates)} candidate(s)",
        )
    ]
    return update
