import type { OrderStatusView } from "../types/chat";
import { ClockIcon, MapPinIcon, MessageIcon, StoreIcon } from "./Icons";

export interface OrderSupportPanelProps {
  order: OrderStatusView;
  onNeedHelp: () => void;
  onContinueShopping: () => void;
}

function formatDateTime(value: string | null): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function shortStoreName(storeName: string | null): string {
  if (!storeName) return "Scout store";
  return storeName.replace(/^Scout Demo Store\s*-\s*/i, "");
}

export function OrderSupportPanel({ order, onNeedHelp, onContinueShopping }: OrderSupportPanelProps): JSX.Element {
  const fulfillment = order.fulfillment;
  const pickup = fulfillment.fulfillment_type === "pickup";
  const estimate = pickup
    ? formatDateTime(fulfillment.estimated_ready_at)
    : formatDateTime(fulfillment.estimated_delivery_at);
  const destination = pickup
    ? fulfillment.store_name ?? "Scout store"
    : fulfillment.shipping_address
      ? `${fulfillment.shipping_address.city}, ${fulfillment.shipping_address.state}`
      : "Delivery destination";

  return (
    <>
      <section className="order-side-card" aria-labelledby="order-side-summary-title">
        <div className="order-side-card__heading">
          <div>
            <p>Order fulfillment</p>
            <h2 id="order-side-summary-title">{pickup ? "Pickup summary" : "Delivery summary"}</h2>
            <strong className="order-side-card__destination">{destination}</strong>
          </div>
          <span className="order-side-card__status">{fulfillment.status.replace(/_/g, " ")}</span>
        </div>

        <div className="fulfillment-map order-side-map" aria-label="Stylized order fulfillment preview">
          <span className="fulfillment-map__grid" aria-hidden="true" />
          <span className="fulfillment-map__pin fulfillment-map__pin--origin"><MapPinIcon /> Order</span>
          <span className="fulfillment-map__pin fulfillment-map__pin--destination">
            {pickup ? <StoreIcon /> : <MapPinIcon />} {pickup ? shortStoreName(fulfillment.store_name) : "Destination"}
          </span>
          <span className="fulfillment-map__route" aria-hidden="true" />
        </div>

        {estimate && (
          <div className="order-side-card__estimate">
            <ClockIcon />
            <div><span>{pickup ? "Estimated ready" : "Estimated arrival"}</span><strong>{estimate}</strong></div>
          </div>
        )}

        {fulfillment.shipping_address && (
          <p className="order-side-card__address">
            {fulfillment.shipping_address.line1}<br />
            {fulfillment.shipping_address.city}, {fulfillment.shipping_address.state} {fulfillment.shipping_address.postal_code}
          </p>
        )}

        <p className="order-side-card__note">
          {fulfillment.estimate_source === "configured_policy"
            ? "Prototype estimate based on Scout's configured policy."
            : "Estimate based on persisted fulfillment data."}
        </p>
      </section>

      <section className="order-help-card" aria-labelledby="order-help-title">
        <span className="order-help-card__icon" aria-hidden="true"><MessageIcon /></span>
        <div>
          <h2 id="order-help-title">Need help with this order?</h2>
          <p>Ask Scout about payment, pickup, delivery, tracking, or eligibility.</p>
        </div>
        <button type="button" onClick={onNeedHelp}>Get order help</button>
      </section>

      <button type="button" className="order-continue-button" onClick={onContinueShopping}>Continue shopping</button>
    </>
  );
}
