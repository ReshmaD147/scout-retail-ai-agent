import type { FulfillmentOption } from "../types/chat";

export interface FulfillmentInfoProps {
  options: FulfillmentOption[];
}

export function FulfillmentInfo({ options }: FulfillmentInfoProps): JSX.Element {
  if (options.length === 0) return <p className="fulfillment-info__unavailable">Pickup time unavailable</p>;

  return (
    <ul className="fulfillment-info">
      {options.map((option, index) => (
        <li key={`${option.channel}-${option.store_id ?? "unknown"}-${index}`} className={`fulfillment-info__item${option.sellable_quantity > 0 ? " fulfillment-info__item--available" : " fulfillment-info__item--unavailable"}`}>
          <span className="fulfillment-info__dot" aria-hidden="true" />
          <span>{describeOption(option)}</span>
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

  if (option.channel === "delivery") {
    const window =
      option.delivery_min_days !== null && option.delivery_max_days !== null
        ? ` Standard prototype delivery is estimated at ${option.delivery_min_days}-${option.delivery_max_days} days.`
        : "";
    return `Available across the Scout store network (${quantity} in stock).${window}`;
  }

  if (option.channel === "substitute") {
    return `Offered as a substitute for ${option.substitute_for ?? "the original item"}, with ${quantity} available for pickup today at ${option.store_name ?? "your selected store"}.`;
  }

  return `Available via ${option.channel} (${quantity} in stock).`;
}
