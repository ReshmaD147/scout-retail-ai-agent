"""Specialist agent nodes: interpret state, call MCP tools/services, and
return grounded, structured updates. Agents never run SQL directly and
never invent a product, price, stock level, or store - see
scout/mcp/product_tools.py's module docstring for why agents get
tools, not database access.
"""
