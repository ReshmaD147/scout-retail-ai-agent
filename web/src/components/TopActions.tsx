import { CartButton } from "./CartButton";
import { HeartIcon, MessageIcon } from "./Icons";

export interface TopActionsProps {
  itemCount: number;
  subtotal: number;
  showHelp?: boolean;
  onCartClick: () => void;
  onNeedHelp: () => void;
  onSaved: () => void;
}

export function TopActions({ itemCount, subtotal, showHelp = true, onCartClick, onNeedHelp, onSaved }: TopActionsProps): JSX.Element {
  return (
    <div className={`top-actions${showHelp ? "" : " top-actions--compact"}`} aria-label="Quick actions">
      {showHelp && (
        <button type="button" className="top-actions__help" onClick={onNeedHelp}>
          <MessageIcon /> <span>Need help?</span>
        </button>
      )}
      <button type="button" className="top-actions__icon" onClick={onSaved} aria-label="Open saved products">
        <HeartIcon />
      </button>
      <CartButton itemCount={itemCount} subtotal={subtotal} onClick={onCartClick} />
    </div>
  );
}
