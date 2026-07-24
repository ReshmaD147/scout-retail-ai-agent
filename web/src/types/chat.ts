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
  attributes?: Record<string, unknown>;
  verified_promotion?: VerifiedPromotionSummary | null;
  explanation?: string | null;
  explanation_source?: "ollama" | "retry" | "deterministic_fallback" | null;
  memory_influence?: string | null;
}

export interface VerifiedPromotionSummary {
  promotion_id: string;
  label: string;
  discount_type: "percent" | "amount";
  discount_value: number;
  original_price: number;
  promotional_price: number;
  savings: number;
  valid_until: string;
  terms_summary: string | null;
  verified: boolean;
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
  delivery_min_days: number | null;
  delivery_max_days: number | null;
}

export interface FulfillmentEvidence {
  verified: boolean;
  availability_type: "selected_store" | "nearby_store" | "network" | "delivery";
  product_id: string;
  store_id: string | null;
  store_name: string | null;
  quantity: number | null;
  pickup_available: boolean | null;
  delivery_available: boolean | null;
  delivery_estimate: string | null;
  estimate_type: "prototype" | "carrier" | null;
  checked_at: string | null;
  evidence_ids: string[];
}

export interface RequestedLocation {
  label: string;
  latitude: number;
  longitude: number;
}


/** scout/mcp/schemas.py::ExternalOfferSummary */
export interface ExternalOfferSummary {
  offer_id: string;
  merchant_name: string;
  external_product_id: string;
  product_name: string;
  brand: string;
  category: string;
  description: string;
  price: number;
  currency: string;
  rating: number | null;
  review_count: number;
  availability_status: string;
  image_url: string | null;
  match_type: "exact" | "similar";
  match_label: string;
  match_reason: string;
  source_product_id: string | null;
  matched_identifier_type: string | null;
  observed_at?: string | null;
  same_product_verified?: boolean;
  affiliate_disclosure?: string;
  evidence_ids?: string[];
  relevance_score: number;
  disclosure: string;
}

export interface OrderItemStatus {
  order_item_id: string;
  product_id: string;
  product_name: string;
  brand: string;
  quantity: number;
  charged_unit_price: number;
  line_total: number;
}

export interface PaymentStatus {
  status: string;
  provider: string;
  provider_reference: string;
  amount: number;
  currency: string;
  paid_at: string;
}

export interface TrackingInformation {
  available: boolean;
  carrier_name: string | null;
  tracking_number: string | null;
  tracking_url: string | null;
  message: string;
}

export interface OrderShippingAddress {
  full_name: string;
  line1: string;
  line2: string | null;
  city: string;
  state: string;
  postal_code: string;
  country: string;
}

export interface FulfillmentStatus {
  fulfillment_type: "pickup" | "delivery";
  status: string;
  store_id: string | null;
  store_name: string | null;
  shipping_address: OrderShippingAddress | null;
  estimated_ready_at: string | null;
  estimated_delivery_at: string | null;
  estimate_source: "configured_policy" | "persisted_tracking";
  tracking: TrackingInformation;
}

export interface EligibilityCheck {
  eligible: boolean;
  reason: string;
  deadline: string | null;
}

export interface OrderEligibility {
  cancellation: EligibilityCheck;
  return_eligibility: EligibilityCheck;
  exchange: EligibilityCheck;
}

export interface OrderStatusView {
  order_id: string;
  session_id: string;
  order_status: string;
  created_at: string;
  items: OrderItemStatus[];
  subtotal: number;
  discount_total: number;
  tax_total: number;
  shipping_total: number;
  total: number;
  currency: string;
  payment: PaymentStatus;
  fulfillment: FulfillmentStatus;
  eligibility: OrderEligibility;
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
  filters?: RecommendationFilters;
}

export interface RecommendationFilters {
  max_price?: number;
  category?: string;
  product_type?: string;
  attributes?: string[];
  in_stock_only?: boolean;
  fulfillment?: "pickup" | "delivery";
}

/** scout/api/schemas/chat.py::ChatResponse - the whole body POST /chat returns, and also the `final_response` stream event's `data`. */
export interface ChatResponse {
  workflow_id: string;
  session_id: string;
  status: WorkflowStatus;
  answer: string | null;
  products: ProductSummary[];
  product_groups?: ProductGroup[];
  missing_product_targets?: MissingProductTarget[];
  fulfillment_options: FulfillmentOption[];
  fulfillment_evidence?: FulfillmentEvidence[];
  requested_location?: RequestedLocation | null;
  external_offers: ExternalOfferSummary[];
  order?: OrderStatusView | null;
  activity_events: string[];
  errors: ChatError[];
  approved_claims?: Array<Record<string, unknown>>;
  request_id?: string | null;
  assistant_message_id?: string | null;
  message_type?: ConversationMessageType;
  product_ids?: string[];
  suggested_actions?: SuggestedAction[];
  quick_replies?: SuggestedAction[];
  protected_action?: ProtectedActionConfirmationCard | null;
}

export type ConversationRole = "user" | "assistant" | "system";
export type ConversationMessageType =
  | "text"
  | "clarification"
  | "recommendation"
  | "fulfillment"
  | "order_status"
  | "partial_result"
  | "safe_failure";
export type ConversationMessageStatus = "pending" | "streaming" | "completed" | "failed" | "canceled";

export interface SuggestedAction {
  action_id: string;
  label: string;
  query: string;
}

export interface ConversationMessage {
  message_id: string;
  session_id: string;
  request_id: string;
  role: ConversationRole;
  message_type: ConversationMessageType;
  content: string;
  status: ConversationMessageStatus;
  created_at: string;
  product_ids: string[];
  order_id: string | null;
  approved_claims: Array<Record<string, unknown>>;
  suggested_actions: SuggestedAction[];
  response?: ChatResponse | null;
  activities?: ActivityEvent[];
  feedback?: "helpful" | "not_helpful" | null;
}

export interface ProtectedActionConfirmationCard {
  confirmation_id: string;
  action_type: string;
  resource_type: string;
  resource_id: string;
  proposal_summary: string;
  customer_effects: string[];
  financial_effects: string[];
  eligibility_status: string;
  eligibility_reason_code: string;
  expires_at: string;
}

export interface ProtectedActionResult {
  confirmation_id: string;
  action_type: string;
  execution_status: "verified" | "rejected" | "expired" | "failed";
  resource_id: string;
  result_state: string;
  request_id: string | null;
  verified_at: string;
  evidence_ids: string[];
  message: string;
  payment_handoff?: Record<string, unknown> | null;
}

export interface ProductGroup {
  target_label: string;
  products: ProductSummary[];
  missing: boolean;
  message: string | null;
}

export interface MissingProductTarget {
  label: string;
  message: string | null;
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
  status: "active" | "completed" | "failed";
}
