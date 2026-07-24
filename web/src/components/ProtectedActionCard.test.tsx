import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ProtectedActionCard } from "./ProtectedActionCard";

const action = {
  confirmation_id: "conf-1",
  action_type: "cancel_order",
  resource_type: "order",
  resource_id: "ORD-1005",
  proposal_summary: "Cancel order ORD-1005 before fulfillment completes",
  customer_effects: ["The order is still processing."],
  financial_effects: ["Order total on record: USD 80.99."],
  eligibility_status: "eligible",
  eligibility_reason_code: "not_fulfilled",
  expires_at: new Date(Date.now() + 60_000).toISOString(),
};

describe("ProtectedActionCard", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders the explicit confirmation details", () => {
    render(<ProtectedActionCard action={action} sessionId="sess-1" />);

    expect(screen.getByText("Confirmation required")).toBeInTheDocument();
    expect(screen.getByText("Cancel order ORD-1005 before fulfillment completes")).toBeInTheDocument();
    expect(screen.getByText("ORD-1005")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /confirm cancel order/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /reject/i })).toBeInTheDocument();
  });

  it("posts one approval and shows the verified backend result", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({
        confirmation_id: "conf-1",
        action_type: "cancel_order",
        execution_status: "verified",
        resource_id: "ORD-1005",
        result_state: "canceled",
        request_id: null,
        verified_at: new Date().toISOString(),
        evidence_ids: [],
        message: "Order ORD-1005 was canceled successfully.",
      }),
    } as Response);
    render(<ProtectedActionCard action={action} sessionId="sess-1" />);

    const button = screen.getByRole("button", { name: /confirm cancel order/i });
    fireEvent.click(button);
    fireEvent.click(button);

    await waitFor(() => expect(screen.getByText("Order ORD-1005 was canceled successfully.")).toBeInTheDocument());
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
