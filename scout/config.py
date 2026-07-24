"""Centralized application configuration.

Every setting the application needs is defined once, here, as a typed
Pydantic field. Values are read from environment variables or a local
.env file. No other module should read os.environ directly - if a new
setting is needed, add it here first.
"""

from functools import lru_cache
from typing import List, Literal, Optional

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, loaded from environment / .env."""

    app_name: str = "Retail AI Assistant (Scout)"
    environment: str = "development"
    log_level: str = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    database_path: str = "data/scout.db"
    nearby_store_radius_miles: float = 25.0
    max_search_radius_miles: float = 100.0
    standard_delivery_min_days: int = 3
    standard_delivery_max_days: int = 5
    max_workflow_steps: int = Field(default=50, ge=1)
    """Hard ceiling on Supervisor decisions per workflow (CLAUDE.md
    section 3: "Continue calling tools indefinitely" is explicitly
    disallowed). scout/orchestration/supervisor.py checks this before
    ever consulting the Supervisor's policy/model."""
    max_retries: int = Field(default=3, ge=1)
    """Hard ceiling on how many times the Supervisor may re-route to
    the same agent after an error before it must stop with
    workflow_status="failed" instead of retrying forever."""
    max_agent_iterations: int = Field(default=8, ge=1)
    """Hard ceiling on autonomous specialist/supervisor loop iterations
    in one graph run. This bounds the Step 5 cyclic supervisor loop
    separately from LangGraph's lower-level superstep count."""
    max_tool_calls: int = Field(default=10, ge=1)
    """Hard ceiling on read-only MCP/tool calls an autonomous workflow
    may make before stopping safely."""
    max_identical_tool_call_count: int = Field(default=1, ge=1)
    """Hard ceiling for repeating the same tool call with the same
    validated arguments in one autonomous workflow."""
    max_correction_attempts: int = Field(default=1, ge=0)
    """Hard ceiling on how many times the Response Verification Agent
    (scout/agents/response_verification.py, Step 11) may send the
    workflow back through the pipeline for a fresh attempt after every
    candidate failed verification. Distinct from max_retries (the
    Supervisor's own re-routing limit): this counts correction passes
    through the recommendation/inventory pipeline specifically. Once
    exhausted, the verifier must return the fixed safe-failure message
    instead of looping again."""
    scout_workflow_timeout_seconds: float = Field(default=20.0, gt=0)
    """Hard wall-clock ceiling on one POST /chat request's graph
    invocation (scout/api/routes/chat.py, Step 12). Enforced with
    asyncio.wait_for around the (blocking) compiled-graph call, on top
    of - not instead of - the graph's own step/retry/correction limits:
    those bound *how much work* one workflow can do; this bounds *how
    long a customer waits* for an HTTP response no matter what the
    graph is doing. A development default of 20 seconds is generous
    for this deterministic, LLM-free pipeline (typical runs complete in
    well under a second) while still catching a genuinely stuck call
    (e.g. a hung database) instead of leaving a request open forever."""
    scout_stream_heartbeat_seconds: float = Field(default=15.0, gt=0)
    """How long POST /chat/stream (scout/api/routes/chat_stream.py,
    Step 13) may go without a real workflow event before sending a
    `heartbeat` frame, so a proxy or load balancer in front of Scout
    never sees the connection go quiet. This pipeline is deterministic
    and fast (typically well under a second end to end), so a
    development default of 15 seconds means a heartbeat almost never
    actually fires in normal use - it exists for the rare slow request,
    not for every request."""
    max_cart_item_quantity: int = Field(default=10, ge=1)
    """Hard ceiling on how many units of one product a single cart line
    (scout/services/cart_service.py, Step 15) may hold. Exists so a
    single add-to-cart or quantity-update call cannot silently create
    an unbounded line item - CLAUDE.md's "bounded autonomy" principle
    applies to deterministic services too, not only to agents calling
    tools."""
    checkout_tax_rate: float = Field(default=0.08, ge=0.0, le=1.0)
    """Deterministic prototype sales-tax rate applied to the discounted
    merchandise total during Step 16 checkout. A real retailer would
    replace this flat demo rate with a jurisdiction-aware tax service."""
    flat_shipping_fee: float = Field(default=5.99, ge=0.0)
    """Configured delivery fee used when an order does not qualify for
    free shipping. Pickup always has a shipping total of zero."""
    free_shipping_threshold: float = Field(default=50.0, ge=0.0)
    """Discounted merchandise total at or above which delivery shipping
    is waived in this prototype."""
    checkout_currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    """Currency code used by the deterministic checkout and mock payment
    adapter. Scout does not accept a client-supplied currency."""
    payment_provider: Literal["mock", "stripe_test"] = "mock"
    """Payment provider for deterministic checkout. Stripe mode is test-only."""
    mock_payment_provider: str = "mock"
    """Payment-provider label persisted for Step 16's local test-mode
    adapter. No real payment credential or card data is collected."""
    stripe_secret_key: Optional[str] = None
    """Stripe test secret key. Must start with sk_test_ when configured."""
    stripe_publishable_key: Optional[str] = None
    """Stripe test publishable key. Must start with pk_test_ when configured."""
    stripe_webhook_secret: Optional[str] = None
    """Stripe webhook signing secret for test-mode webhook verification."""
    stripe_currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    """Currency code sent to Stripe PaymentIntents."""

    cors_allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    """Comma-separated list of browser origins allowed to call this API
    (scout/api/app.py, Step 14 - the React dev server at
    http://localhost:5173 by default). CLAUDE.md section 11 lists "CORS
    origins" as required, environment-driven configuration; this must
    never default to "*" (section 7's API-layer rules), so a real
    deployment must set this explicitly to its actual frontend
    origin(s) rather than inheriting the local dev default."""

    embedding_provider: Literal["hashing", "ollama"] = "hashing"
    """Which local embedding backend scout/services/embedding_service.py
    uses to turn product/query text into vectors for semantic search
    (Step 15.5). "hashing" (default) is a deterministic, dependency-free
    local embedding - no network call, no model download - used
    everywhere in tests and by default in development, exactly like
    RuleBasedSupervisorPolicy stands in for a real model everywhere else
    in this codebase until Phase 5's Ollama integration exists.
    "ollama" switches to a real local neural embedding model served by
    Ollama (CLAUDE.md section 2's approved local LLM runtime) at
    `ollama_base_url`, using `ollama_embedding_model` - a genuine local
    embedding model, not a cloud API, satisfying Step 15.5's "use a
    local embedding model" for a real deployment, while keeping this
    deterministic default for anything that must run offline and
    reproducibly (tests, CI, a laptop with no Ollama installed)."""
    embedding_dimensions: int = Field(default=256, ge=8)
    """Vector length for the "hashing" embedding provider. Unused by
    "ollama", whose dimensionality is whatever the served model
    returns."""
    ollama_base_url: str = "http://localhost:11434"
    ollama_embedding_model: str = "nomic-embed-text"
    semantic_search_candidate_limit: int = Field(default=20, ge=1, le=100)
    """Upper bound on how many candidates
    scout/services/product_search_service.py's semantic path retrieves
    by meaning before deterministic filtering and ranking - Step 15.5's
    "retrieve 10-20 relevant candidates by meaning.\""""
    semantic_search_min_similarity: float = Field(default=0.0, ge=0.0, le=1.0)
    """Minimum cosine similarity a candidate must clear (strictly
    greater than this value) to be considered at all - keeps a
    completely unrelated product (zero shared vocabulary, a similarity
    of exactly 0) out of the candidate set even when fewer than
    `semantic_search_candidate_limit` products are available, without
    requiring a high, hard-to-calibrate score from the deterministic
    default embedding."""
    supervisor_policy: Literal["rule_based", "ollama"] = "ollama"
    """Which SupervisorPolicy scout/orchestration/graph.py wires into the
    compiled workflow (scout/orchestration/supervisor.py, Step 9-10).
    "ollama" (default) switches to
    LangChainSupervisorPolicy (scout/orchestration/supervisor_policy.py)
    bound to a real local chat model served by Ollama (CLAUDE.md section
    2's approved local LLM runtime) at `ollama_base_url`, using
    `ollama_chat_model` - the Supervisor's routing decision
    (recommendation, inventory, order, clarification, finish,
    safe_failure, ...) is then made by that model at runtime instead of
    a fixed if/else tree. Mirrors `embedding_provider`'s existing
    hashing/ollama pattern exactly, including the same fail-safe spirit:
    a deterministic default that needs nothing installed, and a genuine
    local-model default with deterministic rule-based fallback when the
    model is unavailable. "rule_based" forces the deterministic policy
    without trying Ollama."""
    ollama_chat_model: str = "llama3.2"
    """Which locally-served Ollama chat model
    scout/orchestration/supervisor_policy.py's LangChainSupervisorPolicy
    binds to when supervisor_policy="ollama". Ignored entirely when
    supervisor_policy="rule_based"."""
    ollama_chat_temperature: float = Field(default=0.1, ge=0.0, le=0.2)
    """Temperature for the local Ollama chat model used by the
    Supervisor. Kept deliberately low so routing stays stable and
    bounded while still allowing a real model-backed policy."""
    max_recommended_products: int = Field(default=3, ge=1)
    """Hard ceiling on how many verified products
    scout/agents/recommendation_agent.py's rerank_node ever hands to the
    Response Verification Agent - Step 15.5's "return up to 3 verified
    results." Never padded when fewer valid candidates exist (CLAUDE.md's
    bounded-autonomy principle again: an interface cap, not a target to
    fill)."""
    max_external_offers: int = Field(default=3, ge=1, le=10)
    """Hard ceiling on customer-facing mock merchant alternatives returned
    by the Step 16.5 fallback. External retrieval is a recovery path, not an
    unlimited marketplace feed, so the default stays aligned with Scout's
    three-result recommendation interface."""
    order_pickup_ready_minutes: int = Field(default=120, ge=0)
    """Prototype estimate for when a newly confirmed pickup order will be ready.
    This is a configured policy estimate, not a live store promise."""
    order_cancellation_window_minutes: int = Field(default=60, ge=0)
    """Read-only Step 17 eligibility window. Scout reports whether an order
    appears eligible; it never performs the cancellation in this phase."""
    order_return_window_days: int = Field(default=30, ge=0)
    """Read-only return eligibility window after delivery or pickup."""
    order_exchange_window_days: int = Field(default=30, ge=0)
    """Read-only exchange eligibility window after delivery or pickup."""
    session_memory_ttl_hours: int = Field(default=24, ge=1)
    """How long temporary shopping/session memory remains usable."""
    durable_preference_ttl_days: int = Field(default=365, ge=1)
    """Default expiration window for explicit customer preferences."""
    memory_enabled_default: bool = True
    """Default memory setting for customers without an explicit control row."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @model_validator(mode="after")
    def _validate_delivery_window(self) -> "Settings":
        """Fail fast at startup on an unusable delivery-window config.

        A negative minimum or a maximum below the minimum would let
        get_delivery_estimate hand out a nonsensical window (e.g.
        "5-3 days") to every customer - this is a configuration error,
        not something a request-time guard should have to catch.
        """
        if self.standard_delivery_min_days < 0:
            raise ValueError("standard_delivery_min_days must be >= 0")
        if self.standard_delivery_max_days < self.standard_delivery_min_days:
            raise ValueError(
                "standard_delivery_max_days must be >= standard_delivery_min_days"
            )
        if self.payment_provider == "stripe_test":
            if not self.stripe_secret_key or not self.stripe_secret_key.startswith("sk_test_"):
                raise ValueError("STRIPE_SECRET_KEY must be a Stripe test secret key starting with sk_test_")
            if not self.stripe_publishable_key or not self.stripe_publishable_key.startswith("pk_test_"):
                raise ValueError("STRIPE_PUBLISHABLE_KEY must be a Stripe test publishable key starting with pk_test_")
        return self

    @property
    def cors_allowed_origins_list(self) -> List[str]:
        """`cors_allowed_origins` split into a clean list of origins,
        for scout/api/app.py's CORSMiddleware - never an empty string
        entry from a trailing comma or extra whitespace."""
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    """Return the cached application settings singleton.

    Using lru_cache means Settings() is constructed once per process
    and reused everywhere, instead of re-reading the environment on
    every call.
    """
    return Settings()
