"""The single shared MCP server instance every Scout tool registers on.

Keeping exactly one FastMCP instance means an agent (a later phase)
connects once and sees every approved tool - product tools
(product_tools.py) and inventory/fulfillment tools (inventory_tools.py)
- instead of the tool surface being split across disconnected servers
that each need their own connection.
"""

from mcp.server.fastmcp import FastMCP

mcp_server = FastMCP("scout-tools")
