import { useState } from "react";
import { CheckoutPanel } from "./CheckoutPanel";
import { useCheckout } from "../hooks/useCheckout";
import type { CartItemView, CartView, StoreSummary } from "../types/cart";

export interface CartDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  cart: CartView | null;
  isLoading: boolean;
  errorMessage: string | null;
  stores: StoreSummary[];
  onUpdateQuantity: (cartItemId: string, quantity: number) => void;
  onRemoveItem: (cartItemId: string) => void;
  onClear: () => void;
  onChoosePickup: (storeId: string) => void;
  onChooseDelivery: () => void;
  onDismissError: () => void;
  sessionId?: string;
  onOrderCompleted?: () => void;
}

/**
 * The cart drawer (Step 15): items, quantities, subtotal, pickup/
 * delivery selection, and validation warnings. Every number shown here
 * (unit price, line total, subtotal) comes directly from the backend's
 * `CartView` - nothing is computed in this component.
 */
export function CartDrawer({
  isOpen,
  onClose,
  cart,
  isLoading,
  errorMessage,
  stores,
  onUpdateQuantity,
  onRemoveItem,
  onClear,
  onChoosePickup,
  onChooseDelivery,
  onDismissError,
  sessionId,
  onOrderCompleted,
}: CartDrawerProps): JSX.Element | null {
  const checkout = useCheckout(sessionId ?? cart?.session_id ?? "", onOrderCompleted);

  if (!isOpen) {
    return null;
  }

  const items = cart?.items ?? [];
  const isEmpty = items.length === 0;

  return (
    <div className="cart-drawer" role="dialog" aria-label="Shopping cart">
      <div className="cart-drawer__header">
        <h2>Your cart</h2>
        <button type="button" className="cart-drawer__close" onClick={onClose} aria-label="Close cart">
          &times;
        </button>
      </div>

      {errorMessage && (
        <div className="cart-drawer__error" role="alert">
          <p>{errorMessage}</p>
          <button type="button" onClick={onDismissError}>
            Dismiss
          </button>
        </div>
      )}

      {isLoading && (
        <p className="cart-drawer__loading" role="status">
          Updating your cart...
        </p>
      )}

      {isEmpty ? (
        <p className="cart-drawer__empty">Your cart is empty. Add a product to get started.</p>
      ) : (
        <>
          <ul className="cart-drawer__items">
            {items.map((item) => (
              <CartItemRow
                key={item.cart_item_id}
                item={item}
                onUpdateQuantity={onUpdateQuantity}
                onRemove={onRemoveItem}
              />
            ))}
          </ul>

          {cart && cart.warnings.length > 0 && (
            <ul className="cart-drawer__warnings" aria-live="polite">
              {cart.warnings.map((warning, index) => (
                <li key={index}>{warning}</li>
              ))}
            </ul>
          )}

          <div className="cart-drawer__subtotal" aria-label="Cart subtotal">
            <span>Subtotal</span>
            <span>${cart?.subtotal.toFixed(2)}</span>
          </div>

          <FulfillmentSelector
            cart={cart}
            stores={stores}
            onChoosePickup={onChoosePickup}
            onChooseDelivery={onChooseDelivery}
          />

          {cart && <CheckoutPanel cart={cart} checkout={checkout} />}

          <button type="button" className="cart-drawer__clear" onClick={onClear}>
            Clear cart
          </button>
        </>
      )}
    </div>
  );
}

interface CartItemRowProps {
  item: CartItemView;
  onUpdateQuantity: (cartItemId: string, quantity: number) => void;
  onRemove: (cartItemId: string) => void;
}

function CartItemRow({ item, onUpdateQuantity, onRemove }: CartItemRowProps): JSX.Element {
  return (
    <li className="cart-item">
      <div className="cart-item__info">
        <p className="cart-item__name">{item.product_name}</p>
        <p className="cart-item__price">${item.unit_price.toFixed(2)} each</p>
        {item.warnings.map((warning, index) => (
          <p key={index} className="cart-item__warning">
            {warning}
          </p>
        ))}
      </div>

      <div className="cart-item__quantity" role="group" aria-label={`Quantity for ${item.product_name}`}>
        <button
          type="button"
          onClick={() => onUpdateQuantity(item.cart_item_id, item.quantity - 1)}
          disabled={item.quantity <= 1}
          aria-label={`Decrease quantity of ${item.product_name}`}
        >
          −
        </button>
        <span aria-live="polite">{item.quantity}</span>
        <button
          type="button"
          onClick={() => onUpdateQuantity(item.cart_item_id, item.quantity + 1)}
          aria-label={`Increase quantity of ${item.product_name}`}
        >
          +
        </button>
      </div>

      <p className="cart-item__line-total">${item.line_total.toFixed(2)}</p>

      <button
        type="button"
        className="cart-item__remove"
        onClick={() => onRemove(item.cart_item_id)}
        aria-label={`Remove ${item.product_name} from cart`}
      >
        Remove
      </button>
    </li>
  );
}

interface FulfillmentSelectorProps {
  cart: CartView | null;
  stores: StoreSummary[];
  onChoosePickup: (storeId: string) => void;
  onChooseDelivery: () => void;
}

/** Pickup-or-delivery selection, with a store dropdown that only
 * appears once "pickup" is chosen - Step 15's required fulfillment and
 * pickup-store selectors. */
function FulfillmentSelector({
  cart,
  stores,
  onChoosePickup,
  onChooseDelivery,
}: FulfillmentSelectorProps): JSX.Element {
  const [selectedStoreId, setSelectedStoreId] = useState(cart?.store_id ?? "");
  const fulfillmentType = cart?.fulfillment_type ?? null;

  return (
    <fieldset className="fulfillment-selector">
      <legend>Fulfillment</legend>
      <div className="fulfillment-selector__options">
        <label>
          <input
            type="radio"
            name="fulfillment"
            value="pickup"
            checked={fulfillmentType === "pickup"}
            onChange={() => selectedStoreId && onChoosePickup(selectedStoreId)}
          />
          Pickup
        </label>
        <label>
          <input
            type="radio"
            name="fulfillment"
            value="delivery"
            checked={fulfillmentType === "delivery"}
            onChange={onChooseDelivery}
          />
          Delivery
        </label>
      </div>

      <label className="fulfillment-selector__store">
        Pickup store
        <select
          value={selectedStoreId}
          onChange={(event) => {
            const storeId = event.target.value;
            setSelectedStoreId(storeId);
            if (storeId) {
              onChoosePickup(storeId);
            }
          }}
        >
          <option value="">Choose a store...</option>
          {stores.map((store) => (
            <option key={store.store_id} value={store.store_id} disabled={!store.pickup_enabled}>
              {store.store_name}
              {store.pickup_enabled ? "" : " (pickup unavailable)"}
            </option>
          ))}
        </select>
      </label>

      {fulfillmentType === "delivery" && (
        <p className="fulfillment-selector__note">
          Delivery selected. Enter the shipping address in checkout below.
        </p>
      )}
    </fieldset>
  );
}
