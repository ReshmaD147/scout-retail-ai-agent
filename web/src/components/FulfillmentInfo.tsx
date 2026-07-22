import type { FulfillmentOption } from "../types/chat";

export interface FulfillmentInfoProps {
  options: FulfillmentOption[];
}

/**
 * Renders one product's verified fulfillment options, clearly
 * distinguishing where each one comes from - never blurring a
 * selected-store result together with a nearby-store or substitute
 * one (CLAUDE.md's Inventory Agent responsibilities; Step 14's "do
 * not present store-network inventory as warehouse inventory").
 *
 * Only real `FulfillmentOption` fields are ever shown (`channel`,
 * `store_name`/`store_id`, `sellable_quantity`, `distance_miles`,
 * `substitute_for`). A pickup estimate, a configured delivery window,
 * and a restock date are all things Scout's MCP tools *can* compute
 * (scout/mcp/inventory_tools.py, Step 7) but the current workflow
 * (Step 10) does not attach any of them to `FulfillmentOption` - so
 * none are rendered here. Guessing a delivery date or pickup time the
 * backend never sent would violate "omit unsupported fields instead
 * of guessing," so an honest, fixed sentence is shown instead.
 */
export function FulfillmentInfo({ options }: FulfillmentInfoProps): JSX.Element {
  if (options.length === 0) {
    return <p className="fulfillment-info__unavailable">Pickup time unavailable</p>;
  }

  return (
    <ul className="fulfillment-info">
      {options.map((option, index) => (
        <li key={`${option.channel}-${option.store_id ?? "unknown"}-${index}`} className="fulfillment-info__item">
          {describeOption(option)}
        </li>
      ))}
    </ul>
  );
}

function describeOption(option: FulfillmentOption): string {
  const quantity = option.sellable_quantity;
  const inStock = quantity > 0;

  if (option.channel === "selected_store") {
    return inStock
      ? `Available for pickup today at ${option.store_name ?? "your selected store"} (${quantity} in stock).`
      : `Not currently available for pickup at ${option.store_name ?? "your selected store"}.`;
  }

  if (option.channel === "nearby_store") {
    const distance = option.distance_miles !== null ? `, ${option.distance_miles} miles away` : "";
    return inStock
      ? `Available at a nearby store, ${option.store_name ?? "a nearby Scout store"}${distance} (${quantity} in stock).`
      : `Checked a nearby store (${option.store_name ?? "unnamed"}) - not currently in stock.`;
  }

  if (option.channel === "substitute") {
    return `Offered as a substitute for ${option.substitute_for ?? "the original item"}, with ${quantity} available for pickup today at ${option.store_name ?? "your selected store"}.`;
  }

  return `Available via ${option.channel} (${quantity} in stock).`;
}
