import { API_BASE_URL } from "./config";
import type { ProtectedActionResult } from "../types/chat";

export class ProtectedActionRequestError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ProtectedActionRequestError";
  }
}

async function request<T>(path: string, body: Record<string, unknown>): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    throw new ProtectedActionRequestError("Scout could not reach the protected-action service.");
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => ({})) as Record<string, unknown>;
    const message = typeof payload.message === "string" ? payload.message : "Scout could not complete this protected action safely.";
    throw new ProtectedActionRequestError(message);
  }
  return (await response.json()) as T;
}

export function decideProtectedAction(
  confirmationId: string,
  sessionId: string,
  decision: "approve" | "reject",
  customerId = sessionId
): Promise<ProtectedActionResult> {
  return request<ProtectedActionResult>("/protected-actions/confirm", {
    confirmation_id: confirmationId,
    session_id: sessionId,
    customer_id: customerId,
    decision,
  });
}
