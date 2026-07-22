"""Scout MCP layer.

This package exposes a fixed set of approved, structured tools that an
agent can call - it is the ONLY way agents reach product data. Agents
never import a repository or a service directly (see product_tools.py
module docstring for why).

Everything here is built on the official Model Context Protocol Python
SDK (the `mcp` package, via `mcp.server.fastmcp.FastMCP`), so each
`@tool()` function has a real, inspectable MCP name, description, and
JSON Schema - not a hand-maintained document that can drift from the
code. Tool functions remain plain, directly callable Python functions,
which is how they are tested in this phase (no running MCP server or
LangGraph involved yet).
"""
