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
  const facts: string[] = [];

  if (response.products.length > 0) {
    facts.push(`${response.products.length} product ${response.products.length === 1 ? "identity was" : "identities were"} returned by the verified catalog response.`);
    facts.push("Displayed prices come from structured product records.");
  }

  const pickupOptions = response.fulfillment_options.filter((option) =>
    (option.channel === "selected_store" || option.channel === "nearby_store") && option.sellable_quantity > 0
  );
  if (pickupOptions.some((option) => option.channel === "selected_store")) {
    facts.push("Selected-store pickup inventory was returned as structured fulfillment data.");
  }
  if (pickupOptions.some((option) => option.channel === "nearby_store")) {
    facts.push("Nearby pickup inventory was returned as structured fulfillment data.");
  }
  if (response.fulfillment_options.some((option) => option.channel === "delivery" && option.sellable_quantity > 0)) {
    facts.push("Delivery availability was returned as structured fulfillment data.");
  }
  if (response.external_offers.length > 0) {
    facts.push("External offers are labeled separately from Scout catalog products.");
  }

  return facts;
}
