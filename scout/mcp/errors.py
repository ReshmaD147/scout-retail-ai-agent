"""Error handling shared by every MCP tool.

Tools never let a raw exception or stack trace reach a caller (an
agent, later a customer-facing response). Every tool function validates
its own inputs and catches exactly this one, narrow exception type -
anything else is a genuine bug and is allowed to propagate so it shows
up loudly in tests instead of being hidden.
"""


class ToolValidationError(Exception):
    """Raised inside a tool implementation for a specific invalid input.

    Always caught inside the tool function that raised it and turned
    into a structured ToolError (see schemas.py) before returning -
    never allowed to escape as a Python exception.
    """
