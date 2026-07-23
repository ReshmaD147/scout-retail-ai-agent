/** Strict TypeScript mirrors of Scout Step 16 checkout responses. */

export interface ShippingAddress {
  full_name: string;
  line1: string;
  line2: string | null;
  city: string;
  state: string;
  postal_code: string;
  country: string;
}

export interface CheckoutLineReview {
  product_id: string;
  product_name: string;
  brand: string;
  quantity: number;
  catalog_unit_price: number;
  charged_unit_price: number;
  line_subtotal: number;
  discount_total: number;
  line_total: number;
  promotion_id: string | null;
  promotion_label: string | null;
}

export interface CheckoutReview {
  checkout_id: string;
  session_id: string;
  cart_id: string;
  cart_updated_at: string | null;
  status: string;
  fulfillment_type: "pickup" | "delivery";
  store_id: string | null;
  store_name: string | null;
  shipping_address: ShippingAddress | null;
  items: CheckoutLineReview[];
  subtotal: number;
  discount_total: number;
  merchandise_total: number;
  tax_rate: number;
  tax_total: number;
  shipping_total: number;
  total: number;
  currency: string;
  payment_provider?: "mock" | "stripe_test";
  warnings: string[];
}

export interface CheckoutPaymentIntent {
  checkout_id: string;
  session_id: string;
  status: string;
  provider: string;
  provider_reference: string;
  client_secret: string;
  publishable_key: string;
  amount: number;
  currency: string;
}

export interface CheckoutPaymentStatus {
  checkout_id: string;
  status: string;
  order_id: string | null;
}

export interface InventoryReservationSummary {
  store_id: string;
  store_name: string | null;
  quantity: number;
  status: string;
}

export interface OrderItemConfirmation extends CheckoutLineReview {
  order_item_id: string;
  reservations: InventoryReservationSummary[];
}

export interface PaymentConfirmation {
  provider: string;
  provider_reference: string;
  status: string;
  amount: number;
  currency: string;
}

export interface OrderConfirmation {
  order_id: string;
  checkout_id: string;
  session_id: string;
  status: string;
  fulfillment_type: "pickup" | "delivery";
  store_id: string | null;
  store_name: string | null;
  shipping_address: ShippingAddress | null;
  items: OrderItemConfirmation[];
  subtotal: number;
  discount_total: number;
  merchandise_total: number;
  tax_total: number;
  shipping_total: number;
  total: number;
  currency: string;
  payment: PaymentConfirmation;
  created_at: string;
}
