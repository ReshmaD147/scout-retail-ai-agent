"""Inspect the actual FastMCP tool registry used by Scout.

This module is intentionally tiny and import-only: it imports every MCP
tool module so each `@mcp_server.tool()` decorator has executed, then
reads the names from the shared FastMCP server's own tool manager.
"""

from __future__ import annotations

from importlib import import_module
from typing import FrozenSet

from scout.mcp.server import mcp_server

_MCP_TOOL_MODULES: tuple[str, ...] = (
    "scout.mcp.product_tools",
    "scout.mcp.semantic_search_tools",
    "scout.mcp.inventory_tools",
    "scout.mcp.store_tools",
    "scout.mcp.affiliate_tools",
    "scout.mcp.order_tools",
    "scout.mcp.cart_tools",
    "scout.mcp.checkout_tools",
)


def registered_mcp_tool_names() -> FrozenSet[str]:
    """Return exact tool names registered on Scout's shared FastMCP server."""
    for module_name in _MCP_TOOL_MODULES:
        import_module(module_name)

    return frozenset(mcp_server._tool_manager._tools.keys())
