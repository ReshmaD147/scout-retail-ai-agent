"""Reusable FastAPI dependencies shared across API routes.

Step 12 adds exactly one: the compiled LangGraph workflow.

Why a dependency instead of a mutable module-level global
--------------------------------------------------------------
The obvious alternative - a module-level `_graph = build_retail_graph()`
built at import time, or built lazily into a global the first time a
route needs it - works, but ties every route directly to one specific,
hard-to-replace object. `get_compiled_graph` is a plain function that
FastAPI resolves through its dependency-injection system instead:

- The route asks for "the compiled graph" (`Depends(get_compiled_graph)`)
  without knowing or caring how it was built or how many times.
- `@lru_cache` means the graph still only compiles once per process
  (compiling a LangGraph StateGraph is a repeatable, deterministic
  step with no per-request state baked into the returned object, so
  reuse across requests is safe) - "compile once, do not rebuild every
  request" without a hand-rolled `if _graph is None: build()` global.
- Tests can replace the dependency entirely -
  `app.dependency_overrides[get_compiled_graph] = lambda: fake_graph` -
  so a route test can inject a small scripted fake graph and verify
  the route's own validation, timeout, and response-mapping logic in
  complete isolation, with no real database, no real LangGraph
  execution, and no risk of one test's graph state leaking into
  another's. A module-level global offers no equivalent seam - a test
  would have to monkeypatch the module attribute directly and remember
  to restore it, which FastAPI's dependency_overrides already does
  safely and explicitly (tests just clear the dict afterward).
"""

from functools import lru_cache
from typing import Any

from scout.orchestration.graph import build_retail_graph


@lru_cache
def get_compiled_graph() -> Any:
    """Return Scout's compiled retail workflow graph, building it once.

    Returns:
        The same compiled LangGraph object on every call within a
        process (subsequent calls hit the cache) - a fresh one is
        never built per-request. The return type is the LangGraph
        `CompiledStateGraph` `build_retail_graph()` itself returns;
        typed as `Any` here rather than importing LangGraph's internal
        class name, since callers only ever need to call `.invoke(...)`
        on it.
    """
    return build_retail_graph()
