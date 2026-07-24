import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ExternalOfferSummary } from "../types/chat";
import { ExternalOfferCard } from "./ExternalOfferCard";

const offer: ExternalOfferSummary = {
  offer_id: "EXT-OFF-001",
  merchant_name: "Northstar Marketplace Demo",
  external_product_id: "NS-WORK-101",
  product_name: "ShiftEase All-Day Work Shoe",
  brand: "ShiftEase",
  category: "Footwear",
  description: "Supportive work shoe for long standing shifts.",
  price: 79.99,
  currency: "USD",
  rating: 4.6,
  review_count: 318,
  availability_status: "in_stock",
  image_url: null,
  match_type: "similar",
  match_label: "Similar external alternative",
  match_reason: "Matches requested comfort and standing needs.",
  source_product_id: null,
  matched_identifier_type: null,
  observed_at: "2026-07-23T20:00:00Z",
  same_product_verified: false,
  affiliate_disclosure: "Demo external offer. Scout may earn a commission in production.",
  evidence_ids: ["external-offer-EXT-OFF-001"],
  relevance_score: 0.8,
  disclosure: "Demo external offer. Scout may earn a commission in production.",
};

describe("ExternalOfferCard", () => {
  it("labels a similar external offer and provides only a retailer link", () => {
    render(<ExternalOfferCard offer={offer} sessionId="session-1" workflowId="workflow-1" />);

    expect(screen.getByText("External alternative")).toBeInTheDocument();
    expect(screen.getByText("Similar external alternative")).toBeInTheDocument();
    expect(screen.getByText("Referral link · external checkout")).toBeInTheDocument();
    expect(screen.getByText("Availability: in stock")).toBeInTheDocument();
    expect(screen.getByText(/Checked at/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /add to cart/i })).not.toBeInTheDocument();

    const link = screen.getByRole("link", { name: "Open retailer" });
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer sponsored");
    expect(link.getAttribute("href")).toContain("/affiliate/click/EXT-OFF-001");
    expect(link.getAttribute("href")).toContain("match_type=similar");
  });
});
