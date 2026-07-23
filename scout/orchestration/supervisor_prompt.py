"""The Supervisor's prompt: fixed instructions plus a per-turn state summary.

`SUPERVISOR_SYSTEM_PROMPT` is static - it never contains customer data.
`format_state_summary()` renders the *safe* parts of the current
RetailGraphState (never hidden chain-of-thought, never secrets - see
scout/orchestration/state.py's "Which data should not be placed in
state") into plain text for the model to read. `build_supervisor_prompt()`
combines them into a `ChatPromptTemplate` ready for
`.format_messages(state_summary=...)`.
"""

from langchain_core.prompts import ChatPromptTemplate

from scout.orchestration.state import RetailGraphState

SUPERVISOR_SYSTEM_PROMPT = """\
You are the Supervisor for Scout, a bounded-autonomous retail assistant.
You do not answer the customer directly and you do not call tools
yourself. Each turn, you choose exactly one next decision for the
workflow, grounded only in the state summary you are given - never
invent products, prices, stock, orders, or policies that are not
already present in that summary.

Choose exactly one `decision` per turn, from:
- "recommendation": route to the Product Recommendation agent (finding
  or narrowing candidate products).
- "inventory": route to the Inventory and Fulfillment agent (stock,
  pickup, delivery, substitutes).
- "order": route to the Order agent (order status, tracking,
  eligibility).
- "support": route to the Customer Support agent (policy questions).
- "verification": route to the Response Verification agent (check a
  draft answer against evidence before it is shown to the customer).
- "clarification": pause and ask the customer a specific question,
  when the request is too vague or off-topic to plan against. Required
  whenever you choose this: a non-empty `clarification_question`.
- "confirmation": pause because a protected action (cancel, return,
  exchange, refund, or payment charge) needs the customer's explicit
  confirmation before anything is executed.
- "finish": the goal is fully satisfied with grounded evidence - stop.
- "safe_failure": nothing further can be validly attempted (e.g.
  repeated errors, no evidence to proceed on) - stop safely rather than
  guessing.

Rules:
1. Ground every decision in the evidence, errors, and plan already in
   the state summary - never in outside knowledge.
2. If the request is vague, ambiguous, or off-topic, choose
   "clarification" rather than guessing what the customer meant.
3. Only choose "finish" once the plan's steps are complete and grounded
   evidence supports the answer.
4. If recent errors show a step keeps failing with no new evidence,
   prefer "safe_failure" over repeating the same failing step forever.
5. Always provide a short, plain-language `decision_summary` describing
   what you decided and why - a factual sentence, not your reasoning
   process.
6. Provide `plan` only when you are setting the plan for the first time
   or replanning; leave it empty to continue the existing plan.
7. Set `needs_multiple_agents` to true if the plan involves more than
   one specialist agent.
"""


def format_state_summary(state: RetailGraphState) -> str:
    """Render the safe, relevant parts of `state` as plain text.

    Deliberately excludes raw tool payloads, full product catalogs, and
    anything not already summarized elsewhere in state - the Supervisor
    reasons over the same safe, structured trail everything else in
    Scout is grounded in, not a fresh dump of the database.
    """
    lines = [
        f"Customer query: {state.customer_query}",
        f"Goal: {state.goal or '(not yet set)'}",
        f"Workflow status: {state.workflow_status}",
        f"Step count: {state.step_count}",
        f"Retry count: {state.retry_count}",
    ]

    if state.plan:
        lines.append("Plan:")
        for step in state.plan:
            lines.append(f"  - [{step.status}] {step.step_id} ({step.agent}): {step.description}")
    else:
        lines.append("Plan: (none yet)")

    lines.append(f"Completed steps: {state.completed_steps or '(none)'}")
    lines.append(f"Pending steps: {state.pending_steps or '(none)'}")

    if state.evidence:
        lines.append("Evidence collected so far:")
        for entry in state.evidence[-10:]:
            lines.append(f"  - ({entry.source}) {entry.claim}")
    else:
        lines.append("Evidence collected so far: (none)")

    if state.errors:
        lines.append("Errors encountered so far:")
        for error in state.errors[-10:]:
            lines.append(f"  - [{error.error_type}] {error.message}")
    else:
        lines.append("Errors encountered so far: (none)")

    lines.append(f"Product candidates so far: {len(state.product_candidates)}")
    if state.order_context:
        lines.append(
            "Order context: "
            f"{state.order_context.get('order_id', '(unknown id)')} / "
            f"{state.order_context.get('order_status', '(unknown status)')}"
        )
    else:
        lines.append("Order context: (none)")
    lines.append(f"Pending confirmation: {'yes' if state.pending_confirmation else 'no'}")

    return "\n".join(lines)


def build_supervisor_prompt(state: RetailGraphState) -> ChatPromptTemplate:
    """Build the two-message prompt (system instructions + state summary)
    ready to format and send to a structured-output-capable chat model."""
    return ChatPromptTemplate.from_messages(
        [
            ("system", SUPERVISOR_SYSTEM_PROMPT),
            ("human", "{state_summary}"),
        ]
    )
