"""The Product Recommendation Agent's two pipeline steps.

`recommendation_agent_node` runs first: it turns the extracted intent
(scout/agents/understand_request.py) into an initial, budget-enforced,
ranked candidate set, using the approved MCP semantic-search tool
(scout/mcp/semantic_search_tools.py, Step 15.5) - never SQL, never an
invented product. Step 15.5 replaced the literal-only
scout.mcp.product_tools.search_products call this node used through
Step 15 with scout.mcp.semantic_search_tools.semantic_search_products,
which still runs that exact same literal path whenever
intent["keyword"] is set (see that tool's module docstring for the
full exact/literal/semantic retrieval order) and only falls back to
meaning-based retrieval when it is not - so every scenario this node
already handled continues to resolve identically, and queries with no
literal keyword match (e.g. "comfortable shoes for standing all day")
now retrieve relevant candidates instead of an unfiltered category
dump.

`rerank_node` runs last, after every fulfillment channel has been
checked (scout/agents/inventory_agent.py): it removes any candidate
with no confirmed sellable stock from any channel, then re-ranks
whatever remains, then caps the result at
`settings.max_recommended_products` (Step 15.5's "return up to 3
verified results" - never padded when fewer valid candidates survive).
This is "Rerank valid products" and "Remove invalid or unavailable
options" from CLAUDE.md's primary example workflow, done together in
one place since both need the same computation (which candidates are
still valid).
"""

from typing import Any, Dict

from scout.config import get_settings
from scout.mcp.product_tools import rank_products
from scout.mcp.semantic_search_tools import semantic_search_products
from scout.orchestration.limits import check_step_budget
from scout.orchestration.state import EvidenceEntry, RetailGraphState, ToolCallTrace, WorkflowError


def recommendation_agent_node(state: RetailGraphState) -> Dict[str, Any]:
    """Search the catalog for candidates matching the extracted intent."""
    limit_update = check_step_budget(state)
    if limit_update is not None:
        return limit_update

    intent = state.intent or {}
    result = semantic_search_products(
        query_text=state.customer_query,
        keyword=intent.get("keyword"),
        category=intent.get("category"),
        max_price=intent.get("max_price"),
        limit=20,
    )

    update: Dict[str, Any] = {"step_count": state.step_count + 1}

    if result.error is not None:
        update["errors"] = [
            WorkflowError(
                error_type=result.error.error_type,
                message=result.error.message,
                agent="recommendation",
                step="semantic_search_products",
            )
        ]
        update["product_candidates"] = []
        update["tool_results"] = [
            ToolCallTrace(tool_name="semantic_search_products", status="error", summary=result.error.message)
        ]
        return update

    if not result.products:
        update["product_candidates"] = []
        update["tool_results"] = [
            ToolCallTrace(
                tool_name="semantic_search_products",
                status="success",
                summary=(
                    f"no products matched via {result.retrieval_method} "
                    f"({result.candidates_considered} candidate(s) considered)"
                ),
            )
        ]
        return update

    ranked = rank_products([product.product_id for product in result.products])
    candidates = [entry.product for entry in ranked.ranked_products]

    update["product_candidates"] = candidates
    update["tool_results"] = [
        ToolCallTrace(
            tool_name="semantic_search_products",
            status="success",
            summary=(
                f"found {len(result.products)} candidate(s) within budget via "
                f"{result.retrieval_method} ({result.candidates_considered} candidate(s) considered)"
            ),
        ),
        ToolCallTrace(
            tool_name="rank_products", status="success", summary=f"ranked {len(candidates)} candidate(s)"
        ),
    ]
    update["evidence"] = [
        EvidenceEntry(
            source="semantic_search_products",
            claim=f"{product.name} ({product.product_id}) is priced at ${product.price:.2f}",
            data=product.model_dump(),
        )
        for product in candidates
    ]
    return update


def rerank_node(state: RetailGraphState) -> Dict[str, Any]:
    """Drop candidates with no confirmed stock anywhere, rerank the
    rest, then cap at the configured maximum recommended products."""
    limit_update = check_step_budget(state)
    if limit_update is not None:
        return limit_update

    update: Dict[str, Any] = {"step_count": state.step_count + 1}

    fulfilled_ids = {
        entry["product_id"] for entry in state.inventory_results if entry.get("sellable_quantity", 0) > 0
    }
    survivors = [candidate for candidate in state.product_candidates if candidate.product_id in fulfilled_ids]

    if not survivors:
        update["product_candidates"] = []
        update["tool_results"] = [
            ToolCallTrace(
                tool_name="rank_products",
                status="success",
                summary="no candidate had confirmed fulfillment; nothing to rerank",
            )
        ]
        return update

    max_recommended = get_settings().max_recommended_products
    ranked = rank_products([candidate.product_id for candidate in survivors])
    final_candidates = [entry.product for entry in ranked.ranked_products][:max_recommended]
    update["product_candidates"] = final_candidates
    update["tool_results"] = [
        ToolCallTrace(
            tool_name="rank_products",
            status="success",
            summary=(
                f"reranked {len(survivors)} fulfillable candidate(s), "
                f"returning the top {len(final_candidates)}"
            ),
        )
    ]
    return update