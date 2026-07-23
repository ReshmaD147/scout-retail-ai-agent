import { CartIcon } from "./Icons";

export interface CartButtonProps {
  itemCount: number;
  subtotal?: number;
  onClick: () => void;
}

/** Header-level cart summary. Count and subtotal are both supplied by
 * the Step 15 backend CartView; this component never recalculates them. */
export function CartButton({ itemCount, subtotal = 0, onClick }: CartButtonProps): JSX.Element {
  return (
    <button
      type="button"
      className="cart-button"
      onClick={onClick}
      aria-haspopup="dialog"
      aria-label={`Open cart, ${itemCount} item${itemCount === 1 ? "" : "s"}, subtotal $${subtotal.toFixed(2)}`}
    >
      <span className="cart-button__icon"><CartIcon /></span>
      <span className="cart-button__count" aria-label={`${itemCount} item${itemCount === 1 ? "" : "s"} in cart`}>
        {itemCount}
      </span>
      <span className="cart-button__subtotal">${subtotal.toFixed(2)}</span>
    </button>
  );
}
