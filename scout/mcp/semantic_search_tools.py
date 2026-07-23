"""Scout's approved MCP semantic-search tool (Step 15.5).

Mirrors every other MCP tool's rationale (see scout/mcp/product_tools.py's
module docstring): validated input, validated structured output, one
underlying deterministic service - here,
scout.services.product_search_service.search_products_by_meaning() -
never raw SQL or a raw embedding vector reaching the caller. This is the
Recommendation Agent's (scout/agents/recommendation_agent.py) main
retrieval tool; scout.mcp.product_tools.search_products, rank_products,
and the rest are unchanged and still used exactly as they were - this
is an addition, not a replacement.
"""

from typing import List, Optional

from scout.mcp.errors import ToolValidationError
from scout.mcp.schemas import SemanticSearchProductsResult, ToolError
from scout.mcp.server import mcp_server
from scout.mcp.summaries import product_to_summary
from scout.services.embedding_service import EmbeddingUnavailableError
from scout.services.product_search_service import search_products_by_meaning

_MAX_LIMIT = 20


@mcp_server.tool()
def semantic_search_products(
    query_text: str,
    keyword: Optional[str] = None,
    category: Optional[str] = None,
    subcategory: Optional[str] = None,
    max_price: Optional[float] = None,
    attributes: Optional[List[str]] = None,
    deals_only: bool = False,
    limit: int = 20,
) -> SemanticSearchProductsResult:
    """Search the catalog for products matching a natural-language query.

    Input schema:
        query_text: The customer's raw request (e.g. "comfortable shoes
            for standing all day"). Required, non-empty.
        keyword: A narrow literal descriptor already extracted upstream
            (scout.agents.understand_request), if any - when given, the
            existing literal keyword search runs unchanged instead of
            semantic retrieval (see scout.services.product_search_service
            module docstring for the full retrieval order).
        category: Exact category to require, if known.
        max_price: Maximum price, inclusive, if the customer stated a
            budget.
        limit: Maximum products to return (1-20, default 20) - this is
            candidate retrieval, not the final 1-3 shown to the
            customer (scout.agents.recommendation_agent.rerank_node
            applies that cap after inventory validation).

    Output schema: SemanticSearchProductsResult(products, count,
    retrieval_method, candidates_considered, error).

    Validation: query_text must be a non-empty string; limit must be
    between 1 and 20; max_price, if given, must not be negative.
    Violation returns error.error_type == "validation_error".

    Error responses: error.error_type == "tool_execution_error" if the
    configured embedding provider is unavailable (e.g. a real Ollama
    deployment whose server is unreachable) - never an unhandled
    exception reaching the caller.

    Service called: scout.services.product_search_service.search_products_by_meaning() -
    see that module for the full exact-match / literal-keyword /
    semantic retrieval strategy, and scout.services.embedding_service
    for how "by meaning" is actually computed.
    """
    try:
        if not query_text or not query_text.strip():
            raise ToolValidationError("query_text must not be empty")
        if not (1 <= limit <= _MAX_LIMIT):
            raise ToolValidationError(f"limit must be between 1 and {_MAX_LIMIT}")
        if max_price is not None and max_price < 0:
            raise ToolValidationError("max_price must not be negative")
    except ToolValidationError as exc:
        return SemanticSearchProductsResult(
            products=[],
            count=0,
            retrieval_method="semantic",
            candidates_considered=0,
            error=ToolError(error_type="validation_error", message=str(exc)),
        )

    try:
        outcome = search_products_by_meaning(
            query_text=query_text,
            keyword=keyword,
            category=category,
            subcategory=subcategory,
            max_price=max_price,
            attributes=attributes,
            deals_only=deals_only,
        )
    except EmbeddingUnavailableError as exc:
        return SemanticSearchProductsResult(
            products=[],
            count=0,
            retrieval_method="semantic",
            candidates_considered=0,
            error=ToolError(error_type="tool_execution_error", message=str(exc)),
        )

    products = outcome.products[:limit]
    summaries = [product_to_summary(product) for product in products]

    return SemanticSearchProductsResult(
        products=summaries,
        count=len(summaries),
        retrieval_method=outcome.retrieval_method,
        candidates_considered=outcome.candidates_considered,
        error=None,
    )