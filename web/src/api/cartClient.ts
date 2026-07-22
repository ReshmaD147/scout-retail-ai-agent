/**
 * A thin wrapper around Scout's cart REST endpoints (Step 15) - the
 * same "only send/receive, never compute" rule web/src/api/chatClient.ts
 * already follows: no quantity math, no subtotal, no validation logic
 * lives here. Every function sends one validated request and returns
 * the backend's own `CartView` (or `CartCommandResponse`), already
 * fully revalidated server-side.
 */
import type { CartCommandResponse, CartView, StoreSummary } from "../types/cart";
import { API_BASE_URL } from "./config";

/** A safe, customer-facing error - mirrors chatClient.ts's
 * ChatRequestError so useCart can handle both the same way. */
export class CartRequestError extends Error {
  readonly status?: number;
  readonly code?: string;

  constructor(message: string, status?: number, code?: string) {
    super(message);
    this.name = "CartRequestError";
    this.status = status;
    this.code = code;
  }
}

async function extractSafeErrorMessage(response: Response): Promise<{ message: string; code?: string }> {
  try {
    const body: unknown = await response.json();
    if (typeof body === "object" && body !== null) {
      const record = body as Record<string, unknown>;
      const message = typeof record.message === "string" ? record.message : undefined;
      const code = typeof record.code === "string" ? record.code : undefined;
      if (message) {
        return { message, code };
      }
      if (typeof record.error === "string") {
        return { message: record.error, code };
      }
    }
  } catch {
    // The error body was not JSON - fall through to the generic message.
  }
  return { message: "Scout could not update your cart. Please try again." };
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...init,
    });
  } catch {
    throw new CartRequestError("Scout could not be reached. Please check your connection and try again.");
  }

  if (!response.ok) {
    const { message, code } = await extractSafeErrorMessage(response);
    throw new CartRequestError(message, response.status, code);
  }

  return (await response.json()) as T;
}

export function getCart(sessionId: string): Promise<CartView> {
  return request<CartView>(`/cart/${encodeURIComponent(sessionId)}`);
}

export function addCartItem(sessionId: string, productId: string, quantity: number): Promise<CartView> {
  return request<CartView>("/cart/items", {
    method: "POST",
    body: JSON.stringify({ session_id: sessionId, product_id: productId, quantity }),
  });
}

export function updateCartItemQuantity(
  sessionId: string,
  cartItemId: string,
  quantity: number
): Promise<CartView> {
  return request<CartView>(`/cart/items/${encodeURIComponent(cartItemId)}`, {
    method: "PATCH",
    body: JSON.stringify({ session_id: sessionId, quantity }),
  });
}

export function removeCartItem(sessionId: string, cartItemId: string): Promise<CartView> {
  return request<CartView>(
    `/cart/items/${encodeURIComponent(cartItemId)}?session_id=${encodeURIComponent(sessionId)}`,
    { method: "DELETE" }
  );
}

export function clearCart(sessionId: string): Promise<CartView> {
  return request<CartView>(`/cart/${encodeURIComponent(sessionId)}`, { method: "DELETE" });
}

export function setFulfillment(
  sessionId: string,
  fulfillmentType: "pickup" | "delivery",
  storeId: string | null
): Promise<CartView> {
  return request<CartView>(`/cart/${encodeURIComponent(sessionId)}/fulfillment`, {
    method: "PUT",
    body: JSON.stringify({ fulfillment_type: fulfillmentType, store_id: storeId }),
  });
}

export function validateCart(sessionId: string): Promise<CartView> {
  return request<CartView>(`/cart/${encodeURIComponent(sessionId)}/validate`, { method: "POST" });
}

export function sendCartCommand(sessionId: string, message: string): Promise<CartCommandResponse> {
  return request<CartCommandResponse>(`/cart/${encodeURIComponent(sessionId)}/command`, {
    method: "POST",
    body: JSON.stringify({ message }),
  });
}

export function listStores(): Promise<StoreSummary[]> {
  return request<StoreSummary[]>("/stores");
}
