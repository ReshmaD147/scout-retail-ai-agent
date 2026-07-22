/**
 * A thin wrapper around POST /chat (Step 12) - the non-streaming
 * endpoint. Used both directly (when a caller wants one blocking
 * request) and as the streaming fallback `useScoutChat` calls when
 * POST /chat/stream fails safely (Step 14's requirement 10).
 *
 * This file only ever *sends* a validated `ChatRequest` and *returns*
 * a `ChatResponse` - no ranking, pricing, inventory, or verification
 * logic lives here, exactly like scout/api/routes/chat.py's route
 * itself stays thin on the backend.
 */
import type { ChatRequest, ChatResponse } from "../types/chat";
import { API_BASE_URL } from "./config";

/** A safe, customer-facing error - `message` is always something the
 * backend itself produced or a generic network-failure sentence,
 * never a raw exception string. */
export class ChatRequestError extends Error {
  readonly status?: number;

  constructor(message: string, status?: number) {
    super(message);
    this.name = "ChatRequestError";
    this.status = status;
  }
}

async function extractSafeErrorMessage(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json();
    if (
      typeof body === "object" &&
      body !== null &&
      "message" in body &&
      typeof (body as { message?: unknown }).message === "string"
    ) {
      return (body as { message: string }).message;
    }
    if (
      typeof body === "object" &&
      body !== null &&
      "error" in body &&
      typeof (body as { error?: unknown }).error === "string"
    ) {
      return (body as { error: string }).error;
    }
  } catch {
    // The error body was not JSON - fall through to the generic message.
  }
  return "Scout could not process this request. Please try again.";
}

/**
 * Send one chat request and wait for the complete, verified response.
 *
 * @param request A validated ChatRequest (session_id + message, plus
 *   optional user_id/store_id/location) - the same shape POST
 *   /chat/stream accepts.
 * @param signal Optional AbortSignal so a caller (useScoutChat) can
 *   cancel an in-flight request.
 */
export async function sendChatRequest(
  request: ChatRequest,
  signal?: AbortSignal
): Promise<ChatResponse> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
      signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw error;
    }
    throw new ChatRequestError(
      "Scout could not be reached. Please check your connection and try again."
    );
  }

  if (!response.ok) {
    throw new ChatRequestError(await extractSafeErrorMessage(response), response.status);
  }

  return (await response.json()) as ChatResponse;
}
