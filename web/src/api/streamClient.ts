/**
 * The POST /chat/stream (Step 13) client.
 *
 * Why `fetch` + `ReadableStream` instead of native `EventSource`
 * -------------------------------------------------------------------
 * The browser's built-in `EventSource` can only issue GET requests -
 * it has no way to send a JSON body, and Scout's `ChatRequest` (the
 * customer's message, session_id, and optional hints) must be sent as
 * a POST body (see scout/api/routes/chat_stream.py). `fetch` lets us
 * POST normally and then read `response.body` as a `ReadableStream`
 * of raw bytes ourselves, decoding and splitting it into SSE frames
 * by hand (see `parseEventBlock` below) - the same wire format
 * `EventSource` would have parsed for us, just done manually because
 * `fetch` does not parse SSE framing on its own.
 *
 * This module never buffers the whole response before returning
 * anything: `streamChat` is an async generator that `yield`s each
 * `StreamEvent` the moment its SSE block is fully received, so
 * `useScoutChat` can update the UI incrementally exactly as Scout's
 * backend produces new activity.
 */
import type { ChatRequest, StreamEvent } from "../types/chat";
import { API_BASE_URL } from "./config";

/**
 * Thrown when the stream could not even be started - a network
 * failure, a non-200 response, or a response that is not actually an
 * event stream (e.g. a proxy or an old server returning plain JSON).
 * `useScoutChat` catches this specific error type to fall back to
 * POST /chat (Step 14 requirement: "Fall back to /chat when streaming
 * fails safely") - any other error is treated as a genuine failure.
 */
export class StreamUnavailableError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "StreamUnavailableError";
  }
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

/** Runtime validation of one parsed JSON payload against the
 * StreamEvent shape - guards against a malformed or truncated event
 * without ever using `any`. */
function isStreamEvent(value: unknown): value is StreamEvent {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.event_id === "number" &&
    typeof candidate.event_type === "string" &&
    typeof candidate.workflow_id === "string" &&
    typeof candidate.session_id === "string" &&
    typeof candidate.label === "string" &&
    typeof candidate.data === "object" &&
    candidate.data !== null &&
    typeof candidate.timestamp === "string"
  );
}

/**
 * Parse one raw SSE block (the text between two blank lines) into a
 * StreamEvent, or `null` if the block is malformed or unrecognized.
 *
 * "Ignore or safely handle malformed events" (Step 14) means a bad
 * block is skipped, never thrown as an error that would kill the rest
 * of an otherwise-healthy stream.
 */
function parseEventBlock(block: string): StreamEvent | null {
  let dataLine: string | null = null;

  for (const line of block.split("\n")) {
    if (line.startsWith("data:")) {
      dataLine = line.slice("data:".length).trim();
    }
  }

  if (!dataLine) {
    return null;
  }

  try {
    const parsed: unknown = JSON.parse(dataLine);
    return isStreamEvent(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

/**
 * POST a ChatRequest to /chat/stream and yield each StreamEvent as it
 * arrives.
 *
 * @param request The same ChatRequest shape POST /chat accepts.
 * @param signal An AbortSignal (from an `AbortController`) - aborting
 *   it stops the underlying fetch and this generator raises the
 *   resulting `AbortError`, letting the caller distinguish a deliberate
 *   cancellation from a real failure.
 */
export async function* streamChat(
  request: ChatRequest,
  signal?: AbortSignal
): AsyncGenerator<StreamEvent, void, void> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/chat/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify(request),
      signal,
    });
  } catch (error) {
    if (isAbortError(error)) {
      throw error;
    }
    throw new StreamUnavailableError("Could not reach Scout's streaming endpoint.");
  }

  const contentType = response.headers.get("content-type") ?? "";
  if (!response.ok || !contentType.includes("text/event-stream") || !response.body) {
    throw new StreamUnavailableError(`Streaming is unavailable (status ${response.status}).`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }
      buffer += decoder.decode(value, { stream: true });

      let boundary = buffer.indexOf("\n\n");
      while (boundary !== -1) {
        const block = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const event = parseEventBlock(block);
        if (event) {
          yield event;
        }
        boundary = buffer.indexOf("\n\n");
      }
    }
  } finally {
    reader.releaseLock();
  }
}
