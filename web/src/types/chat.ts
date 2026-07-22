/**
 * Strict TypeScript types mirroring Scout's backend Pydantic schemas
 * (Step 14). Every type here corresponds 1:1 to a real backend model -
 * see the comment above each one for exactly which Python file/class
 * it mirrors. Nothing here invents a field the backend does not
 * return; optional fields are optional here only where the backend
 * schema itself makes them optional.
 *
 * React only ever *displays* these shapes - no ranking, pricing,
 * inventory, or verification logic is implemented against them here.
 */

/** scout/mcp/schemas.py::ProductSummary */
export interface ProductSummary {
  product_id: string;
  name: string;
  brand: string;
  category: string;
  subcategory: string;
  price: number;
  rating: number | null;
  review_count: number;
  active: boolean;
}

/**
 * scout/api/schemas/chat.py::FulfillmentOption
 *
 * `channel` is one of "selected_store" | "nearby_store" | "substitute"
 * (see scout/agents/inventory_agent.py) but the backend schema itself
 * types it as a plain `str`, not a Literal - kept as `string` here
 * too, rather than inventing a stricter union the backend does not
 * actually enforce.
 */
export interface FulfillmentOption {
  product_id: string;
  channel: string;
  store_id: string | null;
  store_name: string | null;
  sellable_quantity: number;
  distance_miles: number | null;
  substitute_for: string | null;
}

/** scout/api/schemas/chat.py::ChatError */
export interface ChatError {
  code: string;
  message: string;
}

/** The five values scout/api/schemas/chat.py::ChatResponse.status allows. */
export type WorkflowStatus =
  | "completed"
  | "clarification_required"
  | "no_results"
  | "confirmation_required"
  | "failed";

/** scout/api/schemas/chat.py::ChatRequest - the only shape POST /chat and POST /chat/stream accept. */
export interface ChatRequest {
  session_id: string;
  message: string;
  user_id?: string;
  store_id?: string;
  location?: string;
}

/** scout/api/schemas/chat.py::ChatResponse - the whole body POST /chat returns, and also the `final_response` stream event's `data`. */
export interface ChatResponse {
  workflow_id: string;
  session_id: string;
  status: WorkflowStatus;
  answer: string | null;
  products: ProductSummary[];
  fulfillment_options: FulfillmentOption[];
  activity_events: string[];
  errors: ChatError[];
}

/** scout/api/schemas/events.py::EventType */
export type StreamEventType =
  | "workflow_started"
  | "plan_created"
  | "agent_selected"
  | "tool_started"
  | "tool_completed"
  | "workflow_replanned"
  | "verification_started"
  | "verification_completed"
  | "clarification_required"
  | "confirmation_required"
  | "final_response"
  | "workflow_failed"
  | "stream_closed"
  | "heartbeat";

/**
 * scout/api/schemas/events.py::StreamEvent - one parsed Server-Sent
 * Event from POST /chat/stream. `data` mirrors the backend's own
 * `Dict[str, Any]` - its exact shape depends on `event_type` (e.g.
 * `final_response`'s `data` is a `ChatResponse`, `workflow_failed`'s is
 * a `ChatError`-shaped object), so callers narrow it at the point of
 * use (see web/src/api/streamClient.ts) instead of this type claiming
 * a specific shape the backend schema itself does not guarantee.
 */
export interface StreamEvent {
  event_id: number;
  event_type: StreamEventType;
  workflow_id: string;
  session_id: string;
  label: string;
  data: Record<string, unknown>;
  timestamp: string;
}

/** A single safe, customer-facing workflow activity entry for display (derived from StreamEvent, not a backend type itself). */
export interface ActivityEvent {
  id: number;
  type: StreamEventType;
  label: string;
}
