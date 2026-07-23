import { useState } from "react";
import type { UseCheckoutResult } from "../hooks/useCheckout";
import type { CartView } from "../types/cart";
import type { ShippingAddress } from "../types/checkout";

export interface CheckoutPanelProps {
  cart: CartView;
  checkout: UseCheckoutResult;
}

const EMPTY_ADDRESS: ShippingAddress = {
  full_name: "",
  line1: "",
  line2: null,
  city: "",
  state: "",
  postal_code: "",
  country: "US",
};

export function CheckoutPanel({ cart, checkout }: CheckoutPanelProps): JSX.Element {
  const [address, setAddress] = useState<ShippingAddress>(EMPTY_ADDRESS);
  const [paymentConfirmed, setPaymentConfirmed] = useState(false);

  if (checkout.confirmation) {
    return (
      <section className="checkout-panel checkout-panel--confirmed" aria-label="Order confirmation">
        <h3>Order confirmed</h3>
        <p>Your test order was created successfully.</p>
        <dl className="checkout-summary">
          <div>
            <dt>Order</dt>
            <dd>{checkout.confirmation.order_id}</dd>
          </div>
          <div>
            <dt>Payment</dt>
            <dd>{checkout.confirmation.payment.status}</dd>
          </div>
          <div>
            <dt>Total</dt>
            <dd>${checkout.confirmation.total.toFixed(2)}</dd>
          </div>
        </dl>
        <p className="checkout-panel__test-note">This used Scout&apos;s mock payment adapter. No real card was charged.</p>
      </section>
    );
  }

  if (checkout.review) {
    return (
      <section className="checkout-panel" aria-label="Order review">
        <div className="checkout-panel__heading-row">
          <h3>Order review</h3>
          <button type="button" className="checkout-panel__link" onClick={checkout.reset}>
            Change details
          </button>
        </div>

        <ul className="checkout-review__items">
          {checkout.review.items.map((item) => (
            <li key={item.product_id}>
              <div className="checkout-review__item-info">
                <span>{item.product_name} × {item.quantity}</span>
                {item.promotion_label && (
                  <span className="checkout-review__promotion">{item.promotion_label}</span>
                )}
              </div>
              <span>${item.line_total.toFixed(2)}</span>
            </li>
          ))}
        </ul>

        <dl className="checkout-summary">
          <div><dt>Price before discount</dt><dd>${checkout.review.subtotal.toFixed(2)}</dd></div>
          <div><dt>Discount</dt><dd>−${checkout.review.discount_total.toFixed(2)}</dd></div>
          <div><dt>Merchandise total</dt><dd>${checkout.review.merchandise_total.toFixed(2)}</dd></div>
          <div><dt>Tax</dt><dd>${checkout.review.tax_total.toFixed(2)}</dd></div>
          <div><dt>Shipping</dt><dd>${checkout.review.shipping_total.toFixed(2)}</dd></div>
          <div className="checkout-summary__total"><dt>Total</dt><dd>${checkout.review.total.toFixed(2)}</dd></div>
        </dl>

        <p className="checkout-panel__test-note">Payment method: mock payment in test mode.</p>
        <label className="checkout-panel__confirmation">
          <input
            type="checkbox"
            checked={paymentConfirmed}
            onChange={(event) => setPaymentConfirmed(event.target.checked)}
          />
          I confirm this test payment and want to place the order.
        </label>

        {checkout.errorMessage && <p className="checkout-panel__error" role="alert">{checkout.errorMessage}</p>}
        <button
          type="button"
          className="checkout-panel__primary"
          disabled={!paymentConfirmed || checkout.isLoading}
          onClick={() => void checkout.confirm(paymentConfirmed)}
        >
          {checkout.isLoading ? "Placing order..." : `Place test order · $${checkout.review.total.toFixed(2)}`}
        </button>
      </section>
    );
  }

  const fulfillmentReady = cart.fulfillment_type !== null;
  const cartReady = cart.validation_status === "valid" && cart.items.length > 0;
  const delivery = cart.fulfillment_type === "delivery";
  const addressComplete =
    !delivery ||
    Boolean(
      address.full_name.trim() &&
      address.line1.trim() &&
      address.city.trim() &&
      address.state.trim() &&
      address.postal_code.trim()
    );

  const updateAddress = (field: keyof ShippingAddress, value: string): void => {
    setAddress((current) => ({
      ...current,
      [field]: field === "line2" ? value || null : value,
    }) as ShippingAddress);
  };

  return (
    <section className="checkout-panel" aria-label="Checkout">
      <h3>Checkout</h3>

      {delivery && (
        <div className="checkout-address">
          <label>
            Full name
            <input value={address.full_name} onChange={(event) => updateAddress("full_name", event.target.value)} />
          </label>
          <label>
            Address line 1
            <input value={address.line1} onChange={(event) => updateAddress("line1", event.target.value)} />
          </label>
          <label>
            Address line 2 <span>(optional)</span>
            <input value={address.line2 ?? ""} onChange={(event) => updateAddress("line2", event.target.value)} />
          </label>
          <label>
            City
            <input value={address.city} onChange={(event) => updateAddress("city", event.target.value)} />
          </label>
          <div className="checkout-address__row">
            <label>
              State
              <input value={address.state} onChange={(event) => updateAddress("state", event.target.value)} />
            </label>
            <label>
              ZIP code
              <input value={address.postal_code} onChange={(event) => updateAddress("postal_code", event.target.value)} />
            </label>
          </div>
        </div>
      )}

      {!fulfillmentReady && <p className="checkout-panel__note">Choose pickup or delivery first.</p>}
      {cart.validation_status === "invalid" && <p className="checkout-panel__error">Resolve cart warnings before checkout.</p>}
      {checkout.errorMessage && (
        <div className="checkout-panel__error" role="alert">
          <span>{checkout.errorMessage}</span>
          <button type="button" onClick={checkout.dismissError}>Dismiss</button>
        </div>
      )}

      <button
        type="button"
        className="checkout-panel__primary"
        disabled={!fulfillmentReady || !cartReady || !addressComplete || checkout.isLoading}
        onClick={() => void checkout.createReview(delivery ? address : null)}
      >
        {checkout.isLoading ? "Reviewing..." : "Review checkout"}
      </button>
    </section>
  );
}