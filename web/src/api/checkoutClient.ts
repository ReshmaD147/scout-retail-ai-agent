/** Thin Step 16 checkout HTTP client. All totals are server-calculated. */
import { API_BASE_URL } from "./config";
import type { CheckoutReview, OrderConfirmation, ShippingAddress } from "../types/checkout";

export class CheckoutRequestError extends Error {
  readonly status?: number;
  readonly code?: string;

  constructor(message: string, status?: number, code?: string) {
    super(message);
    this.name = "CheckoutRequestError";
    this.status = status;
    this.code = code;
  }
}

async function extractError(response: Response): Promise<{ message: string; code?: string }> {
  try {
    const body = (await response.json()) as Record<string, unknown>;
    const message =
      typeof body.message === "string"
        ? body.message
        : typeof body.error === "string"
          ? body.error
          : undefined;
    const code = typeof body.code === "string" ? body.code : undefined;
    if (message) return { message, code };
  } catch {
    // Fall through to safe generic copy.
  }
  return { message: "Scout could not complete checkout. Please try again." };
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...init,
    });
  } catch {
    throw new CheckoutRequestError("Scout could not be reached. Please check your connection and try again.");
  }
  if (!response.ok) {
    const { message, code } = await extractError(response);
    throw new CheckoutRequestError(message, response.status, code);
  }
  return (await response.json()) as T;
}

export function createCheckoutSession(
  sessionId: string,
  shippingAddress: ShippingAddress | null
): Promise<CheckoutReview> {
  return request<CheckoutReview>("/checkout/sessions", {
    method: "POST",
    body: JSON.stringify({ session_id: sessionId, shipping_address: shippingAddress }),
  });
}

export function confirmCheckout(
  checkoutId: string,
  sessionId: string,
  idempotencyKey: string,
  confirmPayment: boolean,
  paymentMethodToken = "mock_success"
): Promise<OrderConfirmation> {
  return request<OrderConfirmation>(`/checkout/sessions/${encodeURIComponent(checkoutId)}/confirm`, {
    method: "POST",
    body: JSON.stringify({
      session_id: sessionId,
      idempotency_key: idempotencyKey,
      confirm_payment: confirmPayment,
      payment_method_token: paymentMethodToken,
    }),
  });
}
