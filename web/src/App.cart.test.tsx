import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import type { ChatResponse } from "./types/chat";
import type { CartView, StoreSummary } from "./types/cart";

/**
 * Integration tests for Step 15's cart UI, layered on top of App.test.tsx's
 * existing chat-flow tests. `global.fetch` is stubbed per test exactly like
 * App.test.tsx does; these tests additionally control what
 * GET /cart/{session_id}, GET /stores, and POST /cart/items return, since
 * `useCart` fetches both on mount regardless of what the chat flow does.
 *
 * Covers scenario 21 (React cart count updates) and scenario 22 (React
 * quantity controls work) from the Step 15 prompt's 23 test scenarios.
 */

const ACCEPTANCE_QUERY = "Find comfortable work shoes under $100 that I can pick up today near Maple Grove.";

function sseFrame(eventType: string, id: number, data: unknown): string {
  return `event: ${eventType}\nid: ${id}\ndata: ${JSON.stringify(data)}\n\n`;
}

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

const emptyCart: CartView = {
  cart_id: null,
  session_id: "s-1",
  items: [],
  subtotal: 0,
  fulfillment_type: null,
  store_id: null,
  store_name: null,
  status: "active",
  validation_status: "valid",
  warnings: [],
  updated_at: null,
};

const oneItemCart: CartView = {
  cart_id: "CART-1",
  session_id: "s-1",
  items: [
    {
      cart_item_id: "CTI-1",
      product_id: "FTW-004",
      product_name: "ComfortPro Shift Support",
      brand: "ComfortPro",
      quantity: 1,
      unit_price: 89.99,
      unit_price_snapshot: 89.99,
      line_total: 89.99,
      promotion_id: null,
      promotion_label: null,
      active: true,
      warnings: [],
    },
  ],
  subtotal: 89.99,
  fulfillment_type: null,
  store_id: null,
  store_name: null,
  status: "active",
  validation_status: "valid",
  warnings: [],
  updated_at: "2026-01-01T00:00:00Z",
};

const stores: StoreSummary[] = [];

/** Routes each fetch call to the right canned response by URL/method,
 * since App now issues several concurrent requests on mount (the cart
 * fetch and the store list) in addition to whatever a test triggers. */
function routeFetch(handlers: Array<{ match: (url: string, init?: RequestInit) => boolean; respond: () => Response }>) {
  return vi.fn((url: string, init?: RequestInit) => {
    const handler = handlers.find((candidate) => candidate.match(url, init));
    if (!handler) {
      throw new Error(`Unhandled fetch: ${init?.method ?? "GET"} ${url}`);
    }
    return Promise.resolve(handler.respond());
  });
}

describe("Scout cart UI", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows a zero cart count on load, then updates after adding a product (scenario 21)", async () => {
    fetchMock.mockImplementation(
      routeFetch([
        { match: (url, init) => url.includes("/cart/items") && init?.method === "POST", respond: () => makeJsonResponse(oneItemCart) },
        { match: (url, init) => url.includes("/cart/") && !init?.method, respond: () => makeJsonResponse(emptyCart) },
        { match: (url) => url.includes("/stores"), respond: () => makeJsonResponse(stores) },
        { match: (url) => url.includes("/chat/stream"), respond: () => makeStreamResponse([finalResponseFrame(1, completedResponse), streamClosedFrame(2)]) },
      ])
    );

    const user = userEvent.setup();
    render(<App />);

    expect(await screen.findByLabelText("0 items in cart")).toBeInTheDocument();

    await user.type(screen.getByLabelText(/what are you looking for/i), ACCEPTANCE_QUERY);
    await user.click(screen.getByRole("button", { name: "Search" }));

    const addButton = await screen.findByRole("button", { name: "Add to cart" });
    await user.click(addButton);

    await waitFor(() => expect(screen.getByLabelText("1 item in cart")).toBeInTheDocument());

    const addCall = fetchMock.mock.calls.find(
      ([url, init]) => (url as string).includes("/cart/items") && (init as RequestInit)?.method === "POST"
    );
    expect(addCall).toBeDefined();
    const body = JSON.parse((addCall![1] as RequestInit).body as string);
    expect(body.product_id).toBe("FTW-004");
    expect(body.quantity).toBe(1);
  });

  it("updates the displayed quantity and subtotal when a quantity control is used (scenario 22)", async () => {
    const updatedCart: CartView = {
      ...oneItemCart,
      items: [{ ...oneItemCart.items[0], quantity: 2, line_total: 179.98 }],
      subtotal: 179.98,
    };

    fetchMock.mockImplementation(
      routeFetch([
        { match: (url, init) => url.includes("/cart/items/") && init?.method === "PATCH", respond: () => makeJsonResponse(updatedCart) },
        { match: (url, init) => /\/cart\/[^/]+$/.test(url) && !init?.method, respond: () => makeJsonResponse(oneItemCart) },
        { match: (url) => url.includes("/stores"), respond: () => makeJsonResponse(stores) },
      ])
    );

    const user = userEvent.setup();
    render(<App />);

    await waitFor(() => expect(screen.getByLabelText("1 item in cart")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: /cart/i }));

    const drawer = await screen.findByRole("dialog", { name: "Shopping cart" });
    await user.click(within(drawer).getByLabelText(/increase quantity of comfortpro/i));

    await waitFor(() =>
      expect(within(within(drawer).getByLabelText("Cart subtotal")).getByText("$179.98")).toBeInTheDocument()
    );
    expect(screen.getByLabelText("2 items in cart")).toBeInTheDocument();

    const patchCall = fetchMock.mock.calls.find(
      ([url, init]) => (url as string).includes("/cart/items/") && (init as RequestInit)?.method === "PATCH"
    );
    expect(patchCall).toBeDefined();
    const body = JSON.parse((patchCall![1] as RequestInit).body as string);
    expect(body.quantity).toBe(2);
  });
});
