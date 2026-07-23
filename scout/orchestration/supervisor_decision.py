"""The Supervisor's structured output schema.

Every Supervisor turn produces exactly one `SupervisorDecision` - never
free text the rest of the graph would have to re-parse. This is the
Pydantic schema a chat model is bound to via
`BaseChatModel.with_structured_output(SupervisorDecision)`
(scout/orchestration/supervisor_policy.py), and it is also what
scout/orchestration/supervisor.py validates before trusting anything
the model returned.
"""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from scout.orchestration.state import PlanStep

# The nine decisions CLAUDE.md section 4 and Step 9 require the
# Supervisor to be able to make. "recommendation", "inventory",
# "order", "support", and "verification" route to a specialist agent;
# "clarification" and "confirmation" pause the workflow for customer
# input; "finish" and "safe_failure" end it.
SupervisorDecisionType = Literal[
    "recommendation",
    "inventory",
    "order",
    "support",
    "verification",
    "clarification",
    "confirmation",
    "finish",
    "safe_failure",
]


class SupervisorDecision(BaseModel):
    """One Supervisor turn's complete, validated decision."""

    decision: SupervisorDecisionType

    goal: str = Field(min_length=1)
    """A short statement of what the workflow is trying to accomplish
    (CLAUDE.md section 9's `goal` field) - set or reaffirmed every
    turn, since a replan can change it."""

    decision_summary: str = Field(min_length=1)
    """A short, safe, customer-and-audit-log-safe description of what
    was decided and why in plain terms (e.g. "selected store had no
    stock; checking nearby stores next") - never chain-of-thought, and
    never a stack trace or internal detail (CLAUDE.md section 9: "Safe
    trace data may include ... Decision summary")."""

    plan: List[PlanStep] = Field(default_factory=list)
    """The Supervisor's plan for the workflow. Empty when this turn is
    continuing an existing plan unchanged; populated when planning for
    the first time or replanning after failure/insufficient evidence.
    Each step's `agent` should be one of "recommendation", "inventory",
    "order", "support", or "verification"."""

    needs_multiple_agents: bool = False
    """Whether satisfying this request requires more than one
    specialist agent (e.g. a product recommendation with a pickup
    requirement needs both `recommendation` and `inventory`).
    Informational: this reflects the Supervisor's own assessment for
    tracing/debugging, and does not itself change how a single turn is
    routed - that always follows `decision`/`plan` directly."""

    clarification_question: Optional[str] = None
    """Required, non-empty, only when decision == "clarification" -
    the exact question to show the customer."""

    @model_validator(mode="after")
    def _validate_clarification_question(self) -> "SupervisorDecision":
        if self.decision == "clarification":
            if not (self.clarification_question and self.clarification_question.strip()):
                raise ValueError(
                    "clarification_question is required and must be non-empty when decision is 'clarification'"
                )
        return self


class SupervisorLoopDecision(BaseModel):
    """Structured output for the cyclic Supervisor loop."""

    next_agent: Literal[
        "recommendation_agent",
        "inventory_agent",
        "external_offer_agent",
        "order_agent",
        "verification_agent",
        "clarification",
        "finish",
        "safe_failure",
    ]
    reason: str = Field(min_length=1, max_length=300)
    goal_complete: bool = False
