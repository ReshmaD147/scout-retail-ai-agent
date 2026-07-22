import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import type { ChatResponse } from "./types/chat";

// These tests cover the Step 14 chat flow. Cart networking is tested
// separately in App.cart.test.tsx, so isolate it here to keep the chat
// fetch assertions focused on /chat/stream and /chat only.
vi.mock("./hooks/useCart", () => ({
  useCart: () => ({
    cart: null,
    itemCount: 0,
    isLoading: false,
    errorMessage: null,
    stores: [],
    addItem: vi.fn().mockResolvedValue(undefined),
    updateQuantity: vi.fn().mockResolvedValue(undefined),
    removeItem: vi.fn().mockResolvedValue(undefined),
    clear: vi.fn().mockResolvedValue(undefined),
    choosePickup: vi.fn().mockResolvedValue(undefined),
    chooseDelivery: vi.fn().mockResolvedValue(undefined),
    dismissError: vi.fn(),
    refresh: vi.fn().mockResolvedValue(undefined),
  }),
}));

/**
 * Integration tests for Scout's main shopping interface (Step 14).
 * `global.fetch` is stubbed per test so no real network call is ever
 * made - each test controls exactly what POST /chat/stream (and, for
 * the fallback scenario, POST /chat) returns.
 *
 * Scenario -> test name, matching the 20 scenarios the Step 14 prompt
 * lists explicitly (7-10 are covered in ProductCard.test.tsx instead,
 * since they are more naturally unit tests of one component; 20 is
 * "all existing backend tests still pass," confirmed by running the
 * backend's own suite, not something a frontend test file can assert):
 *   1.  renders the page
 *   2.  search input accepts text
 *   3.  empty submission is blocked
 *   4.  request is sent correctly
 *   5.  loading state appears
 *   6.  streaming events display in order
 *   11. clarification state works
 *   12. no-results state works
 *   13. safe errors display
 *   14. raw internal errors are hidden
 *   15. submission is disabled while active
 *   16. cancellation works
 *   17. /chat fallback works
 *   18. keyboard submission works
 *   19. accessibility labels exist
 */

const ACCEPTANCE_QUERY = "Find comfortable work shoes under $100 that I can pick up today near Maple Grove.";

function sseFrame(eventType: string, id: number, data: unknown): string {
  return `event: ${eventType}\nid: ${id}\ndata: ${JSON.stringify(data)}\n\n`;
}

/** Builds a real SSE frame whose "data:" line is a full StreamEvent
 * (event_id/event_type/workflow_id/session_id/label/data/timestamp) -
 * matching the actual backend contract (scout/api/schemas/events.py).
 * A frame whose data line is only the inner payload (e.g. a bare
 * ChatResponse) is malformed and would be correctly ignored by
 * streamClient's isStreamEvent guard, exactly like a real malformed
 * event would be. */
function finalResponseFrame(id: number, response: ChatResponse): string {
  return sseFrame("final_response", id, {
    event_id: id,
    event_type: "final_response",
    workflow_id: response.workflow_id,
    session_id: response.session_id,
    label: "Here is what Scout found",
    data: response,
    timestamp: "2026-01-01T00:00:00Z",
  });
}

function streamClosedFrame(id: number): string {
  return sseFrame("stream_closed", id, {
    event_id: id,
    event_type: "stream_closed",
    workflow_id: "wf-1",
    session_id: "s-1",
    label: "Stream closed",
    data: { status: "closed" },
    timestamp: "2026-01-01T00:00:00Z",
  });
}

function makeStreamResponse(frames: string[]): Response {
  const encoder = new TextEncoder();
  let index = 0;
  const stream = new ReadableStream<Uint8Array>({
    pull(controller) {
      if (index < frames.length) {
        controller.enqueue(encoder.encode(frames[index]));
        index += 1;
      } else {
        controller.close();
      }
    },
  });
  return new Response(stream, { status: 200, headers: { "content-type": "text/event-stream" } });
}

function makeJsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

const completedResponse: ChatResponse = {
  workflow_id: "wf-1",
  session_id: "s-1",
  status: "completed",
  answer: "ComfortPro Shift Support ($89.99) has 7 unit(s) available for pickup today at Scout Demo Store - Plymouth.",
  products: [
    {
      product_id: "FTW-004",
      name: "ComfortPro Shift Support",
      brand: "ComfortPro",
      category: "Footwear",
      subcategory: "Work",
      price: 89.99,
      rating: 4.7,
      review_count: 401,
      active: true,
    },
  ],
  fulfillment_options: [
    {
      product_id: "FTW-004",
      channel: "nearby_store",
      store_id: "STR-002",
      store_name: "Scout Demo Store - Plymouth",
      sellable_quantity: 7,
      distance_miles: 4.28,
      substitute_for: null,
    },
  ],
  activity_events: [],
  errors: [],
};

describe("Scout shopping interface", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders the page (scenario 1)", () => {
    render(<App />);
    expect(screen.getByRole("heading", { name: "Scout" })).toBeInTheDocument();
    expect(screen.getByLabelText(/what are you looking for/i)).toBeInTheDocument();
  });

  it("accepts typed text in the search input (scenario 2)", async () => {
    const user = userEvent.setup();
    render(<App />);
    const input = screen.getByLabelText(/what are you looking for/i);
    await user.type(input, "running shoes");
    expect(input).toHaveValue("running shoes");
  });

  it("blocks empty and whitespace-only submission (scenario 3)", async () => {
    const user = userEvent.setup();
    render(<App />);
    const input = screen.getByLabelText(/what are you looking for/i);
    const button = screen.getByRole("button", { name: "Search" });

    expect(button).toBeDisabled();

    await user.type(input, "   ");
    expect(button).toBeDisabled();
    await user.click(button);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("sends the request correctly (scenario 4)", async () => {
    const user = userEvent.setup();
    fetchMock.mockResolvedValueOnce(
      makeStreamResponse([
        finalResponseFrame(1, completedResponse),
        streamClosedFrame(2),
      ])
    );

    render(<App />);
    await user.type(screen.getByLabelText(/what are you looking for/i), ACCEPTANCE_QUERY);
    await user.click(screen.getByRole("button", { name: "Search" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/chat/stream");
    expect(init.method).toBe("POST");
    const body = JSON.parse(init.body as string);
    expect(body.message).toBe(ACCEPTANCE_QUERY);
    expect(typeof body.session_id).toBe("string");
    expect(body.session_id.length).toBeGreaterThan(0);

    await screen.findByText("ComfortPro Shift Support");
  });

  it("shows a loading state while a request is active (scenario 5)", async () => {
    const user = userEvent.setup();
    fetchMock.mockImplementationOnce(() => new Promise(() => {}));

    render(<App />);
    await user.type(screen.getByLabelText(/what are you looking for/i), ACCEPTANCE_QUERY);
    await user.click(screen.getByRole("button", { name: "Search" }));

    expect(await screen.findByText(/scout is working on your request/i)).toBeInTheDocument();
  });

  it("displays streaming activity events in the order they arrive (scenario 6)", async () => {
    const user = userEvent.setup();
    fetchMock.mockResolvedValueOnce(
      makeStreamResponse([
        sseFrame("workflow_started", 1, {
          event_id: 1,
          event_type: "workflow_started",
          workflow_id: "wf-1",
          session_id: "s-1",
          label: "Understanding your request",
          data: {},
          timestamp: "2026-01-01T00:00:00Z",
        }),
        sseFrame("tool_started", 2, {
          event_id: 2,
          event_type: "tool_started",
          workflow_id: "wf-1",
          session_id: "s-1",
          label: "Searching the product catalog",
          data: {},
          timestamp: "2026-01-01T00:00:01Z",
        }),
        sseFrame("tool_started", 3, {
          event_id: 3,
          event_type: "tool_started",
          workflow_id: "wf-1",
          session_id: "s-1",
          label: "Checking Maple Grove inventory",
          data: {},
          timestamp: "2026-01-01T00:00:02Z",
        }),
        finalResponseFrame(4, completedResponse),
        streamClosedFrame(5),
      ])
    );

    render(<App />);
    await user.type(screen.getByLabelText(/what are you looking for/i), ACCEPTANCE_QUERY);
    await user.click(screen.getByRole("button", { name: "Search" }));

    await screen.findByText("ComfortPro Shift Support");

    const items = screen.getAllByText(
      /^(Understanding your request|Searching the product catalog|Checking Maple Grove inventory)$/
    );
    const labels = items.map((item) => item.textContent);
    expect(labels).toEqual([
      "Understanding your request",
      "Searching the product catalog",
      "Checking Maple Grove inventory",
    ]);
  });

  it("shows the clarification state (scenario 11)", async () => {
    const user = userEvent.setup();
    const clarificationResponse: ChatResponse = {
      ...completedResponse,
      status: "clarification_required",
      answer: "Could you tell me what product you're looking for, your budget, and which store or area you'd like to check?",
      products: [],
      fulfillment_options: [],
    };
    fetchMock.mockResolvedValueOnce(
      makeStreamResponse([finalResponseFrame(1, clarificationResponse), streamClosedFrame(2)])
    );

    render(<App />);
    await user.type(screen.getByLabelText(/what are you looking for/i), "hi there");
    await user.click(screen.getByRole("button", { name: "Search" }));

    expect(await screen.findByText(/scout needs a bit more information/i)).toBeInTheDocument();
    expect(screen.getByText(/could you tell me what product/i)).toBeInTheDocument();
  });

  it("shows the no-results state (scenario 12)", async () => {
    const user = userEvent.setup();
    const noResultsResponse: ChatResponse = {
      ...completedResponse,
      status: "no_results",
      answer: "I couldn't find a product matching your request that's available for pickup today within your budget and location.",
      products: [],
      fulfillment_options: [],
    };
    fetchMock.mockResolvedValueOnce(
      makeStreamResponse([finalResponseFrame(1, noResultsResponse), streamClosedFrame(2)])
    );

    render(<App />);
    await user.type(screen.getByLabelText(/what are you looking for/i), "Find work shoes under $1.");
    await user.click(screen.getByRole("button", { name: "Search" }));

    expect(await screen.findByText("No matching products found")).toBeInTheDocument();
    expect(screen.getByText(/couldn't find a product/i)).toBeInTheDocument();
  });

  it("displays a safe error and hides raw internal errors (scenarios 13 and 14)", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("NetworkError when attempting to fetch resource: secret-internal-detail"));
    fetchMock.mockRejectedValueOnce(new TypeError("NetworkError when attempting to fetch resource: secret-internal-detail"));

    const user = userEvent.setup();
    render(<App />);
    await user.type(screen.getByLabelText(/what are you looking for/i), ACCEPTANCE_QUERY);
    await user.click(screen.getByRole("button", { name: "Search" }));

    // Both /chat/stream and its /chat fallback reject at the network
    // level, so the safe message surfaced is chatClient's own
    // connection-failure sentence (ChatRequestError), not the generic
    // "could not process this request" fallback that guards a
    // stream that closes without ever explaining itself.
    expect(await screen.findByText(/something went wrong/i)).toBeInTheDocument();
    expect(
      screen.getByText("Scout could not be reached. Please check your connection and try again.")
    ).toBeInTheDocument();
    expect(screen.queryByText(/secret-internal-detail/)).not.toBeInTheDocument();
    expect(screen.queryByText(/TypeError/)).not.toBeInTheDocument();
    expect(screen.queryByText(/NetworkError/)).not.toBeInTheDocument();
  });

  it("disables submission while a request is active (scenario 15)", async () => {
    const user = userEvent.setup();
    fetchMock.mockImplementationOnce(() => new Promise(() => {}));

    render(<App />);
    await user.type(screen.getByLabelText(/what are you looking for/i), ACCEPTANCE_QUERY);
    const button = screen.getByRole("button", { name: "Search" });
    await user.click(button);

    expect(await screen.findByRole("button", { name: "Searching..." })).toBeDisabled();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("supports cancellation (scenario 16)", async () => {
    const user = userEvent.setup();
    fetchMock.mockImplementationOnce((_url: string, init: RequestInit) => {
      return new Promise((_resolve, reject) => {
        init.signal?.addEventListener("abort", () => {
          reject(new DOMException("The user aborted a request.", "AbortError"));
        });
      });
    });

    render(<App />);
    await user.type(screen.getByLabelText(/what are you looking for/i), ACCEPTANCE_QUERY);
    await user.click(screen.getByRole("button", { name: "Search" }));

    const cancelButton = await screen.findByRole("button", { name: "Cancel" });
    await user.click(cancelButton);

    expect(await screen.findByText("Search canceled.")).toBeInTheDocument();
  });

  it("falls back to /chat when streaming fails safely (scenario 17)", async () => {
    const user = userEvent.setup();
    fetchMock.mockResolvedValueOnce(makeJsonResponse({ error: "Not found" }, 404));
    fetchMock.mockResolvedValueOnce(makeJsonResponse(completedResponse));

    render(<App />);
    await user.type(screen.getByLabelText(/what are you looking for/i), ACCEPTANCE_QUERY);
    await user.click(screen.getByRole("button", { name: "Search" }));

    await screen.findByText("ComfortPro Shift Support");
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect((fetchMock.mock.calls[1] as [string, RequestInit])[0]).toContain("/chat");
    expect(screen.getByText(/live updates weren.t available/i)).toBeInTheDocument();
  });

  it("supports keyboard submission via Enter (scenario 18)", async () => {
    const user = userEvent.setup();
    fetchMock.mockResolvedValueOnce(
      makeStreamResponse([finalResponseFrame(1, completedResponse), streamClosedFrame(2)])
    );

    render(<App />);
    const input = screen.getByLabelText(/what are you looking for/i);
    await user.type(input, ACCEPTANCE_QUERY);
    await user.keyboard("{Enter}");

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    await screen.findByText("ComfortPro Shift Support");
  });

  it("exposes accessibility labels and live regions (scenario 19)", async () => {
    const user = userEvent.setup();
    fetchMock.mockResolvedValueOnce(
      makeStreamResponse([finalResponseFrame(1, completedResponse), streamClosedFrame(2)])
    );

    const { container } = render(<App />);
    expect(screen.getByLabelText(/what are you looking for/i)).toBeInTheDocument();
    expect(container.querySelector('[aria-live="polite"]')).not.toBeNull();

    await user.type(screen.getByLabelText(/what are you looking for/i), ACCEPTANCE_QUERY);
    await user.click(screen.getByRole("button", { name: "Search" }));

    await screen.findByText("ComfortPro Shift Support");
    expect(screen.getByAltText("ComfortPro Shift Support product photo")).toBeInTheDocument();
  });
});
