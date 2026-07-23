import type { StoreSummary } from "../types/cart";
import type { FulfillmentOption, RequestedLocation } from "../types/chat";
import { FulfillmentMap } from "./FulfillmentMap";

export interface FulfillmentSummaryProps {
  options: FulfillmentOption[];
  stores: StoreSummary[];
  requestedLocation: RequestedLocation | null;
}

export function FulfillmentSummary({ options, stores, requestedLocation }: FulfillmentSummaryProps): JSX.Element {
  const pickupOptions = deduplicateStoreOptions(
    options.filter((option) => option.channel === "selected_store" || option.channel === "nearby_store")
  );
  const availablePickup = [...pickupOptions]
    .filter((option) => option.sellable_quantity > 0)
    .sort((left, right) => (left.distance_miles ?? Number.POSITIVE_INFINITY) - (right.distance_miles ?? Number.POSITIVE_INFINITY))[0] ?? null;
  const selectedStore = pickupOptions.find((option) => option.channel === "selected_store") ?? null;
  const nearbyStores = pickupOptions.filter((option) => option.channel === "nearby_store");
  const delivery = options.find((option) => option.channel === "delivery" && option.sellable_quantity > 0) ?? null;

  return (
    <section className="fulfillment-summary" aria-labelledby="fulfillment-summary-title">
      <h2 id="fulfillment-summary-title">Fulfillment summary</h2>

      {pickupOptions.length > 0 ? (
        <FulfillmentMap options={pickupOptions} stores={stores} requestedLocation={requestedLocation} />
      ) : (
        <div className="fulfillment-map-placeholder" role="status">
          Search for a product to view verified pickup and delivery options.
        </div>
      )}

      {options.length === 0 ? (
        <p className="fulfillment-summary__empty">Search for a product to see verified store and delivery options.</p>
      ) : (
        <>
          {availablePickup ? (
            <div className="fulfillment-summary__primary">
              <div className="fulfillment-summary__section-heading">
                <h3>Best verified pickup option</h3>
                <span className="availability-badge availability-badge--success">Available</span>
              </div>
              <strong>{availablePickup.store_name ?? "Scout store"}</strong>
              <p>{distanceText(availablePickup.distance_miles)}</p>
              <p className="fulfillment-summary__success">{availablePickup.sellable_quantity} in stock · Pickup availability verified</p>
            </div>
          ) : delivery ? (
            <div className="fulfillment-summary__primary">
              <div className="fulfillment-summary__section-heading">
                <h3>Store-network delivery</h3>
                <span className="availability-badge availability-badge--success">Available</span>
              </div>
              <strong>{delivery.sellable_quantity} available across the Scout store network</strong>
              <p>{deliveryWindow(delivery)}</p>
            </div>
          ) : (
            <div className="fulfillment-summary__primary">
              <div className="fulfillment-summary__section-heading">
                <h3>Pickup status</h3>
                <span className="availability-badge availability-badge--danger">Unavailable</span>
              </div>
              <p>No verified pickup option was returned.</p>
            </div>
          )}

          {(selectedStore || nearbyStores.length > 0) && (
            <div className="fulfillment-summary__stores">
              <h3>Store checks</h3>
              {selectedStore && <StoreRow option={selectedStore} label="Selected store" />}
              {nearbyStores.map((option) => <StoreRow key={option.store_id ?? `${option.product_id}-${option.store_name}`} option={option} label="Nearby store" />)}
            </div>
          )}

          {delivery && availablePickup && (
            <div className="fulfillment-summary__delivery">
              <h3>Delivery option</h3>
              <p>{delivery.sellable_quantity} available across the Scout store network.</p>
              <p>{deliveryWindow(delivery)}</p>
            </div>
          )}
        </>
      )}
    </section>
  );
}

function deduplicateStoreOptions(options: FulfillmentOption[]): FulfillmentOption[] {
  const byStore = new Map<string, FulfillmentOption>();
  for (const option of options) {
    const key = option.store_id ?? `${option.channel}-${option.store_name}`;
    const existing = byStore.get(key);
    if (!existing || option.channel === "selected_store" || option.sellable_quantity > existing.sellable_quantity) {
      byStore.set(key, option);
    }
  }
  return [...byStore.values()];
}

function StoreRow({ option, label }: { option: FulfillmentOption; label: string }): JSX.Element {
  const available = option.sellable_quantity > 0;
  return (
    <div className="fulfillment-store-row">
      <div>
        <span>{label}</span>
        <strong>{option.store_name ?? "Scout store"}</strong>
        <small>{distanceText(option.distance_miles)}</small>
      </div>
      <div className={available ? "fulfillment-store-row__available" : "fulfillment-store-row__unavailable"}>
        {available ? `${option.sellable_quantity} in stock` : "Out of stock"}
      </div>
    </div>
  );
}

function distanceText(distance: number | null): string {
  return distance === null ? "Distance unavailable" : `${distance.toFixed(2)} miles away`;
}

function deliveryWindow(option: FulfillmentOption): string {
  if (option.delivery_min_days === null || option.delivery_max_days === null) {
    return "Configured delivery estimate unavailable.";
  }
  return `Configured prototype estimate: ${option.delivery_min_days}-${option.delivery_max_days} days. Not a carrier guarantee.`;
}
