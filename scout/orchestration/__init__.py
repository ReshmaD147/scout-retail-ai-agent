"""LangGraph orchestration layer: shared state, nodes, routing, and the
Supervisor (built up across Steps 8-10). Nothing in this package
queries SQL directly or calls an LLM directly - it coordinates agents
and tools that do.
"""
