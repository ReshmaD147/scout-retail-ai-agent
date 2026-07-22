export interface CartButtonProps {
  itemCount: number;
  onClick: () => void;
}

/** A header-level button showing how many units are in the cart and
 * opening the cart drawer - Step 15's required "cart count" element. */
export function CartButton({ itemCount, onClick }: CartButtonProps): JSX.Element {
  return (
    <button type="button" className="cart-button" onClick={onClick} aria-haspopup="dialog">
      <span aria-hidden="true">🛒</span>
      <span>Cart</span>
      <span className="cart-button__count" aria-label={`${itemCount} item${itemCount === 1 ? "" : "s"} in cart`}>
        {itemCount}
      </span>
    </button>
  );
}
