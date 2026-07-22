"""Step 16.5 external merchant fallback node.

This node is reachable only after reranking proves that no internal candidate
survived selected-store, nearby-store, network delivery, and substitute checks.
It calls the approved MCP tool and never queries SQLite directly.
"""

from __future__ import annotations

from typing import Any, Dict

from scout.config import get_settings
from scout.mcp.affiliate_tools import search_external_offers
from scout.orchestration.limits import check_step_budget
from scout.orchestration.state import EvidenceEntry, RetailGraphState, ToolCallTrace, WorkflowError


def external_offer_fallback_node(state: RetailGraphState) -> Dict[str, Any]:
    limit_update = check_step_budget(state)
    if limit_update is not None:
        return limit_update

    intent = state.intent or {}
    result = search_external_offers(
        query_text=state.customer_query,
        category=intent.get("category"),
        max_price=intent.get("max_price"),
        limit=get_settings().max_external_offers,
    )

    update: Dict[str, Any] = {"step_count": state.step_count + 1}
    if result.error is not None:
        update["external_offers"] = []
        update["errors"] = [
            WorkflowError(
                error_type=result.error.error_type,
                message=result.error.message,
                agent="external_offers",
                step="search_external_offers",
            )
        ]
        update["tool_results"] = [
            ToolCallTrace(
                tool_name="search_external_offers",
                status="error",
                summary=result.error.message,
            )
        ]
        return update

    update["external_offers"] = result.offers
    update["tool_results"] = [
        ToolCallTrace(
            tool_name="search_external_offers",
            status="success",
            summary=f"found {result.count} mock external alternative(s)",
        )
    ]
    if result.offers:
        update["evidence"] = [
            EvidenceEntry(
                source="search_external_offers",
                claim=(
                    f"{offer.product_name} ({offer.offer_id}) is a {offer.match_type} "
                    f"external offer from {offer.merchant_name} at ${offer.price:.2f}"
                ),
                data=offer.model_dump(),
            )
            for offer in result.offers
        ]
    return update
