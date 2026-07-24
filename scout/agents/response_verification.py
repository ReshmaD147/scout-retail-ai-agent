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
from typing import Any, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field, ValidationError
from scout.config import get_settings
from scout.mcp.affiliate_tools import get_external_offer_details
from scout.mcp.inventory_tools import check_store_inventory, get_delivery_estimate
from scout.mcp.order_tools import lookup_order
from scout.mcp.product_tools import get_product_details, get_promotions
from scout.mcp.schemas import ExternalOfferSummary, ProductDetail, ProductSummary
from scout.orchestration.limits import SAFE_FAILURE_MESSAGE, check_step_budget
from scout.services.policy_retrieval_service import chunk_policy_documents, load_policy_documents
from scout.orchestration.state import EvidenceEntry, RetailGraphState, ToolCallTrace, WorkflowError
from scout.services import budget_service

_NO_RESULTS_MESSAGE = (
    "I couldn't find a product matching your request that's available for pickup today "
    "within your budget and location. You may want to try a different budget, category, or store."
)


def _no_results_message(intent: Dict[str, Any]) -> str:
    if intent.get("deals_only"):
        return (
            "I couldn't find an available product matching your category and filters "
            "with a verified active promotion right now."
        )
    if intent.get("pickup_requested"):
        return _NO_RESULTS_MESSAGE
    return (
        "I couldn't find an available product matching your request and filters. "
        "Try changing the product type, budget, or features."
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


class ProposedClaim(BaseModel):
    """A customer-facing fact candidate that must be verified before rendering."""

    type: Literal[
        "product_identity",
        "product_price",
        "budget_compliance",
        "active_promotion",
        "store_inventory",
        "pickup_availability",
        "delivery_availability",
        "distance",
        "external_offer",
        "order_ownership",
        "order_status",
        "payment_status",
        "tracking_status",
        "eligibility",
        "policy_section",
    ]
    product_id: Optional[str] = None
    product_name: Optional[str] = None
    product_type: Optional[str] = None
    category: Optional[str] = None
    price: Optional[float] = None
    budget_max: Optional[float] = None
    promotion_id: Optional[str] = None
    store_id: Optional[str] = None
    store_name: Optional[str] = None
    quantity: Optional[int] = None
    pickup_available: Optional[bool] = None
    delivery_available: Optional[bool] = None
    delivery_min_days: Optional[int] = None
    delivery_max_days: Optional[int] = None
    distance_miles: Optional[float] = None
    offer_id: Optional[str] = None
    merchant_name: Optional[str] = None
    external_product_id: Optional[str] = None
    order_id: Optional[str] = None
    session_id: Optional[str] = None
    order_status: Optional[str] = None
    payment_status: Optional[str] = None
    tracking_status: Optional[str] = None
    eligibility_type: Optional[Literal["cancellation", "return", "exchange"]] = None
    eligible: Optional[bool] = None
    policy_id: Optional[str] = None
    policy_file: Optional[str] = None
    policy_category: Optional[str] = None
    policy_version: Optional[str] = None
    section_title: Optional[str] = None
    evidence_ids: List[str] = Field(default_factory=list)


class ClaimVerificationReport(BaseModel):
    verified: bool = False
    approved_claims: List[Dict[str, Any]] = Field(default_factory=list)
    rejected_claims: List[Dict[str, Any]] = Field(default_factory=list)
    missing_evidence: List[Dict[str, Any]] = Field(default_factory=list)


def _claim_issue(claim: ProposedClaim, reason: str) -> WorkflowError:
    return WorkflowError(
        error_type="grounding_failure",
        message=f"{claim.type}: {reason}",
        agent="verification",
        step=f"verify_claim_{claim.type}",
    )


def _approve(report: ClaimVerificationReport, claim: ProposedClaim) -> None:
    report.approved_claims.append(claim.model_dump(exclude_none=True))


def _reject(report: ClaimVerificationReport, claim: ProposedClaim, reason: str) -> WorkflowError:
    payload = claim.model_dump(exclude_none=True)
    payload["reason"] = reason
    report.rejected_claims.append(payload)
    return _claim_issue(claim, reason)


def _missing(report: ClaimVerificationReport, claim: ProposedClaim, reason: str) -> WorkflowError:
    payload = claim.model_dump(exclude_none=True)
    payload["reason"] = reason
    report.missing_evidence.append(payload)
    return _claim_issue(claim, reason)


def _product_detail_for_claim(claim: ProposedClaim, report: ClaimVerificationReport) -> Tuple[Optional[ProductDetail], Optional[WorkflowError]]:
    if not claim.product_id:
        return None, _missing(report, claim, "product_id is required")
    result = get_product_details(claim.product_id)
    if result.error is not None or result.product is None:
        return None, _reject(report, claim, "product could not be verified against the catalog")
    return result.product, None


def _verify_product_claim(claim: ProposedClaim, report: ClaimVerificationReport) -> Optional[WorkflowError]:
    product, issue = _product_detail_for_claim(claim, report)
    if issue is not None:
        return issue
    assert product is not None
    if claim.product_name is not None and claim.product_name != product.name:
        return _reject(report, claim, "product name does not match the catalog")
    if claim.product_type is not None and claim.product_type not in {product.category, product.subcategory}:
        return _reject(report, claim, "product type does not match the catalog")
    if claim.category is not None and claim.category != product.category:
        return _reject(report, claim, "category does not match the catalog")
    if claim.price is not None and abs(claim.price - product.price) > 0.005:
        return _reject(report, claim, "price does not match the catalog")
    if claim.budget_max is not None and not budget_service.is_within_budget(product.price, claim.budget_max):
        return _reject(report, claim, "catalog price exceeds the customer's budget")
    _approve(report, claim)
    return None


def _verify_promotion_claim(claim: ProposedClaim, report: ClaimVerificationReport) -> Optional[WorkflowError]:
    if not claim.product_id or not claim.promotion_id:
        return _missing(report, claim, "product_id and promotion_id are required")
    fresh = get_promotions(product_id=claim.product_id)
    if fresh.error is not None:
        return _reject(report, claim, "promotions could not be reverified")
    match = next((promo for promo in fresh.promotions if promo.promotion_id == claim.promotion_id), None)
    if match is None or not match.is_currently_valid:
        return _reject(report, claim, "promotion is not currently active")
    _approve(report, claim)
    return None


def _verify_store_inventory_claim(claim: ProposedClaim, report: ClaimVerificationReport) -> Optional[WorkflowError]:
    if not claim.product_id or not claim.store_id:
        return _missing(report, claim, "product_id and store_id are required")
    fresh = check_store_inventory(product_id=claim.product_id, store_id=claim.store_id)
    if fresh.error is not None:
        return _reject(report, claim, "store inventory could not be reverified")
    if claim.store_name is not None and fresh.store_name != claim.store_name:
        return _reject(report, claim, "store name does not match inventory service")
    if claim.quantity is not None and fresh.sellable_quantity != claim.quantity:
        return _reject(report, claim, "inventory quantity does not match inventory service")
    if claim.pickup_available is not None and (fresh.sellable_quantity > 0) != claim.pickup_available:
        return _reject(report, claim, "pickup availability does not match inventory service")
    _approve(report, claim)
    return None


def _verify_delivery_claim(claim: ProposedClaim, report: ClaimVerificationReport) -> Optional[WorkflowError]:
    if not claim.product_id:
        return _missing(report, claim, "product_id is required")
    fresh = get_delivery_estimate(product_id=claim.product_id, min_quantity=1)
    if fresh.error is not None:
        return _reject(report, claim, "delivery availability could not be reverified")
    if claim.delivery_available is not None and fresh.delivery_available != claim.delivery_available:
        return _reject(report, claim, "delivery availability does not match fulfillment service")
    if claim.quantity is not None and fresh.sellable_quantity != claim.quantity:
        return _reject(report, claim, "delivery quantity does not match fulfillment service")
    if fresh.policy_evidence is not None:
        if claim.delivery_min_days is not None and fresh.policy_evidence.minimum_days != claim.delivery_min_days:
            return _reject(report, claim, "delivery minimum days do not match policy evidence")
        if claim.delivery_max_days is not None and fresh.policy_evidence.maximum_days != claim.delivery_max_days:
            return _reject(report, claim, "delivery maximum days do not match policy evidence")
    _approve(report, claim)
    return None


def _verify_external_offer_claim(claim: ProposedClaim, report: ClaimVerificationReport) -> Optional[WorkflowError]:
    if not claim.offer_id:
        return _missing(report, claim, "offer_id is required")
    details = get_external_offer_details(claim.offer_id)
    if details.error is not None or details.offer is None:
        return _reject(report, claim, "external offer could not be reverified")
    offer = details.offer
    if not offer.active:
        return _reject(report, claim, "external offer is inactive")
    comparisons = {
        "merchant_name": (claim.merchant_name, offer.merchant_name),
        "external_product_id": (claim.external_product_id, offer.external_product_id),
        "product_name": (claim.product_name, offer.product_name),
        "category": (claim.category, offer.category),
        "price": (claim.price, offer.price),
    }
    for field_name, (claimed, actual) in comparisons.items():
        if claimed is None:
            continue
        if isinstance(actual, float):
            if abs(float(claimed) - actual) > 0.005:
                return _reject(report, claim, f"{field_name} does not match merchant feed")
        elif claimed != actual:
            return _reject(report, claim, f"{field_name} does not match merchant feed")
    _approve(report, claim)
    return None


def _verify_order_claim(claim: ProposedClaim, report: ClaimVerificationReport, state: RetailGraphState) -> Optional[WorkflowError]:
    order_id = claim.order_id or (state.structured_intent or {}).get("order_id") or (state.intent or {}).get("order_id")
    session_id = claim.session_id or state.session_id
    if not order_id or not session_id:
        return _missing(report, claim, "session_id and order_id are required")
    result = lookup_order(order_id=order_id, session_id=session_id)
    if result.error is not None or result.order is None:
        return _reject(report, claim, "order could not be verified for this session")
    order = result.order
    if claim.type == "order_ownership" and order.session_id != session_id:
        return _reject(report, claim, "order does not belong to this session")
    if claim.order_status is not None and order.order_status != claim.order_status:
        return _reject(report, claim, "order status does not match order service")
    if claim.payment_status is not None and order.payment.status != claim.payment_status:
        return _reject(report, claim, "payment status does not match order service")
    if claim.tracking_status is not None and order.fulfillment.tracking.message != claim.tracking_status:
        return _reject(report, claim, "tracking status does not match order service")
    if claim.eligibility_type is not None and claim.eligible is not None:
        eligibility = {
            "cancellation": order.eligibility.cancellation,
            "return": order.eligibility.return_eligibility,
            "exchange": order.eligibility.exchange,
        }[claim.eligibility_type]
        if eligibility.eligible != claim.eligible:
            return _reject(report, claim, "eligibility claim does not match order service")
    _approve(report, claim)
    return None


def verify_proposed_claims(state: RetailGraphState) -> Tuple[ClaimVerificationReport, List[WorkflowError]]:
    """Verify structured proposed claims with fresh read-only tool/service calls."""
    report = ClaimVerificationReport()
    issues: List[WorkflowError] = []
    for raw_claim in state.proposed_claims:
        try:
            claim = ProposedClaim.model_validate(raw_claim)
        except ValidationError as exc:
            issues.append(
                WorkflowError(
                    error_type="grounding_failure",
                    message=f"proposed claim failed schema validation: {exc.errors()[0]['msg']}",
                    agent="verification",
                    step="verify_claim_schema",
                )
            )
            report.rejected_claims.append({"claim": raw_claim, "reason": "schema validation failed"})
            continue

        if claim.type in {"product_identity", "product_price", "budget_compliance"}:
            issue = _verify_product_claim(claim, report)
        elif claim.type == "active_promotion":
            issue = _verify_promotion_claim(claim, report)
        elif claim.type in {"store_inventory", "pickup_availability"}:
            issue = _verify_store_inventory_claim(claim, report)
        elif claim.type == "delivery_availability":
            issue = _verify_delivery_claim(claim, report)
        elif claim.type == "external_offer":
            issue = _verify_external_offer_claim(claim, report)
        elif claim.type in {"order_ownership", "order_status", "payment_status", "tracking_status", "eligibility"}:
            issue = _verify_order_claim(claim, report, state)
        elif claim.type == "policy_section":
            issue = _verify_policy_claim(claim, report, state)
        else:
            issue = _reject(report, claim, "unsupported structured claim type")
        if issue is not None:
            issues.append(issue)

    report.verified = bool(report.approved_claims) and not report.rejected_claims and not report.missing_evidence
    return report, issues


def _verify_policy_claim(claim: ProposedClaim, report: ClaimVerificationReport, state: RetailGraphState) -> Optional[WorkflowError]:
    if not claim.policy_id or not claim.policy_file or not claim.policy_category or not claim.policy_version or not claim.section_title:
        return _reject(report, claim, "policy claim is missing required source metadata")
    if not claim.evidence_ids:
        _missing(report, claim, "policy claim has no evidence id")
        return _claim_issue(claim, "policy claim has no evidence id")

    evidence_by_id = {row.get("evidence_id"): row for row in state.policy_results if isinstance(row, dict)}
    evidence_rows = [evidence_by_id.get(evidence_id) for evidence_id in claim.evidence_ids]
    if any(row is None for row in evidence_rows):
        _missing(report, claim, "policy evidence id was not found in policy_results")
        return _claim_issue(claim, "policy evidence id was not found in policy_results")

    chunks = chunk_policy_documents(load_policy_documents())
    matching = next(
        (
            chunk
            for chunk in chunks
            if chunk.policy_id == claim.policy_id
            and chunk.policy_file == claim.policy_file
            and chunk.category == claim.policy_category
            and chunk.version == claim.policy_version
            and chunk.section_title == claim.section_title
            and chunk.status == "active"
        ),
        None,
    )
    if matching is None:
        return _reject(report, claim, "active policy section could not be reverified")

    for row in evidence_rows:
        assert row is not None
        if row.get("policy_id") != matching.policy_id or row.get("policy_file") != matching.policy_file:
            return _reject(report, claim, "policy evidence does not match the claimed policy source")
        if row.get("policy_version") != matching.version or row.get("section_title") != matching.section_title:
            return _reject(report, claim, "policy evidence does not match the claimed section metadata")
        if row.get("text") != matching.text:
            return _reject(report, claim, "policy evidence text no longer matches the active policy section")

    _approve(report, claim)
    return None


def _structured_claims_from_verified(
    verified: List[Tuple[ProductSummary, Dict[str, Any]]],
    evidence: List[EvidenceEntry],
    max_price: Optional[float],
) -> List[Dict[str, Any]]:
    claims: List[Dict[str, Any]] = []
    for candidate, detail in verified:
        base = {
            "product_id": candidate.product_id,
            "product_name": candidate.name,
            "category": candidate.category,
            "product_type": candidate.subcategory,
            "price": candidate.price,
        }
        claims.append({"type": "product_identity", **base})
        claims.append({"type": "product_price", "product_id": candidate.product_id, "price": candidate.price})
        if max_price is not None:
            claims.append({"type": "budget_compliance", "product_id": candidate.product_id, "budget_max": max_price})
        if detail.get("channel") == "delivery":
            claims.append(
                {
                    "type": "delivery_availability",
                    "product_id": candidate.product_id,
                    "delivery_available": True,
                    "quantity": detail.get("sellable_quantity"),
                    "delivery_min_days": detail.get("delivery_min_days"),
                    "delivery_max_days": detail.get("delivery_max_days"),
                }
            )
        else:
            claims.append(
                {
                    "type": "store_inventory",
                    "product_id": candidate.product_id,
                    "store_id": detail.get("store_id"),
                    "store_name": detail.get("store_name"),
                    "quantity": detail.get("sellable_quantity"),
                    "pickup_available": True,
                }
            )
        for entry in evidence:
            if entry.source == "get_promotions" and entry.data.get("product_id") == candidate.product_id:
                claims.append(
                    {
                        "type": "active_promotion",
                        "product_id": candidate.product_id,
                        "promotion_id": entry.data.get("promotion_id"),
                    }
                )
        fresh_promotions = get_promotions(product_id=candidate.product_id)
        if fresh_promotions.error is None:
            for promotion in fresh_promotions.promotions:
                if promotion.is_currently_valid:
                    claims.append(
                        {
                            "type": "active_promotion",
                            "product_id": candidate.product_id,
                            "promotion_id": promotion.promotion_id,
                        }
                    )
    return claims


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


def _approved_promotion_claim(product_id: str, approved_claims: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    for claim in approved_claims:
        if (
            claim.get("type") == "active_promotion"
            and claim.get("product_id") == product_id
            and claim.get("promotion_id")
        ):
            return claim
    return None


def _promotion_display(candidate: ProductSummary, approved_claims: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    claim = _approved_promotion_claim(candidate.product_id, approved_claims)
    if claim is None:
        return None
    fresh = get_promotions(product_id=candidate.product_id)
    if fresh.error is not None:
        return None
    promotion = next(
        (
            item
            for item in fresh.promotions
            if item.promotion_id == claim.get("promotion_id") and item.is_currently_valid
        ),
        None,
    )
    if promotion is None:
        return None
    if promotion.discount_percent is not None:
        promotional_price = round(candidate.price * (1 - promotion.discount_percent / 100), 2)
        discount_text = f"{promotion.discount_percent:g}% off"
    elif promotion.discount_amount is not None:
        promotional_price = round(max(candidate.price - promotion.discount_amount, 0), 2)
        discount_text = f"${promotion.discount_amount:.2f} off"
    else:
        return None
    savings = round(candidate.price - promotional_price, 2)
    if savings <= 0:
        return None
    return {
        "label": promotion.label,
        "original_price": round(candidate.price, 2),
        "promotional_price": promotional_price,
        "savings": savings,
        "discount_text": discount_text,
        "valid_until": promotion.end_date,
    }


def _price_phrase(candidate: ProductSummary, approved_claims: List[Dict[str, Any]]) -> str:
    promotion = _promotion_display(candidate, approved_claims)
    if promotion is None:
        return f"${candidate.price:.2f}"
    return (
        f"${promotion['promotional_price']:.2f} after verified promotion "
        f"{promotion['label']} ({promotion['discount_text']}; was "
        f"${promotion['original_price']:.2f}; save ${promotion['savings']:.2f}; "
        f"valid through {promotion['valid_until']})"
    )


def _build_final_response(
    verified: List[Tuple[ProductSummary, Dict[str, Any]]],
    evidence: List[EvidenceEntry],
    approved_claims: Optional[List[Dict[str, Any]]] = None,
) -> str:
    del evidence  # final prose uses approved structured facts, not raw promotion payloads.
    resolved_claims = approved_claims or []
    lines = []
    for candidate, detail in verified:
        store_name = detail.get("store_name", "a nearby Scout store")
        quantity = detail.get("sellable_quantity")
        channel = detail.get("channel")
        price_phrase = _price_phrase(candidate, resolved_claims)
        if channel == "substitute":
            reference = detail.get("substitute_for")
            lines.append(
                f"{candidate.name} ({price_phrase}) is offered as a substitute for {reference}, "
                f"with {quantity} unit(s) available for pickup today at {store_name}."
            )
        elif channel == "delivery":
            minimum_days = detail.get("delivery_min_days")
            maximum_days = detail.get("delivery_max_days")
            lines.append(
                f"{candidate.name} ({price_phrase}) has {quantity} unit(s) available across "
                f"the Scout store network. Standard prototype delivery is estimated at "
                f"{minimum_days}-{maximum_days} days."
            )
        else:
            lines.append(
                f"{candidate.name} ({price_phrase}) has {quantity} unit(s) available for pickup "
                f"today at {store_name}."
            )
    return " ".join(lines)


def _final_response_unsupported_claim(
    final_response: str,
    verified_candidates: List[ProductSummary],
    approved_claims: Optional[List[Dict[str, Any]]] = None,
) -> Optional[WorkflowError]:
    """Check 8: every dollar figure and product name in the composed text is verified.

    A generic safety net over the composed text itself - independent
    of how it was built - so a future phase that generates this prose
    with a model instead of plain string formatting inherits the same
    guarantee.
    """
    verified_prices = {f"{candidate.price:.2f}" for candidate in verified_candidates}
    for candidate in verified_candidates:
        promotion = _promotion_display(candidate, approved_claims or [])
        if promotion is None:
            continue
        verified_prices.update(
            {
                f"{promotion['original_price']:.2f}",
                f"{promotion['promotional_price']:.2f}",
                f"{promotion['savings']:.2f}",
            }
        )
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
        next_correction_count = state.correction_count + 1
        update["workflow_status"] = "in_progress"
        update["correction_count"] = next_correction_count
        update["inventory_results"] = []
        update["external_offers"] = []
        update["tool_results"] = [
            ToolCallTrace(
                tool_name="response_verification",
                status="error",
                summary=(
                    f"verification failed for every candidate; requesting correction attempt "
                    f"{next_correction_count} of {settings.max_correction_attempts}"
                ),
            )
        ]
        return update

    update["workflow_status"] = "failed"
    update["correction_count"] = state.correction_count
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

    if state.proposed_claims:
        report, claim_issues = verify_proposed_claims(state)
        update["verification_result"] = report.model_dump(mode="json")
        if claim_issues:
            update.update(_request_correction_or_fail(state, claim_issues))
            update["verification_result"] = report.model_dump(mode="json")
            return update
        update["final_response"] = state.final_response or "I verified the requested facts."
        update["tool_results"] = [
            ToolCallTrace(
                tool_name="response_verification",
                status="success",
                summary=f"verified {len(report.approved_claims)} structured claim(s)",
            )
        ]
        return update

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
            claims = [
                {
                    "type": "external_offer",
                    "offer_id": offer.offer_id,
                    "merchant_name": offer.merchant_name,
                    "external_product_id": offer.external_product_id,
                    "product_name": offer.product_name,
                    "category": offer.category,
                    "price": offer.price,
                }
                for offer in verified_external
            ]
            report, claim_issues = verify_proposed_claims(state.model_copy(update={"proposed_claims": claims}))
            if claim_issues:
                external_issues.extend(claim_issues)
                update.update(_request_correction_or_fail(state, external_issues))
                update["verification_result"] = report.model_dump(mode="json")
                return update
            update["external_offers"] = verified_external
            update["final_response"] = _build_external_response(verified_external)
            update["verification_result"] = report.model_dump(mode="json")
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
        update["final_response"] = _no_results_message(state.intent or {})
        update["verification_result"] = ClaimVerificationReport(verified=True).model_dump(mode="json")
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
        report = ClaimVerificationReport(verified=False, rejected_claims=[issue.model_dump() for issue in issues])
        update["verification_result"] = report.model_dump(mode="json")
        update.update(_request_correction_or_fail(state, issues))
        update["verification_result"] = report.model_dump(mode="json")
        return update

    structured_claims = _structured_claims_from_verified(verified, state.evidence, max_price)
    report, claim_issues = verify_proposed_claims(state.model_copy(update={"proposed_claims": structured_claims}))
    update["verification_result"] = report.model_dump(mode="json")
    if claim_issues:
        issues.extend(claim_issues)
        update.update(_request_correction_or_fail(state, issues))
        update["verification_result"] = report.model_dump(mode="json")
        return update

    final_response = _build_final_response(verified, state.evidence, report.approved_claims)
    unsupported = _final_response_unsupported_claim(
        final_response,
        [candidate for candidate, _ in verified],
        report.approved_claims,
    )
    if unsupported is not None:
        issues.append(unsupported)
        report.rejected_claims.append({"type": "final_response", "reason": unsupported.message})
        report.verified = False
        update["verification_result"] = report.model_dump(mode="json")
        update.update(_request_correction_or_fail(state, issues))
        update["verification_result"] = report.model_dump(mode="json")
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
