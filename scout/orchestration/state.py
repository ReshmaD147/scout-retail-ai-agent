"""Scout's shared LangGraph state (Step 8: state only - no graph yet).

What "graph state" is
----------------------
A LangGraph workflow is a graph of nodes (plain Python functions,
later: the Supervisor and each specialist agent) that all read from and
write to one shared object as the workflow runs. That shared object -
RetailGraphState below - is "graph state": a single typed record of
everything known about one customer request so far, passed from node
to node instead of each node keeping its own private memory.

How nodes read state
---------------------
A node is a function `def node(state: RetailGraphState) -> dict: ...`.
LangGraph calls it with the *current* full state. The node reads
whatever fields it needs (e.g. the Inventory agent reads
`state.product_candidates` and `state.intent`) and never has to ask
another node for that information directly - everything relevant is
already sitting in the one object every node was called with.

How nodes return state updates
--------------------------------
A node does not mutate `state` in place and does not return a full new
state. It returns a small dict containing only the keys it changed,
e.g. `return {"inventory_results": [...], "next_agent": "recommendation"}`.
LangGraph merges that dict into the shared state before calling the
next node. This partial-update contract is exactly why reducers matter
(next section) - LangGraph needs to know, per field, whether "merge"
means "replace the old value" or "combine it with the old value."

Reducers, and which fields need one
-------------------------------------
By default, when a node's returned dict includes a key, LangGraph
*replaces* that field's old value with the new one ("last write wins").
That is correct for most of this state - e.g. `next_agent`,
`workflow_status`, and `product_candidates` should always reflect the
latest decision, not an accumulation of every decision ever made for
that field.

A few fields are different: they are logs that must never lose earlier
entries just because a later node's return value did not happen to
repeat them. Those fields are declared as
`Annotated[<type>, <reducer function>]`, which tells LangGraph "combine
old and new with this function" instead of "replace":

- `messages` uses LangGraph's own `add_messages` reducer - the
  standard way to append chat turns (it also updates a message in
  place if a later node re-sends one with the same `id`, instead of
  duplicating it).
- `completed_steps`, `tool_results`, `evidence`, and `errors` use
  `operator.add` (list concatenation) - each is an append-only trace
  that every node contributes to, and earlier entries must survive
  later nodes' updates.

Every other field is intentionally left as plain "replace" - see
"Which data should not be placed in state" below for one more
consequence of that choice.

Why structured state beats one long agent message
----------------------------------------------------
An alternative design would hand every agent one big transcript string
and let each agent re-read and re-parse the whole conversation to find
what it needs. Typed state avoids that:

- A node can read `state.product_candidates` directly - a list of real
  `ProductSummary` objects - instead of re-parsing prose to guess which
  products were mentioned and re-extracting their prices.
- Pydantic validates every update. A node that tries to set
  `workflow_status="oops"` or `retry_count=-1` fails immediately with a
  clear error, instead of silently corrupting a shared transcript that
  nothing checks.
- Grounding stays intact: `evidence` and `tool_results` are structured
  records tied to real tool calls (see scout/mcp/schemas.py), not
  sentences an LLM could paraphrase into something ungrounded.
- Each field can be read, tested, and reasoned about independently -
  exactly how tests/test_orchestration_state.py below exercises them.

How state prevents duplicate work
------------------------------------
Because state is shared and cumulative, a node can always check "has
this already been done?" before doing it again:

- `completed_steps` / `pending_steps` let the Supervisor (Step 9) skip
  a step that is already in `completed_steps` instead of re-running it.
- `evidence` and `tool_results` are the record of which tools already
  ran and what they returned - a node can check them before calling the
  same tool again with the same arguments (e.g. do not call
  `check_store_inventory` for a store already checked this workflow).
- `retry_count` / `step_count` are incremented centrally, so a limit
  check in one place (a future guardrail) can stop the whole workflow
  instead of each agent independently deciding when to give up.

Without shared state, each agent would only know what was in its own
local context, so the same tool call could easily be repeated by two
different agents that do not know about each other's work.

Which data should not be placed in state
-------------------------------------------
- Hidden chain-of-thought or raw LLM reasoning text. CLAUDE.md is
  explicit that this must never be logged or stored; `tool_results`
  intentionally only holds a short, safe `summary` string, not a
  model's reasoning.
- Secrets: passwords, tokens, payment details, API keys.
- Full private customer data beyond what the active workflow needs
  (e.g. do not dump an entire customer profile into `order_context`
  "just in case" - store only what the current request is using).
- Anything the database or a tool result already owns as the source of
  truth (a product's live price, current stock, a promotion's dates).
  State holds *copies used for this one workflow run* - e.g.
  `product_candidates` - never a second, independently-editable copy
  that could drift from scout/database and be trusted over it.
- Large raw payloads with no evidentiary value (a full HTML page, a
  full unfiltered SQL result set). Only the fields a claim actually
  needs to be grounded belong in `evidence`.
"""

import operator
from typing import Annotated, Any, Dict, List, Literal, Optional

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field

from scout.mcp.schemas import ExternalOfferSummary, ProductSummary

# ---------------------------------------------------------------------------
# Sub-models
#
# These give `plan`, `evidence`, `tool_results`, `errors`, and
# `pending_confirmation` real structure instead of untyped dicts, while
# staying generic enough not to anticipate agent-specific schemas that
# do not exist yet (those belong to their own future phases - the
# Recommendation Agent's intent schema, the Order Agent's eligibility
# checks, and so on).
# ---------------------------------------------------------------------------


class PlanStep(BaseModel):
    """One step of the Supervisor's plan for the current workflow."""

    step_id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    """A short, safe description of what this step does (e.g. "check
    selected store inventory") - never chain-of-thought."""
    agent: str = Field(min_length=1)
    """The specialist agent responsible for this step (e.g.
    "recommendation", "inventory", "order", "support")."""
    status: Literal["pending", "in_progress", "completed", "skipped"] = "pending"


class EvidenceEntry(BaseModel):
    """One grounded fact backing a claim Scout might make to the customer.

    Every product, inventory, order, or policy statement in
    `final_response` must be traceable to one of these - see CLAUDE.md
    section 3 ("Scout must never invent...") and section 8 (data truth
    rules).
    """

    source: str = Field(min_length=1)
    """The tool or repository call that produced this evidence (e.g.
    "check_store_inventory", "ProductRepository.get_by_id")."""
    claim: str = Field(min_length=1)
    """The specific statement this evidence supports (e.g. "FTW-004 is
    in stock at STR-002")."""
    data: Dict[str, Any] = Field(default_factory=dict)
    """The raw structured payload backing the claim - typically a
    tool's *Result model, dumped to a dict."""


class ToolCallTrace(BaseModel):
    """A safe, structured record that one tool call happened.

    This is "safe trace data" per CLAUDE.md section 9: which tool ran
    and whether it worked, never the model's reasoning about why.
    """

    tool_name: str = Field(min_length=1)
    status: Literal["success", "error"]
    summary: str = Field(min_length=1)
    """A short, safe description of the result (e.g. "found 3 stores
    within 25 miles"), not raw output and not chain-of-thought."""


class WorkflowError(BaseModel):
    """A structured error, using the categories CLAUDE.md section 12 defines."""

    error_type: Literal[
        "validation_error",
        "not_found",
        "database_error",
        "tool_timeout",
        "tool_execution_error",
        "model_unavailable",
        "malformed_model_output",
        "workflow_limit_reached",
        "unauthorized",
        "confirmation_required",
        "grounding_failure",
    ]
    message: str = Field(min_length=1)
    """A customer-safe description - never a stack trace, SQL, or a
    hidden prompt (CLAUDE.md section 12)."""
    agent: Optional[str] = None
    step: Optional[str] = None


class PendingConfirmation(BaseModel):
    """A protected action awaiting the customer's explicit confirmation.

    Populated only for the sensitive actions CLAUDE.md section 3 lists
    (cancel, return/exchange, refund, charge) - Scout must never
    execute one of these without this being confirmed first (Step 17
    builds the actual confirm/resume flow; this field only describes
    what is waiting).
    """

    action_type: Literal["cancel_order", "return_or_exchange", "refund", "charge_payment"]
    description: str = Field(min_length=1)
    """A clear, customer-facing explanation of the proposed action
    (CLAUDE.md section 3, requirement 4)."""
    target_id: Optional[str] = None
    """The order, return, or payment record this action applies to."""
    requested_at: Optional[str] = None
    """ISO timestamp of when confirmation was requested."""


# ---------------------------------------------------------------------------
# Shared graph state
# ---------------------------------------------------------------------------


class RetailGraphState(BaseModel):
    """Scout's shared LangGraph state for one customer workflow.

    See the module docstring for what this is, how nodes read and
    update it, and which fields use a reducer. Field-by-field notes
    below only cover what is specific to that field.

    `workflow_id` and `user_id` were a known, documented gap through
    Step 11 ("once the API layer that assigns a workflow_id per
    request... exists") - Step 12's `POST /chat` (scout/api/routes/chat.py)
    is that API layer, so both are added here now.
    """

    model_config = {"arbitrary_types_allowed": True}

    # -- Request identity and input -----------------------------------
    workflow_id: Optional[str] = None
    """A UUID assigned once per HTTP request by scout/api/routes/chat.py
    (Step 12) - identifies this specific workflow *run*, distinct from
    `session_id` (which can span many workflow runs across a
    conversation). Optional so tests and other, non-HTTP callers of
    run_graph()/build_retail_graph() can keep omitting it, exactly as
    they did before Step 12."""
    session_id: str = Field(min_length=1)
    user_id: Optional[str] = None
    """The authenticated customer, when available. No authentication
    exists yet (a future phase's job) - Step 12's ChatRequest accepts
    it and this field carries it through for traceability/logging
    only; no node reads it yet."""
    customer_query: str = Field(min_length=1)
    """The customer's original, unmodified request."""
    messages: Annotated[List[BaseMessage], add_messages] = Field(default_factory=list)
    """The conversation so far. Uses LangGraph's add_messages reducer -
    see module docstring."""
    requested_store_id: Optional[str] = None
    """The store_id the client asked for directly (Step 12's
    ChatRequest.store_id), captured only for traceability/logging.
    Distinct from `intent["selected_store_id"]` - understand_request_node's
    own, resolved-from-free-text answer (scout/agents/understand_request.py)
    - which remains the only store_id any node actually trusts.
    Resolving a client-supplied store_id directly would need a new
    "does this store_id exist" tool, which is out of Step 12's scope
    (connecting the API to the existing workflow, not extending it) -
    a known, documented gap for a future phase."""
    location: Optional[str] = None
    """The client's raw location hint (Step 12's ChatRequest.location).
    scout/api/routes/chat.py folds this into `customer_query` when the
    customer's own message did not already mention a location, so the
    existing, already-tested understand_request_node extraction
    handles it without any agent-layer changes. This field itself is
    kept only for traceability/logging, not read by any node."""

    # -- Interpretation and planning ------------------------------------
    intent: Optional[Dict[str, Any]] = None
    """Extracted structured intent (category, budget, location, and so
    on). Kept as a generic dict here deliberately: the Recommendation
    Agent (Phase 5) owns the actual intent schema, and this
    orchestration layer should not guess it prematurely."""
    goal: Optional[str] = None
    """A short statement of what this workflow is trying to accomplish,
    set by the Supervisor (e.g. "find and confirm fulfillment for
    comfortable work shoes under $100")."""
    plan: List[PlanStep] = Field(default_factory=list)
    """The Supervisor's current plan. Replaced wholesale when the
    Supervisor (re)plans - not accumulated, since a stale plan must not
    outlive a replan."""
    completed_steps: Annotated[List[str], operator.add] = Field(default_factory=list)
    """step_ids from `plan` that have finished. Append-only - see
    module docstring."""
    pending_steps: List[str] = Field(default_factory=list)
    """step_ids from `plan` not yet done. Replaced each time the
    Supervisor recomputes it - it should shrink as work finishes, so it
    must not be an append-only log."""

    # -- Routing ----------------------------------------------------------
    active_agent: Optional[str] = None
    """The specialist agent currently executing."""
    next_agent: Optional[str] = None
    """The Supervisor's routing decision for the next node. None (or
    "none") means the workflow should stop."""

    # -- Domain results ----------------------------------------------------
    product_candidates: List[ProductSummary] = Field(default_factory=list)
    """The Recommendation Agent's current, revalidated candidate set.
    Reuses the real ProductSummary schema (scout/mcp/schemas.py)
    instead of an untyped dict, since that type already exists.
    Replaced (not appended) each time the agent filters or re-ranks -
    an old, invalidated candidate must not linger."""
    external_offers: List[ExternalOfferSummary] = Field(default_factory=list)
    """Verified mock merchant offers returned only when every internal
    fulfillment channel has been exhausted. Replaced wholesale on each
    external fallback attempt; never mixed into product_candidates or cart.
    """
    inventory_results: List[Dict[str, Any]] = Field(default_factory=list)
    """Structured results from inventory/fulfillment tool calls so far
    this workflow (see scout/mcp/inventory_tools.py *Result schemas).
    Left as dicts for now - Phase 10 will settle on a single typed
    shape once the multi-agent workflow using it is actually built."""
    order_context: Optional[Dict[str, Any]] = None
    """Reserved for the Order Agent (Phase 15, not yet built)."""
    policy_results: List[Dict[str, Any]] = Field(default_factory=list)
    """Reserved for the Support Agent (Phase 16, not yet built)."""

    # -- Traceability -------------------------------------------------------
    tool_results: Annotated[List[ToolCallTrace], operator.add] = Field(default_factory=list)
    """Every tool call made this workflow, safe-summarized. Append-only
    - see module docstring."""
    evidence: Annotated[List[EvidenceEntry], operator.add] = Field(default_factory=list)
    """Every grounded fact collected this workflow. Append-only - see
    module docstring."""
    errors: Annotated[List[WorkflowError], operator.add] = Field(default_factory=list)
    """Every error encountered this workflow. Append-only - see module
    docstring. Used by the Supervisor to decide whether to replan,
    retry, or stop."""

    # -- Limits and control -------------------------------------------------
    retry_count: int = Field(default=0, ge=0)
    step_count: int = Field(default=0, ge=0)
    correction_count: int = Field(default=0, ge=0)
    """How many times the Response Verification Agent (Step 11) has
    sent the workflow back through the pipeline for a fresh attempt
    after every candidate failed verification. Bounded by
    `max_correction_attempts` (scout/config.py) - a limit distinct from
    `retry_count` (the Supervisor's own re-routing limit) since this
    counts a different kind of retry: not "the Supervisor chose the
    same agent again," but "the Verifier rejected every candidate and
    asked for a fresh pass." See scout/agents/response_verification.py."""
    pending_confirmation: Optional[PendingConfirmation] = None

    # -- Outcome --------------------------------------------------------------
    workflow_status: Literal[
        "in_progress",
        "awaiting_confirmation",
        "awaiting_clarification",
        "completed",
        "failed",
        "stopped_at_limit",
    ] = "in_progress"
    """"awaiting_clarification" was added in Step 9, alongside the
    Supervisor's "clarification" decision - it needed a status distinct
    from "awaiting_confirmation" (which is specifically for protected
    actions, CLAUDE.md section 3) since pausing to ask the customer a
    clarifying question is a different situation with different rules
    (no protected action, no idempotency concern, just needs more
    input to proceed)."""
    final_response: Optional[str] = None
    """The grounded natural-language answer for the customer, or the
    clarifying question when workflow_status is "awaiting_clarification".
    Only set once the workflow reaches a terminal or paused-for-input
    status."""
