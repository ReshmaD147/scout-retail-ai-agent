import type { ChatResponse } from "../types/chat";

export interface VerifiedFactsProps {
  response: ChatResponse;
}

export function VerifiedFacts({ response }: VerifiedFactsProps): JSX.Element | null {
  const facts = buildVerifiedFacts(response);
  if (facts.length === 0) return null;

  return (
    <details className="verified-facts">
      <summary>What Scout verified</summary>
      <ul>
        {facts.map((fact) => <li key={fact}>{fact}</li>)}
      </ul>
    </details>
  );
}

function buildVerifiedFacts(response: ChatResponse): string[] {
  const claims = response.approved_claims ?? [];
  return claims.map(labelForClaim).filter((label): label is string => Boolean(label));
}

function labelForClaim(claim: Record<string, unknown>): string | null {
  switch (claim.type) {
    case "product_identity":
      return "Product identity was verified.";
    case "product_price":
      return "Current product price was verified.";
    case "budget_compliance":
      return "Price is within your budget.";
    case "store_inventory":
      return "Selected-store inventory was checked.";
    case "nearby_inventory":
      return "Nearby-store inventory was checked.";
    case "pickup_availability":
      return "Pickup availability was confirmed.";
    case "delivery_availability":
      return "Delivery availability was confirmed.";
    case "active_promotion":
      return "Promotion is active.";
    default:
      return null;
  }
}
