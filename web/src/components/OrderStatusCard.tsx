import { useState } from "react";
import type { OrderItemStatus, OrderStatusView } from "../types/chat";
import {
  CheckIcon,
  ClockIcon,
  CopyIcon,
  CreditCardIcon,
  MapPinIcon,
  MinusIcon,
  PackageIcon,
  StoreIcon,
} from "./Icons";
import { PRODUCT_IMAGE_PLACEHOLDER, getProductImageSrc } from "./ProductCard";

export interface OrderStatusCardProps {
  order: OrderStatusView;
  onNeedHelp?: () => void;
  onContinueShopping?: () => void;
}

interface ProgressStep {
  label: string;
  state: "completed" | "active" | "pending";
}

function formatMoney(amount: number, currency: string): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency }).format(amount);
}

function formatDateTime(value: string | null): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function formatPlacedDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

function humanize(value: string): string {
  return value.replace(/_/g, " ").replace(/\b\w/g, (character) => character.toUpperCase());
}

function shortOrderId(orderId: string): string {
  return orderId.replace(/-/g, "").slice(-8).toUpperCase();
}

function headline(orderStatus: string): string {
  const normalized = orderStatus.toLowerCase();
  if (normalized === "confirmed") return "Your order is confirmed";
  if (normalized === "canceled" || normalized === "cancelled") return "Your order was canceled";
  if (normalized === "completed") return "Your order is complete";
  return `Your order is ${humanize(orderStatus).toLowerCase()}`;
}

function progressSteps(order: OrderStatusView): ProgressStep[] {
  const isPickup = order.fulfillment.fulfillment_type === "pickup";
  const labels = isPickup
    ? ["Order confirmed", "Processing", "Ready for pickup", "Picked up"]
    : ["Order confirmed", "Processing", "Shipped", "Delivered"];
  const status = order.fulfillment.status.toLowerCase();

  const index = isPickup
    ? status.includes("picked") || status === "completed"
      ? 3
      : status.includes("ready")
        ? 2
        : status.includes("process")
          ? 1
          : 0
    : status.includes("deliver") || status === "completed"
      ? 3
      : status.includes("ship")
        ? 2
        : status.includes("process")
          ? 1
          : 0;

  const isTerminal = index === labels.length - 1;
  return labels.map((label, stepIndex) => ({
    label,
    state: stepIndex < index || (isTerminal && stepIndex === index)
      ? "completed"
      : stepIndex === index
        ? "active"
        : "pending",
  }));
}

function paymentLabel(status: string): string {
  return status.toLowerCase() === "succeeded" ? "Paid" : humanize(status);
}

function EligibilityRow({ label, eligible, reason }: { label: string; eligible: boolean; reason: string }): JSX.Element {
  return (
    <div className={`order-eligibility-row order-eligibility-row--${eligible ? "eligible" : "unavailable"}`}>
      <span className="order-eligibility-row__icon" aria-hidden="true">
        {eligible ? <CheckIcon /> : <MinusIcon />}
      </span>
      <div className="order-eligibility-row__content">
        <strong>{label} {eligible ? "eligible" : "not available yet"}</strong>
        <p>{reason}</p>
      </div>
    </div>
  );
}

function OrderItemRow({ item, currency }: { item: OrderItemStatus; currency: string }): JSX.Element {
  const [imageAttempt, setImageAttempt] = useState(0);
  const imageSource = getProductImageSrc(item.product_id, imageAttempt);

  return (
    <li className="order-item-row">
      <div className="order-item-row__image-wrap">
        <img
          src={imageSource}
          onError={() => setImageAttempt((current) => current + 1)}
          alt={`${item.product_name} product photo`}
          className="order-item-row__image"
          width={92}
          height={72}
        />
      </div>
      <div className="order-item-row__details">
        <strong>{item.product_name}</strong>
        <span>{item.brand}</span>
        <small>Quantity: {item.quantity} · {formatMoney(item.charged_unit_price, currency)} each</small>
      </div>
      <strong className="order-item-row__total">{formatMoney(item.line_total, currency)}</strong>
    </li>
  );
}

/** Read-only Step 17 order status. No protected action is executed here. */
export function OrderStatusCard({ order, onNeedHelp, onContinueShopping }: OrderStatusCardProps): JSX.Element {
  const [copyState, setCopyState] = useState<"idle" | "copied" | "failed">("idle");
  const fulfillment = order.fulfillment;
  const estimate = fulfillment.fulfillment_type === "pickup"
    ? formatDateTime(fulfillment.estimated_ready_at)
    : formatDateTime(fulfillment.estimated_delivery_at);
  const steps = progressSteps(order);
  const pickup = fulfillment.fulfillment_type === "pickup";

  const copyOrderId = async (): Promise<void> => {
    try {
      if (!navigator.clipboard?.writeText) throw new Error("Clipboard unavailable");
      await navigator.clipboard.writeText(order.order_id);
      setCopyState("copied");
    } catch {
      setCopyState("failed");
    }
  };

  return (
    <article className="order-status" aria-label={`Order ${order.order_id} status`}>
      <header className="order-status__header">
        <div>
          <p className="order-status__eyebrow">Order status</p>
          <h2>{headline(order.order_status)}</h2>
          <div className="order-status__order-number">
            <span>Order #{shortOrderId(order.order_id)}</span>
            <span aria-hidden="true">·</span>
            <span>Placed {formatPlacedDate(order.created_at)}</span>
            <button type="button" onClick={() => void copyOrderId()} aria-label={`Copy full order number ${order.order_id}`}>
              <CopyIcon /> {copyState === "copied" ? "Copied" : copyState === "failed" ? "Copy unavailable" : "Copy order number"}
            </button>
          </div>
        </div>
        <span className="order-status__status">{humanize(fulfillment.status)}</span>
      </header>

      <section className="order-progress" aria-label="Order progress">
        <ol className="order-progress__steps" aria-label="Order progress">
          {steps.map((step) => (
            <li key={step.label} className={`order-progress__step order-progress__step--${step.state}`} aria-current={step.state === "active" ? "step" : undefined}>
              <span className="order-progress__marker" aria-hidden="true">{step.state === "completed" ? <CheckIcon /> : null}</span>
              <span>{step.label}</span>
            </li>
          ))}
        </ol>
      </section>

      <dl className="order-status__summary-row">
        <div>
          <PackageIcon />
          <dt>Status</dt>
          <dd>{humanize(fulfillment.status)}</dd>
        </div>
        <div>
          <CreditCardIcon />
          <dt>Payment</dt>
          <dd>{paymentLabel(order.payment.status)}</dd>
        </div>
        <div>
          <strong className="order-status__summary-symbol" aria-hidden="true">$</strong>
          <dt>Total</dt>
          <dd>{formatMoney(order.total, order.currency)}</dd>
        </div>
        <div>
          {pickup ? <StoreIcon /> : <MapPinIcon />}
          <dt>Fulfillment</dt>
          <dd>{humanize(fulfillment.fulfillment_type)}</dd>
        </div>
      </dl>

      <section className="order-status__section order-status__section--items" aria-labelledby="order-items-title">
        <div className="order-status__section-heading">
          <h3 id="order-items-title">Items</h3>
          <span>{order.items.length} {order.items.length === 1 ? "item" : "items"}</span>
        </div>
        <ul className="order-status__items">
          {order.items.map((item) => <OrderItemRow key={item.order_item_id} item={item} currency={order.currency} />)}
        </ul>
      </section>

      <section className="order-fulfillment-card" aria-label="Fulfillment details">
        <div className="order-fulfillment-card__icon" aria-hidden="true">{pickup ? <StoreIcon /> : <MapPinIcon />}</div>
        <div className="order-fulfillment-card__content">
          <p className="order-fulfillment-card__eyebrow">{pickup ? "Pickup details" : "Delivery details"}</p>
          <h3>
            {pickup
              ? `Pickup at ${fulfillment.store_name ?? "Scout store"}`
              : fulfillment.shipping_address
                ? `Delivery to ${fulfillment.shipping_address.city}, ${fulfillment.shipping_address.state}`
                : "Delivery destination"}
          </h3>
          {estimate && (
            <div className="order-fulfillment-card__estimate">
              <ClockIcon />
              <div><span>{pickup ? "Estimated ready" : "Estimated arrival"}</span><strong>{estimate}</strong></div>
            </div>
          )}
          {fulfillment.shipping_address && (
            <p className="order-fulfillment-card__address">
              {fulfillment.shipping_address.line1}, {fulfillment.shipping_address.city}, {fulfillment.shipping_address.state} {fulfillment.shipping_address.postal_code}
            </p>
          )}
          <p className="order-fulfillment-card__note">
            {fulfillment.estimate_source === "configured_policy"
              ? "This estimate is based on Scout's configured prototype policy and is not a carrier guarantee."
              : "This estimate uses persisted fulfillment tracking data."}
          </p>
          {pickup && !fulfillment.tracking.available && <p className="order-fulfillment-card__tracking-note">{fulfillment.tracking.message}</p>}
        </div>
      </section>

      {(!pickup || fulfillment.tracking.available) && (
        <section className="order-status__section" aria-label="Tracking information">
          <div className="order-status__section-heading"><h3>Tracking</h3></div>
          {fulfillment.tracking.available ? (
            <p className="order-status__tracking-line">
              <strong>{fulfillment.tracking.carrier_name}</strong>
              <span>{fulfillment.tracking.tracking_number}</span>
              {fulfillment.tracking.tracking_url && <a href={fulfillment.tracking.tracking_url} target="_blank" rel="noopener noreferrer">Track package</a>}
            </p>
          ) : <p>{fulfillment.tracking.message}</p>}
        </section>
      )}

      <section className="order-status__section order-status__section--eligibility" aria-labelledby="eligibility-title">
        <div className="order-status__section-heading">
          <div>
            <h3 id="eligibility-title">Eligibility</h3>
            <p>Status only — no cancellation, return, or exchange was performed.</p>
          </div>
        </div>
        <div className="order-eligibility-list">
          <EligibilityRow label="Cancellation" eligible={order.eligibility.cancellation.eligible} reason={order.eligibility.cancellation.reason} />
          <EligibilityRow label="Return" eligible={order.eligibility.return_eligibility.eligible} reason={order.eligibility.return_eligibility.reason} />
          <EligibilityRow label="Exchange" eligible={order.eligibility.exchange.eligible} reason={order.eligibility.exchange.reason} />
        </div>
      </section>

      {(onContinueShopping || onNeedHelp) && (
        <footer className="order-status__actions order-status__actions--mobile-only">
          {onContinueShopping && <button type="button" className="order-status__primary-action" onClick={onContinueShopping}>Continue shopping</button>}
          {onNeedHelp && <button type="button" className="order-status__secondary-action" onClick={onNeedHelp}>Get order help</button>}
        </footer>
      )}
    </article>
  );
}
