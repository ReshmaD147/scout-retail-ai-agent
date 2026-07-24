import type { SavedProductsView } from "../types/saved";
import { API_BASE_URL } from "./config";

export class SavedProductsRequestError extends Error {
  readonly status?: number;
  readonly code?: string;

  constructor(message: string, status?: number, code?: string) {
    super(message);
    this.name = "SavedProductsRequestError";
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
      if (message) return { message, code };
    }
  } catch {
    // Fall through to the generic message.
  }
  return { message: "Scout could not load your saved products. Please try again." };
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...init,
    });
  } catch {
    throw new SavedProductsRequestError("Scout could not be reached. Please check your connection and try again.");
  }
  if (!response.ok) {
    const { message, code } = await extractSafeErrorMessage(response);
    throw new SavedProductsRequestError(message, response.status, code);
  }
  return (await response.json()) as T;
}

function ownerQuery(sessionId: string, customerId?: string | null): string {
  const params = new URLSearchParams();
  if (customerId) params.set("customer_id", customerId);
  else params.set("session_id", sessionId);
  return params.toString();
}

export function listSavedProducts(sessionId: string, customerId?: string | null): Promise<SavedProductsView> {
  return request<SavedProductsView>(`/saved-products?${ownerQuery(sessionId, customerId)}`);
}

export function saveProduct(sessionId: string, productId: string, customerId?: string | null): Promise<SavedProductsView> {
  return request<SavedProductsView>("/saved-products", {
    method: "POST",
    body: JSON.stringify(customerId ? { customer_id: customerId, product_id: productId } : { session_id: sessionId, product_id: productId }),
  });
}

export function removeSavedProduct(sessionId: string, productId: string, customerId?: string | null): Promise<SavedProductsView> {
  return request<SavedProductsView>(
    `/saved-products/${encodeURIComponent(productId)}?${ownerQuery(sessionId, customerId)}`,
    { method: "DELETE" }
  );
}
