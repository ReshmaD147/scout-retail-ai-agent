/**
 * Strict TypeScript types mirroring Scout's cart backend schemas
 * (Step 15) - see web/src/types/chat.ts's module docstring for the
 * same rule applied there: every type here corresponds 1:1 to a real
 * backend model, nothing invents a field the backend does not return.
 */

/** scout/services/cart_service.py::CartItemView */
export interface CartItemView {
  cart_item_id: string;
  product_id: string;
  product_name: string;
  brand: string;
  quantity: number;
  unit_price: number;
  unit_price_snapshot: number;
  line_total: number;
  promotion_id: string | null;
  promotion_label: string | null;
  active: boolean;
  warnings: string[];
}

/** scout/services/cart_service.py::CartView - the shape every cart
 * endpoint returns (directly, or nested under `cart` for the
 * natural-language command endpoint). */
export interface CartView {
  cart_id: string | null;
  session_id: string;
  items: CartItemView[];
  subtotal: number;
  fulfillment_type: "pickup" | "delivery" | null;
  store_id: string | null;
  store_name: string | null;
  status: string;
  validation_status: "valid" | "invalid";
  warnings: string[];
  updated_at: string | null;
}

/** scout/api/schemas/cart.py::CartCommandResponse - the response for
 * the natural-language /cart/{session_id}/command endpoint. */
export interface CartCommandResponse {
  interpreted_action: string | null;
  clarification: string | null;
  cart: CartView;
}

/** scout/api/schemas/stores.py::StoreSummary - GET /stores. */
export interface StoreSummary {
  store_id: string;
  store_name: string;
  city: string;
  pickup_enabled: boolean;
  active: boolean;
}
